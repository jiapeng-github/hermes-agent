"""Profile-scoped lifecycle for reusable per-application AppHosts."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import AppManifest
from ..paths import AppPaths
from ..registry import AppRecord
from .host import AppHost
from .service import builtin_finance_service_registry


class AppRuntimeSupervisor:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._hosts: dict[str, tuple[str, AppHost]] = {}
        self._lock = threading.Lock()

    def launch(
        self,
        record: AppRecord,
        manifest: AppManifest,
        app_root: Path,
    ) -> dict[str, Any]:
        with self._lock:
            self._reap_idle_locked()
            current = self._hosts.get(record.id)
            if current is not None and current[0] != manifest.version:
                current[1].stop()
                self._hosts.pop(record.id, None)
                current = None
            if current is None:
                service_registry = self._service_registry(record)
                host = AppHost(
                    manifest,
                    app_root,
                    record.granted_permissions,
                    service_registry=service_registry,
                    storage_root=self.paths.app_runtime_data(record.id) / "storage" / "kv",
                )
                host.start()
                self._hosts[record.id] = (manifest.version, host)
            else:
                host = current[1]

            return {
                "launch_id": str(uuid.uuid4()),
                "url": host.issue_launch_url(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
            }

    def stop(self, app_id: str) -> None:
        with self._lock:
            current = self._hosts.pop(app_id, None)
        if current is not None:
            current[1].stop()

    def close_all(self) -> None:
        with self._lock:
            hosts = list(self._hosts.values())
            self._hosts.clear()
        for _version, host in hosts:
            host.stop()

    def _service_registry(self, record: AppRecord):
        if record.lineage != "builtin":
            return None
        if record.service_handlers:
            return builtin_finance_service_registry(
                app_id=record.id,
                app_data=self.paths.app_runtime_data(record.id),
                inherited_handlers=tuple(record.service_handlers),
            )
        return None

    def _reap_idle_locked(self) -> None:
        expired = [app_id for app_id, (_version, host) in self._hosts.items() if host.is_idle()]
        for app_id in expired:
            _version, host = self._hosts.pop(app_id)
            host.stop()


__all__ = ["AppRuntimeSupervisor"]
