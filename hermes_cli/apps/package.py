"""Secure `.happ` analysis and two-phase profile-scoped import."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import shutil
import stat
import unicodedata
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from utils import atomic_json_write, atomic_yaml_write

from .errors import (
    ImportPlanError,
    ManifestValidationError,
    PackageTooLargeError,
    PackageValidationError,
)
from .manifest import load_manifest
from .models import (
    APP_ID_PATTERN,
    SEMVER_PATTERN,
    AppLineage,
    AppManifest,
    AppPermissions,
)
from .paths import AppPaths
from .permissions import validate_permission_grants
from .registry import AppRegistry, ConflictMode, InstallResult, SignatureState


MAX_COMPRESSED_BYTES = 52_428_800
MAX_UNCOMPRESSED_BYTES = 209_715_200
MAX_FILE_BYTES = 52_428_800
MAX_ENTRIES = 5_000
MAX_COMPRESSION_RATIO = 200
COMPRESSION_RATIO_MIN_BYTES = 1_048_576
MAX_METADATA_BYTES = 5 * 1024 * 1024
PLAN_TTL_SECONDS = 15 * 60
STREAM_CHUNK_BYTES = 64 * 1024

_TRANSPORT_FILES = frozenset(
    {"happ.json", "checksums.json", "signature.json"}
)
_REQUIRED_FILES = frozenset({"happ.json", "app.yaml", "checksums.json"})
_ALLOWED_ROOTS = frozenset(
    {"dist", "source", "prompts", "schemas", "assets", "tests", "screenshots"}
)
_FORBIDDEN_COMPONENTS = frozenset(
    {".git", ".hg", ".svn", "node_modules", "__pycache__"}
)
_SECRET_FILE_NAMES = frozenset(
    {
        ".npmrc",
        ".pypirc",
        "auth.json",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)
_SECRET_SUFFIXES = frozenset({".key", ".p12", ".pem", ".pfx"})
_SERVER_CODE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".jar",
        ".php",
        ".pl",
        ".ps1",
        ".py",
        ".pyc",
        ".rb",
        ".sh",
        ".so",
        ".zsh",
    }
)
_WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _PackageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Semver = Annotated[str, Field(pattern=SEMVER_PATTERN)]
AppId = Annotated[str, Field(pattern=APP_ID_PATTERN, min_length=5, max_length=128)]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class HappEnvelope(_PackageModel):
    format_version: Literal[1]
    app_id: AppId
    app_version: Semver
    created_at: datetime = Field(strict=False)
    created_by: Literal["hermes-desktop", "hermes-cli"]
    source_included: bool
    manifest: Literal["app.yaml"]
    checksums: Literal["checksums.json"]
    signature: Literal["signature.json"] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_signature(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and value.get("signature", object()) is None:
            raise ValueError("signature cannot be null")
        return value

    @model_validator(mode="after")
    def require_timezone(self) -> "HappEnvelope":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return self


class ChecksumEntry(_PackageModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0, le=MAX_FILE_BYTES)
    sha256: Sha256


class ChecksumManifest(_PackageModel):
    format_version: Literal[1]
    algorithm: Literal["sha256"]
    files: list[ChecksumEntry] = Field(min_length=3, max_length=MAX_ENTRIES - 1)


class PackageSignature(_PackageModel):
    format_version: Literal[1]
    algorithm: Literal["ed25519"]
    key_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    signed_file: Literal["checksums.json"]
    signature: str = Field(min_length=86, max_length=88)


class ImportAppSummary(_PackageModel):
    id: AppId
    name: str = Field(min_length=1, max_length=80)
    version: Semver
    description: str = Field(min_length=1, max_length=500)


class ImportConflict(_PackageModel):
    kind: Literal[
        "none",
        "app_id_exists",
        "version_exists",
        "version_checksum_mismatch",
    ]
    existing_version: Semver | None
    incoming_version: Semver


class ImportPlan(_PackageModel):
    import_id: str
    created_at: datetime = Field(strict=False)
    expires_at: datetime = Field(strict=False)
    app: ImportAppSummary
    source_included: bool
    signature_state: SignatureState
    requested_permissions: AppPermissions
    conflict: ImportConflict
    warnings: list[str] = Field(max_length=100)
    package_sha256: Sha256

    @model_validator(mode="after")
    def validate_window(self) -> "ImportPlan":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("import plan timestamps must include a timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("import plan expiry must follow creation")
        return self

    def public_dict(self) -> dict[str, Any]:
        """Return the exact ImportPlan response frozen in management OpenAPI v1."""
        value = self.model_dump(mode="json")
        value.pop("created_at", None)
        return value


class ImportConfirmation(_PackageModel):
    package_sha256: Sha256
    conflict_mode: ConflictMode
    copy_app_id: AppId | None = None
    grants: AppPermissions

    @model_validator(mode="after")
    def validate_copy_target(self) -> "ImportConfirmation":
        if self.conflict_mode == "copy" and self.copy_app_id is None:
            raise ValueError("copy_app_id is required when conflict_mode is copy")
        if self.conflict_mode != "copy" and self.copy_app_id is not None:
            raise ValueError("copy_app_id is only valid when conflict_mode is copy")
        return self


@dataclass(frozen=True, slots=True)
class SigningKey:
    public_key: bytes
    trusted: bool


@dataclass(frozen=True, slots=True)
class _ExtractedFile:
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PackageInspection:
    manifest: AppManifest
    envelope: HappEnvelope
    checksums: ChecksumManifest
    package_sha256: str
    signature_state: SignatureState
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackageExport:
    path: Path
    package_sha256: str
    size: int
    source_included: bool


@dataclass(frozen=True, slots=True)
class _ExportFile:
    path: str
    source: Path | None = None
    content: bytes | None = None

    def size_and_sha256(self) -> tuple[int, str]:
        if self.content is not None:
            return len(self.content), hashlib.sha256(self.content).hexdigest()
        if self.source is None:
            raise PackageValidationError("export entry has no source")
        size = self.source.stat().st_size
        if size > MAX_FILE_BYTES:
            raise PackageTooLargeError(f"package file exceeds 50 MiB: {self.path}")
        return size, _sha256_file(self.source, limit=MAX_FILE_BYTES)


class HappImportService:
    """Analyze hostile `.happ` bytes, then revalidate and atomically install."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        registry: AppRegistry | None = None,
        signing_keys: Mapping[str, SigningKey] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.paths = paths
        self.registry = registry or AppRegistry(paths, clock=clock)
        self.signing_keys = dict(signing_keys or {})
        self._clock = clock

    def analyze(self, package_path: str | Path) -> ImportPlan:
        """Validate and stage a package without changing installed app state."""
        source = Path(package_path)
        self.paths.ensure()
        self.cleanup_expired_plans()
        import_id = str(uuid.uuid4())
        plan_dir = self.paths.import_plan(import_id)
        plan_dir.mkdir(mode=0o700)
        staged_package = plan_dir / "package.happ"
        analyze_dir = plan_dir / ".analyze"
        try:
            package_sha256 = _copy_package(source, staged_package)
            inspection = inspect_happ_package(
                staged_package,
                analyze_dir,
                signing_keys=self.signing_keys,
            )
            if not hmac.compare_digest(package_sha256, inspection.package_sha256):
                raise PackageValidationError("package changed while it was being analyzed")
            conflict = ImportConflict.model_validate(
                self.registry.conflict_for(
                    inspection.manifest.id,
                    inspection.manifest.version,
                    inspection.package_sha256,
                )
            )
            now = self._clock()
            warnings = list(inspection.warnings)
            if inspection.signature_state == "unsigned":
                warnings.append("未签名应用将作为不受信任的本地应用安装")
            if not inspection.envelope.source_included:
                warnings.append("应用包不含源码，安装后只能运行，不能直接修改")
            if conflict.kind != "none":
                warnings.append("检测到已有应用或版本，确认时必须明确选择更新或复制")
            plan = ImportPlan(
                import_id=import_id,
                created_at=now,
                expires_at=now + timedelta(seconds=PLAN_TTL_SECONDS),
                app=ImportAppSummary(
                    id=inspection.manifest.id,
                    name=inspection.manifest.name,
                    version=inspection.manifest.version,
                    description=inspection.manifest.description,
                ),
                source_included=inspection.envelope.source_included,
                signature_state=inspection.signature_state,
                requested_permissions=inspection.manifest.permissions,
                conflict=conflict,
                warnings=warnings,
                package_sha256=inspection.package_sha256,
            )
            atomic_json_write(
                plan_dir / "plan.json",
                plan.model_dump(mode="json"),
                indent=2,
                mode=0o600,
                sort_keys=True,
            )
            return plan
        except BaseException:
            _safe_rmtree(plan_dir)
            raise
        finally:
            _safe_rmtree(analyze_dir)

    def cleanup_expired_plans(self) -> int:
        """Remove expired plans and abandoned incomplete staging directories."""
        self.paths.ensure()
        removed = 0
        now = self._clock()
        for entry in self.paths.import_plans.iterdir():
            if entry.is_symlink():
                entry.unlink()
                removed += 1
                continue
            if not entry.is_dir():
                continue
            plan_path = entry / "plan.json"
            should_remove = False
            try:
                plan = ImportPlan.model_validate_json(plan_path.read_bytes())
                should_remove = plan.expires_at <= now
            except (OSError, ValidationError):
                try:
                    age = now.timestamp() - entry.stat().st_mtime
                except OSError:
                    age = 0
                should_remove = age > PLAN_TTL_SECONDS
            if should_remove:
                _safe_rmtree(entry)
                removed += 1
        return removed

    def get_plan(self, import_id: str) -> ImportPlan:
        plan_dir = self.paths.import_plan(import_id)
        plan_path = plan_dir / "plan.json"
        package_path = plan_dir / "package.happ"
        if plan_dir.is_symlink() or plan_path.is_symlink() or package_path.is_symlink():
            self.discard(import_id)
            raise ImportPlanError(
                "APP_IMPORT_REJECTED",
                "import plan contains an unsafe symlink",
            )
        try:
            raw = plan_path.read_bytes()
        except FileNotFoundError as exc:
            raise ImportPlanError("APP_NOT_FOUND", "import plan was not found") from exc
        except OSError as exc:
            raise ImportPlanError(
                "APP_IMPORT_REJECTED",
                "import plan could not be read",
                retryable=True,
            ) from exc
        if len(raw) > MAX_METADATA_BYTES:
            self.discard(import_id)
            raise ImportPlanError("APP_IMPORT_REJECTED", "import plan is too large")
        try:
            plan = ImportPlan.model_validate_json(raw)
        except ValidationError as exc:
            self.discard(import_id)
            raise ImportPlanError("APP_IMPORT_REJECTED", "import plan is invalid") from exc
        if plan.import_id != import_id:
            self.discard(import_id)
            raise ImportPlanError("APP_IMPORT_REJECTED", "import plan identity mismatch")
        if self._clock() >= plan.expires_at:
            self.discard(import_id)
            raise ImportPlanError("APP_IMPORT_EXPIRED", "import plan has expired")
        return plan

    def discard(self, import_id: str) -> None:
        plan_dir = self.paths.import_plan(import_id)
        if plan_dir.is_symlink():
            try:
                plan_dir.unlink()
            except FileNotFoundError:
                pass
            return
        _safe_rmtree(plan_dir)

    def confirm(
        self,
        import_id: str,
        confirmation: ImportConfirmation,
    ) -> InstallResult:
        """Revalidate staged package bytes and atomically install one version."""
        plan = self.get_plan(import_id)
        if not hmac.compare_digest(
            confirmation.package_sha256,
            plan.package_sha256,
        ):
            raise ImportPlanError(
                "APP_IMPORT_REJECTED",
                "confirmation does not match the analyzed package",
            )
        validate_permission_grants(plan.requested_permissions, confirmation.grants)
        _validate_conflict_choice(plan, confirmation)

        package_path = self.paths.import_plan(import_id) / "package.happ"
        workspace = self.paths.staging / f"import-{import_id}-{uuid.uuid4()}"
        snapshot = workspace / "package.happ"
        install_stage = workspace / "content"
        try:
            try:
                snapshot_sha256 = _copy_package(package_path, snapshot)
                if not hmac.compare_digest(snapshot_sha256, plan.package_sha256):
                    raise ImportPlanError(
                        "APP_IMPORT_REJECTED",
                        "staged package changed after analysis",
                    )
                inspection = inspect_happ_package(
                    snapshot,
                    install_stage,
                    signing_keys=self.signing_keys,
                )
                _match_plan(plan, inspection)
            except (PackageValidationError, PackageTooLargeError, ImportPlanError):
                self.discard(import_id)
                raise
            manifest = inspection.manifest
            if confirmation.conflict_mode == "copy":
                manifest = _rewrite_copy_manifest(
                    install_stage,
                    manifest,
                    confirmation.copy_app_id or "",
                )
            for name in _TRANSPORT_FILES:
                transport = install_stage / name
                if transport.exists():
                    transport.unlink()
            result = self.registry.install_staged_version(
                install_stage,
                manifest,
                package_sha256=inspection.package_sha256,
                source_included=inspection.envelope.source_included,
                signature_state=(
                    "unsigned"
                    if confirmation.conflict_mode == "copy"
                    else inspection.signature_state
                ),
                grants=confirmation.grants,
                conflict_mode=confirmation.conflict_mode,
                lineage="imported",
            )
        except BaseException:
            _safe_rmtree(workspace)
            raise
        self.discard(import_id)
        _safe_rmtree(workspace)
        return result


def export_happ_package(
    app_root: str | Path,
    destination: str | Path,
    *,
    created_at: datetime,
    include_source: bool,
    lineage: AppLineage = "user",
    overwrite: bool = False,
) -> PackageExport:
    """Create one deterministic unsigned `.happ`, then validate it as hostile input."""
    root = Path(app_root)
    output = Path(destination)
    if output.suffix.casefold() != ".happ":
        raise PackageValidationError("export destination must use the .happ extension")
    if created_at.tzinfo is None:
        raise PackageValidationError("export timestamp must include a timezone")
    if root.is_symlink():
        raise PackageValidationError("application root cannot be a symlink")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise PackageValidationError("application root does not exist") from exc
    if not resolved_root.is_dir():
        raise PackageValidationError("application root must be a directory")

    manifest = load_manifest(
        resolved_root / "app.yaml",
        app_root=resolved_root,
        lineage=lineage,
    )
    if include_source and manifest.source is None:
        raise PackageValidationError("editable source is not available for export")

    manifest_for_package = manifest
    manifest_content: bytes | None = None
    if not include_source and manifest.source is not None:
        manifest_for_package = manifest.model_copy(update={"source": None})
        manifest_content = yaml.safe_dump(
            manifest_for_package.contract_dict(),
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8")

    files = _collect_export_files(
        resolved_root,
        manifest_for_package,
        include_source=include_source,
        manifest_content=manifest_content,
    )
    created = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    envelope = {
        "format_version": 1,
        "app_id": manifest_for_package.id,
        "app_version": manifest_for_package.version,
        "created_at": created,
        "created_by": "hermes-cli",
        "source_included": include_source,
        "manifest": "app.yaml",
        "checksums": "checksums.json",
    }
    files["happ.json"] = _ExportFile(
        "happ.json",
        content=_canonical_json(envelope),
    )

    checksum_entries: list[dict[str, Any]] = []
    fingerprints: dict[str, tuple[int, str]] = {}
    total_uncompressed = 0
    for name in sorted(files, key=lambda value: value.encode("utf-8")):
        size, digest = files[name].size_and_sha256()
        fingerprints[name] = (size, digest)
        total_uncompressed += size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise PackageTooLargeError("package exceeds the 200 MiB expanded limit")
        checksum_entries.append({"path": name, "size": size, "sha256": digest})
    checksums = _canonical_json(
        {
            "format_version": 1,
            "algorithm": "sha256",
            "files": checksum_entries,
        }
    )
    files["checksums.json"] = _ExportFile("checksums.json", content=checksums)
    fingerprints["checksums.json"] = (
        len(checksums),
        hashlib.sha256(checksums).hexdigest(),
    )
    if len(files) > MAX_ENTRIES:
        raise PackageTooLargeError("package contains too many entries")

    try:
        output_relative = output.resolve(strict=False).relative_to(resolved_root)
    except ValueError:
        output_relative = None
    if output_relative is not None and output_relative.parts:
        if output_relative.parts[0] in _ALLOWED_ROOTS:
            raise PackageValidationError("export destination cannot be inside package content")
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise PackageValidationError("export destination must be a regular file path")
    if output.exists() and not overwrite:
        raise PackageValidationError("export destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid.uuid4()}.tmp"
    verify_dir = output.parent / f".{output.name}.{uuid.uuid4()}.verify"
    try:
        with zipfile.ZipFile(
            temporary,
            "x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for name in sorted(files, key=lambda value: value.encode("utf-8")):
                size, digest = fingerprints[name]
                _write_export_member(
                    archive,
                    files[name],
                    expected_size=size,
                    expected_sha256=digest,
                )
        if temporary.stat().st_size > MAX_COMPRESSED_BYTES:
            raise PackageTooLargeError(".happ exceeds the 50 MiB compressed limit")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        inspection = inspect_happ_package(temporary, verify_dir)
        if inspection.manifest != manifest_for_package:
            raise PackageValidationError("exported Manifest changed during packaging")
        os.replace(temporary, output)
        try:
            output.chmod(0o600)
        except OSError:
            pass
        return PackageExport(
            path=output,
            package_sha256=inspection.package_sha256,
            size=output.stat().st_size,
            source_included=include_source,
        )
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    finally:
        _safe_rmtree(verify_dir)


def inspect_happ_package(
    package_path: Path,
    extract_dir: Path,
    *,
    signing_keys: Mapping[str, SigningKey] | None = None,
) -> PackageInspection:
    """Fully validate one archive and stream regular files into a fresh directory."""
    package_sha256 = _sha256_file(package_path, limit=MAX_COMPRESSED_BYTES)
    _validate_zip_container(package_path)
    if extract_dir.exists() or extract_dir.is_symlink():
        raise PackageValidationError("extraction directory must not already exist")
    extract_dir.mkdir(parents=True, mode=0o700)
    try:
        try:
            with zipfile.ZipFile(package_path, "r") as archive:
                members = _validate_members(archive)
                extracted = _extract_members(archive, members, extract_dir)
        except zipfile.BadZipFile as exc:
            raise PackageValidationError("package ZIP structure or CRC is invalid") from exc
        _envelope_data, envelope_raw = _read_json_file(extract_dir / "happ.json")
        checksum_data, checksum_raw = _read_json_file(extract_dir / "checksums.json")
        try:
            envelope = HappEnvelope.model_validate_json(envelope_raw)
            checksums = ChecksumManifest.model_validate_json(checksum_raw)
        except ValidationError as exc:
            raise PackageValidationError(
                "package metadata does not match .happ format v1",
                details={"issues": len(exc.errors())},
            ) from exc
        _validate_canonical_checksums(checksum_data, checksum_raw)
        _validate_checksums(checksums, extracted, envelope)
        signature_state = _validate_signature(
            envelope,
            extract_dir,
            checksum_raw,
            signing_keys or {},
        )
        try:
            manifest = load_manifest(
                extract_dir / envelope.manifest,
                app_root=extract_dir,
                lineage="imported",
            )
        except ManifestValidationError as exc:
            raise PackageValidationError(
                "application Manifest is invalid or requests a forbidden capability",
                details={"issues": [issue.as_dict() for issue in exc.issues]},
            ) from exc
        if envelope.app_id != manifest.id or envelope.app_version != manifest.version:
            raise PackageValidationError("package envelope and Manifest identity do not match")
        has_source_file = any(path.startswith("source/") for path in extracted)
        if envelope.source_included != has_source_file:
            raise PackageValidationError("source_included does not match package contents")
        if (manifest.source is not None) != envelope.source_included:
            raise PackageValidationError("Manifest source does not match package contents")
        return PackageInspection(
            manifest=manifest,
            envelope=envelope,
            checksums=checksums,
            package_sha256=package_sha256,
            signature_state=signature_state,
            warnings=(),
        )
    except BaseException:
        _safe_rmtree(extract_dir)
        raise


def _copy_package(source: Path, destination: Path) -> str:
    if source.is_symlink() or not source.is_file():
        raise PackageValidationError(".happ source must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            while chunk := reader.read(STREAM_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_COMPRESSED_BYTES:
                    raise PackageTooLargeError(".happ exceeds the 50 MiB compressed limit")
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        destination.chmod(0o600)
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return digest.hexdigest()


def _sha256_file(path: Path, *, limit: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise PackageValidationError("package must be a regular file")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(STREAM_CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                raise PackageTooLargeError("package exceeds the compressed size limit")
            digest.update(chunk)
    return digest.hexdigest()


def _validate_zip_container(path: Path) -> None:
    raw_size = path.stat().st_size
    if raw_size < 22:
        raise PackageValidationError("package is not a valid ZIP container")
    with path.open("rb") as handle:
        if handle.read(4) != b"PK\x03\x04":
            raise PackageValidationError("package contains prepended data or no local file header")
        tail_size = min(raw_size, 65_557)
        handle.seek(raw_size - tail_size)
        tail = handle.read(tail_size)
    marker = b"PK\x05\x06"
    offset = tail.rfind(marker)
    if offset < 0 or offset + 22 > len(tail):
        raise PackageValidationError("package has no valid end-of-central-directory record")
    comment_length = int.from_bytes(tail[offset + 20 : offset + 22], "little")
    if comment_length != 0 or offset + 22 != len(tail):
        raise PackageValidationError("ZIP comments and trailing data are not allowed")


def _validate_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str, bool]]:
    infos = archive.infolist()
    if not infos:
        raise PackageValidationError("package archive is empty")
    if len(infos) > MAX_ENTRIES:
        raise PackageTooLargeError("package contains too many entries")

    validated: list[tuple[zipfile.ZipInfo, str, bool]] = []
    seen: dict[str, str] = {}
    files: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        is_directory = info.is_dir()
        if any(ord(character) > 127 for character in info.filename) and not (
            info.flag_bits & 0x800
        ):
            raise PackageValidationError("non-ASCII archive paths must use UTF-8 encoding")
        normalized = _validate_archive_path(info.filename, is_directory=is_directory)
        folded = unicodedata.normalize("NFC", normalized).casefold()
        previous = seen.get(folded)
        if previous is not None:
            raise PackageValidationError(
                f"duplicate or case-colliding archive path: {normalized!r} and {previous!r}"
            )
        seen[folded] = normalized
        _validate_member_type(info, is_directory=is_directory)
        _validate_allowed_location(normalized, is_directory=is_directory)

        if not is_directory:
            files.add(normalized)
            if info.file_size > MAX_FILE_BYTES:
                raise PackageTooLargeError(f"package file exceeds 50 MiB: {normalized}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise PackageTooLargeError("package exceeds the 200 MiB expanded limit")
            if info.file_size >= COMPRESSION_RATIO_MIN_BYTES:
                if info.compress_size == 0:
                    raise PackageTooLargeError(f"package file has an invalid ratio: {normalized}")
                if info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    raise PackageTooLargeError(f"package file is excessively compressed: {normalized}")
        validated.append((info, normalized, is_directory))

    missing = sorted(_REQUIRED_FILES - files)
    if missing:
        raise PackageValidationError(f"package is missing required files: {', '.join(missing)}")
    for path in files:
        parents = list(PurePosixPath(path).parents)[:-1]
        if any(parent.as_posix() in files for parent in parents):
            raise PackageValidationError("archive file path is also used as a directory")
    return validated


def _validate_archive_path(name: str, *, is_directory: bool) -> str:
    if not name or "\x00" in name or "\\" in name or ":" in name:
        raise PackageValidationError("archive path contains a forbidden character")
    if name != unicodedata.normalize("NFC", name):
        raise PackageValidationError("archive path must use Unicode NFC form")
    trimmed = name[:-1] if is_directory and name.endswith("/") else name
    if not trimmed or trimmed.startswith("/") or (len(trimmed) >= 2 and trimmed[1] == ":"):
        raise PackageValidationError("archive path must be relative")
    if len(trimmed.encode("utf-8")) > 1024:
        raise PackageValidationError("archive path exceeds 1024 UTF-8 bytes")
    components = trimmed.split("/")
    for component in components:
        if component in {"", ".", ".."}:
            raise PackageValidationError("archive path contains an unsafe component")
        if len(component.encode("utf-8")) > 255:
            raise PackageValidationError("archive path component exceeds 255 UTF-8 bytes")
        if component.endswith((" ", ".")):
            raise PackageValidationError("archive path component has a non-portable suffix")
        device = component.split(".", 1)[0].upper()
        if device in _WINDOWS_DEVICES:
            raise PackageValidationError("archive path uses a reserved Windows device name")
        if component.casefold() in _FORBIDDEN_COMPONENTS:
            raise PackageValidationError(f"archive contains forbidden directory: {component}")
        folded_component = component.casefold()
        if (
            folded_component == ".env"
            or folded_component.startswith(".env.")
            or folded_component in _SECRET_FILE_NAMES
            or Path(folded_component).suffix in _SECRET_SUFFIXES
        ):
            raise PackageValidationError("archive contains a credential-like file")
    return trimmed


def _validate_member_type(info: zipfile.ZipInfo, *, is_directory: bool) -> None:
    if info.flag_bits & 0x1:
        raise PackageValidationError("encrypted ZIP entries are not supported")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise PackageValidationError("only stored and DEFLATE ZIP entries are supported")
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if info.create_system == 3:
        expected = stat.S_IFDIR if is_directory else stat.S_IFREG
        if file_type not in {0, expected}:
            raise PackageValidationError("archive contains a link or special file")
        if not is_directory and unix_mode & 0o111:
            raise PackageValidationError("archive regular files cannot be executable")


def _validate_allowed_location(path: str, *, is_directory: bool) -> None:
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        if is_directory and parts[0] in _ALLOWED_ROOTS:
            return
        if parts[0] in _REQUIRED_FILES or parts[0] == "signature.json":
            return
        lower = parts[0].lower()
        if lower in {"icon.png", "icon.webp", "icon.jpg", "icon.jpeg"}:
            return
        raise PackageValidationError(f"package contains an unsupported root entry: {path}")
    if parts[0] not in _ALLOWED_ROOTS:
        raise PackageValidationError(f"package path is outside an allowed root: {path}")
    if not is_directory and Path(parts[-1]).suffix.lower() in _SERVER_CODE_SUFFIXES:
        raise PackageValidationError(f"package contains forbidden server-side code: {path}")


def _extract_members(
    archive: zipfile.ZipFile,
    members: list[tuple[zipfile.ZipInfo, str, bool]],
    destination: Path,
) -> dict[str, _ExtractedFile]:
    extracted: dict[str, _ExtractedFile] = {}
    total = 0
    for info, relative, is_directory in members:
        target = destination.joinpath(*PurePosixPath(relative).parts)
        if is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        try:
            with archive.open(info, "r") as reader, target.open("xb") as writer:
                while chunk := reader.read(STREAM_CHUNK_BYTES):
                    written += len(chunk)
                    total += len(chunk)
                    if written > MAX_FILE_BYTES or total > MAX_UNCOMPRESSED_BYTES:
                        raise PackageTooLargeError("package exceeded limits while extracting")
                    digest.update(chunk)
                    writer.write(chunk)
        except BaseException:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        if written != info.file_size:
            raise PackageValidationError(f"ZIP metadata size mismatch: {relative}")
        try:
            target.chmod(0o600)
        except OSError:
            pass
        extracted[relative] = _ExtractedFile(written, digest.hexdigest())
    return extracted


def _read_json_file(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_METADATA_BYTES:
        raise PackageTooLargeError(f"metadata file is too large: {path.name}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageValidationError(f"invalid JSON metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise PackageValidationError(f"metadata root must be an object: {path.name}")
    return value, raw


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _validate_canonical_checksums(value: dict[str, Any], raw: bytes) -> None:
    if not hmac.compare_digest(_canonical_json(value), raw):
        raise PackageValidationError("checksums.json is not in canonical byte form")


def _validate_checksums(
    checksums: ChecksumManifest,
    extracted: Mapping[str, _ExtractedFile],
    envelope: HappEnvelope,
) -> None:
    listed_paths = [entry.path for entry in checksums.files]
    if listed_paths != sorted(listed_paths, key=lambda path: path.encode("utf-8")):
        raise PackageValidationError("checksums.json files must be sorted by UTF-8 path")
    if len(listed_paths) != len(set(listed_paths)):
        raise PackageValidationError("checksums.json contains duplicate paths")
    expected = set(extracted) - {"checksums.json", "signature.json"}
    if set(listed_paths) != expected:
        raise PackageValidationError("checksums.json does not exactly cover package files")
    for entry in checksums.files:
        actual = extracted[entry.path]
        if entry.size != actual.size or not hmac.compare_digest(entry.sha256, actual.sha256):
            raise PackageValidationError(f"checksum mismatch for {entry.path}")
    has_signature = "signature.json" in extracted
    if (envelope.signature is not None) != has_signature:
        raise PackageValidationError("signature metadata does not match package contents")


def _validate_signature(
    envelope: HappEnvelope,
    extracted_root: Path,
    canonical_checksums: bytes,
    signing_keys: Mapping[str, SigningKey],
) -> SignatureState:
    if envelope.signature is None:
        return "unsigned"
    value, _raw = _read_json_file(extracted_root / envelope.signature)
    try:
        signature = PackageSignature.model_validate(value)
    except ValidationError as exc:
        raise PackageValidationError("signature.json is invalid") from exc
    key = signing_keys.get(signature.key_id)
    if key is None:
        raise PackageValidationError("package signature uses an unknown signing key")
    try:
        decoded = base64.b64decode(signature.signature, validate=True)
        if len(decoded) != 64:
            raise ValueError("invalid Ed25519 signature length")
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(
            decoded,
            canonical_checksums,
        )
    except (ValueError, InvalidSignature, binascii.Error) as exc:
        raise PackageValidationError("package signature verification failed") from exc
    return "valid_trusted" if key.trusted else "valid_untrusted"


def _validate_conflict_choice(
    plan: ImportPlan,
    confirmation: ImportConfirmation,
) -> None:
    existing = plan.conflict.kind != "none"
    if existing and confirmation.conflict_mode == "install":
        raise ImportPlanError(
            "APP_VERSION_CONFLICT",
            "existing application requires update or copy",
        )
    if not existing and confirmation.conflict_mode == "update":
        raise ImportPlanError(
            "APP_VERSION_CONFLICT",
            "update requires an existing application",
        )
    if confirmation.copy_app_id == plan.app.id:
        raise ImportPlanError(
            "APP_VERSION_CONFLICT",
            "copy target id must differ from the package app id",
        )


def _match_plan(plan: ImportPlan, inspection: PackageInspection) -> None:
    if not hmac.compare_digest(plan.package_sha256, inspection.package_sha256):
        raise ImportPlanError(
            "APP_IMPORT_REJECTED",
            "staged package changed after analysis",
        )
    identity = (
        inspection.manifest.id,
        inspection.manifest.name,
        inspection.manifest.version,
        inspection.manifest.description,
    )
    planned = (plan.app.id, plan.app.name, plan.app.version, plan.app.description)
    if identity != planned:
        raise ImportPlanError("APP_IMPORT_REJECTED", "package identity changed after analysis")
    if inspection.manifest.permissions != plan.requested_permissions:
        raise ImportPlanError("APP_IMPORT_REJECTED", "package permissions changed after analysis")
    if inspection.envelope.source_included != plan.source_included:
        raise ImportPlanError("APP_IMPORT_REJECTED", "package source state changed after analysis")
    if inspection.signature_state != plan.signature_state:
        raise ImportPlanError("APP_IMPORT_REJECTED", "package signature state changed after analysis")


def _rewrite_copy_manifest(
    app_root: Path,
    manifest: AppManifest,
    copy_app_id: str,
) -> AppManifest:
    data = manifest.contract_dict()
    data["id"] = copy_app_id
    atomic_yaml_write(
        app_root / "app.yaml",
        data,
        sort_keys=False,
    )
    return load_manifest(
        app_root / "app.yaml",
        app_root=app_root,
        lineage="imported",
    )


def _collect_export_files(
    root: Path,
    manifest: AppManifest,
    *,
    include_source: bool,
    manifest_content: bytes | None,
) -> dict[str, _ExportFile]:
    files: dict[str, _ExportFile] = {
        "app.yaml": _ExportFile(
            "app.yaml",
            source=None if manifest_content is not None else root / "app.yaml",
            content=manifest_content,
        )
    }
    roots = set(_ALLOWED_ROOTS)
    if not include_source:
        roots.discard("source")
    for root_name in sorted(roots):
        directory = root / root_name
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise PackageValidationError(f"export root must be a real directory: {root_name}")
        for current, directory_names, file_names in os.walk(
            directory,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            kept_directories: list[str] = []
            for name in sorted(directory_names):
                candidate = current_path / name
                relative = candidate.relative_to(root)
                if name.casefold() in _FORBIDDEN_COMPONENTS:
                    continue
                if candidate.is_symlink():
                    raise PackageValidationError(
                        f"export cannot include a symlink: {relative.as_posix()}"
                    )
                kept_directories.append(name)
            directory_names[:] = kept_directories

            for name in sorted(file_names):
                candidate = current_path / name
                relative = candidate.relative_to(root)
                if candidate.is_symlink():
                    raise PackageValidationError(
                        f"export cannot include a symlink: {relative.as_posix()}"
                    )
                if not candidate.is_file():
                    raise PackageValidationError(
                        f"export cannot include a special file: {relative.as_posix()}"
                    )
                archive_path = relative.as_posix()
                _validate_archive_path(archive_path, is_directory=False)
                _validate_allowed_location(archive_path, is_directory=False)
                files[archive_path] = _ExportFile(archive_path, source=candidate)

    if "/" not in manifest.icon:
        icon = root / manifest.icon
        if icon.is_symlink() or not icon.is_file():
            raise PackageValidationError("application icon must be a regular file")
        files[manifest.icon] = _ExportFile(manifest.icon, source=icon)
    if include_source and not any(path.startswith("source/") for path in files):
        raise PackageValidationError("source export requires at least one source file")
    return files


def _write_export_member(
    archive: zipfile.ZipFile,
    entry: _ExportFile,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    info = zipfile.ZipInfo(entry.path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    digest = hashlib.sha256()
    written = 0
    with archive.open(info, "w", force_zip64=expected_size >= 2**31) as writer:
        if entry.content is not None:
            digest.update(entry.content)
            writer.write(entry.content)
            written = len(entry.content)
        elif entry.source is not None:
            with entry.source.open("rb") as reader:
                while chunk := reader.read(STREAM_CHUNK_BYTES):
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise PackageTooLargeError(
                            f"package file exceeds 50 MiB while exporting: {entry.path}"
                        )
                    digest.update(chunk)
                    writer.write(chunk)
        else:
            raise PackageValidationError("export entry has no source")
    if written != expected_size or not hmac.compare_digest(
        digest.hexdigest(), expected_sha256
    ):
        raise PackageValidationError(f"application file changed during export: {entry.path}")


def _safe_rmtree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
        return
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "HappEnvelope",
    "HappImportService",
    "ImportConfirmation",
    "ImportPlan",
    "PackageExport",
    "PackageInspection",
    "PackageSignature",
    "SigningKey",
    "export_happ_package",
    "inspect_happ_package",
]
