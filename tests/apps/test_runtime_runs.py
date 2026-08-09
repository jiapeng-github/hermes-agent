from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_cli.apps.manifest import parse_manifest
from hermes_cli.apps.runtime.auth import CSRF_HEADER_NAME, RuntimeAuth
from hermes_cli.apps.runtime.host import create_apphost_app
from hermes_cli.apps.runtime.runs import ActionRuntime

from .happ_fixtures import manifest_data
from .runtime_fixtures import runtime_app


def _client(tmp_path: Path):
    definition, manifest, _grants = runtime_app(tmp_path / "fixture")
    auth = RuntimeAuth()
    origin = "http://127.0.0.1:49182"
    app = create_apphost_app(
        manifest,
        definition,
        manifest.permissions,
        expected_origin=origin,
        runtime_auth=auth,
        allow_test_client=True,
        storage_root=tmp_path / "storage",
    )
    client = TestClient(app, base_url=origin, follow_redirects=False)
    code = auth.issue_launch_code()
    assert client.get(f"/launch/{code}").status_code == 302
    bootstrap = client.get("/__hermes/bootstrap").json()
    headers = {
        "origin": origin,
        "sec-fetch-site": "same-origin",
        CSRF_HEADER_NAME: bootstrap["csrf_token"],
    }
    return client, headers


def _wait_for_terminal(client: TestClient, run_id: str) -> dict:
    for _ in range(200):
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if snapshot["status"] in {"completed", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("run did not become terminal")


def test_portable_mcp_action_runs_through_the_declared_executor(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    (root / "schemas").mkdir(parents=True)
    for schema in (
        "refresh.input.json",
        "refresh.output.json",
        "analyze.input.json",
        "analyze.output.json",
    ):
        (root / "schemas" / schema).write_text('{"type":"object"}', encoding="utf-8")
    manifest = parse_manifest(manifest_data())
    calls: list[tuple[str, dict]] = []

    def invoke(action, input_data):
        calls.append((action.tool, input_data))
        return {"quotes": []}

    runtime = ActionRuntime(manifest, root, None, mcp_invoker=invoke)
    accepted = runtime.start(
        "refresh_quotes",
        {"codes": ["600519"]},
        session="runtime-session",
        idempotency_key=None,
    )
    record = runtime.get(accepted["run_id"])
    for _ in range(200):
        if record.snapshot()["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)

    assert record.snapshot()["status"] == "completed"
    assert record.snapshot()["result"] == {"quotes": []}
    assert calls == [("stock/quotes", {"codes": ["600519"]})]
    assert record.events[3]["payload"]["kind"] == "mcp"


def test_runtime_storage_is_profile_scoped_and_requires_csrf(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)

    rejected = client.put("/api/storage/preferences", json={"value": {"sort": "change"}})
    written = client.put(
        "/api/storage/preferences",
        headers=headers,
        json={"value": {"sort": "change"}},
    )
    read = client.get("/api/storage/preferences")
    deleted = client.delete("/api/storage/preferences", headers=headers)

    assert rejected.status_code == 403
    assert written.status_code == 200
    assert read.json() == {"value": {"sort": "change"}}
    assert deleted.json() == {"deleted": True}
