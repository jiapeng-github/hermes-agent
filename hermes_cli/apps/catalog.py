"""Runtime-owned catalog for first-party applications bundled with Hermes."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version

from .errors import AppDomainError, AppRegistryError
from .manifest import load_manifest
from .models import AppManifest
from .paths import AppPaths
from .registry import AppRecord, AppRegistry
from .workspace import validate_app_bundle


INDUSTRY_MONITOR_APP_ID = "ai.hermes.industry-monitor"
COMPANY_ANALYSIS_APP_ID = "ai.hermes.company-analysis"
WATCHLIST_APP_ID = "ai.hermes.watchlist"
INDUSTRY_MONITOR_SERVICE_HANDLERS = (
    "finance.industry.snapshot",
    "finance.industry.refresh",
)
COMPANY_ANALYSIS_SERVICE_HANDLERS = (
    "finance.company.analysis",
    "finance.company.refresh",
)
WATCHLIST_SERVICE_HANDLERS = (
    "finance.watchlist.snapshot",
    "finance.watchlist.refresh",
    "finance.watchlist.add",
    "finance.watchlist.remove",
    "finance.watchlist.detail",
    "finance.company.analysis",
)


@dataclass(frozen=True, slots=True)
class BuiltinApp:
    app_id: str
    root: Path
    service_handlers: tuple[str, ...]

    def load_manifest(self, root: Path | None = None) -> AppManifest:
        selected = root or self.root
        return load_manifest(
            selected / "app.yaml",
            app_root=selected,
            lineage="builtin",
            allowed_service_handlers=frozenset(self.service_handlers),
        )


_CATALOG = {
    INDUSTRY_MONITOR_APP_ID: BuiltinApp(
        app_id=INDUSTRY_MONITOR_APP_ID,
        root=Path(__file__).parent / "catalog" / "industry-monitor",
        service_handlers=INDUSTRY_MONITOR_SERVICE_HANDLERS,
    ),
    COMPANY_ANALYSIS_APP_ID: BuiltinApp(
        app_id=COMPANY_ANALYSIS_APP_ID,
        root=Path(__file__).parent / "catalog" / "company-analysis",
        service_handlers=COMPANY_ANALYSIS_SERVICE_HANDLERS,
    ),
    WATCHLIST_APP_ID: BuiltinApp(
        app_id=WATCHLIST_APP_ID,
        root=Path(__file__).parent / "catalog" / "watchlist",
        service_handlers=WATCHLIST_SERVICE_HANDLERS,
    )
}


def builtin_app(app_id: str) -> BuiltinApp | None:
    return _CATALOG.get(app_id)


def ensure_builtin_apps(paths: AppPaths, registry: AppRegistry) -> list[AppRecord]:
    """Install newer bundled versions without replacing user-owned identities."""
    installed: list[AppRecord] = []
    for definition in _CATALOG.values():
        installed.append(_ensure_builtin(definition, paths, registry))
    return installed


def _ensure_builtin(
    definition: BuiltinApp,
    paths: AppPaths,
    registry: AppRegistry,
) -> AppRecord:
    manifest = definition.load_manifest()
    validation = validate_app_bundle(definition.root, manifest)
    if not validation.valid:
        raise AppDomainError(
            "APP_MANIFEST_INVALID",
            "bundled application failed static validation",
            details={"issues": [issue.model_dump(mode="json") for issue in validation.issues]},
        )
    existing = registry.get(definition.app_id)
    if existing is not None:
        if existing.lineage != "builtin":
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "a non-built-in application already uses a reserved built-in id",
                details={"app_id": definition.app_id},
            )
        if tuple(existing.service_handlers) != definition.service_handlers:
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "built-in service-handler inheritance changed without a version update",
                details={"app_id": definition.app_id},
            )
        if Version(existing.active_version) >= Version(manifest.version):
            return existing

    paths.ensure()
    staging = paths.staging / f"builtin-{uuid.uuid4()}"
    try:
        shutil.copytree(definition.root, staging)
        staged_manifest = definition.load_manifest(staging)
        try:
            result = registry.install_staged_version(
                staging,
                staged_manifest,
                package_sha256=_tree_sha256(staging),
                source_included=False,
                signature_state="valid_trusted",
                grants=staged_manifest.permissions,
                conflict_mode="update" if existing is not None else "install",
                lineage="builtin",
                service_handlers=definition.service_handlers,
            )
            return result.app
        except AppRegistryError as exc:
            # Concurrent first-list requests can both observe an empty catalog.
            # The registry serializes publication; reuse the compatible winner.
            current = registry.get(definition.app_id)
            if (
                exc.code == "APP_VERSION_CONFLICT"
                and current is not None
                and current.lineage == "builtin"
                and tuple(current.service_handlers) == definition.service_handlers
                and Version(current.active_version) >= Version(manifest.version)
            ):
                return current
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


__all__ = [
    "BuiltinApp",
    "COMPANY_ANALYSIS_APP_ID",
    "COMPANY_ANALYSIS_SERVICE_HANDLERS",
    "INDUSTRY_MONITOR_APP_ID",
    "INDUSTRY_MONITOR_SERVICE_HANDLERS",
    "WATCHLIST_APP_ID",
    "WATCHLIST_SERVICE_HANDLERS",
    "builtin_app",
    "ensure_builtin_apps",
]
