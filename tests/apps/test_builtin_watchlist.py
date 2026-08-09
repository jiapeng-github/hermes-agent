from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hermes_cli.apps.catalog import (
    COMPANY_ANALYSIS_APP_ID,
    INDUSTRY_MONITOR_APP_ID,
    LEGACY_BUILTIN_APP_IDS,
    STOCK_DEEP_ANALYSIS_APP_ID,
    ensure_builtin_apps,
)
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths

from .runtime_fixtures import runtime_app


def test_removed_finance_builtins_are_not_installed(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")
    manager = AppManager(paths)

    items = manager.list_apps()["items"]
    assert items == []
    assert all(manager.registry.get(app_id) is None for app_id in RETIRED_FINANCE_APP_IDS)


def test_concurrent_first_lists_reuse_one_atomic_builtin_install(
    tmp_path: Path,
) -> None:
    paths = AppPaths(tmp_path / "profile")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: AppManager(paths).list_apps(), range(2)))

    expected = set()
    assert [{item["id"] for item in result["items"]} for result in results] == [
        expected,
        expected,
    ]


RETIRED_FINANCE_APP_IDS = (
    COMPANY_ANALYSIS_APP_ID,
    INDUSTRY_MONITOR_APP_ID,
    STOCK_DEEP_ANALYSIS_APP_ID,
)


@pytest.mark.parametrize("app_id", RETIRED_FINANCE_APP_IDS)
def test_removed_finance_builtin_and_data_are_retired(tmp_path: Path, app_id: str) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    staged, manifest, grants = runtime_app(paths.staging)
    manager = AppManager(paths)
    manager.registry.install_staged_version(
        staged,
        manifest.model_copy(update={"id": app_id}),
        package_sha256="c" * 64,
        source_included=False,
        signature_state="valid_trusted",
        grants=grants,
        conflict_mode="install",
        lineage="builtin",
        service_handlers=(),
    )
    data = paths.app_runtime_data(app_id)
    data.mkdir(parents=True)
    (data / "stale.json").write_text("{}", encoding="utf-8")

    manager.list_apps()

    assert manager.registry.get(app_id) is None
    assert not paths.app_package(app_id).exists()
    assert not data.exists()


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
        service_handlers=(),
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


def test_retired_watchlist_id_can_be_owned_by_user_lineage(tmp_path: Path) -> None:
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

    ensure_builtin_apps(paths, manager.registry)
    record = manager.registry.get(manifest.id)
    assert record is not None
    assert record.lineage == "user"
