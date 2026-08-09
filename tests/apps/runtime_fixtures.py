from __future__ import annotations

import json
from pathlib import Path

import yaml

from hermes_cli.apps.manifest import parse_manifest

from .happ_fixtures import manifest_data


def runtime_app(tmp_path: Path):
    root = tmp_path / "app"
    for directory in ("dist/assets", "source", "prompts", "schemas"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "dist/index.html").write_text(
        '<!doctype html><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (root / "dist/assets/app.js").write_text("window.appReady = true", encoding="utf-8")
    (root / "dist/assets/Chart.js").write_text("window.Chart = {}", encoding="utf-8")
    (root / "icon.png").write_bytes(b"png")
    (root / "source/main.ts").write_text("export {}", encoding="utf-8")
    (root / "prompts/analyze.md").write_text("分析股票。", encoding="utf-8")
    for name in (
        "refresh.input.json",
        "refresh.output.json",
        "analyze.input.json",
        "analyze.output.json",
    ):
        (root / "schemas" / name).write_text("{}", encoding="utf-8")
    manifest = parse_manifest(manifest_data())
    (root / "app.yaml").write_text(
        yaml.safe_dump(manifest_data(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root, manifest, manifest.permissions


def service_runtime_app(tmp_path: Path):
    """Create a small generic service-backed app fixture for runtime tests."""
    root, _manifest, _grants = runtime_app(tmp_path)
    data = manifest_data(version="1.0.1")
    data["permissions"] = {
        "agent": False,
        "mcp_servers": [],
        "storage": {"mode": "persistent", "quota_mb": 5},
    }
    data["actions"] = {
        "snapshot": {
            "kind": "service",
            "title": "获取测试快照",
            "handler": "test.snapshot",
            "input_schema": "schemas/snapshot.input.json",
            "output_schema": "schemas/snapshot.output.json",
            "timeout_seconds": 30,
            "max_concurrent_runs": 2,
            "cache_ttl_seconds": 10,
        }
    }
    (root / "schemas/snapshot.input.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "properties": {"auto_refresh": {"type": "boolean"}},
            }
        ),
        encoding="utf-8",
    )
    (root / "schemas/snapshot.output.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["ok"],
                "additionalProperties": True,
            }
        ),
        encoding="utf-8",
    )
    manifest = parse_manifest(
        data,
        lineage="builtin",
        allowed_service_handlers={"test.snapshot"},
    )
    (root / "app.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root, manifest, manifest.permissions
