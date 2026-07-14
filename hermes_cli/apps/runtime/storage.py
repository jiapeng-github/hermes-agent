"""App-scoped JSON storage for the frozen Runtime v1 routes."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Literal

from utils import atomic_json_write

from .runs import RuntimeRunError


class RuntimeStorage:
    def __init__(self, mode: Literal["none", "session", "persistent"], quota_mb: int, root: Path):
        self.mode = mode
        self.quota_bytes = quota_mb * 1024 * 1024
        self.root = root
        self._session: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        normalized = self._key(key)
        with self._lock:
            if self.mode == "session":
                if normalized not in self._session:
                    raise RuntimeRunError(404, "STORAGE_KEY_NOT_FOUND", "storage key was not found")
                return self._session[normalized]
            path = self._path(normalized)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise RuntimeRunError(404, "STORAGE_KEY_NOT_FOUND", "storage key was not found") from exc
            if payload.get("key") != normalized or "value" not in payload:
                raise RuntimeRunError(404, "STORAGE_KEY_NOT_FOUND", "storage key was not found")
            return payload["value"]

    def put(self, key: str, value: Any) -> None:
        normalized = self._key(key)
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeRunError(400, "STORAGE_VALUE_INVALID", "storage value must be JSON") from exc
        if len(encoded) > self.quota_bytes:
            raise RuntimeRunError(413, "STORAGE_QUOTA_EXCEEDED", "storage quota exceeded")
        with self._lock:
            if self.mode == "session":
                candidate = dict(self._session)
                candidate[normalized] = value
                size = len(
                    json.dumps(candidate, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                        "utf-8"
                    )
                )
                if size > self.quota_bytes:
                    raise RuntimeRunError(413, "STORAGE_QUOTA_EXCEEDED", "storage quota exceeded")
                self._session = candidate
                return

            self.root.mkdir(parents=True, exist_ok=True)
            target = self._path(normalized)
            existing_size = target.stat().st_size if target.exists() and target.is_file() else 0
            total = sum(
                path.stat().st_size
                for path in self.root.glob("*.json")
                if path.is_file() and not path.is_symlink()
            )
            envelope = {"key": normalized, "value": value}
            envelope_size = len(
                json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            if total - existing_size + envelope_size > self.quota_bytes:
                raise RuntimeRunError(413, "STORAGE_QUOTA_EXCEEDED", "storage quota exceeded")
            atomic_json_write(target, envelope, mode=0o600, sort_keys=True)

    def delete(self, key: str) -> bool:
        normalized = self._key(key)
        with self._lock:
            if self.mode == "session":
                return self._session.pop(normalized, None) is not None
            path = self._path(normalized)
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False

    def _key(self, key: str) -> str:
        if self.mode == "none":
            raise RuntimeRunError(404, "STORAGE_UNAVAILABLE", "application storage is not enabled")
        if (
            not key
            or len(key.encode("utf-8")) > 512
            or key.startswith("__hermes")
            or any(ord(character) < 32 for character in key)
        ):
            raise RuntimeRunError(400, "STORAGE_KEY_INVALID", "invalid storage key")
        return key

    def _path(self, key: str) -> Path:
        return self.root / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"


__all__ = ["RuntimeStorage"]
