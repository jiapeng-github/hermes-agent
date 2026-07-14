"""Hermes application workspaces, deterministic builds, and publish validation."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, model_validator

from utils import atomic_json_write, atomic_yaml_write

from .errors import AppDomainError, ManifestValidationError
from .manifest import load_manifest
from .models import APP_ID_PATTERN, SEMVER_PATTERN, AppManifest
from .package import MAX_ENTRIES, MAX_FILE_BYTES, MAX_UNCOMPRESSED_BYTES
from .paths import AppPaths
from .registry import AppRegistry


APP_RUNTIME_VERSION = "1.0.0"
APP_SDK_MAJOR = 1
WORKSPACE_METADATA = ".hermes-app-workspace.json"
_REMOTE_CSS = re.compile(
    r"(?i)(?:url\s*\(\s*|@import\s+)[\"']?(?:https?:)?//"
)
_REMOTE_JS = re.compile(
    r"(?i)(?:fetch|import|WebSocket|EventSource|Worker)\s*\(\s*[\"'](?:https?:|wss?:)?//"
)
_SECRET_NAMES = frozenset(
    {".env", ".npmrc", ".pypirc", "auth.json", "credentials.json", "secrets.json"}
)
_SECRET_SUFFIXES = frozenset({".key", ".p12", ".pem", ".pfx"})
_SCANNED_TEXT_SUFFIXES = frozenset({".css", ".html", ".js", ".json", ".mjs"})
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _WorkspaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WorkspaceMetadata(_WorkspaceModel):
    schema_version: Literal[1] = 1
    app_id: str = Field(pattern=APP_ID_PATTERN)
    template: Literal["vanilla", "dashboard", "checkout"]
    created_at: datetime = Field(strict=False)
    base_version: str | None = Field(default=None, pattern=SEMVER_PATTERN)
    trusted_build_scripts: bool

    @model_validator(mode="after")
    def validate_context(self) -> "WorkspaceMetadata":
        if self.created_at.tzinfo is None:
            raise ValueError("workspace created_at must include a timezone")
        if self.template == "checkout" and self.base_version is None:
            raise ValueError("checkout workspace requires base_version")
        if self.template != "checkout" and self.base_version is not None:
            raise ValueError("base_version is reserved for checkout workspaces")
        return self


class ValidationIssue(_WorkspaceModel):
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


class ValidationReport(_WorkspaceModel):
    valid: bool
    app_id: str | None
    version: str | None
    issues: list[ValidationIssue]
    files: int = Field(ge=0)
    bytes: int = Field(ge=0)


class BuildResult(_WorkspaceModel):
    workspace: str
    dist: str
    files: int = Field(ge=1)
    bytes: int = Field(ge=1)


def validate_app_bundle(root: Path, manifest: AppManifest) -> ValidationReport:
    """Apply publish-time static checks to a prebuilt first-party bundle."""
    issues: list[ValidationIssue] = []
    files, total_bytes = _validate_workspace_tree(root, issues)
    _validate_runtime_compatibility(manifest, issues)
    _validate_action_schemas(root, manifest, issues)
    _validate_permission_minimization(manifest, issues)
    _validate_dist(root / "dist", issues)
    return ValidationReport(
        valid=not any(issue.severity == "error" for issue in issues),
        app_id=manifest.id,
        version=manifest.version,
        issues=issues,
        files=files,
        bytes=total_bytes,
    )


class _AppHTMLParser(HTMLParser):
    def __init__(self, relative_path: str):
        super().__init__(convert_charrefs=True)
        self.relative_path = relative_path
        self.issues: list[ValidationIssue] = []
        self.references: list[str] = []
        self._inside_style = False
        self._inside_script_without_src = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        values = {name.casefold(): value or "" for name, value in attrs}
        if lowered == "style":
            self._inside_style = True
            self._error("csp.inline_style", "inline <style> blocks are forbidden")
        if lowered == "script":
            if not values.get("src"):
                self._inside_script_without_src = True
                self._error("csp.inline_script", "inline <script> blocks are forbidden")
            elif not _is_local_resource(values["src"]):
                self._error("csp.remote_script", "non-local script sources are forbidden")
            else:
                self.references.append(values["src"])
        if lowered in {"base", "iframe", "object", "embed"}:
            self._error("csp.forbidden_element", f"<{lowered}> is forbidden in AppHost")
        if lowered == "meta" and values.get("http-equiv", "").casefold() == "content-security-policy":
            self._error("csp.manifest_override", "HTML cannot replace the AppHost CSP")
        for name, value in values.items():
            if name.startswith("on"):
                self._error("csp.inline_handler", f"inline event handler {name!r} is forbidden")
            if name == "style":
                self._error("csp.inline_style", "inline style attributes are forbidden")
            resource_attribute = name in {"src", "action", "poster"} or (
                name == "href" and lowered == "link"
            )
            if resource_attribute and not (lowered == "script" and name == "src"):
                local = _is_local_resource(
                    value,
                    allow_data=lowered == "img" and name == "src",
                )
                if not local:
                    self._error(
                        "csp.remote_resource",
                        f"non-local resource is forbidden: {value[:120]}",
                    )
                elif name != "action" and not value.strip().casefold().startswith("data:"):
                    self.references.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style":
            self._inside_style = False
        if tag.casefold() == "script":
            self._inside_script_without_src = False

    def _error(self, code: str, message: str) -> None:
        self.issues.append(
            ValidationIssue(
                severity="error",
                code=code,
                path=self.relative_path,
                message=message,
            )
        )


class AppWorkspaceService:
    """Create and modify mutable workspaces without touching installed versions."""

    def __init__(self, paths: AppPaths, registry: AppRegistry | None = None):
        self.paths = paths
        self.registry = registry or AppRegistry(paths)

    def init(
        self,
        target: str | Path,
        *,
        app_id: str,
        template: Literal["vanilla", "dashboard"] = "dashboard",
        name: str | None = None,
    ) -> Path:
        if re.fullmatch(APP_ID_PATTERN, app_id) is None:
            raise AppDomainError("APP_REQUEST_INVALID", "application id must use reverse-DNS form")
        workspace = self._new_workspace_path(target)
        display_name = (name or app_id.rsplit(".", 1)[-1].replace("-", " ").title()).strip()
        if not display_name or len(display_name) > 80:
            raise AppDomainError("APP_REQUEST_INVALID", "application name must be 1-80 characters")
        manifest_data = _template_manifest(app_id, display_name)
        try:
            workspace.mkdir(parents=True, mode=0o700)
            atomic_yaml_write(workspace / "app.yaml", manifest_data, sort_keys=False)
            (workspace / "icon.png").write_bytes(_PNG_1X1)
            (workspace / "prompts").mkdir()
            (workspace / "prompts" / "analyze.md").write_text(
                "Analyze the validated browser input and return JSON matching the output schema.\n",
                encoding="utf-8",
            )
            (workspace / "schemas").mkdir()
            schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
            for filename in ("analyze.input.json", "analyze.output.json"):
                atomic_json_write(workspace / "schemas" / filename, schema, indent=2, sort_keys=True)
            source = workspace / "source"
            source.mkdir()
            if template == "vanilla":
                _write_vanilla_template(source, display_name)
            else:
                _write_dashboard_template(source, display_name)
            self._write_metadata(
                workspace,
                WorkspaceMetadata(
                    app_id=app_id,
                    template=template,
                    created_at=datetime.now(timezone.utc),
                    trusted_build_scripts=template == "dashboard",
                ),
            )
            if template == "vanilla":
                self.build(workspace)
            return workspace
        except BaseException:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    def checkout(
        self,
        app_id: str,
        target: str | Path,
        *,
        version: str | None = None,
    ) -> Path:
        record = self.registry.get(app_id)
        if record is None:
            raise AppDomainError("APP_NOT_FOUND", "application was not found")
        selected = version or record.active_version
        version_record = record.versions.get(selected)
        if version_record is None:
            raise AppDomainError("APP_NOT_FOUND", "application version was not found")
        if not version_record.source_editable:
            raise AppDomainError("APP_VERSION_CONFLICT", "application version has no editable source")
        source = self.paths.version(app_id, selected)
        if source.is_symlink() or not source.is_dir():
            raise AppDomainError("APP_NOT_FOUND", "installed application version is unavailable")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise AppDomainError(
                "APP_VERSION_CONFLICT",
                "installed application version contains an unsafe symlink",
            )
        workspace = self._new_workspace_path(target)
        try:
            shutil.copytree(source, workspace, symlinks=False)
            _make_tree_writable(workspace)
            self._write_metadata(
                workspace,
                WorkspaceMetadata(
                    app_id=app_id,
                    template="checkout",
                    created_at=datetime.now(timezone.utc),
                    base_version=selected,
                    trusted_build_scripts=False,
                ),
            )
            return workspace
        except BaseException:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    def validate(self, workspace: str | Path) -> ValidationReport:
        root = self._existing_workspace_path(workspace)
        issues: list[ValidationIssue] = []
        files, total_bytes = _validate_workspace_tree(root, issues)
        manifest: AppManifest | None = None
        try:
            manifest = load_manifest(root / "app.yaml", app_root=root, lineage="user")
        except ManifestValidationError as exc:
            issues.extend(
                ValidationIssue(
                    severity="error",
                    code=issue.code,
                    path=issue.path,
                    message=issue.message,
                )
                for issue in exc.issues
            )
        if manifest is not None:
            _validate_runtime_compatibility(manifest, issues)
            _validate_action_schemas(root, manifest, issues)
            _validate_permission_minimization(manifest, issues)
            _validate_dist(root / "dist", issues)
        return ValidationReport(
            valid=not any(issue.severity == "error" for issue in issues),
            app_id=manifest.id if manifest else None,
            version=manifest.version if manifest else None,
            issues=issues,
            files=files,
            bytes=total_bytes,
        )

    def require_valid(self, workspace: str | Path) -> ValidationReport:
        report = self.validate(workspace)
        if not report.valid:
            raise AppDomainError(
                "APP_MANIFEST_INVALID",
                "application workspace failed validation",
                details={
                    "issues": [issue.model_dump(mode="json") for issue in report.issues]
                },
            )
        return report

    def build(
        self,
        workspace: str | Path,
        *,
        allow_scripts: bool = False,
        timeout_seconds: int = 300,
    ) -> BuildResult:
        root = self._existing_workspace_path(workspace)
        try:
            manifest = load_manifest(root / "app.yaml", lineage="user")
        except ManifestValidationError as exc:
            raise AppDomainError(
                "APP_MANIFEST_INVALID",
                "application Manifest is invalid",
                details={"issues": [issue.as_dict() for issue in exc.issues]},
            ) from exc
        if manifest.source is None:
            raise AppDomainError("APP_VERSION_CONFLICT", "application has no editable source")
        source = root / manifest.source
        if source.is_symlink() or not source.is_dir():
            raise AppDomainError("APP_MANIFEST_INVALID", "source directory is unavailable")
        temporary = root / f".hermes-build-{uuid.uuid4()}"
        package_json = source / "package.json"
        try:
            if package_json.is_file():
                metadata = self._read_metadata(root)
                if not (allow_scripts or metadata.trusted_build_scripts):
                    raise AppDomainError(
                        "APP_PERMISSION_REQUIRED",
                        "build scripts from a checked-out package require --allow-scripts",
                    )
                _run_node_build(source, temporary, timeout_seconds=timeout_seconds)
            else:
                _copy_static_source(source, temporary)
            build_issues: list[ValidationIssue] = []
            _validate_dist(temporary, build_issues, path_prefix="dist")
            if any(issue.severity == "error" for issue in build_issues):
                raise AppDomainError(
                    "APP_MANIFEST_INVALID",
                    "build output failed AppHost validation",
                    details={
                        "issues": [issue.model_dump(mode="json") for issue in build_issues]
                    },
                )
            expected_entry = PurePosixPath(manifest.entry).relative_to("dist")
            if not temporary.joinpath(*expected_entry.parts).is_file():
                raise AppDomainError(
                    "APP_MANIFEST_INVALID",
                    f"build did not produce {manifest.entry}",
                )
            _replace_dist_atomically(root / "dist", temporary)
            files, total = _tree_stats(root / "dist")
            return BuildResult(
                workspace=str(root),
                dist=str(root / "dist"),
                files=files,
                bytes=total,
            )
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def metadata(self, workspace: str | Path) -> WorkspaceMetadata:
        return self._read_metadata(self._existing_workspace_path(workspace))

    def resolve(self, workspace: str | Path) -> Path:
        return self._existing_workspace_path(workspace)

    def _new_workspace_path(self, target: str | Path) -> Path:
        path = Path(target).expanduser().resolve(strict=False)
        self._reject_runtime_path(path)
        if path.exists() or path.is_symlink():
            raise AppDomainError("APP_VERSION_CONFLICT", "workspace destination already exists")
        return path

    def _existing_workspace_path(self, workspace: str | Path) -> Path:
        path = Path(workspace).expanduser()
        if path.is_symlink():
            raise AppDomainError("APP_REQUEST_INVALID", "workspace cannot be a symlink")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise AppDomainError("APP_NOT_FOUND", "workspace was not found") from exc
        self._reject_runtime_path(resolved)
        if not resolved.is_dir():
            raise AppDomainError("APP_REQUEST_INVALID", "workspace must be a directory")
        return resolved

    def _reject_runtime_path(self, path: Path) -> None:
        for protected in (self.paths.root, self.paths.app_data):
            try:
                path.relative_to(protected.resolve(strict=False))
            except ValueError:
                continue
            raise AppDomainError(
                "APP_PERMISSION_REQUIRED",
                "mutable workspaces cannot live inside App Runtime directories",
            )

    @staticmethod
    def _write_metadata(workspace: Path, metadata: WorkspaceMetadata) -> None:
        atomic_json_write(
            workspace / WORKSPACE_METADATA,
            metadata.model_dump(mode="json", exclude_none=True),
            indent=2,
            mode=0o600,
            sort_keys=True,
        )

    @staticmethod
    def _read_metadata(workspace: Path) -> WorkspaceMetadata:
        path = workspace / WORKSPACE_METADATA
        try:
            return WorkspaceMetadata.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise AppDomainError(
                "APP_REQUEST_INVALID",
                "workspace metadata is missing or invalid; run hermes apps init/checkout",
            ) from exc


def _template_manifest(app_id: str, name: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": app_id,
        "name": name,
        "version": "0.1.0",
        "description": f"{name} Hermes application",
        "entry": "dist/index.html",
        "icon": "icon.png",
        "source": "source",
        "sdk_version": "1.0.0",
        "min_runtime_version": "1.0.0",
        "display": {"theme": "auto", "preferred_width": 1280, "preferred_height": 800},
        "permissions": {
            "agent": True,
            "mcp_servers": [],
            "storage": {"mode": "none", "quota_mb": 0},
        },
        "actions": {
            "analyze": {
                "kind": "agent",
                "title": "Analyze",
                "prompt": "prompts/analyze.md",
                "input_schema": "schemas/analyze.input.json",
                "output_schema": "schemas/analyze.output.json",
                "mode": "stateless",
                "toolsets": [],
                "timeout_seconds": 120,
                "max_iterations": 8,
                "max_concurrent_runs": 1,
                "cache_ttl_seconds": 0,
            }
        },
    }


def _write_vanilla_template(source: Path, name: str) -> None:
    escaped_name = escape(name)
    (source / "index.html").write_text(
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escaped_name}</title><link rel=\"stylesheet\" href=\"./styles.css\"></head>"
        '<body><main><header><span class="mark"></span><h1 id="title">Hermes App</h1></header>'
        '<section><p id="status">Connecting to Hermes Runtime...</p>'
        '<button id="analyze" type="button">Analyze</button></section></main>'
        '<script type="module" src="./app.js"></script></body></html>\n',
        encoding="utf-8",
    )
    (source / "styles.css").write_text(
        ":root{color-scheme:light dark;font-family:Inter,system-ui,sans-serif;}"
        "body{margin:0;background:#f5f7fb;color:#172033;}"
        "main{max-width:960px;margin:0 auto;padding:32px 24px;}"
        "header{display:flex;align-items:center;gap:10px;}"
        ".mark{width:10px;height:28px;background:#2f6fed;border-radius:2px;}"
        "section{margin-top:24px;padding:20px;border:1px solid #dce2ec;border-radius:8px;background:#fff;}"
        "button{border:0;border-radius:6px;padding:9px 14px;background:#2f6fed;color:#fff;}"
        "@media(prefers-color-scheme:dark){body{background:#101318;color:#edf2f7;}section{background:#171b22;border-color:#303744;}}\n",
        encoding="utf-8",
    )
    (source / "app.js").write_text(
        "const status = document.querySelector('#status');\n"
        "const title = document.querySelector('#title');\n"
        "const bootstrap = await fetch('/__hermes/bootstrap').then((response) => response.json());\n"
        "title.textContent = bootstrap.app_id;\n"
        "status.textContent = `Runtime v${bootstrap.protocol_version} ready`;\n"
        "document.querySelector('#analyze').addEventListener('click', () => {\n"
        "  status.textContent = 'Connect this control to a declared Runtime action.';\n"
        "});\n",
        encoding="utf-8",
    )


def _write_dashboard_template(source: Path, name: str) -> None:
    package = {
        "name": "hermes-app",
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {"build": "vite build"},
        "dependencies": {"react": "19.2.5", "react-dom": "19.2.5"},
        "devDependencies": {
            "@vitejs/plugin-react": "6.0.1",
            "typescript": "6.0.3",
            "vite": "8.0.10",
        },
    }
    atomic_json_write(source / "package.json", package, indent=2, sort_keys=True)
    atomic_json_write(
        source / "tsconfig.json",
        {
            "compilerOptions": {
                "target": "ES2022",
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "jsx": "react-jsx",
                "strict": True,
                "noEmit": True,
            },
            "include": ["src"],
        },
        indent=2,
        sort_keys=True,
    )
    (source / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(name)}</title></head><body><div id=\"root\"></div>"
        '<script type="module" src="/src/main.tsx"></script></body></html>\n',
        encoding="utf-8",
    )
    (source / "vite.config.ts").write_text(
        "import { defineConfig } from 'vite';\n"
        "import react from '@vitejs/plugin-react';\n"
        "export default defineConfig({ plugins: [react()], build: { emptyOutDir: true } });\n",
        encoding="utf-8",
    )
    src = source / "src"
    src.mkdir()
    (src / "main.tsx").write_text(
        "import React from 'react';\n"
        "import { createRoot } from 'react-dom/client';\n"
        "import './styles.css';\n"
        "function App() { return <main><h1>Hermes App</h1><p>Runtime-ready workspace</p></main>; }\n"
        "createRoot(document.getElementById('root')!).render(<App />);\n",
        encoding="utf-8",
    )
    (src / "styles.css").write_text(
        ":root{color-scheme:light dark;font-family:Inter,system-ui,sans-serif;}"
        "body{margin:0;background:#f5f7fb;color:#172033;}main{padding:32px;}"
        "@media(prefers-color-scheme:dark){body{background:#101318;color:#edf2f7;}}\n",
        encoding="utf-8",
    )


def _validate_workspace_tree(root: Path, issues: list[ValidationIssue]) -> tuple[int, int]:
    count = 0
    total = 0
    excluded_directories = {"node_modules", ".git", "__pycache__"}
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if name in excluded_directories or name.startswith(
                (".hermes-build-", ".hermes-dist-backup-")
            ):
                continue
            if path.is_symlink():
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="path.symlink",
                        path=relative,
                        message="symlinks are forbidden",
                    )
                )
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="path.symlink",
                        path=relative,
                        message="symlinks are forbidden",
                    )
                )
                continue
            if not path.is_file():
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="path.special",
                        path=relative,
                        message="special files are forbidden",
                    )
                )
                continue
            count += 1
            size = path.stat().st_size
            total += size
            if size > MAX_FILE_BYTES:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="package.file_too_large",
                        path=relative,
                        message="file exceeds 50 MiB",
                    )
                )
            folded_name = path.name.casefold()
            if folded_name in _SECRET_NAMES or path.suffix.casefold() in _SECRET_SUFFIXES:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="security.credential_file",
                        path=relative,
                        message="credential-like files cannot be published",
                    )
                )
            if path.suffix.casefold() == ".map" and relative.startswith("dist/"):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="build.source_map",
                        path=relative,
                        message="production source maps are forbidden",
                    )
                )
    if count > MAX_ENTRIES:
        issues.append(ValidationIssue(severity="error", code="package.too_many_files", path="$", message="workspace exceeds 5000 files"))
    if total > MAX_UNCOMPRESSED_BYTES:
        issues.append(ValidationIssue(severity="error", code="package.too_large", path="$", message="workspace exceeds 200 MiB"))
    return count, total


def _validate_runtime_compatibility(manifest: AppManifest, issues: list[ValidationIssue]) -> None:
    try:
        sdk = Version(manifest.sdk_version)
        minimum = Version(manifest.min_runtime_version)
        runtime = Version(APP_RUNTIME_VERSION)
    except InvalidVersion:
        return
    if sdk.major != APP_SDK_MAJOR:
        issues.append(ValidationIssue(severity="error", code="runtime.sdk_incompatible", path="sdk_version", message=f"SDK major {sdk.major} is not supported"))
    if minimum > runtime:
        issues.append(ValidationIssue(severity="error", code="runtime.version_incompatible", path="min_runtime_version", message=f"requires Runtime {minimum}, current is {runtime}"))


def _validate_action_schemas(root: Path, manifest: AppManifest, issues: list[ValidationIssue]) -> None:
    seen: set[str] = set()
    for action_id, action in manifest.actions.items():
        for field in ("input_schema", "output_schema"):
            relative = getattr(action, field)
            if relative in seen:
                continue
            seen.add(relative)
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                if path.stat().st_size > 1_048_576:
                    raise ValueError("schema exceeds 1 MiB")
                value = json.loads(path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(value)
                external_refs = [
                    reference
                    for reference in _json_schema_refs(value)
                    if not reference.startswith("#")
                ]
                if external_refs:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="action.schema_external_ref",
                            path=f"actions.{action_id}.{field}",
                            message="Action schemas may use only document-local $ref fragments",
                        )
                    )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                SchemaError,
                RecursionError,
                ValueError,
                TypeError,
            ) as exc:
                issues.append(ValidationIssue(severity="error", code="action.schema_invalid", path=f"actions.{action_id}.{field}", message=str(exc)))


def _json_schema_refs(value: Any) -> list[str]:
    refs: list[str] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key in ("$ref", "$dynamicRef"):
                reference = current.get(key)
                if isinstance(reference, str):
                    refs.append(reference)
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return refs


def _validate_permission_minimization(manifest: AppManifest, issues: list[ValidationIssue]) -> None:
    agent_used = any(action.kind == "agent" for action in manifest.actions.values())
    mcp_used = {action.server for action in manifest.actions.values() if action.kind == "mcp"}
    if manifest.permissions.agent and not agent_used:
        issues.append(ValidationIssue(severity="warning", code="permission.agent_unused", path="permissions.agent", message="agent permission is requested but no Agent action uses it"))
    for server in manifest.permissions.mcp_servers:
        if server not in mcp_used:
            issues.append(ValidationIssue(severity="warning", code="permission.mcp_unused", path="permissions.mcp_servers", message=f"MCP server {server!r} is requested but unused"))


def _validate_dist(
    dist: Path,
    issues: list[ValidationIssue],
    *,
    path_prefix: str = "dist",
) -> None:
    if dist.is_symlink() or not dist.is_dir():
        issues.append(ValidationIssue(severity="error", code="build.dist_missing", path=path_prefix, message="production dist directory is missing"))
        return
    for path in sorted(dist.rglob("*")):
        relative = f"{path_prefix}/{path.relative_to(dist).as_posix()}"
        if path.is_symlink():
            issues.append(ValidationIssue(severity="error", code="path.symlink", path=relative, message="dist cannot contain symlinks"))
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            issues.append(ValidationIssue(severity="error", code="path.special", path=relative, message="dist cannot contain special files"))
            continue
        suffix = path.suffix.casefold()
        if suffix == ".map":
            issues.append(ValidationIssue(severity="error", code="build.source_map", path=relative, message="production source maps are forbidden"))
        if suffix not in _SCANNED_TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append(ValidationIssue(severity="error", code="build.text_encoding", path=relative, message="Web text assets must be UTF-8"))
            continue
        has_remote_resource = (
            suffix == ".css" and _REMOTE_CSS.search(text)
        ) or (suffix in {".js", ".mjs"} and _REMOTE_JS.search(text))
        if has_remote_resource:
            issues.append(ValidationIssue(severity="error", code="csp.remote_resource", path=relative, message="remote URLs are forbidden in production assets"))
        if suffix == ".html":
            parser = _AppHTMLParser(relative)
            try:
                parser.feed(text)
                parser.close()
            except ValueError as exc:
                issues.append(ValidationIssue(severity="error", code="build.html_invalid", path=relative, message=str(exc)))
            issues.extend(parser.issues)
            for reference in parser.references:
                _validate_local_asset_reference(
                    dist,
                    path,
                    reference,
                    issues,
                    owner_path=relative,
                )


def _is_local_resource(value: str, *, allow_data: bool = False) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    lowered = normalized.casefold()
    if allow_data and lowered.startswith("data:image/"):
        return True
    if "\\" in normalized or lowered.startswith("//"):
        return False
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return False
    if parsed.scheme or parsed.netloc:
        return False
    return ".." not in PurePosixPath(parsed.path).parts


def _validate_local_asset_reference(
    dist: Path,
    owner: Path,
    reference: str,
    issues: list[ValidationIssue],
    *,
    owner_path: str,
) -> None:
    parsed = urlsplit(reference)
    raw_path = unquote(parsed.path)
    if not raw_path or raw_path.startswith(("/__hermes/", "/api/")):
        return
    parts = PurePosixPath(raw_path.lstrip("/")).parts
    if any(part in {"", ".", ".."} for part in parts):
        issues.append(
            ValidationIssue(
                severity="error",
                code="build.asset_escape",
                path=owner_path,
                message=f"asset reference escapes dist: {reference[:120]}",
            )
        )
        return
    target = dist.joinpath(*parts) if raw_path.startswith("/") else owner.parent.joinpath(*parts)
    try:
        current = target
        while current != dist:
            if current.is_symlink():
                raise ValueError("symlink")
            current = current.parent
        resolved = target.resolve(strict=True)
        resolved.relative_to(dist.resolve(strict=True))
    except (OSError, ValueError):
        issues.append(
            ValidationIssue(
                severity="error",
                code="build.asset_missing",
                path=owner_path,
                message=f"referenced local asset is missing or unsafe: {reference[:120]}",
            )
        )
        return
    if not resolved.is_file():
        issues.append(
            ValidationIssue(
                severity="error",
                code="build.asset_missing",
                path=owner_path,
                message=f"referenced local asset is not a file: {reference[:120]}",
            )
        )


def _copy_static_source(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in {"node_modules", ".git", "__pycache__"} for part in relative.parts):
            continue
        target = destination / relative
        if path.is_symlink():
            raise AppDomainError("APP_MANIFEST_INVALID", f"source contains a symlink: {relative.as_posix()}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        else:
            raise AppDomainError("APP_MANIFEST_INVALID", f"source contains a special file: {relative.as_posix()}")


def _run_node_build(source: Path, destination: Path, *, timeout_seconds: int) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise AppDomainError("APP_REQUEST_INVALID", "npm is required for this application template")
    if not (source / "node_modules").is_dir():
        raise AppDomainError(
            "APP_REQUEST_INVALID",
            f"build dependencies are missing; run npm install in {source}",
        )
    build_home = Path(tempfile.mkdtemp(prefix="hermes-app-build-"))
    try:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}
        }
        environment.update(
            {
                "HOME": str(build_home),
                "USERPROFILE": str(build_home),
                "npm_config_audit": "false",
                "npm_config_fund": "false",
                "npm_config_offline": "true",
            }
        )
        process = subprocess.run(
            [npm, "run", "build", "--", "--outDir", str(destination), "--emptyOutDir"],
            cwd=source,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppDomainError("APP_BUSY", "application build timed out", retryable=True) from exc
    finally:
        shutil.rmtree(build_home, ignore_errors=True)
    if process.returncode != 0:
        output = (process.stdout + "\n" + process.stderr).strip()[-4000:]
        raise AppDomainError(
            "APP_MANIFEST_INVALID",
            "application build failed",
            details={"output": output},
        )


def _replace_dist_atomically(destination: Path, replacement: Path) -> None:
    backup = destination.parent / f".hermes-dist-backup-{uuid.uuid4()}"
    moved_old = False
    try:
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                raise AppDomainError("APP_MANIFEST_INVALID", "dist must be a real directory")
            os.replace(destination, backup)
            moved_old = True
        os.replace(replacement, destination)
    except BaseException:
        if moved_old and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if moved_old:
        shutil.rmtree(backup, ignore_errors=True)


def _tree_stats(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def _make_tree_writable(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            mode = path.stat().st_mode
            path.chmod(mode | (stat.S_IWUSR | stat.S_IRUSR))
        except OSError:
            pass
    try:
        root.chmod(0o700)
    except OSError:
        pass


__all__ = [
    "APP_RUNTIME_VERSION",
    "AppWorkspaceService",
    "BuildResult",
    "ValidationIssue",
    "ValidationReport",
    "WorkspaceMetadata",
    "validate_app_bundle",
]
