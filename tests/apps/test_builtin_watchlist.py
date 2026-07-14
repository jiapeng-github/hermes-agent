from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hermes_cli.apps.catalog import (
    COMPANY_ANALYSIS_APP_ID,
    COMPANY_ANALYSIS_SERVICE_HANDLERS,
    INDUSTRY_MONITOR_APP_ID,
    INDUSTRY_MONITOR_SERVICE_HANDLERS,
    WATCHLIST_APP_ID,
    WATCHLIST_SERVICE_HANDLERS,
    builtin_app,
    ensure_builtin_apps,
)
from hermes_cli.apps.errors import AppDomainError
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths
from hermes_cli.apps.workspace import validate_app_bundle

from .runtime_fixtures import runtime_app


def test_finance_builtins_install_with_exact_runtime_owned_lineage(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")
    manager = AppManager(paths)

    items = manager.list_apps()["items"]
    expected = {
        COMPANY_ANALYSIS_APP_ID: COMPANY_ANALYSIS_SERVICE_HANDLERS,
        INDUSTRY_MONITOR_APP_ID: INDUSTRY_MONITOR_SERVICE_HANDLERS,
        WATCHLIST_APP_ID: WATCHLIST_SERVICE_HANDLERS,
    }
    expected_names = {
        COMPANY_ANALYSIS_APP_ID: "上市公司基本面分析",
        INDUSTRY_MONITOR_APP_ID: "行业轮动于资金流向监控",
        WATCHLIST_APP_ID: "自选股盯盘看板",
    }

    assert {item["id"] for item in items} == set(expected)
    assert {item["id"]: item["name"] for item in items} == expected_names
    assert all(item["status"] == "ready" for item in items)
    assert all(item["trust_state"] == "builtin" for item in items)
    for app_id, handlers in expected.items():
        record = manager.registry.get(app_id)
        assert record is not None
        assert record.lineage == "builtin"
        assert tuple(record.service_handlers) == handlers
        assert record.versions[record.active_version].trust_state == "signed"


def test_concurrent_first_lists_reuse_one_atomic_builtin_install(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: AppManager(paths).list_apps(), range(2)))

    expected = {COMPANY_ANALYSIS_APP_ID, INDUSTRY_MONITOR_APP_ID, WATCHLIST_APP_ID}
    assert [{item["id"] for item in result["items"]} for result in results] == [expected, expected]
    for app_id in expected:
        record = AppManager(paths).registry.get(app_id)
        assert record is not None
        assert set(record.versions) == {"1.0.1"}


def test_reserved_builtin_id_cannot_replace_user_lineage(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    staged, manifest, grants = runtime_app(paths.staging)
    manager = AppManager(paths)
    manager.registry.install_staged_version(
        staged,
        manifest,
        package_sha256="a" * 64,
        source_included=True,
        signature_state="unsigned",
        grants=grants,
        conflict_mode="install",
    )

    with pytest.raises(AppDomainError, match="reserved built-in id"):
        ensure_builtin_apps(paths, manager.registry)
    assert manifest.id == WATCHLIST_APP_ID


@pytest.mark.parametrize(
    "app_id",
    [COMPANY_ANALYSIS_APP_ID, INDUSTRY_MONITOR_APP_ID, WATCHLIST_APP_ID],
)
def test_builtin_action_schemas_are_draft_2020_12_and_local(app_id: str) -> None:
    definition = builtin_app(app_id)
    assert definition is not None
    manifest = definition.load_manifest()

    for action in manifest.actions.values():
        for relative in (action.input_schema, action.output_schema):
            path = definition.root / relative
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            assert path.resolve().is_relative_to(definition.root.resolve())

    report = validate_app_bundle(definition.root, manifest)
    assert report.valid is True
    assert not [issue for issue in report.issues if issue.severity == "warning"]

    css = (definition.root / "dist/assets/app.css").read_text(encoding="utf-8")
    assert ':root[data-theme="dark"]' in css
    assert "@media (max-width:" in css and "980px)" in css
    assert "@media (max-width:" in css and "640px)" in css
