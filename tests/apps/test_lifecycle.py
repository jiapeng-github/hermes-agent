from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli.apps.catalog import WATCHLIST_APP_ID
from hermes_cli.apps.errors import AppDomainError
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths


class RecordingSupervisor:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def stop(self, app_id: str) -> None:
        self.stopped.append(app_id)


def _published_app(tmp_path: Path) -> tuple[AppManager, str, Path]:
    manager = AppManager(AppPaths(tmp_path / "Profile 数据"))
    app_id = "local.stockagent.portable"
    workspace = manager.workspaces.init(
        tmp_path / "应用 source",
        app_id=app_id,
        template="vanilla",
        name="Portable App",
    )
    manager.publish(workspace)
    data = manager.paths.app_runtime_data(app_id) / "storage" / "state.json"
    data.parent.mkdir(parents=True)
    data.write_text('{"symbols":["600519"]}', encoding="utf-8")
    return manager, app_id, data


def test_uninstall_preserves_data_by_default_and_stops_runtime(tmp_path: Path) -> None:
    manager, app_id, data = _published_app(tmp_path)
    package_root = manager.paths.app_package(app_id)
    supervisor = RecordingSupervisor()

    manager.uninstall(app_id, supervisor)

    assert supervisor.stopped == [app_id]
    assert manager.registry.get(app_id) is None
    assert not package_root.exists()
    assert data.read_text(encoding="utf-8") == '{"symbols":["600519"]}'


def test_uninstall_can_remove_runtime_data(tmp_path: Path) -> None:
    manager, app_id, data = _published_app(tmp_path)

    manager.uninstall(app_id, RecordingSupervisor(), preserve_data=False)

    assert manager.registry.get(app_id) is None
    assert not data.exists()
    assert not manager.paths.app_runtime_data(app_id).exists()


def test_uninstall_rolls_files_back_when_registry_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager, app_id, data = _published_app(tmp_path)
    package_root = manager.paths.app_package(app_id)
    manager.list_apps()

    def fail_write(_document) -> None:
        raise OSError("simulated registry failure")

    monkeypatch.setattr(manager.registry, "_write_unlocked", fail_write)

    with pytest.raises(OSError, match="simulated"):
        manager.uninstall(app_id, RecordingSupervisor(), preserve_data=False)

    assert package_root.is_dir()
    assert data.is_file()
    assert manager.registry.get(app_id) is not None


def test_builtin_app_cannot_be_uninstalled_but_its_data_can_be_deleted(
    tmp_path: Path,
) -> None:
    manager = AppManager(AppPaths(tmp_path / "profile"))
    manager.list_apps()
    data = manager.paths.app_runtime_data(WATCHLIST_APP_ID) / "storage" / "state.json"
    data.parent.mkdir(parents=True)
    data.write_text("{}", encoding="utf-8")
    supervisor = RecordingSupervisor()

    with pytest.raises(AppDomainError, match="built-in"):
        manager.uninstall(WATCHLIST_APP_ID, supervisor)

    manager.delete_data(WATCHLIST_APP_ID, supervisor)

    assert manager.registry.get(WATCHLIST_APP_ID) is not None
    assert not data.exists()
    assert supervisor.stopped == [WATCHLIST_APP_ID]


@pytest.mark.parametrize("unsafe", ["../escape", "AI.Hermes.App", "ai.hermes", "ai/hermes/app"])
def test_paths_reject_cross_platform_traversal_shapes(tmp_path: Path, unsafe: str) -> None:
    paths = AppPaths(tmp_path / "profile")

    with pytest.raises(ValueError, match="invalid app id"):
        paths.app_package(unsafe)
