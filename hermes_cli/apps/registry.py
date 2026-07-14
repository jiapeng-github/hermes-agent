"""Atomic profile-scoped registry and immutable app version installation."""

from __future__ import annotations

import copy
import os
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from packaging.version import Version
from pydantic import ConfigDict, BaseModel, Field, ValidationError, model_validator

from utils import atomic_json_write

from .errors import AppRegistryError
from .locking import app_file_lock
from .manifest import validate_manifest_files
from .models import APP_ID_PATTERN, HANDLER_PATTERN, SEMVER_PATTERN, AppLineage, AppManifest, AppPermissions
from .paths import AppPaths
from .permissions import validate_permission_grants


MAX_REGISTRY_BYTES = 10 * 1024 * 1024
SignatureState = Literal["unsigned", "valid_trusted", "valid_untrusted", "invalid"]
ConflictMode = Literal["install", "update", "copy"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AppVersionRecord(_RegistryModel):
    version: str = Field(pattern=SEMVER_PATTERN)
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    installed_at: datetime = Field(strict=False)
    source_editable: bool
    signature_state: SignatureState
    trust_state: Literal["signed", "local_untrusted"]


class AppRecord(_RegistryModel):
    id: str = Field(pattern=APP_ID_PATTERN)
    active_version: str = Field(pattern=SEMVER_PATTERN)
    enabled: bool
    revision: int = Field(ge=1)
    requested_permissions: AppPermissions
    granted_permissions: AppPermissions
    versions: dict[str, AppVersionRecord]
    order: int = Field(ge=0)
    lineage: AppLineage = "user"
    service_handlers: list[str] = Field(default_factory=list, max_length=64)
    development_session: str | None = None
    last_opened_at: datetime | None = Field(default=None, strict=False)
    created_at: datetime = Field(strict=False)
    updated_at: datetime = Field(strict=False)

    @model_validator(mode="after")
    def validate_active_version(self) -> "AppRecord":
        if self.active_version not in self.versions:
            raise ValueError("active_version must identify an installed version")
        for key, record in self.versions.items():
            if key != record.version:
                raise ValueError("version map key must match record.version")
        if len(self.service_handlers) != len(set(self.service_handlers)):
            raise ValueError("service_handlers must not contain duplicates")
        if any(re.fullmatch(HANDLER_PATTERN, handler) is None for handler in self.service_handlers):
            raise ValueError("service_handlers contains an invalid handler")
        if self.lineage != "builtin" and self.service_handlers:
            raise ValueError("only built-in applications can inherit service handlers")
        return self


class AppRegistryDocument(_RegistryModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    apps: dict[str, AppRecord] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_app_keys(self) -> "AppRegistryDocument":
        for key, record in self.apps.items():
            if key != record.id:
                raise ValueError("app map key must match record.id")
        return self


class InstallResult(_RegistryModel):
    app: AppRecord
    installed: bool
    registry_revision: int


class AppRegistry:
    """Own registry reads and the package-rename plus registry-write transaction."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.paths = paths
        self._clock = clock

    def snapshot(self) -> AppRegistryDocument:
        self.paths.ensure()
        with app_file_lock(self.paths.registry_lock):
            return self._read_unlocked()

    def get(self, app_id: str) -> AppRecord | None:
        return self.snapshot().apps.get(app_id)

    def conflict_for(
        self,
        app_id: str,
        version: str,
        package_sha256: str,
    ) -> dict[str, str | None]:
        app = self.get(app_id)
        if app is None:
            return {
                "kind": "none",
                "existing_version": None,
                "incoming_version": version,
            }
        existing = app.versions.get(version)
        if existing is None:
            kind = "app_id_exists"
        elif existing.package_sha256 == package_sha256:
            kind = "version_exists"
        else:
            kind = "version_checksum_mismatch"
        return {
            "kind": kind,
            "existing_version": app.active_version,
            "incoming_version": version,
        }

    def install_staged_version(
        self,
        staging_dir: Path,
        manifest: AppManifest,
        *,
        package_sha256: str,
        source_included: bool,
        signature_state: SignatureState,
        grants: AppPermissions,
        conflict_mode: ConflictMode,
        development_session: str | None = None,
        lineage: AppLineage = "user",
        service_handlers: tuple[str, ...] = (),
    ) -> InstallResult:
        """Atomically publish one validated staging directory and registry revision."""
        if conflict_mode not in {"install", "update", "copy"}:
            raise AppRegistryError(
                "APP_REQUEST_INVALID",
                "invalid application conflict mode",
            )
        if not re.fullmatch(r"[a-f0-9]{64}", package_sha256):
            raise AppRegistryError(
                "APP_REQUEST_INVALID",
                "invalid package SHA-256",
            )
        if development_session is not None and (
            not development_session.strip()
            or len(development_session) > 256
            or any(ord(character) < 32 for character in development_session)
        ):
            raise AppRegistryError(
                "APP_REQUEST_INVALID",
                "invalid development session id",
            )
        self.paths.ensure()
        try:
            resolved_staging = staging_dir.resolve(strict=True)
            resolved_staging.relative_to(self.paths.staging.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "validated package staging is outside the active Profile",
            ) from exc
        if len(service_handlers) != len(set(service_handlers)) or any(
            re.fullmatch(HANDLER_PATTERN, handler) is None for handler in service_handlers
        ):
            raise AppRegistryError("APP_REQUEST_INVALID", "invalid inherited service handlers")
        if lineage != "builtin" and service_handlers:
            raise AppRegistryError(
                "APP_REQUEST_INVALID",
                "only built-in applications can inherit service handlers",
            )
        if staging_dir.is_symlink() or not resolved_staging.is_dir():
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "validated package staging must be a real directory",
            )
        validate_manifest_files(manifest, resolved_staging)
        validate_permission_grants(manifest.permissions, grants)
        with app_file_lock(self.paths.registry_lock):
            document = self._read_unlocked()
            data = document.model_dump(mode="python")
            existing = document.apps.get(manifest.id)
            version_record = existing.versions.get(manifest.version) if existing else None

            if existing is not None and (
                existing.lineage != lineage
                or tuple(existing.service_handlers) != tuple(service_handlers)
            ):
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "application lineage cannot change during install or update",
                    details={"app_id": manifest.id},
                )

            if version_record and version_record.package_sha256 != package_sha256:
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "the same app version is already installed with different content",
                    details={"app_id": manifest.id, "version": manifest.version},
                )
            if conflict_mode == "install" and existing is not None:
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "application id already exists; choose update or copy",
                    details={"app_id": manifest.id},
                )
            if conflict_mode == "update" and existing is None:
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "cannot update an application that is not installed",
                    details={"app_id": manifest.id},
                )
            if (
                conflict_mode == "update"
                and existing is not None
                and Version(manifest.version) <= Version(existing.active_version)
            ):
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "updates must be newer than the active version; use rollback for history",
                    details={
                        "active_version": existing.active_version,
                        "incoming_version": manifest.version,
                    },
                )
            if conflict_mode == "copy" and existing is not None:
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "copy target application id already exists",
                    details={"app_id": manifest.id},
                )

            now = self._clock()
            final_dir = self.paths.version(manifest.id, manifest.version)
            if version_record is not None and (
                final_dir.is_symlink() or not final_dir.is_dir()
            ):
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "registered application version is unavailable or unsafe",
                    details={"app_id": manifest.id, "version": manifest.version},
                )
            moved = False
            orphan_backup: Path | None = None
            if version_record is None:
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_dir.is_symlink() or (final_dir.exists() and not final_dir.is_dir()):
                    raise AppRegistryError(
                        "APP_VERSION_CONFLICT",
                        "version path exists with an unsafe type",
                        details={"app_id": manifest.id, "version": manifest.version},
                    )
                if final_dir.exists():
                    orphan_backup = self.paths.staging / f"orphan-{uuid.uuid4()}"
                    os.replace(final_dir, orphan_backup)
                try:
                    os.replace(resolved_staging, final_dir)
                except OSError as exc:
                    if orphan_backup is not None and orphan_backup.exists():
                        os.replace(orphan_backup, final_dir)
                    raise AppRegistryError(
                        "APP_IMPORT_REJECTED",
                        "failed to publish the validated application version",
                        retryable=True,
                    ) from exc
                moved = True

            trust_state = "signed" if signature_state == "valid_trusted" else "local_untrusted"
            new_version = AppVersionRecord(
                version=manifest.version,
                package_sha256=package_sha256,
                installed_at=now,
                source_editable=source_included,
                signature_state=signature_state,
                trust_state=trust_state,
            )
            if existing is None:
                versions = {manifest.version: new_version}
                app_record = AppRecord(
                    id=manifest.id,
                    active_version=manifest.version,
                    enabled=True,
                    revision=1,
                    requested_permissions=manifest.permissions,
                    granted_permissions=grants,
                    versions=versions,
                    order=len(document.apps),
                    lineage=lineage,
                    service_handlers=list(service_handlers),
                    development_session=development_session,
                    created_at=now,
                    updated_at=now,
                )
            else:
                versions = dict(existing.versions)
                versions[manifest.version] = version_record or new_version
                app_record = existing.model_copy(
                    update={
                        "active_version": manifest.version,
                        "enabled": True,
                        "revision": existing.revision + 1,
                        "requested_permissions": manifest.permissions,
                        "granted_permissions": grants,
                        "versions": versions,
                        "development_session": (
                            development_session
                            if development_session is not None
                            else existing.development_session
                        ),
                        "updated_at": now,
                    }
                )

            data["revision"] = document.revision + 1
            data["apps"] = copy.deepcopy(data["apps"])
            data["apps"][manifest.id] = app_record.model_dump(mode="python")
            updated = AppRegistryDocument.model_validate(data)
            try:
                self._write_unlocked(updated)
            except BaseException as exc:
                if moved:
                    shutil.rmtree(final_dir, ignore_errors=True)
                if orphan_backup is not None and orphan_backup.exists():
                    os.replace(orphan_backup, final_dir)
                if isinstance(exc, AppRegistryError):
                    raise
                raise AppRegistryError(
                    "APP_IMPORT_REJECTED",
                    "failed to commit the application registry",
                    retryable=True,
                ) from exc
            if orphan_backup is not None:
                shutil.rmtree(orphan_backup, ignore_errors=True)
            if moved:
                _make_tree_read_only(final_dir)
            return InstallResult(
                app=app_record,
                installed=moved,
                registry_revision=updated.revision,
            )

    def activate_version(
        self,
        manifest: AppManifest,
        *,
        grants: AppPermissions,
    ) -> AppRecord:
        """Atomically activate one installed version without changing app data."""
        app_id = manifest.id
        version = manifest.version
        target = self.paths.version(app_id, version)
        validate_manifest_files(manifest, target)
        validate_permission_grants(manifest.permissions, grants)
        self.paths.ensure()
        with app_file_lock(self.paths.registry_lock):
            document = self._read_unlocked()
            existing = document.apps.get(app_id)
            if existing is None:
                raise AppRegistryError("APP_NOT_FOUND", "application was not found")
            if version not in existing.versions:
                raise AppRegistryError("APP_NOT_FOUND", "application version was not found")
            if target.is_symlink() or not target.is_dir():
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "application version directory is unavailable or unsafe",
                    details={"app_id": app_id, "version": version},
                )
            if (
                existing.active_version == version
                and existing.requested_permissions == manifest.permissions
                and existing.granted_permissions == grants
            ):
                return existing

            now = self._clock()
            updated_app = existing.model_copy(
                update={
                    "active_version": version,
                    "revision": existing.revision + 1,
                    "requested_permissions": manifest.permissions,
                    "granted_permissions": grants,
                    "updated_at": now,
                }
            )
            data = document.model_dump(mode="python")
            data["revision"] = document.revision + 1
            data["apps"] = copy.deepcopy(data["apps"])
            data["apps"][app_id] = updated_app.model_dump(mode="python")
            self._write_unlocked(AppRegistryDocument.model_validate(data))
            return updated_app

    def uninstall(self, app_id: str, *, preserve_data: bool = True) -> AppRecord:
        """Remove a non-built-in app while keeping registry and files in sync."""
        package_root = self.paths.app_package(app_id)
        data_root = self.paths.app_runtime_data(app_id)
        self.paths.ensure()
        with app_file_lock(self.paths.registry_lock):
            document = self._read_unlocked()
            existing = document.apps.get(app_id)
            if existing is None:
                raise AppRegistryError("APP_NOT_FOUND", "application was not found")
            if existing.lineage == "builtin":
                raise AppRegistryError(
                    "APP_VERSION_CONFLICT",
                    "built-in applications cannot be uninstalled",
                    details={"app_id": app_id},
                )

            package_backup = self._stage_for_removal(package_root, "uninstall-package")
            try:
                data_backup = (
                    self._stage_for_removal(data_root, "uninstall-data")
                    if not preserve_data
                    else None
                )
            except BaseException:
                self._restore_staged(package_backup, package_root)
                raise
            data = document.model_dump(mode="python")
            data["revision"] = document.revision + 1
            data["apps"] = copy.deepcopy(data["apps"])
            del data["apps"][app_id]
            try:
                self._write_unlocked(AppRegistryDocument.model_validate(data))
            except BaseException:
                self._restore_staged(package_backup, package_root)
                self._restore_staged(data_backup, data_root)
                raise

        self._discard_staged(package_backup)
        self._discard_staged(data_backup)
        return existing

    def delete_data(self, app_id: str) -> bool:
        """Delete app-scoped runtime data without touching the installed package."""
        self.paths.ensure()
        with app_file_lock(self.paths.registry_lock):
            document = self._read_unlocked()
            if app_id not in document.apps:
                raise AppRegistryError("APP_NOT_FOUND", "application was not found")
            data_root = self.paths.app_runtime_data(app_id)
            staged = self._stage_for_removal(data_root, "delete-data")
        self._discard_staged(staged)
        return staged is not None

    def _stage_for_removal(self, target: Path, prefix: str) -> Path | None:
        if target.is_symlink():
            raise AppRegistryError(
                "APP_VERSION_CONFLICT",
                "application path has an unsafe type",
            )
        if not target.exists():
            return None
        if not target.is_dir():
            raise AppRegistryError(
                "APP_VERSION_CONFLICT",
                "application path has an unsafe type",
            )
        staged = self.paths.staging / f"{prefix}-{uuid.uuid4()}"
        try:
            os.replace(target, staged)
        except OSError as exc:
            raise AppRegistryError(
                "APP_VERSION_CONFLICT",
                "application files could not be prepared for removal",
                retryable=True,
            ) from exc
        return staged

    @staticmethod
    def _restore_staged(staged: Path | None, target: Path) -> None:
        if staged is None or not staged.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)

    @staticmethod
    def _discard_staged(staged: Path | None) -> None:
        if staged is not None:
            shutil.rmtree(staged, ignore_errors=True)

    def _read_unlocked(self) -> AppRegistryDocument:
        path = self.paths.registry
        if not path.exists():
            return AppRegistryDocument()
        if path.is_symlink():
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "application registry cannot be a symlink",
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "application registry could not be read",
                retryable=True,
            ) from exc
        if len(raw) > MAX_REGISTRY_BYTES:
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "application registry exceeds its safety limit",
            )
        try:
            return AppRegistryDocument.model_validate_json(raw)
        except ValidationError as exc:
            raise AppRegistryError(
                "APP_IMPORT_REJECTED",
                "application registry is invalid; refusing to overwrite it",
                details={"issues": len(exc.errors())},
            ) from exc

    def _write_unlocked(self, document: AppRegistryDocument) -> None:
        atomic_json_write(
            self.paths.registry,
            document.model_dump(mode="json"),
            indent=2,
            mode=0o600,
            sort_keys=True,
        )


def _make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            path.chmod(0o700 if path.is_dir() else 0o400)
        except OSError:
            pass
    try:
        root.chmod(0o700)
    except OSError:
        pass


__all__ = [
    "AppRecord",
    "AppRegistry",
    "AppRegistryDocument",
    "AppVersionRecord",
    "ConflictMode",
    "InstallResult",
    "SignatureState",
]
