from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_cli.apps.errors import AppDomainError, PackageValidationError
from hermes_cli.apps.package import export_happ_package, inspect_happ_package
from hermes_cli.apps.paths import AppPaths
from hermes_cli.apps.workspace import AppWorkspaceService


REPO_ROOT = Path(__file__).resolve().parents[2]


def _service(tmp_path: Path) -> AppWorkspaceService:
    return AppWorkspaceService(AppPaths(tmp_path / "profile"))


def test_vanilla_init_builds_a_valid_runtime_workspace(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "watchlist",
        app_id="local.stockagent.watchlist",
        template="vanilla",
        name="Watchlist",
    )

    report = service.validate(workspace)

    assert report.valid is True
    assert report.app_id == "local.stockagent.watchlist"
    assert (workspace / "dist/index.html").is_file()
    assert service.metadata(workspace).template == "vanilla"


def test_validation_rejects_invalid_action_schema_and_remote_script(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "unsafe",
        app_id="local.stockagent.unsafe",
        template="vanilla",
    )
    (workspace / "schemas/analyze.input.json").write_text(
        json.dumps({"type": 42}),
        encoding="utf-8",
    )
    (workspace / "dist/index.html").write_text(
        '<!doctype html><script src="https://evil.example/app.js"></script>',
        encoding="utf-8",
    )

    report = service.validate(workspace)
    codes = {issue.code for issue in report.issues}

    assert report.valid is False
    assert "action.schema_invalid" in codes
    assert "csp.remote_script" in codes


def test_validation_rejects_non_http_script_schemes_but_allows_reference_links(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "schemes",
        app_id="local.stockagent.schemes",
        template="vanilla",
    )
    (workspace / "dist/index.html").write_text(
        '<!doctype html><a href="https://example.com/research">Research</a>'
        '<script src="javascript:alert(1)"></script>',
        encoding="utf-8",
    )

    report = service.validate(workspace)

    assert report.valid is False
    assert [issue.code for issue in report.issues].count("csp.remote_script") == 1
    assert not any(issue.code == "csp.remote_resource" for issue in report.issues)


def test_validation_rejects_missing_or_escaped_local_assets(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "missing-assets",
        app_id="local.stockagent.missing-assets",
        template="vanilla",
    )
    (workspace / "dist/index.html").write_text(
        '<!doctype html><link rel="stylesheet" href="./missing.css">'
        '<script src="/%2e%2e/escape.js"></script>',
        encoding="utf-8",
    )

    report = service.validate(workspace)
    codes = {issue.code for issue in report.issues}

    assert report.valid is False
    assert "build.asset_missing" in codes
    assert "build.asset_escape" in codes


def test_validation_rejects_nested_external_action_schema_refs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "external-ref",
        app_id="local.stockagent.external-ref",
        template="vanilla",
    )
    (workspace / "schemas/analyze.input.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "quote": {"$ref": "https://evil.example/quote.schema.json"}
                },
            }
        ),
        encoding="utf-8",
    )

    report = service.validate(workspace)

    assert report.valid is False
    assert any(issue.code == "action.schema_external_ref" for issue in report.issues)


def test_failed_build_preserves_previous_dist(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "preserved",
        app_id="local.stockagent.preserved",
        template="vanilla",
    )
    original = (workspace / "dist/index.html").read_bytes()
    (workspace / "source/index.html").write_text(
        '<!doctype html><script src="https://evil.example/app.js"></script>',
        encoding="utf-8",
    )

    with pytest.raises(AppDomainError):
        service.build(workspace)

    assert (workspace / "dist/index.html").read_bytes() == original


def test_happ_export_is_reproducible_and_can_exclude_source(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "exportable",
        app_id="local.stockagent.exportable",
        template="vanilla",
    )
    created = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)

    first = export_happ_package(
        workspace,
        tmp_path / "first.happ",
        created_at=created,
        include_source=True,
    )
    second = export_happ_package(
        workspace,
        tmp_path / "second.happ",
        created_at=created,
        include_source=True,
    )
    source_less = export_happ_package(
        workspace,
        tmp_path / "source-less.happ",
        created_at=created,
        include_source=False,
    )
    inspection = inspect_happ_package(
        source_less.path,
        tmp_path / "source-less-inspection",
    )

    assert first.package_sha256 == second.package_sha256
    assert first.path.read_bytes() == second.path.read_bytes()
    assert inspection.envelope.source_included is False
    assert inspection.manifest.source is None


def test_export_refuses_destination_inside_package_content_without_side_effects(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "inside-export",
        app_id="local.stockagent.inside-export",
        template="vanilla",
    )
    destination = workspace / "dist/generated/app.happ"

    with pytest.raises(PackageValidationError):
        export_happ_package(
            workspace,
            destination,
            created_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
            include_source=True,
        )

    assert not destination.parent.exists()


def test_mutable_workspace_cannot_live_in_runtime_or_app_data(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(AppDomainError) as runtime_error:
        service.init(
            service.paths.root / "workspace",
            app_id="local.stockagent.runtime-path",
            template="vanilla",
        )
    with pytest.raises(AppDomainError) as data_error:
        service.init(
            service.paths.app_data / "workspace",
            app_id="local.stockagent.data-path",
            template="vanilla",
        )

    assert runtime_error.value.code == "APP_PERMISSION_REQUIRED"
    assert data_error.value.code == "APP_PERMISSION_REQUIRED"


@pytest.mark.skipif(
    not (REPO_ROOT / "node_modules/vite").is_dir(),
    reason="root frontend dependencies are not installed",
)
def test_dashboard_template_runs_a_real_vite_production_build(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workspace = service.init(
        tmp_path / "dashboard",
        app_id="local.stockagent.dashboard",
        template="dashboard",
    )
    try:
        (workspace / "source/node_modules").symlink_to(
            REPO_ROOT / "node_modules",
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"dependency symlinks unavailable: {exc}")

    result = service.build(workspace)
    report = service.validate(workspace)

    assert result.files >= 2
    assert report.valid is True
