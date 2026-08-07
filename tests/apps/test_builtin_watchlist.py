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
    LEGACY_BUILTIN_APP_IDS,
    STOCK_DEEP_ANALYSIS_APP_ID,
    STOCK_DEEP_ANALYSIS_SERVICE_HANDLERS,
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


def test_finance_builtins_install_with_exact_runtime_owned_lineage(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")
    manager = AppManager(paths)

    items = manager.list_apps()["items"]
    expected = {
        COMPANY_ANALYSIS_APP_ID: COMPANY_ANALYSIS_SERVICE_HANDLERS,
        INDUSTRY_MONITOR_APP_ID: INDUSTRY_MONITOR_SERVICE_HANDLERS,
        STOCK_DEEP_ANALYSIS_APP_ID: STOCK_DEEP_ANALYSIS_SERVICE_HANDLERS,
        WATCHLIST_APP_ID: WATCHLIST_SERVICE_HANDLERS,
    }
    expected_names = {
        COMPANY_ANALYSIS_APP_ID: "上市公司基本面分析",
        INDUSTRY_MONITOR_APP_ID: "行业轮动和资金流向监控",
        STOCK_DEEP_ANALYSIS_APP_ID: "个股三维深度分析",
        WATCHLIST_APP_ID: "自选股盯盘看板",
    }

    assert {item["id"] for item in items} == set(expected)
    assert {item["id"]: item["name"] for item in items} == expected_names
    assert all(item["id"].startswith("ai.stocksense.") for item in items)
    assert {item["id"]: item["version"] for item in items} == {
        COMPANY_ANALYSIS_APP_ID: "1.0.1",
        INDUSTRY_MONITOR_APP_ID: "1.0.1",
        STOCK_DEEP_ANALYSIS_APP_ID: "1.0.1",
        WATCHLIST_APP_ID: "1.0.1",
    }
    assert all(item["status"] == "ready" for item in items)
    assert all(item["trust_state"] == "builtin" for item in items)
    for app_id, handlers in expected.items():
        record = manager.registry.get(app_id)
        assert record is not None
        assert record.lineage == "builtin"
        assert tuple(record.service_handlers) == handlers
        assert record.versions[record.active_version].trust_state == "signed"
        definition = builtin_app(app_id)
        assert definition is not None
        runtime = (definition.root / "dist/assets/runtime.js").read_text(
            encoding="utf-8"
        )
        assert "publishCurrentPage" in runtime


def test_concurrent_first_lists_reuse_one_atomic_builtin_install(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: AppManager(paths).list_apps(), range(2)))

    expected = {
        COMPANY_ANALYSIS_APP_ID,
        INDUSTRY_MONITOR_APP_ID,
        STOCK_DEEP_ANALYSIS_APP_ID,
        WATCHLIST_APP_ID,
    }
    assert [{item["id"] for item in result["items"]} for result in results] == [
        expected,
        expected,
    ]
    for app_id in expected:
        record = AppManager(paths).registry.get(app_id)
        assert record is not None
        definition = builtin_app(app_id)
        assert definition is not None
        assert set(record.versions) == {definition.load_manifest().version}


def test_legacy_builtin_id_and_runtime_data_are_retired(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    staged, manifest, grants = runtime_app(paths.staging)
    legacy_id = LEGACY_BUILTIN_APP_IDS[-1]
    legacy_manifest = manifest.model_copy(update={"id": legacy_id})
    manager = AppManager(paths)
    manager.registry.install_staged_version(
        staged,
        legacy_manifest,
        package_sha256="b" * 64,
        source_included=False,
        signature_state="valid_trusted",
        grants=grants,
        conflict_mode="install",
        lineage="builtin",
        service_handlers=WATCHLIST_SERVICE_HANDLERS,
    )
    legacy_data = paths.app_runtime_data(legacy_id)
    legacy_data.mkdir(parents=True)
    (legacy_data / "watchlist.json").write_text("[]", encoding="utf-8")

    ids = {item["id"] for item in manager.list_apps()["items"]}

    assert legacy_id not in ids
    assert manager.registry.get(legacy_id) is None
    assert not paths.app_package(legacy_id).exists()
    assert not legacy_data.exists()


def test_orphaned_legacy_builtin_data_is_removed(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")
    legacy_data = paths.app_runtime_data(LEGACY_BUILTIN_APP_IDS[0])
    legacy_data.mkdir(parents=True)
    (legacy_data / "cache.json").write_text("{}", encoding="utf-8")

    AppManager(paths).list_apps()

    assert not legacy_data.exists()


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
    [
        COMPANY_ANALYSIS_APP_ID,
        INDUSTRY_MONITOR_APP_ID,
        STOCK_DEEP_ANALYSIS_APP_ID,
        WATCHLIST_APP_ID,
    ],
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


def test_stock_deep_analysis_starts_empty_and_uses_compact_available_data_views() -> (
    None
):
    definition = builtin_app(STOCK_DEEP_ANALYSIS_APP_ID)
    assert definition is not None

    html = (definition.root / "dist/index.html").read_text(encoding="utf-8")
    script = (definition.root / "dist/assets/app.js").read_text(encoding="utf-8")

    assert 'id="query" value=""' in html
    assert "stock-deep-analysis.last-query" not in script
    assert 'id="fundamental-detail"' in html
    assert "data.peers" in script
    assert 'id="capital-signals"' in html
    assert "turnover_rate_percent" in script
    assert "main_net_inflow" not in script
    assert "northbound_" not in script
    assert 'id="research-summary"' in html
    assert "article-dialog" not in html
    assert "openArticle" not in script
