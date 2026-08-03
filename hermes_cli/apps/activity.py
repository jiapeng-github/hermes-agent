"""Profile-scoped application activity sessions and immutable HTML artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from hermes_state import SessionDB

from .models import AppManifest
from .paths import AppPaths


MAX_ARTIFACT_HTML_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_TITLE = 160
MAX_ARTIFACT_SUMMARY = 1000
_ACTIVE_TAGS = frozenset({"script", "iframe", "frame", "object", "embed", "base"})
_URL_ATTRIBUTES = frozenset({"action", "formaction", "href", "src", "xlink:href"})
_ARTIFACT_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)


class AppActivityError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class _StaticArtifactValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.seen_html = False
        self.unsafe = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._inspect(tag, attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._inspect(tag, attrs)

    def _inspect(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "html":
            self.seen_html = True
        if normalized_tag in _ACTIVE_TAGS:
            self.unsafe = True
        for name, value in attrs:
            normalized_name = name.casefold()
            normalized_value = (value or "").strip().casefold()
            if normalized_name.startswith("on"):
                self.unsafe = True
            if normalized_name in _URL_ATTRIBUTES and normalized_value.startswith(
                "javascript:"
            ):
                self.unsafe = True
            if (
                normalized_tag == "meta"
                and normalized_name == "http-equiv"
                and normalized_value == "refresh"
            ):
                self.unsafe = True


@dataclass(frozen=True, slots=True)
class AppArtifact:
    id: str
    app_id: str
    app_version: str
    session_id: str
    run_id: str
    title: str
    summary: str
    html_path: Path
    snapshot_path: Path | None
    sha256: str
    size_bytes: int
    created_at: float

    def as_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "app_id": self.app_id,
            "app_version": self.app_version,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "title": self.title,
            "summary": self.summary,
            "mime_type": "text/html",
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }
        if include_path:
            result["file_path"] = str(self.html_path)
        return result


class AppActivityStore:
    """Own app events separately from the LLM-visible ``messages`` table."""

    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or AppPaths.active_profile()
        self.paths.ensure()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.paths.activity_db,
            timeout=5,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_activity_sessions (
                app_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                app_name TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                visible INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS app_runs (
                run_id TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                app_version TEXT NOT NULL,
                action_id TEXT NOT NULL,
                input_json TEXT NOT NULL,
                status TEXT NOT NULL,
                result_summary TEXT,
                error_json TEXT,
                created_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY(app_id) REFERENCES app_activity_sessions(app_id)
            );
            CREATE TABLE IF NOT EXISTS app_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                app_id TEXT NOT NULL,
                app_version TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                html_path TEXT NOT NULL,
                snapshot_path TEXT,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(run_id) REFERENCES app_runs(run_id),
                FOREIGN KEY(app_id) REFERENCES app_activity_sessions(app_id)
            );
            CREATE INDEX IF NOT EXISTS idx_app_runs_session_created
                ON app_runs(session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_app_artifacts_session_created
                ON app_artifacts(session_id, created_at DESC);
            """
        )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            artifact_columns = {
                row["name"]
                for row in self._conn.execute(
                    "PRAGMA table_info(app_artifacts)"
                ).fetchall()
            }
            if "app_version" not in artifact_columns:
                self._conn.execute(
                    "ALTER TABLE app_artifacts ADD COLUMN app_version TEXT NOT NULL DEFAULT ''"
                )
                self._conn.execute(
                    """UPDATE app_artifacts
                       SET app_version = COALESCE(
                           (SELECT app_version FROM app_runs WHERE app_runs.run_id = app_artifacts.run_id),
                           ''
                       )
                       WHERE app_version = ''"""
                )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record_run_started(
        self,
        manifest: AppManifest,
        run_id: str,
        action_id: str,
        input_data: Any,
    ) -> str:
        now = time.time()
        session_id = self._session_id(manifest.id)
        canonical_input = json.dumps(
            input_data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """INSERT INTO app_activity_sessions(
                           app_id, session_id, app_name, created_at, updated_at, visible
                       ) VALUES (?, ?, ?, ?, ?, 0)
                       ON CONFLICT(app_id) DO UPDATE SET app_name = excluded.app_name""",
                    (manifest.id, session_id, manifest.name, now, now),
                )
                self._conn.execute(
                    """INSERT OR IGNORE INTO app_runs(
                           run_id, app_id, session_id, app_version, action_id,
                           input_json, status, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
                    (
                        run_id,
                        manifest.id,
                        session_id,
                        manifest.version,
                        action_id,
                        canonical_input,
                        now,
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return session_id

    def record_run_finished(
        self,
        run_id: str,
        status: str,
        *,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        summary = _result_summary(result)
        error_json = (
            json.dumps(error, ensure_ascii=False, sort_keys=True) if error else None
        )
        with self._lock:
            self._conn.execute(
                """UPDATE app_runs
                   SET status = ?, result_summary = ?, error_json = ?, completed_at = ?
                   WHERE run_id = ?""",
                (status, summary, error_json, time.time(), run_id),
            )

    def publish_artifact(
        self,
        manifest: AppManifest,
        run_id: str,
        *,
        title: str,
        summary: str,
        html: str,
        snapshot: dict[str, Any] | None = None,
    ) -> AppArtifact:
        clean_title = _bounded_text(title, MAX_ARTIFACT_TITLE, "artifact title")
        clean_summary = _bounded_text(summary, MAX_ARTIFACT_SUMMARY, "artifact summary")
        safe_html = _prepare_html(html)
        html_bytes = safe_html.encode("utf-8")
        snapshot_bytes = None
        if snapshot is not None:
            snapshot_bytes = json.dumps(
                snapshot,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(snapshot_bytes) > MAX_ARTIFACT_SNAPSHOT_BYTES:
                raise AppActivityError(
                    413, "APP_ARTIFACT_TOO_LARGE", "artifact snapshot exceeds 2 MiB"
                )

        with self._lock:
            run = self._conn.execute(
                "SELECT * FROM app_runs WHERE run_id = ? AND app_id = ?",
                (run_id, manifest.id),
            ).fetchone()
            if run is None:
                raise AppActivityError(
                    404, "APP_RUN_NOT_FOUND", "application run was not found"
                )
            if run["status"] != "completed":
                raise AppActivityError(
                    409,
                    "APP_RUN_NOT_COMPLETED",
                    "only a completed run can publish an artifact",
                )
            existing = self._conn.execute(
                "SELECT * FROM app_artifacts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is not None:
                artifact = self._artifact(existing)
                self._publish_session_row(
                    run["session_id"], manifest.id, manifest.name, artifact.created_at
                )
                return artifact

            artifact_id = str(uuid.uuid4())
            artifact_dir = self.paths.app_artifacts(manifest.id) / artifact_id
            artifact_dir.mkdir(parents=True, mode=0o700)
            html_path = artifact_dir / "index.html"
            snapshot_path = (
                artifact_dir / "snapshot.json" if snapshot_bytes is not None else None
            )
            try:
                _atomic_write(html_path, html_bytes)
                if snapshot_path is not None and snapshot_bytes is not None:
                    _atomic_write(snapshot_path, snapshot_bytes)
                now = time.time()
                digest = hashlib.sha256(html_bytes).hexdigest()
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute(
                        """INSERT INTO app_artifacts(
                               id, run_id, app_id, app_version, session_id, title, summary,
                               html_path, snapshot_path, sha256, size_bytes, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            artifact_id,
                            run_id,
                            manifest.id,
                            run["app_version"],
                            run["session_id"],
                            clean_title,
                            clean_summary,
                            str(html_path),
                            str(snapshot_path) if snapshot_path else None,
                            digest,
                            len(html_bytes),
                            now,
                        ),
                    )
                    self._conn.execute(
                        """UPDATE app_activity_sessions
                           SET visible = 1, updated_at = ?, app_name = ? WHERE app_id = ?""",
                        (now, manifest.name, manifest.id),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except BaseException:
                shutil.rmtree(artifact_dir, ignore_errors=True)
                raise

            self._publish_session_row(
                run["session_id"], manifest.id, manifest.name, now
            )
            row = self._conn.execute(
                "SELECT * FROM app_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            return self._artifact(row)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._conn.execute(
                "SELECT * FROM app_activity_sessions WHERE session_id = ? AND visible = 1",
                (session_id,),
            ).fetchone()
            if session is None:
                raise AppActivityError(
                    404,
                    "APP_ACTIVITY_NOT_FOUND",
                    "application activity session was not found",
                )
            artifacts = self._conn.execute(
                "SELECT * FROM app_artifacts WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT 200",
                (session_id,),
            ).fetchall()
            runs = self._conn.execute(
                """SELECT run_id, action_id, input_json, status, result_summary,
                          error_json, created_at, completed_at
                   FROM app_runs WHERE session_id = ?
                   ORDER BY created_at DESC, run_id DESC LIMIT 200""",
                (session_id,),
            ).fetchall()
        return {
            "session": {
                "app_id": session["app_id"],
                "session_id": session["session_id"],
                "app_name": session["app_name"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
            },
            "artifacts": [
                self._artifact(row).as_dict(include_path=True) for row in artifacts
            ],
            "runs": [
                {
                    "run_id": row["run_id"],
                    "action_id": row["action_id"],
                    "input": json.loads(row["input_json"]),
                    "status": row["status"],
                    "result_summary": row["result_summary"],
                    "error": json.loads(row["error_json"])
                    if row["error_json"]
                    else None,
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                }
                for row in runs
            ],
        }

    def get_artifact(
        self, artifact_id: str, *, app_id: str | None = None
    ) -> AppArtifact:
        try:
            artifact_id = str(uuid.UUID(artifact_id))
        except (ValueError, AttributeError) as exc:
            raise AppActivityError(
                404, "APP_ARTIFACT_NOT_FOUND", "artifact was not found"
            ) from exc
        with self._lock:
            if app_id:
                row = self._conn.execute(
                    "SELECT * FROM app_artifacts WHERE id = ? AND app_id = ?",
                    (artifact_id, app_id),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM app_artifacts WHERE id = ?", (artifact_id,)
                ).fetchone()
        if row is None:
            raise AppActivityError(
                404, "APP_ARTIFACT_NOT_FOUND", "artifact was not found"
            )
        artifact = self._artifact(row)
        root = self.paths.app_artifacts(artifact.app_id).resolve()
        try:
            artifact.html_path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise AppActivityError(
                404, "APP_ARTIFACT_NOT_FOUND", "artifact file was not found"
            ) from exc
        return artifact

    def delete_app(self, app_id: str) -> None:
        with self._lock:
            session = self._conn.execute(
                "SELECT session_id FROM app_activity_sessions WHERE app_id = ?",
                (app_id,),
            ).fetchone()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "DELETE FROM app_artifacts WHERE app_id = ?", (app_id,)
                )
                self._conn.execute("DELETE FROM app_runs WHERE app_id = ?", (app_id,))
                self._conn.execute(
                    "DELETE FROM app_activity_sessions WHERE app_id = ?", (app_id,)
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        if session is not None:
            db = SessionDB(db_path=self.paths.hermes_home / "state.db")
            try:
                db.delete_session(session["session_id"])
            finally:
                db.close()
        shutil.rmtree(self.paths.app_artifacts(app_id), ignore_errors=True)

    def _publish_session_row(
        self, session_id: str, app_id: str, app_name: str, now: float
    ) -> None:
        db = SessionDB(db_path=self.paths.hermes_home / "state.db")
        try:
            db.create_session(
                session_id,
                "app",
                model_config={"_app_activity": {"app_id": app_id}},
            )
            if not db.get_session_title(session_id):
                try:
                    db.set_auto_title_if_empty(session_id, f"{app_name}（应用记录）")
                except ValueError:
                    db.set_auto_title_if_empty(
                        session_id,
                        f"{app_name[:60]}（{app_id[:80]}）",
                    )
            db.touch_empty_session(session_id, now)
        finally:
            db.close()

    def _session_id(self, app_id: str) -> str:
        profile_scope = self.paths.hermes_home.expanduser().resolve(strict=False)
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"stocksense:app-activity:{profile_scope}:{app_id}",
            )
        )

    @staticmethod
    def _artifact(row: sqlite3.Row) -> AppArtifact:
        return AppArtifact(
            id=row["id"],
            app_id=row["app_id"],
            app_version=row["app_version"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            title=row["title"],
            summary=row["summary"],
            html_path=Path(row["html_path"]),
            snapshot_path=Path(row["snapshot_path"]) if row["snapshot_path"] else None,
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
        )


def _bounded_text(value: str, limit: int, label: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise AppActivityError(400, "APP_ARTIFACT_INVALID", f"{label} is required")
    if len(normalized) > limit:
        raise AppActivityError(400, "APP_ARTIFACT_INVALID", f"{label} is too long")
    return normalized


def _prepare_html(value: str) -> str:
    if not isinstance(value, str):
        raise AppActivityError(
            400, "APP_ARTIFACT_INVALID", "artifact html must be a string"
        )
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_HTML_BYTES:
        raise AppActivityError(
            413, "APP_ARTIFACT_TOO_LARGE", "artifact html exceeds 5 MiB"
        )
    validator = _StaticArtifactValidator()
    try:
        validator.feed(value)
        validator.close()
    except (AssertionError, ValueError) as exc:
        raise AppActivityError(
            400, "APP_ARTIFACT_INVALID", "artifact html could not be parsed"
        ) from exc
    if not validator.seen_html or validator.unsafe:
        raise AppActivityError(
            400, "APP_ARTIFACT_UNSAFE", "artifact html contains active content"
        )
    meta = f'<meta http-equiv="Content-Security-Policy" content="{_ARTIFACT_CSP}">'
    head_match = re.search(r"<head\b[^>]*>", value, re.IGNORECASE)
    if head_match:
        return value[: head_match.end()] + meta + value[head_match.end() :]
    html_match = re.search(r"<html\b[^>]*>", value, re.IGNORECASE)
    assert html_match is not None
    return (
        value[: html_match.end()] + f"<head>{meta}</head>" + value[html_match.end() :]
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _result_summary(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, dict):
        for key in ("summary", "headline", "message", "status"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:1000]
    try:
        encoded = json.dumps(
            result, ensure_ascii=False, allow_nan=False, sort_keys=True
        )
    except (TypeError, ValueError):
        return None
    return encoded[:1000]


__all__ = [
    "AppActivityError",
    "AppActivityStore",
    "AppArtifact",
    "MAX_ARTIFACT_HTML_BYTES",
]
