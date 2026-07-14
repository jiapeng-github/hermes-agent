from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from hermes_cli.apps.errors import AppDomainError
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.models import AppPermissions
from hermes_cli.apps.package import ImportConfirmation
from hermes_cli.apps.paths import AppPaths


def _empty_grants() -> AppPermissions:
    return AppPermissions.model_validate(
        {
            "agent": False,
            "mcp_servers": [],
            "storage": {"mode": "none", "quota_mb": 0},
        }
    )


def _set_version(workspace: Path, version: str) -> None:
    path = workspace / "app.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["version"] = version
    path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_fixture_create_modify_recover_export_import_and_rollback(tmp_path: Path) -> None:
    primary = AppManager(AppPaths(tmp_path / "primary-profile"))
    workspace = primary.workspaces.init(
        tmp_path / "watchlist-v1",
        app_id="local.stockagent.watchlist",
        template="vanilla",
        name="Watchlist",
    )
    first = primary.publish(workspace, session_id="session-create")
    data_file = primary.paths.app_runtime_data("local.stockagent.watchlist") / "state.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text('{"symbols":["600519"]}', encoding="utf-8")

    edit = primary.workspaces.checkout(
        "local.stockagent.watchlist",
        tmp_path / "watchlist-v2",
    )
    _set_version(edit, "0.2.0")
    (edit / "source/app.js").write_text(
        (edit / "source/app.js").read_text(encoding="utf-8")
        + "\ndocument.title = 'Watchlist v2';\n",
        encoding="utf-8",
    )
    primary.workspaces.build(edit)

    schema = edit / "schemas/analyze.output.json"
    schema.unlink()
    with pytest.raises(AppDomainError):
        primary.publish(edit, session_id="session-failed-edit")

    assert primary.registry.get("local.stockagent.watchlist").active_version == "0.1.0"
    assert edit.is_dir()
    assert not any(primary.paths.staging.iterdir())

    schema.write_text(
        json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        ),
        encoding="utf-8",
    )
    second = primary.publish(edit, session_id="session-modify")

    assert second["app"]["version"] == "0.2.0"
    assert set(primary.registry.get("local.stockagent.watchlist").versions) == {
        "0.1.0",
        "0.2.0",
    }
    assert primary.inspect("local.stockagent.watchlist")["development_session"] == "session-modify"

    exported = primary.export(
        "local.stockagent.watchlist",
        tmp_path / "watchlist.happ",
    )
    secondary = AppManager(AppPaths(tmp_path / "secondary-profile"))
    plan = secondary.analyze_import(exported.path)
    imported = secondary.confirm_import(
        plan.import_id,
        ImportConfirmation(
            package_sha256=plan.package_sha256,
            conflict_mode="install",
            grants=_empty_grants(),
        ),
    )

    assert imported["app"]["version"] == "0.2.0"
    assert secondary.registry.get("local.stockagent.watchlist") is not None

    rolled_back = primary.rollback("local.stockagent.watchlist", "0.1.0")

    assert first["app"]["version"] == "0.1.0"
    assert rolled_back["version"] == "0.1.0"
    assert data_file.read_text(encoding="utf-8") == '{"symbols":["600519"]}'


def test_publish_requires_a_version_increment(tmp_path: Path) -> None:
    manager = AppManager(AppPaths(tmp_path / "profile"))
    workspace = manager.workspaces.init(
        tmp_path / "v1",
        app_id="local.stockagent.versioned",
        template="vanilla",
    )
    manager.publish(workspace)
    edit = manager.workspaces.checkout(
        "local.stockagent.versioned",
        tmp_path / "same-version-edit",
    )
    (edit / "source/app.js").write_text("document.title = 'changed';\n", encoding="utf-8")
    manager.workspaces.build(edit)

    with pytest.raises(AppDomainError) as caught:
        manager.publish(edit)

    assert caught.value.code == "APP_VERSION_CONFLICT"
    assert manager.registry.get("local.stockagent.versioned").active_version == "0.1.0"
