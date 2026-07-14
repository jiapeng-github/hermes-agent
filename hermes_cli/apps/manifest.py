"""Loading and semantic validation for frozen App Manifest v1 files."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import AbstractSet, Any

import yaml
from pydantic import ValidationError

from .errors import ManifestIssue, ManifestValidationError
from .models import AgentAction, AppLineage, AppManifest, McpAction, ServiceAction


MAX_MANIFEST_BYTES = 1_048_576
_EMPTY_HANDLERS: frozenset[str] = frozenset()


def parse_manifest(
    data: Mapping[str, Any],
    *,
    lineage: AppLineage = "user",
    allowed_service_handlers: AbstractSet[str] = _EMPTY_HANDLERS,
) -> AppManifest:
    """Parse a manifest and enforce runtime-owned capability boundaries.

    ``lineage`` and ``allowed_service_handlers`` come from the runtime registry,
    never from manifest fields. User and imported manifests cannot use service
    actions. Built-ins can use only the exact handlers supplied by their
    registry lineage.
    """
    try:
        manifest = AppManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestValidationError(_pydantic_issues(exc)) from exc

    issues = _semantic_issues(
        manifest,
        lineage=lineage,
        allowed_service_handlers=allowed_service_handlers,
    )
    if issues:
        raise ManifestValidationError(issues)
    return manifest


def load_manifest(
    path: str | Path,
    *,
    app_root: str | Path | None = None,
    lineage: AppLineage = "user",
    allowed_service_handlers: AbstractSet[str] = _EMPTY_HANDLERS,
) -> AppManifest:
    """Load UTF-8 YAML/JSON and optionally verify every referenced file.

    Pass ``app_root`` while analyzing a staged or installed package. Omitting
    it is useful for editor validation before the app has been built.
    """
    manifest_path = Path(path)
    try:
        if manifest_path.is_symlink():
            raise ManifestValidationError(
                [ManifestIssue("manifest.symlink", ("$",), "manifest cannot be a symlink")]
            )
        raw = manifest_path.read_bytes()
    except ManifestValidationError:
        raise
    except OSError as exc:
        raise ManifestValidationError(
            [ManifestIssue("manifest.read_failed", ("$",), str(exc))]
        ) from exc

    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestValidationError(
            [
                ManifestIssue(
                    "manifest.too_large",
                    ("$",),
                    f"manifest exceeds {MAX_MANIFEST_BYTES} bytes",
                )
            ]
        )

    try:
        text = raw.decode("utf-8")
        data = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ManifestValidationError(
            [ManifestIssue("manifest.parse_failed", ("$",), str(exc))]
        ) from exc
    if not isinstance(data, Mapping):
        raise ManifestValidationError(
            [ManifestIssue("manifest.root_type", ("$",), "manifest root must be an object")]
        )

    manifest = parse_manifest(
        data,
        lineage=lineage,
        allowed_service_handlers=allowed_service_handlers,
    )
    if app_root is not None:
        validate_manifest_files(manifest, app_root)
    return manifest


def validate_manifest_files(manifest: AppManifest, app_root: str | Path) -> None:
    """Verify referenced app files stay within ``app_root`` and have the right type."""
    root = Path(app_root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ManifestValidationError(
            [ManifestIssue("files.root_missing", ("$",), str(exc))]
        ) from exc
    if not resolved_root.is_dir():
        raise ManifestValidationError(
            [ManifestIssue("files.root_type", ("$",), "app_root must be a directory")]
        )

    issues: list[ManifestIssue] = []
    for location, relative, expected_kind in _referenced_paths(manifest):
        current = resolved_root
        symlink_found = False
        for component in PurePosixPath(relative).parts:
            current = current / component
            if current.is_symlink():
                symlink_found = True
                break
        if symlink_found:
            issues.append(
                ManifestIssue(
                    "files.symlink",
                    location,
                    "referenced path cannot contain a symlink",
                )
            )
            continue

        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            issues.append(
                ManifestIssue(
                    "files.missing",
                    location,
                    f"referenced path does not exist: {relative}",
                )
            )
            continue

        valid_kind = resolved.is_file() if expected_kind == "file" else resolved.is_dir()
        if not valid_kind:
            issues.append(
                ManifestIssue(
                    "files.wrong_type",
                    location,
                    f"referenced path must be a {expected_kind}: {relative}",
                )
            )
    if issues:
        raise ManifestValidationError(issues)


def _semantic_issues(
    manifest: AppManifest,
    *,
    lineage: AppLineage,
    allowed_service_handlers: AbstractSet[str],
) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    referenced: dict[str, tuple[str, tuple[str | int, ...]]] = {}

    for location, relative, _expected_kind in _referenced_paths(manifest):
        issue = _relative_path_issue(relative, location)
        if issue is not None:
            issues.append(issue)
            continue
        folded = unicodedata.normalize("NFC", relative).casefold()
        existing = referenced.get(folded)
        if existing is not None and existing[0] != relative:
            issues.append(
                ManifestIssue(
                    "path.case_collision",
                    location,
                    f"path collides with {existing[0]!r} on case-insensitive filesystems",
                )
            )
        else:
            referenced[folded] = (relative, location)

    for action_id, action in manifest.actions.items():
        action_location = ("actions", action_id)
        if isinstance(action, AgentAction) and not manifest.permissions.agent:
            issues.append(
                ManifestIssue(
                    "permission.agent_not_requested",
                    action_location,
                    "agent action requires permissions.agent=true",
                )
            )
        elif isinstance(action, McpAction):
            if action.server not in manifest.permissions.mcp_servers:
                issues.append(
                    ManifestIssue(
                        "permission.mcp_not_requested",
                        (*action_location, "server"),
                        f"MCP server {action.server!r} is not requested in permissions.mcp_servers",
                    )
                )
            try:
                json.dumps(action.arguments_template, allow_nan=False)
            except (TypeError, ValueError) as exc:
                issues.append(
                    ManifestIssue(
                        "action.arguments_not_json",
                        (*action_location, "arguments_template"),
                        str(exc),
                    )
                )
        elif isinstance(action, ServiceAction):
            if lineage != "builtin":
                issues.append(
                    ManifestIssue(
                        "service.user_forbidden",
                        action_location,
                        "service actions are reserved for runtime-owned built-in lineage",
                    )
                )
            elif action.handler not in allowed_service_handlers:
                issues.append(
                    ManifestIssue(
                        "service.handler_not_inherited",
                        (*action_location, "handler"),
                        "handler is not in the exact built-in lineage allowlist",
                    )
                )
    return issues


def _relative_path_issue(
    value: str, location: tuple[str | int, ...]
) -> ManifestIssue | None:
    if value != unicodedata.normalize("NFC", value):
        return ManifestIssue("path.not_nfc", location, "path must use Unicode NFC form")
    if "\x00" in value or "\\" in value:
        return ManifestIssue(
            "path.invalid_character",
            location,
            "path contains a forbidden character",
        )
    if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
        return ManifestIssue("path.absolute", location, "path must be relative")
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        return ManifestIssue("path.traversal", location, "path contains an unsafe component")
    return None


def _referenced_paths(
    manifest: AppManifest,
) -> list[tuple[tuple[str | int, ...], str, str]]:
    references: list[tuple[tuple[str | int, ...], str, str]] = [
        (("entry",), manifest.entry, "file"),
        (("icon",), manifest.icon, "file"),
    ]
    if manifest.source is not None:
        references.append((("source",), manifest.source, "directory"))
    for action_id, action in manifest.actions.items():
        base = ("actions", action_id)
        references.extend(
            [
                ((*base, "input_schema"), action.input_schema, "file"),
                ((*base, "output_schema"), action.output_schema, "file"),
            ]
        )
        if isinstance(action, AgentAction):
            references.append(((*base, "prompt"), action.prompt, "file"))
    return references


def _pydantic_issues(exc: ValidationError) -> list[ManifestIssue]:
    return [
        ManifestIssue(
            code=f"schema.{error['type']}",
            location=tuple(error["loc"]),
            message=error["msg"],
        )
        for error in exc.errors(include_url=False, include_context=False)
    ]


__all__ = [
    "MAX_MANIFEST_BYTES",
    "load_manifest",
    "parse_manifest",
    "validate_manifest_files",
]
