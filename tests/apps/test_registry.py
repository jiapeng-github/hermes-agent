from __future__ import annotations

from pathlib import Path
import threading

import pytest

from hermes_cli.apps.errors import AppRegistryError
from hermes_cli.apps.manifest import parse_manifest
from hermes_cli.apps.paths import AppPaths
from hermes_cli.apps.locking import AppLockTimeout, app_file_lock
from hermes_cli.apps.registry import AppRegistry

from .happ_fixtures import manifest_data


def test_paths_are_profile_scoped_and_separate_package_from_data(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile-a")

    assert paths.version("ai.hermes.watchlist", "1.0.0") == (
        tmp_path
        / "profile-a/apps/packages/ai.hermes.watchlist/versions/1.0.0"
    )
    assert paths.app_runtime_data("ai.hermes.watchlist") == (
        tmp_path / "profile-a/app-data/ai.hermes.watchlist"
    )


@pytest.mark.parametrize(
    ("app_id", "version"),
    [("../../escape", "1.0.0"), ("ai.hermes.valid", "../../escape")],
)
def test_paths_reject_untrusted_identifiers(
    tmp_path: Path,
    app_id: str,
    version: str,
) -> None:
    paths = AppPaths(tmp_path)

    with pytest.raises(ValueError):
        paths.version(app_id, version)


def test_corrupt_registry_fails_closed_without_overwrite(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path)
    paths.ensure()
    paths.registry.write_text("not-json", encoding="utf-8")
    registry = AppRegistry(paths)

    with pytest.raises(AppRegistryError):
        registry.snapshot()

    assert paths.registry.read_text(encoding="utf-8") == "not-json"


def test_registry_symlink_is_rejected(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    target = tmp_path / "outside.json"
    target.write_text('{"schema_version":1,"revision":0,"apps":{}}', encoding="utf-8")
    try:
        paths.registry.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(AppRegistryError):
        AppRegistry(paths).snapshot()


def test_profile_lock_serializes_concurrent_writers(tmp_path: Path) -> None:
    lock_path = tmp_path / "registry.lock"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_writer() -> None:
        with app_file_lock(lock_path):
            first_entered.set()
            release_first.wait(timeout=2)

    def second_writer() -> None:
        first_entered.wait(timeout=2)
        with app_file_lock(lock_path):
            second_entered.set()

    first = threading.Thread(target=first_writer)
    second = threading.Thread(target=second_writer)
    first.start()
    second.start()
    assert first_entered.wait(timeout=1)
    assert not second_entered.wait(timeout=0.05)
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert second_entered.is_set()


def test_profile_lock_has_bounded_timeout(tmp_path: Path) -> None:
    lock_path = tmp_path / "registry.lock"
    result: list[BaseException] = []

    def contender() -> None:
        try:
            with app_file_lock(lock_path, timeout_seconds=0.05):
                pass
        except BaseException as exc:
            result.append(exc)

    with app_file_lock(lock_path):
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=1)

    assert len(result) == 1
    assert isinstance(result[0], AppLockTimeout)


def test_registry_refuses_staging_outside_active_profile(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "profile")
    paths.ensure()
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = parse_manifest(manifest_data())

    with pytest.raises(AppRegistryError, match="outside the active Profile"):
        AppRegistry(paths).install_staged_version(
            outside,
            manifest,
            package_sha256="0" * 64,
            source_included=True,
            signature_state="unsigned",
            grants=manifest.permissions,
            conflict_mode="install",
        )
