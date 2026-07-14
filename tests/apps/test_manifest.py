from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from hermes_cli.apps import ManifestValidationError, load_manifest, parse_manifest
from hermes_cli.apps.contracts import contract_path


def _manifest_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "ai.hermes.watchlist",
        "name": "自选股",
        "version": "1.0.0",
        "description": "本地自选股盯盘与分析应用",
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
                "input_schema": "schemas/refresh-quotes.input.json",
                "output_schema": "schemas/refresh-quotes.output.json",
                "timeout_seconds": 30,
                "max_concurrent_runs": 2,
                "cache_ttl_seconds": 15,
            },
            "analyze_stock": {
                "kind": "agent",
                "title": "详细分析",
                "prompt": "prompts/analyze-stock.md",
                "input_schema": "schemas/analyze-stock.input.json",
                "output_schema": "schemas/analyze-stock.output.json",
                "mode": "stateless",
                "toolsets": ["mcp"],
                "timeout_seconds": 180,
                "max_iterations": 12,
                "max_concurrent_runs": 1,
                "cache_ttl_seconds": 300,
            },
        },
    }


def _service_action(handler: str = "finance.watchlist.snapshot") -> dict[str, Any]:
    return {
        "kind": "service",
        "title": "读取内置快照",
        "handler": handler,
        "input_schema": "schemas/snapshot.input.json",
        "output_schema": "schemas/snapshot.output.json",
        "timeout_seconds": 30,
        "max_concurrent_runs": 1,
        "cache_ttl_seconds": 15,
    }


def _write_app_tree(root: Path, data: dict[str, Any]) -> Path:
    for directory in ("dist", "source", "schemas", "prompts"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "dist/index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "icon.png").write_bytes(b"png")
    for name in (
        "refresh-quotes.input.json",
        "refresh-quotes.output.json",
        "analyze-stock.input.json",
        "analyze-stock.output.json",
    ):
        (root / "schemas" / name).write_text("{}", encoding="utf-8")
    (root / "prompts/analyze-stock.md").write_text("分析股票。", encoding="utf-8")
    manifest_path = root / "app.yaml"
    manifest_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return manifest_path


def _issue_codes(exc: ManifestValidationError) -> set[str]:
    return {issue.code for issue in exc.issues}


def test_parse_manifest_returns_strict_domain_model() -> None:
    manifest = parse_manifest(_manifest_data())

    assert manifest.id == "ai.hermes.watchlist"
    assert set(manifest.actions) == {"refresh_quotes", "analyze_stock"}

    schema = json.loads(contract_path("app-manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest.contract_dict())


@pytest.mark.parametrize("field", ["trust_state", "granted_permissions", "backend"])
def test_runtime_authority_fields_are_rejected(field: str) -> None:
    data = _manifest_data()
    data[field] = {}

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data)

    assert any(code == "schema.extra_forbidden" for code in _issue_codes(caught.value))


@pytest.mark.parametrize("field", ["source", "display"])
def test_optional_manifest_fields_reject_explicit_null(field: str) -> None:
    data = _manifest_data()
    data[field] = None

    with pytest.raises(ManifestValidationError):
        parse_manifest(data)


def test_agent_action_requires_agent_permission_request() -> None:
    data = _manifest_data()
    data["permissions"]["agent"] = False

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data)

    assert "permission.agent_not_requested" in _issue_codes(caught.value)


def test_mcp_action_requires_matching_server_permission() -> None:
    data = _manifest_data()
    data["permissions"]["mcp_servers"] = []

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data)

    assert "permission.mcp_not_requested" in _issue_codes(caught.value)


@pytest.mark.parametrize("lineage", ["user", "imported"])
def test_user_controlled_lineage_cannot_use_service_actions(lineage: str) -> None:
    data = _manifest_data()
    data["actions"] = {"snapshot": _service_action()}

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data, lineage=lineage)  # type: ignore[arg-type]

    assert "service.user_forbidden" in _issue_codes(caught.value)


def test_builtin_service_action_requires_exact_inherited_handler() -> None:
    data = _manifest_data()
    data["actions"] = {"snapshot": _service_action()}

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(
            data,
            lineage="builtin",
            allowed_service_handlers={"finance.watchlist.other"},
        )
    assert "service.handler_not_inherited" in _issue_codes(caught.value)

    manifest = parse_manifest(
        data,
        lineage="builtin",
        allowed_service_handlers={"finance.watchlist.snapshot"},
    )
    assert manifest.actions["snapshot"].kind == "service"


def test_relative_references_reject_traversal() -> None:
    data = _manifest_data()
    data["actions"]["refresh_quotes"]["input_schema"] = "schemas/../secret.json"

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data)

    assert "path.traversal" in _issue_codes(caught.value)


def test_references_reject_case_insensitive_collisions() -> None:
    data = _manifest_data()
    data["actions"]["refresh_quotes"]["input_schema"] = "schemas/Quote.json"
    data["actions"]["refresh_quotes"]["output_schema"] = "schemas/quote.json"

    with pytest.raises(ManifestValidationError) as caught:
        parse_manifest(data)

    assert "path.case_collision" in _issue_codes(caught.value)


def test_load_manifest_verifies_all_referenced_files(tmp_path: Path) -> None:
    data = _manifest_data()
    manifest_path = _write_app_tree(tmp_path, data)

    manifest = load_manifest(manifest_path, app_root=tmp_path)

    assert manifest.version == "1.0.0"


def test_load_manifest_reports_missing_referenced_file(tmp_path: Path) -> None:
    data = _manifest_data()
    manifest_path = _write_app_tree(tmp_path, data)
    (tmp_path / "schemas/refresh-quotes.output.json").unlink()

    with pytest.raises(ManifestValidationError) as caught:
        load_manifest(manifest_path, app_root=tmp_path)

    assert "files.missing" in _issue_codes(caught.value)
    assert any(issue.path.endswith("output_schema") for issue in caught.value.issues)


def test_load_manifest_rejects_symlinked_reference(tmp_path: Path) -> None:
    data = _manifest_data()
    manifest_path = _write_app_tree(tmp_path, data)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    linked = tmp_path / "schemas/refresh-quotes.input.json"
    linked.unlink()
    try:
        linked.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ManifestValidationError) as caught:
        load_manifest(manifest_path, app_root=tmp_path)

    assert "files.symlink" in _issue_codes(caught.value)


def test_parse_does_not_mutate_input() -> None:
    data = _manifest_data()
    before = copy.deepcopy(data)

    parse_manifest(data)

    assert data == before
