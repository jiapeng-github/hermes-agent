"""Local web-application domain for Hermes desktop."""

from .errors import AppDomainError, ManifestIssue, ManifestValidationError
from .manager import AppManager
from .marketplace import AppMarketplaceOperations
from .manifest import load_manifest, parse_manifest, validate_manifest_files
from .models import AppManifest
from .package import (
    HappImportService,
    ImportConfirmation,
    ImportPlan,
    PackageExport,
    export_happ_package,
)
from .paths import AppPaths
from .registry import AppRegistry
from .workspace import AppWorkspaceService, ValidationReport


__all__ = [
    "AppDomainError",
    "AppManifest",
    "AppManager",
    "AppMarketplaceOperations",
    "AppPaths",
    "AppRegistry",
    "AppWorkspaceService",
    "HappImportService",
    "ImportConfirmation",
    "ImportPlan",
    "ManifestIssue",
    "ManifestValidationError",
    "PackageExport",
    "ValidationReport",
    "export_happ_package",
    "load_manifest",
    "parse_manifest",
    "validate_manifest_files",
]
