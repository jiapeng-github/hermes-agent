from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from hermes_cli.apps.contracts import CONTRACT_VERSION, contract_directory
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths


CONTRACTS = contract_directory()
NORMATIVE_FILES = {
    "app-manifest.schema.json",
    "happ-format-v1.md",
    "happ-package.schema.json",
    "management-api.openapi.yaml",
    "runtime-event-protocol-v1.md",
    "runtime-event.schema.json",
}


def _read_json(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_read_json(name), format_checker=FormatChecker())


def _valid_manifest() -> dict[str, Any]:
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
        "display": {
            "theme": "auto",
            "preferred_width": 1280,
            "preferred_height": 800,
        },
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


def _runtime_event(event_type: str, payload: dict[str, Any], seq: int) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "run_id": "123e4567-e89b-42d3-a456-426614174000",
        "seq": seq,
        "timestamp": "2026-07-12T08:00:00Z",
        "type": event_type,
        "payload": payload,
    }


def _walk_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            yield ref
        for child in value.values():
            yield from _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_refs(child)


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw_part in pointer.removeprefix("#/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _openapi_schema(name: str) -> dict[str, Any]:
    document = yaml.safe_load(
        (CONTRACTS / "management-api.openapi.yaml").read_text(encoding="utf-8")
    )

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                return {"$ref": ref.replace("#/components/schemas/", "#/$defs/")}
            if ref == "./app-manifest.schema.json":
                return _read_json("app-manifest.schema.json")
            return {key: rewrite(child) for key, child in value.items()}
        if isinstance(value, list):
            return [rewrite(child) for child in value]
        return value

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": rewrite(document["components"]["schemas"]),
        "$ref": f"#/$defs/{name}",
    }


def test_contract_lock_matches_all_normative_files() -> None:
    lock = _read_json("CONTRACTS.lock.json")
    assert lock["contract_version"] == CONTRACT_VERSION
    assert lock["hash_algorithm"] == "sha256"
    assert set(lock["files"]) == NORMATIVE_FILES

    actual = {
        name: hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest()
        for name in NORMATIVE_FILES
    }
    assert lock["files"] == actual


@pytest.mark.parametrize(
    "schema_name",
    [
        "app-manifest.schema.json",
        "happ-package.schema.json",
        "runtime-event.schema.json",
    ],
)
def test_json_schema_is_valid_draft_2020_12(schema_name: str) -> None:
    Draft202012Validator.check_schema(_read_json(schema_name))


def test_watchlist_manifest_satisfies_frozen_schema() -> None:
    _validator("app-manifest.schema.json").validate(_valid_manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trust_state", "builtin"),
        ("granted_permissions", {"agent": True}),
        ("backend", {"command": "python server.py"}),
    ],
)
def test_manifest_cannot_self_declare_runtime_authority(field: str, value: Any) -> None:
    manifest = _valid_manifest()
    manifest[field] = value

    errors = list(_validator("app-manifest.schema.json").iter_errors(manifest))

    assert errors


def test_manifest_rejects_arbitrary_action_fields() -> None:
    manifest = _valid_manifest()
    manifest["actions"]["refresh_quotes"]["shell_command"] = "curl example.com"

    errors = list(_validator("app-manifest.schema.json").iter_errors(manifest))

    assert errors


def test_happ_metadata_definitions_validate_canonical_examples() -> None:
    schema = _read_json("happ-package.schema.json")
    envelope = {
        "format_version": 1,
        "app_id": "ai.hermes.watchlist",
        "app_version": "1.0.0",
        "created_at": "2026-07-12T08:00:00Z",
        "created_by": "hermes-desktop",
        "source_included": True,
        "manifest": "app.yaml",
        "checksums": "checksums.json",
    }
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(envelope)

    checksum_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/checksumManifest",
    }
    checksum_manifest = {
        "format_version": 1,
        "algorithm": "sha256",
        "files": [
            {"path": "app.yaml", "size": 200, "sha256": "0" * 64},
            {"path": "happ.json", "size": 180, "sha256": "1" * 64},
            {"path": "icon.png", "size": 500, "sha256": "2" * 64},
        ],
    }
    Draft202012Validator(checksum_schema).validate(checksum_manifest)


def test_runtime_schema_accepts_every_frozen_event_type() -> None:
    operation_id = "123e4567-e89b-42d3-a456-426614174001"
    payloads = [
        ("run.accepted", {"action_id": "refresh_quotes", "queue_position": 0}),
        ("run.started", {"attempt": 1}),
        ("status", {"phase": "running", "message": "正在刷新", "progress": 0.5}),
        ("text.delta", {"text": "分析结果"}),
        ("data.snapshot", {"data": {"quotes": []}}),
        ("data.delta", {"patch": [{"op": "add", "path": "/quotes/0", "value": {}}]}),
        (
            "operation.started",
            {"operation_id": operation_id, "kind": "mcp", "label": "查询行情"},
        ),
        ("operation.progress", {"operation_id": operation_id, "progress": 0.7}),
        ("operation.completed", {"operation_id": operation_id, "summary": "完成"}),
        (
            "usage.updated",
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ),
        ("run.completed", {"result": {"quotes": []}}),
        (
            "run.failed",
            {"error": {"code": "MCP_UNAVAILABLE", "message": "数据源不可用", "retryable": True}},
        ),
        ("run.cancelled", {"reason": "用户取消", "requested_by": "user"}),
        ("heartbeat", {}),
    ]
    validator = _validator("runtime-event.schema.json")

    for seq, (event_type, payload) in enumerate(payloads, start=1):
        validator.validate(_runtime_event(event_type, payload, seq))


def test_runtime_event_payload_must_match_event_type() -> None:
    invalid = _runtime_event("heartbeat", {"text": "not empty"}, 1)

    errors = list(_validator("runtime-event.schema.json").iter_errors(invalid))

    assert errors


def test_openapi_contract_has_resolvable_refs_and_unique_operations() -> None:
    path = CONTRACTS / "management-api.openapi.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == CONTRACT_VERSION
    assert document["security"] == [{"sessionBearer": []}]

    for ref in _walk_refs(document):
        if ref.startswith("#/"):
            assert _resolve_pointer(document, ref) is not None
            continue
        external_name, _, pointer = ref.partition("#")
        external_path = (path.parent / external_name).resolve()
        assert external_path.parent == path.parent.resolve()
        external = json.loads(external_path.read_text(encoding="utf-8"))
        if pointer:
            assert _resolve_pointer(external, f"#{pointer}") is not None

    operation_ids: list[str] = []
    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_ids.append(operation["operationId"])
    assert len(operation_ids) == len(set(operation_ids))


def test_openapi_mutating_body_operations_require_idempotency_keys() -> None:
    document = yaml.safe_load(
        (CONTRACTS / "management-api.openapi.yaml").read_text(encoding="utf-8")
    )

    for path, path_item in document["paths"].items():
        for method in ("post", "put", "patch"):
            operation = path_item.get(method)
            if operation is None:
                continue
            refs = {
                parameter.get("$ref")
                for parameter in operation.get("parameters", [])
                if isinstance(parameter, dict)
            }
            assert "#/components/parameters/IdempotencyKey" in refs, (method, path)


def test_manager_outputs_match_frozen_openapi_schemas(tmp_path: Path) -> None:
    manager = AppManager(AppPaths(tmp_path / "profile"))
    workspace = manager.workspaces.init(
        tmp_path / "contract-app",
        app_id="local.stockagent.contract-app",
        template="vanilla",
    )
    manager.publish(workspace)

    app_list = manager.list_apps()
    detail = manager.inspect("local.stockagent.contract-app")["app"]
    package = manager.export(
        "local.stockagent.contract-app",
        tmp_path / "contract-app.happ",
    )
    import_manager = AppManager(AppPaths(tmp_path / "import-profile"))
    plan = import_manager.analyze_import(package.path).public_dict()

    Draft202012Validator(
        _openapi_schema("AppList"),
        format_checker=FormatChecker(),
    ).validate(app_list)
    Draft202012Validator(
        _openapi_schema("AppDetail"),
        format_checker=FormatChecker(),
    ).validate(detail)
    Draft202012Validator(
        _openapi_schema("ImportPlan"),
        format_checker=FormatChecker(),
    ).validate(plan)


def test_frozen_protocol_excludes_remote_gateway_and_custom_backend() -> None:
    design = Path("docs/design/app-platform-contracts-v1.md").read_text(encoding="utf-8")
    happ = (CONTRACTS / "happ-format-v1.md").read_text(encoding="utf-8")
    runtime = (CONTRACTS / "runtime-event-protocol-v1.md").read_text(encoding="utf-8")

    assert "does not expose or depend on a remote Gateway" in design
    assert "cannot ship custom backend code" in design
    assert "never contains executable server-side code" in happ
    assert "Remote Gateway access" in runtime
    assert "out of scope" in runtime


def test_manifest_schema_rejects_mcp_action_with_missing_fields() -> None:
    manifest = _valid_manifest()
    invalid = copy.deepcopy(manifest)
    del invalid["actions"]["refresh_quotes"]["server"]

    errors = list(_validator("app-manifest.schema.json").iter_errors(invalid))

    assert errors
