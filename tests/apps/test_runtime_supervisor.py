from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hermes_cli.apps.catalog import (
    COMPANY_ANALYSIS_APP_ID,
    COMPANY_ANALYSIS_SERVICE_HANDLERS,
    INDUSTRY_MONITOR_APP_ID,
    INDUSTRY_MONITOR_SERVICE_HANDLERS,
    WATCHLIST_APP_ID,
    WATCHLIST_SERVICE_HANDLERS,
)
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths
from hermes_cli.apps.runtime.supervisor import AppRuntimeSupervisor


class FakeHost:
    instances: list["FakeHost"] = []

    def __init__(self, manifest, app_root, grants, **kwargs):
        self.manifest = manifest
        self.app_root = app_root
        self.grants = grants
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def is_idle(self):
        return False

    def issue_launch_url(self):
        return "http://127.0.0.1:49182/launch/one-time"


@pytest.mark.parametrize(
    ("app_id", "handlers"),
    [
        (COMPANY_ANALYSIS_APP_ID, COMPANY_ANALYSIS_SERVICE_HANDLERS),
        (INDUSTRY_MONITOR_APP_ID, INDUSTRY_MONITOR_SERVICE_HANDLERS),
        (WATCHLIST_APP_ID, WATCHLIST_SERVICE_HANDLERS),
    ],
)
def test_manager_launch_reuses_one_profile_scoped_apphost(
    monkeypatch,
    tmp_path: Path,
    app_id: str,
    handlers: tuple[str, ...],
) -> None:
    FakeHost.instances.clear()
    monkeypatch.setattr("hermes_cli.apps.runtime.supervisor.AppHost", FakeHost)
    paths = AppPaths(tmp_path / "profile")
    manager = AppManager(paths)
    supervisor = AppRuntimeSupervisor(paths)

    first = manager.launch(app_id, supervisor)
    second = manager.launch(app_id, supervisor)

    assert len(FakeHost.instances) == 1
    assert FakeHost.instances[0].started is True
    assert first["launch_id"] != second["launch_id"]
    assert urlsplit(first["url"]).hostname == "127.0.0.1"
    assert urlsplit(first["url"]).path.startswith("/launch/")
    assert FakeHost.instances[0].kwargs["storage_root"] == (
        paths.app_runtime_data(app_id) / "storage" / "kv"
    )
    assert FakeHost.instances[0].kwargs["service_registry"].names == frozenset(handlers)

    manager.stop(app_id, supervisor)
    assert FakeHost.instances[0].stopped is True
