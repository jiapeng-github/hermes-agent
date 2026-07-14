"""Stable domain errors for local Hermes applications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AppDomainError(RuntimeError):
    """Stable application-domain error suitable for an API error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


class PackageValidationError(AppDomainError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("APP_IMPORT_REJECTED", message, details=details)


class PackageTooLargeError(AppDomainError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("APP_PACKAGE_TOO_LARGE", message, details=details)


class ImportPlanError(AppDomainError):
    pass


class AppRegistryError(AppDomainError):
    pass


class PermissionGrantError(AppDomainError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("APP_PERMISSION_REQUIRED", message, details=details)


@dataclass(frozen=True, slots=True)
class ManifestIssue:
    """One user-correctable manifest problem."""

    code: str
    location: tuple[str | int, ...]
    message: str

    @property
    def path(self) -> str:
        return ".".join(str(part) for part in self.location) or "$"

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "path": self.path, "message": self.message}


class ManifestValidationError(ValueError):
    """Raised when an app manifest violates structure or runtime policy."""

    def __init__(self, issues: list[ManifestIssue] | tuple[ManifestIssue, ...]):
        if not issues:
            raise ValueError("ManifestValidationError requires at least one issue")
        self.issues = tuple(issues)
        summary = "; ".join(
            f"{issue.path}: {issue.message}" for issue in self.issues[:5]
        )
        if len(self.issues) > 5:
            summary += f"; and {len(self.issues) - 5} more"
        super().__init__(summary)


__all__ = [
    "AppDomainError",
    "AppRegistryError",
    "ImportPlanError",
    "ManifestIssue",
    "ManifestValidationError",
    "PackageValidationError",
    "PackageTooLargeError",
    "PermissionGrantError",
]
