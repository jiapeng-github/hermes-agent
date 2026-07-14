"""Permission-request and grant relationships for local applications."""

from __future__ import annotations

from .errors import PermissionGrantError
from .models import AppPermissions


_STORAGE_RANK = {"none": 0, "session": 1, "persistent": 2}


def validate_permission_grants(
    requested: AppPermissions,
    granted: AppPermissions,
) -> None:
    """Require every grant to be equal to or narrower than the request."""
    violations: list[str] = []
    if granted.agent and not requested.agent:
        violations.append("agent")

    extra_servers = sorted(set(granted.mcp_servers) - set(requested.mcp_servers))
    violations.extend(f"mcp:{server}" for server in extra_servers)

    if _STORAGE_RANK[granted.storage.mode] > _STORAGE_RANK[requested.storage.mode]:
        violations.append(f"storage:{granted.storage.mode}")
    if granted.storage.quota_mb > requested.storage.quota_mb:
        violations.append(f"storage:quota:{granted.storage.quota_mb}")

    if violations:
        raise PermissionGrantError(
            "permission grants exceed the active Manifest request",
            details={"violations": violations},
        )
__all__ = ["validate_permission_grants"]
