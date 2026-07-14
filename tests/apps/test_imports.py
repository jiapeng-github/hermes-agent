from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hermes_cli.apps.errors import (
    AppRegistryError,
    ImportPlanError,
    PermissionGrantError,
)
from hermes_cli.apps.models import AppPermissions
from hermes_cli.apps.package import (
    HappImportService,
    ImportConfirmation,
    SigningKey,
)
from hermes_cli.apps.paths import AppPaths

from .happ_fixtures import build_happ, manifest_data


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _service(
    tmp_path: Path,
    clock: MutableClock | None = None,
    *,
    signing_keys=None,
) -> HappImportService:
    paths = AppPaths(tmp_path / "profile")
    return HappImportService(
        paths,
        clock=clock or MutableClock(),
        signing_keys=signing_keys,
    )


def _confirmation(plan, *, mode="install", copy_id=None, grants=None):
    return ImportConfirmation(
        package_sha256=plan.package_sha256,
        conflict_mode=mode,
        copy_app_id=copy_id,
        grants=grants or plan.requested_permissions,
    )


def test_analyze_creates_plan_but_does_not_install(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "watchlist.happ")
    service = _service(tmp_path)

    plan = service.analyze(package)

    assert plan.app.id == "ai.hermes.watchlist"
    assert plan.conflict.kind == "none"
    assert service.registry.get(plan.app.id) is None
    assert not service.paths.version(plan.app.id, plan.app.version).exists()
    assert (service.paths.import_plan(plan.import_id) / "package.happ").is_file()
    assert "created_at" not in plan.public_dict()


def test_source_less_package_is_valid_and_marked_read_only(tmp_path: Path) -> None:
    manifest = manifest_data()
    manifest.pop("source")
    package = build_happ(
        tmp_path / "read-only.happ",
        manifest=manifest,
        include_source=False,
    )
    service = _service(tmp_path)

    plan = service.analyze(package)

    assert plan.source_included is False
    assert any("不含源码" in warning for warning in plan.warnings)


def test_confirm_revalidates_and_atomically_installs(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "watchlist.happ")
    service = _service(tmp_path)
    plan = service.analyze(package)

    result = service.confirm(plan.import_id, _confirmation(plan))

    installed = service.paths.version(plan.app.id, plan.app.version)
    assert result.installed is True
    assert result.registry_revision == 1
    assert (installed / "app.yaml").is_file()
    assert (installed / "dist/index.html").is_file()
    assert not (installed / "happ.json").exists()
    assert not (installed / "checksums.json").exists()
    assert not service.paths.import_plan(plan.import_id).exists()
    assert service.registry.get(plan.app.id).active_version == "1.0.0"


def test_confirm_rejects_permission_escalation(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "watchlist.happ")
    service = _service(tmp_path)
    plan = service.analyze(package)
    grants = AppPermissions.model_validate(
        {
            "agent": True,
            "mcp_servers": ["mx-ds-mcp", "other-mcp"],
            "storage": {"mode": "persistent", "quota_mb": 25},
        }
    )

    with pytest.raises(PermissionGrantError):
        service.confirm(plan.import_id, _confirmation(plan, grants=grants))

    assert service.registry.get(plan.app.id) is None


def test_expired_plan_is_deleted(tmp_path: Path) -> None:
    clock = MutableClock()
    package = build_happ(tmp_path / "watchlist.happ")
    service = _service(tmp_path, clock)
    plan = service.analyze(package)
    clock.now += timedelta(minutes=16)

    with pytest.raises(ImportPlanError) as caught:
        service.confirm(plan.import_id, _confirmation(plan))

    assert caught.value.code == "APP_IMPORT_EXPIRED"
    assert not service.paths.import_plan(plan.import_id).exists()


def test_new_analysis_cleans_other_expired_plans(tmp_path: Path) -> None:
    clock = MutableClock()
    service = _service(tmp_path, clock)
    first = service.analyze(build_happ(tmp_path / "first-plan.happ"))
    clock.now += timedelta(minutes=16)

    second = service.analyze(build_happ(tmp_path / "second-plan.happ"))

    assert not service.paths.import_plan(first.import_id).exists()
    assert service.paths.import_plan(second.import_id).exists()


def test_confirm_detects_staged_package_tampering(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "watchlist.happ")
    service = _service(tmp_path)
    plan = service.analyze(package)
    staged = service.paths.import_plan(plan.import_id) / "package.happ"
    with staged.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ImportPlanError) as caught:
        service.confirm(plan.import_id, _confirmation(plan))

    assert caught.value.code == "APP_IMPORT_REJECTED"
    assert service.registry.get(plan.app.id) is None
    assert not service.paths.import_plan(plan.import_id).exists()


def test_update_installs_new_immutable_version(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.analyze(build_happ(tmp_path / "v1.happ"))
    service.confirm(first.import_id, _confirmation(first))
    second_manifest = manifest_data(version="1.1.0")
    second = service.analyze(
        build_happ(tmp_path / "v2.happ", manifest=second_manifest)
    )

    assert second.conflict.kind == "app_id_exists"
    result = service.confirm(second.import_id, _confirmation(second, mode="update"))

    assert result.app.active_version == "1.1.0"
    assert set(result.app.versions) == {"1.0.0", "1.1.0"}
    assert service.paths.version(second.app.id, "1.0.0").exists()
    assert service.paths.version(second.app.id, "1.1.0").exists()


def test_update_cannot_downgrade_active_version(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.analyze(build_happ(tmp_path / "v1.happ"))
    service.confirm(first.import_id, _confirmation(first))
    second = service.analyze(
        build_happ(tmp_path / "v2.happ", manifest=manifest_data(version="1.1.0"))
    )
    service.confirm(second.import_id, _confirmation(second, mode="update"))
    older = service.analyze(
        build_happ(tmp_path / "older.happ", manifest=manifest_data(version="0.9.0"))
    )

    with pytest.raises(AppRegistryError) as caught:
        service.confirm(older.import_id, _confirmation(older, mode="update"))

    assert caught.value.code == "APP_VERSION_CONFLICT"
    assert service.registry.get(older.app.id).active_version == "1.1.0"


def test_same_version_different_checksum_is_never_overwritten(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.analyze(build_happ(tmp_path / "first.happ"))
    service.confirm(first.import_id, _confirmation(first))
    changed = manifest_data(description="内容已经变化")
    second = service.analyze(build_happ(tmp_path / "changed.happ", manifest=changed))

    assert second.conflict.kind == "version_checksum_mismatch"
    with pytest.raises(AppRegistryError) as caught:
        service.confirm(second.import_id, _confirmation(second, mode="update"))

    assert caught.value.code == "APP_VERSION_CONFLICT"
    installed_manifest = yaml.safe_load(
        service.paths.version(second.app.id, "1.0.0").joinpath("app.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert installed_manifest["description"] == "自选股应用"


def test_copy_rewrites_only_installed_manifest_identity(tmp_path: Path) -> None:
    service = _service(tmp_path)
    plan = service.analyze(build_happ(tmp_path / "copy.happ"))

    result = service.confirm(
        plan.import_id,
        _confirmation(plan, mode="copy", copy_id="ai.hermes.watchlist-copy"),
    )

    assert result.app.id == "ai.hermes.watchlist-copy"
    copied = service.paths.version("ai.hermes.watchlist-copy", "1.0.0")
    copied_manifest = yaml.safe_load((copied / "app.yaml").read_text(encoding="utf-8"))
    assert copied_manifest["id"] == "ai.hermes.watchlist-copy"
    assert service.registry.get("ai.hermes.watchlist") is None


def test_copy_downgrades_signature_trust_after_manifest_rewrite(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    service = _service(
        tmp_path,
        signing_keys={"official-test": SigningKey(public_key, trusted=True)},
    )
    plan = service.analyze(
        build_happ(
            tmp_path / "signed-copy.happ",
            signing_key=("official-test", private_key),
        )
    )
    assert plan.signature_state == "valid_trusted"

    result = service.confirm(
        plan.import_id,
        _confirmation(plan, mode="copy", copy_id="ai.hermes.signed-copy"),
    )

    version = result.app.versions["1.0.0"]
    assert version.signature_state == "unsigned"
    assert version.trust_state == "local_untrusted"


def test_registry_write_failure_rolls_back_published_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    plan = service.analyze(build_happ(tmp_path / "rollback.happ"))

    def fail_write(_document):
        raise OSError("disk full")

    monkeypatch.setattr(service.registry, "_write_unlocked", fail_write)
    with pytest.raises(AppRegistryError) as caught:
        service.confirm(plan.import_id, _confirmation(plan))

    assert caught.value.retryable is True
    assert not service.paths.version(plan.app.id, plan.app.version).exists()
    assert service.paths.import_plan(plan.import_id).exists()


def test_retry_recovers_unregistered_directory_left_by_crash(tmp_path: Path) -> None:
    service = _service(tmp_path)
    plan = service.analyze(build_happ(tmp_path / "recovery.happ"))
    orphan = service.paths.version(plan.app.id, plan.app.version)
    orphan.mkdir(parents=True)
    (orphan / "partial.txt").write_text("crash", encoding="utf-8")

    result = service.confirm(plan.import_id, _confirmation(plan))

    assert result.installed is True
    assert not (orphan / "partial.txt").exists()
    assert (orphan / "dist/index.html").is_file()


def test_imports_are_isolated_between_profiles(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "profile-isolation.happ")
    service_a = HappImportService(AppPaths(tmp_path / "profile-a"), clock=MutableClock())
    service_b = HappImportService(AppPaths(tmp_path / "profile-b"), clock=MutableClock())
    plan_a = service_a.analyze(package)

    service_a.confirm(plan_a.import_id, _confirmation(plan_a))

    assert service_a.registry.get(plan_a.app.id) is not None
    assert service_b.registry.get(plan_a.app.id) is None
    assert not service_b.paths.version(plan_a.app.id, plan_a.app.version).exists()
