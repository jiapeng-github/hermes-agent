"""Single application-domain facade shared by CLI and future management routes."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from .catalog import ensure_builtin_apps
from .errors import AppDomainError, ManifestValidationError
from .manifest import load_manifest
from .models import AppManifest, AppPermissions
from .package import (
    HappImportService,
    ImportConfirmation,
    ImportPlan,
    PackageExport,
    export_happ_package,
    inspect_happ_package,
)
from .paths import AppPaths
from .registry import AppRecord, AppRegistry
from .runtime.supervisor import AppRuntimeSupervisor
from .workspace import APP_RUNTIME_VERSION, AppWorkspaceService, ValidationReport


_TRANSPORT_FILES = ("happ.json", "checksums.json", "signature.json")


class AppManager:
    """Coordinate workspace, package, registry, and import operations."""

    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        registry: AppRegistry | None = None,
        imports: HappImportService | None = None,
    ):
        self.paths = paths or AppPaths.active_profile()
        self.registry = registry or AppRegistry(self.paths)
        self.imports = imports or HappImportService(self.paths, registry=self.registry)
        self.workspaces = AppWorkspaceService(self.paths, self.registry)

    def list_apps(self, *, query: str | None = None) -> dict[str, Any]:
        if query is not None and len(query) > 200:
            raise AppDomainError("APP_REQUEST_INVALID", "application query exceeds 200 characters")
        ensure_builtin_apps(self.paths, self.registry)
        document = self.registry.snapshot()
        folded_query = query.casefold().strip() if query else ""
        items: list[dict[str, Any]] = []
        records = sorted(document.apps.values(), key=lambda record: (record.order, record.id))
        for record in records:
            summary = self._summary(record)
            haystack = f"{summary['id']} {summary['name']} {summary['description']}".casefold()
            if folded_query and folded_query not in haystack:
                continue
            items.append(summary)
        return {"items": items, "next_cursor": None}

    def inspect(self, app_id: str) -> dict[str, Any]:
        ensure_builtin_apps(self.paths, self.registry)
        record = self._require_record(app_id)
        detail = self._detail(record)
        active_root = self.paths.version(app_id, record.active_version)
        files = [
            path.relative_to(active_root).as_posix()
            for path in sorted(active_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
        return {
            "app": detail,
            "versions": self.list_versions(app_id),
            "development_session": record.development_session,
            "active_path": str(active_root),
            "files": files[:5000],
        }

    def get(self, app_id: str) -> dict[str, Any]:
        ensure_builtin_apps(self.paths, self.registry)
        return self._detail(self._require_record(app_id))

    def list_versions(self, app_id: str) -> list[dict[str, Any]]:
        record = self._require_record(app_id)
        versions = sorted(
            record.versions.values(),
            key=lambda item: Version(item.version),
            reverse=True,
        )
        items: list[dict[str, Any]] = []
        for version_record in versions:
            compatible = False
            try:
                manifest = self._load_installed_manifest(app_id, version_record.version)
                compatible = _is_compatible(manifest)
            except (AppDomainError, ManifestValidationError, InvalidVersion):
                pass
            items.append(
                {
                    "version": version_record.version,
                    "active": version_record.version == record.active_version,
                    "compatible": compatible,
                    "source_editable": version_record.source_editable,
                    "installed_at": version_record.installed_at.isoformat(),
                    "checksum": version_record.package_sha256,
                }
            )
        return items

    def publish(
        self,
        workspace: str | Path,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        root = self.workspaces.resolve(workspace)
        report = self.workspaces.require_valid(root)
        manifest = load_manifest(root / "app.yaml", app_root=root, lineage="user")
        metadata = self.workspaces.metadata(root)
        if metadata.app_id != manifest.id:
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "workspace identity does not match its creation or checkout context",
            )
        existing = self.registry.get(manifest.id)
        if existing is not None and Version(manifest.version) <= Version(
            existing.active_version
        ):
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "published version must be greater than the active version; use rollback to activate history",
                details={
                    "active_version": existing.active_version,
                    "workspace_version": manifest.version,
                },
            )

        self.paths.ensure()
        publish_root = self.paths.staging / f"publish-{uuid.uuid4()}"
        package_path = publish_root / "application.happ"
        content = publish_root / "content"
        publish_root.mkdir(mode=0o700)
        try:
            exported = export_happ_package(
                root,
                package_path,
                created_at=metadata.created_at,
                include_source=True,
                lineage="user",
            )
            inspection = inspect_happ_package(package_path, content)
            if inspection.package_sha256 != exported.package_sha256:
                raise AppDomainError(
                    "APP_IMPORT_REJECTED",
                    "published package changed during validation",
                )
            for name in _TRANSPORT_FILES:
                transport = content / name
                if transport.exists():
                    transport.unlink()

            grants = (
                _narrow_permissions(existing.granted_permissions, manifest.permissions)
                if existing is not None
                else _empty_permissions()
            )
            result = self.registry.install_staged_version(
                content,
                inspection.manifest,
                package_sha256=inspection.package_sha256,
                source_included=True,
                signature_state="unsigned",
                grants=grants,
                conflict_mode="update" if existing is not None else "install",
                development_session=session_id,
            )
            return {
                "app": self._detail(result.app),
                "installed": result.installed,
                "registry_revision": result.registry_revision,
                "checksum": inspection.package_sha256,
                "market_visible": True,
                "validation": report.model_dump(mode="json"),
            }
        finally:
            shutil.rmtree(publish_root, ignore_errors=True)

    def rollback(self, app_id: str, version: str) -> dict[str, Any]:
        existing = self._require_record(app_id)
        manifest = self._load_installed_manifest(app_id, version, record=existing)
        grants = _narrow_permissions(existing.granted_permissions, manifest.permissions)
        updated = self.registry.activate_version(
            manifest,
            grants=grants,
        )
        return self._detail(updated)

    def export(
        self,
        app_id: str,
        destination: str | Path,
        *,
        version: str | None = None,
        include_source: bool | None = None,
        overwrite: bool = False,
    ) -> PackageExport:
        record = self._require_record(app_id)
        if record.lineage == "builtin":
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "built-in service applications cannot be exported as portable user applications",
            )
        selected = version or record.active_version
        version_record = record.versions.get(selected)
        if version_record is None:
            raise AppDomainError("APP_NOT_FOUND", "application version was not found")
        source_included = (
            version_record.source_editable if include_source is None else include_source
        )
        if source_included and not version_record.source_editable:
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "selected application version has no editable source",
            )
        return export_happ_package(
            self.paths.version(app_id, selected),
            destination,
            created_at=version_record.installed_at,
            include_source=source_included,
            lineage="imported",
            overwrite=overwrite,
        )

    def analyze_import(self, package_path: str | Path) -> ImportPlan:
        return self.imports.analyze(package_path)

    def get_import_plan(self, import_id: str) -> ImportPlan:
        return self.imports.get_plan(import_id)

    def confirm_import(
        self,
        import_id: str,
        confirmation: ImportConfirmation,
    ) -> dict[str, Any]:
        result = self.imports.confirm(import_id, confirmation)
        return {
            "app": self._detail(result.app),
            "installed": result.installed,
            "registry_revision": result.registry_revision,
        }

    def discard_import(self, import_id: str) -> None:
        self.imports.discard(import_id)

    def validate(self, workspace: str | Path) -> ValidationReport:
        return self.workspaces.validate(workspace)

    def launch(
        self,
        app_id: str,
        supervisor: AppRuntimeSupervisor,
    ) -> dict[str, Any]:
        ensure_builtin_apps(self.paths, self.registry)
        record = self._require_record(app_id)
        if not record.enabled:
            raise AppDomainError("APP_DISABLED", "application is disabled")
        manifest = self._load_installed_manifest(
            app_id,
            record.active_version,
            record=record,
        )
        if not _is_compatible(manifest):
            raise AppDomainError(
                "APP_RUNTIME_INCOMPATIBLE",
                "application requires a newer runtime",
            )
        return supervisor.launch(
            record,
            manifest,
            self.paths.version(app_id, record.active_version),
        )

    def stop(self, app_id: str, supervisor: AppRuntimeSupervisor) -> None:
        ensure_builtin_apps(self.paths, self.registry)
        self._require_record(app_id)
        supervisor.stop(app_id)

    def uninstall(
        self,
        app_id: str,
        supervisor: AppRuntimeSupervisor,
        *,
        preserve_data: bool = True,
    ) -> None:
        ensure_builtin_apps(self.paths, self.registry)
        record = self._require_record(app_id)
        if record.lineage == "builtin":
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "built-in applications cannot be uninstalled",
                details={"app_id": app_id},
            )
        supervisor.stop(app_id)
        self.registry.uninstall(app_id, preserve_data=preserve_data)

    def delete_data(self, app_id: str, supervisor: AppRuntimeSupervisor) -> None:
        ensure_builtin_apps(self.paths, self.registry)
        self._require_record(app_id)
        supervisor.stop(app_id)
        self.registry.delete_data(app_id)

    def _require_record(self, app_id: str) -> AppRecord:
        try:
            record = self.registry.get(app_id)
        except ValueError as exc:
            raise AppDomainError("APP_REQUEST_INVALID", "invalid application id") from exc
        if record is None:
            raise AppDomainError("APP_NOT_FOUND", "application was not found")
        return record

    def _load_installed_manifest(
        self,
        app_id: str,
        version: str,
        *,
        record: AppRecord | None = None,
    ) -> AppManifest:
        root = self.paths.version(app_id, version)
        if root.is_symlink() or not root.is_dir():
            raise AppDomainError("APP_NOT_FOUND", "application version was not found")
        owner = record or self._require_record(app_id)
        return load_manifest(
            root / "app.yaml",
            app_root=root,
            lineage=owner.lineage,
            allowed_service_handlers=frozenset(owner.service_handlers),
        )

    def _summary(self, record: AppRecord) -> dict[str, Any]:
        version_record = record.versions[record.active_version]
        try:
            manifest = self._load_installed_manifest(
                record.id,
                record.active_version,
                record=record,
            )
        except (AppDomainError, ManifestValidationError):
            return {
                "id": record.id,
                "name": record.id,
                "description": "Installed application metadata is invalid",
                "version": record.active_version,
                "enabled": record.enabled,
                "source_editable": version_record.source_editable,
                "trust_state": self._trust_state(record, version_record.trust_state),
                "status": "invalid",
                "requested_permissions": record.requested_permissions.model_dump(mode="json"),
                "granted_permissions": record.granted_permissions.model_dump(mode="json"),
            }
        status = "disabled" if not record.enabled else (
            "ready" if _is_compatible(manifest) else "incompatible"
        )
        return {
            "id": record.id,
            "name": manifest.name,
            "description": manifest.description,
            "version": manifest.version,
            "enabled": record.enabled,
            "source_editable": version_record.source_editable,
            "trust_state": self._trust_state(record, version_record.trust_state),
            "status": status,
            "requested_permissions": record.requested_permissions.model_dump(mode="json"),
            "granted_permissions": record.granted_permissions.model_dump(mode="json"),
        }

    def _detail(self, record: AppRecord) -> dict[str, Any]:
        manifest = self._load_installed_manifest(
            record.id,
            record.active_version,
            record=record,
        )
        summary = self._summary(record)
        return {
            **summary,
            "manifest": manifest.contract_dict(),
            "revision": record.revision,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _trust_state(record: AppRecord, version_trust: str) -> str:
        return "builtin" if record.lineage == "builtin" else version_trust


def _empty_permissions() -> AppPermissions:
    return AppPermissions.model_validate(
        {
            "agent": False,
            "mcp_servers": [],
            "storage": {"mode": "none", "quota_mb": 0},
        }
    )


def _narrow_permissions(
    granted: AppPermissions,
    requested: AppPermissions,
) -> AppPermissions:
    storage_rank = {"none": 0, "session": 1, "persistent": 2}
    rank = min(storage_rank[granted.storage.mode], storage_rank[requested.storage.mode])
    mode = {value: key for key, value in storage_rank.items()}[rank]
    quota = 0 if mode == "none" else min(granted.storage.quota_mb, requested.storage.quota_mb)
    if mode != "none" and quota < 1:
        mode = "none"
        quota = 0
    granted_servers = set(granted.mcp_servers)
    return AppPermissions.model_validate(
        {
            "agent": granted.agent and requested.agent,
            "mcp_servers": [
                server for server in requested.mcp_servers if server in granted_servers
            ],
            "storage": {"mode": mode, "quota_mb": quota},
        }
    )


def _is_compatible(manifest: AppManifest) -> bool:
    return Version(manifest.min_runtime_version) <= Version(APP_RUNTIME_VERSION)


__all__ = ["AppManager"]
