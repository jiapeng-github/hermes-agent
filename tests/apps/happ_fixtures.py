from __future__ import annotations

import base64
import hashlib
import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def manifest_data(*, version: str = "1.0.0", description: str = "自选股应用") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "ai.hermes.watchlist",
        "name": "自选股",
        "version": version,
        "description": description,
        "entry": "dist/index.html",
        "icon": "icon.png",
        "source": "source",
        "sdk_version": "1.0.0",
        "min_runtime_version": "1.0.0",
        "permissions": {
            "agent": True,
            "mcp_servers": ["mx-ds-mcp"],
            "storage": {"mode": "persistent", "quota_mb": 25},
        },
        "actions": {
            "refresh_quotes": {
                "kind": "mcp",
                "title": "刷新行情",
                "server": "mx-ds-mcp",
                "tool": "stock/quotes",
                "arguments_template": {"codes": "{{input.codes}}"},
                "input_schema": "schemas/refresh.input.json",
                "output_schema": "schemas/refresh.output.json",
                "timeout_seconds": 30,
                "max_concurrent_runs": 2,
                "cache_ttl_seconds": 15,
            },
            "analyze_stock": {
                "kind": "agent",
                "title": "详细分析",
                "prompt": "prompts/analyze.md",
                "input_schema": "schemas/analyze.input.json",
                "output_schema": "schemas/analyze.output.json",
                "mode": "stateless",
                "toolsets": ["mcp"],
                "timeout_seconds": 180,
                "max_iterations": 12,
                "max_concurrent_runs": 1,
                "cache_ttl_seconds": 300,
            },
        },
    }


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def build_happ(
    path: Path,
    *,
    manifest: dict[str, Any] | None = None,
    extra_files: dict[str, bytes] | None = None,
    checksum_override: dict[str, str] | None = None,
    canonical_checksums: bool = True,
    member_modes: dict[str, int] | None = None,
    duplicate_files: list[tuple[str, bytes]] | None = None,
    signing_key: tuple[str, Ed25519PrivateKey] | None = None,
    include_source: bool = True,
) -> Path:
    manifest = manifest or manifest_data()
    files: dict[str, bytes] = {
        "app.yaml": yaml.safe_dump(
            manifest,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        "icon.png": b"not-a-real-png",
        "dist/index.html": b"<!doctype html><title>Watchlist</title>",
        "prompts/analyze.md": "分析股票。\n".encode(),
        "schemas/refresh.input.json": b"{}",
        "schemas/refresh.output.json": b"{}",
        "schemas/analyze.input.json": b"{}",
        "schemas/analyze.output.json": b"{}",
    }
    if include_source:
        files["source/main.ts"] = b"export const app = 'watchlist'\n"
    files.update(extra_files or {})
    envelope = {
        "format_version": 1,
        "app_id": manifest["id"],
        "app_version": manifest["version"],
        "created_at": "2026-07-12T08:00:00Z",
        "created_by": "hermes-desktop",
        "source_included": any(name.startswith("source/") for name in files),
        "manifest": "app.yaml",
        "checksums": "checksums.json",
    }
    if signing_key is not None:
        envelope["signature"] = "signature.json"
    files["happ.json"] = canonical_json(envelope)
    overrides = checksum_override or {}
    checksum_entries = []
    for name in sorted(files, key=lambda value: value.encode("utf-8")):
        content = files[name]
        checksum_entries.append(
            {
                "path": name,
                "size": len(content),
                "sha256": overrides.get(name, hashlib.sha256(content).hexdigest()),
            }
        )
    checksum_manifest = {
        "format_version": 1,
        "algorithm": "sha256",
        "files": checksum_entries,
    }
    if canonical_checksums:
        checksum_bytes = canonical_json(checksum_manifest)
    else:
        checksum_bytes = json.dumps(
            checksum_manifest,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
    files["checksums.json"] = checksum_bytes
    if signing_key is not None:
        key_id, private_key = signing_key
        files["signature.json"] = canonical_json(
            {
                "format_version": 1,
                "algorithm": "ed25519",
                "key_id": key_id,
                "signed_file": "checksums.json",
                "signature": base64.b64encode(private_key.sign(checksum_bytes)).decode(
                    "ascii"
                ),
            }
        )

    modes = member_modes or {}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            _write_member(archive, name, content, modes.get(name))
        for name, content in duplicate_files or []:
            _write_member(archive, name, content, modes.get(name))
    return path


def _write_member(
    archive: zipfile.ZipFile,
    name: str,
    content: bytes,
    mode: int | None,
) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 7, 12, 8, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = ((mode or (stat.S_IFREG | 0o600)) & 0xFFFF) << 16
    archive.writestr(info, content)
