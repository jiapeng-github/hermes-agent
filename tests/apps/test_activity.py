from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_cli.apps.activity import AppActivityError, AppActivityStore
from hermes_cli.apps.paths import AppPaths
from hermes_cli.apps.runtime.auth import CSRF_HEADER_NAME, RuntimeAuth
from hermes_cli.apps.runtime.host import create_apphost_app
from hermes_cli.apps.runtime.service import ServiceActionRegistry, ServiceContext
from hermes_state import SessionDB

from .runtime_fixtures import service_runtime_app


SAFE_HTML = "<!doctype html><html><head><title>Snapshot</title></head><body><h1>Result</h1></body></html>"


def _manifest(tmp_path: Path):
    root, manifest, _grants = service_runtime_app(tmp_path / "fixture")
    return root, manifest


def test_completed_run_publishes_one_visible_read_only_session(tmp_path: Path) -> None:
    definition, manifest = _manifest(tmp_path)
    paths = AppPaths(tmp_path / "profile")
    store = AppActivityStore(paths)
    try:
        session_id = store.record_run_started(
            manifest, "run-1", "snapshot", {"refresh": True}
        )
        store.record_run_finished(
            "run-1", "completed", result={"summary": "行情已刷新"}
        )
        artifact = store.publish_artifact(
            manifest,
            "run-1",
            title="自选股行情快照",
            summary="行情已刷新",
            html=SAFE_HTML,
            snapshot={"symbol": "600519"},
        )
        duplicate = store.publish_artifact(
            manifest,
            "run-1",
            title="自选股行情快照",
            summary="行情已刷新",
            html=SAFE_HTML,
        )
        timeline = store.get_session(session_id)

        assert duplicate.id == artifact.id
        assert artifact.app_version == "1.0.1"
        assert artifact.html_path.is_file()
        assert artifact.snapshot_path is not None and artifact.snapshot_path.is_file()
        assert "Content-Security-Policy" in artifact.html_path.read_text(
            encoding="utf-8"
        )
        assert timeline["session"]["app_id"] == manifest.id
        assert [item["id"] for item in timeline["artifacts"]] == [artifact.id]
        assert timeline["runs"][0]["status"] == "completed"

        db = SessionDB(db_path=paths.hermes_home / "state.db")
        try:
            sessions = db.list_sessions_rich(
                source="app",
                min_message_count=1,
                limit=20,
            )
            assert [
                (row["id"], row["source"], row["message_count"]) for row in sessions
            ] == [(session_id, "app", 0)]
        finally:
            db.close()

        store.delete_app(manifest.id)
        db = SessionDB(db_path=paths.hermes_home / "state.db")
        try:
            assert db.session_count(source="app", min_message_count=1) == 0
        finally:
            db.close()
        assert not paths.app_artifacts(manifest.id).exists()
    finally:
        store.close()


def test_completed_run_without_artifact_still_publishes_activity_session(
    tmp_path: Path,
) -> None:
    _definition, manifest = _manifest(tmp_path)
    paths = AppPaths(tmp_path / "profile")
    store = AppActivityStore(paths)
    try:
        session_id = store.record_run_started(
            manifest, "run-without-artifact", "snapshot", {"refresh": True}
        )
        store.record_run_finished(
            "run-without-artifact",
            "completed",
            result={"summary": "行情已刷新"},
        )

        timeline = store.get_session(session_id)
        assert timeline["artifacts"] == []
        assert timeline["runs"][0]["status"] == "completed"

        db = SessionDB(db_path=paths.hermes_home / "state.db")
        try:
            sessions = db.list_sessions_rich(
                source="app",
                min_message_count=1,
                limit=20,
            )
            assert [(row["id"], row["source"]) for row in sessions] == [
                (session_id, "app")
            ]
        finally:
            db.close()
    finally:
        store.close()


def test_artifacts_require_completed_runs_and_static_html(tmp_path: Path) -> None:
    _definition, manifest = _manifest(tmp_path)
    store = AppActivityStore(AppPaths(tmp_path / "profile"))
    try:
        store.record_run_started(manifest, "run-1", "snapshot", {})
        with pytest.raises(AppActivityError) as incomplete:
            store.publish_artifact(
                manifest,
                "run-1",
                title="未完成",
                summary="未完成",
                html=SAFE_HTML,
            )
        assert incomplete.value.code == "APP_RUN_NOT_COMPLETED"

        store.record_run_finished("run-1", "completed", result={})
        with pytest.raises(AppActivityError) as unsafe:
            store.publish_artifact(
                manifest,
                "run-1",
                title="不安全页面",
                summary="包含活动脚本",
                html="<html><body><script>alert(1)</script></body></html>",
            )
        assert unsafe.value.code == "APP_ARTIFACT_UNSAFE"

        literal = store.publish_artifact(
            manifest,
            "run-1",
            title="正文文本",
            summary="普通正文中的协议名称不应被误拦截",
            html="<html><body><p>javascript: 只是这里的正文文本。</p></body></html>",
        )
        assert literal.html_path.is_file()

        store.record_run_started(manifest, "run-2", "snapshot", {})
        store.record_run_finished("run-2", "completed", result={})
        with pytest.raises(AppActivityError) as event_handler:
            store.publish_artifact(
                manifest,
                "run-2",
                title="不安全属性",
                summary="包含事件处理器",
                html='<html><body><button onclick="alert(1)">打开</button></body></html>',
            )
        assert event_handler.value.code == "APP_ARTIFACT_UNSAFE"
    finally:
        store.close()


def test_activity_session_identity_is_stable_and_profile_scoped(tmp_path: Path) -> None:
    _definition, manifest = _manifest(tmp_path)
    first = AppActivityStore(AppPaths(tmp_path / "profiles" / "first"))
    second = AppActivityStore(AppPaths(tmp_path / "profiles" / "second"))
    try:
        first_id = first.record_run_started(manifest, "first-run", "snapshot", {})
        repeated_id = first.record_run_started(manifest, "second-run", "snapshot", {})
        second_profile_id = second.record_run_started(
            manifest, "third-run", "snapshot", {}
        )

        assert first_id == repeated_id
        assert first_id != second_profile_id
    finally:
        first.close()
        second.close()


def test_activity_store_migrates_legacy_artifacts_to_versioned_records(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    connection = sqlite3.connect(paths.activity_db)
    try:
        connection.execute(
            """CREATE TABLE app_artifacts (
                   id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL UNIQUE,
                   app_id TEXT NOT NULL,
                   session_id TEXT NOT NULL,
                   title TEXT NOT NULL,
                   summary TEXT NOT NULL,
                   html_path TEXT NOT NULL,
                   snapshot_path TEXT,
                   sha256 TEXT NOT NULL,
                   size_bytes INTEGER NOT NULL,
                   created_at REAL NOT NULL
               )"""
        )
        connection.commit()
    finally:
        connection.close()

    store = AppActivityStore(paths)
    store.close()
    connection = sqlite3.connect(paths.activity_db)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(app_artifacts)")
        }
    finally:
        connection.close()

    assert "app_version" in columns


def test_apphost_artifact_publication_is_bound_to_runtime_session(tmp_path: Path) -> None:
    definition, manifest = _manifest(tmp_path)
    paths = AppPaths(tmp_path / "profile")
    activity = AppActivityStore(paths)
    auth = RuntimeAuth()
    origin = "http://127.0.0.1:49182"
    services = ServiceActionRegistry(
        {"test.snapshot": lambda _input, _context: {"ok": True}},
        context=ServiceContext(app_id=manifest.id, app_data=tmp_path / "data"),
    )
    app = create_apphost_app(
        manifest,
        definition,
        manifest.permissions,
        expected_origin=origin,
        runtime_auth=auth,
        allow_test_client=True,
        service_registry=services,
        storage_root=tmp_path / "storage",
        activity_store=activity,
    )

    def authenticate(client: TestClient) -> dict[str, str]:
        code = auth.issue_launch_code()
        assert client.get(f"/launch/{code}").status_code == 302
        csrf = client.get("/__hermes/bootstrap").json()["csrf_token"]
        return {
            "origin": origin,
            "sec-fetch-site": "same-origin",
            CSRF_HEADER_NAME: csrf,
        }

    try:
        with (
            TestClient(app, base_url=origin, follow_redirects=False) as owner,
            TestClient(
                app,
                base_url=origin,
                follow_redirects=False,
            ) as other,
        ):
            owner_headers = authenticate(owner)
            other_headers = authenticate(other)
            accepted = owner.post(
                "/api/actions/snapshot/runs",
                headers=owner_headers,
                json={"input": {}},
            )
            run_id = accepted.json()["run_id"]
            for _ in range(200):
                terminal = owner.get(f"/api/runs/{run_id}").json()
                if terminal["status"] == "completed":
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("run did not complete")

            payload = {
                "title": "自选股行情快照",
                "summary": "暂无自选股",
                "html": SAFE_HTML,
                "snapshot": {"total": 0},
            }
            rejected = other.post(
                f"/api/runs/{run_id}/artifacts",
                headers=other_headers,
                json=payload,
            )
            published = owner.post(
                f"/api/runs/{run_id}/artifacts",
                headers=owner_headers,
                json=payload,
            )
            artifact_id = published.json()["artifact"]["id"]
            rendered = owner.get(f"/__hermes/artifacts/{artifact_id}")

            assert rejected.status_code == 404
            assert rejected.json()["error"]["code"] == "RUN_NOT_FOUND"
            assert published.status_code == 201
            assert rendered.status_code == 200
            assert "default-src 'none'" in rendered.headers["content-security-policy"]
            assert "<h1>Result</h1>" in rendered.text
    finally:
        activity.close()
