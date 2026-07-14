from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from hermes_cli.apps.catalog import (
    WATCHLIST_APP_ID,
    WATCHLIST_SERVICE_HANDLERS,
    builtin_app,
)
from hermes_cli.apps.runtime.auth import CSRF_HEADER_NAME, RuntimeAuth
from hermes_cli.apps.runtime.host import create_apphost_app
from hermes_cli.apps.runtime.service import watchlist_service_registry


def _snapshot() -> dict:
    return {
        "ok": True,
        "source": "mx-ds-mcp",
        "status": "ready",
        "indices": [],
        "items": [],
        "sectors": [],
        "summary": {
            "total": 0,
            "priced": 0,
            "rising": 0,
            "falling": 0,
            "flat": 0,
            "main_net_flow_yi": 0,
            "strongest_sector": None,
            "weakest_sector": None,
            "headline": "暂无自选股",
        },
        "gaps": [],
    }


def _client(tmp_path: Path):
    definition = builtin_app(WATCHLIST_APP_ID)
    assert definition is not None
    manifest = definition.load_manifest()
    auth = RuntimeAuth()
    origin = "http://127.0.0.1:49182"
    services = watchlist_service_registry(
        app_id=WATCHLIST_APP_ID,
        app_data=tmp_path / "data",
        inherited_handlers=WATCHLIST_SERVICE_HANDLERS,
    )
    app = create_apphost_app(
        manifest,
        definition.root,
        manifest.permissions,
        expected_origin=origin,
        runtime_auth=auth,
        allow_test_client=True,
        service_registry=services,
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


def test_service_run_emits_frozen_ordered_events(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.get_watchlist_snapshot_cached",
        lambda *, auto_refresh=True: _snapshot(),
    )
    client, headers = _client(tmp_path)

    accepted = client.post(
        "/api/actions/snapshot/runs",
        headers={**headers, "idempotency-key": "snapshot-1"},
        json={"input": {"auto_refresh": False}},
    )
    terminal = _wait_for_terminal(client, accepted.json()["run_id"])
    stream = client.get(accepted.json()["events_url"])

    assert accepted.status_code == 202
    assert terminal["status"] == "completed"
    assert terminal["result"] == _snapshot()
    events = [
        json.loads(line.removeprefix("data: "))
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == [
        "run.accepted",
        "run.started",
        "status",
        "operation.started",
        "operation.completed",
        "data.snapshot",
        "run.completed",
    ]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    schema = json.loads(
        (Path(__file__).parents[2] / "hermes_cli/apps/contracts/runtime-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for event in events:
        validator.validate(event)


def test_action_input_and_idempotency_are_enforced_before_execution(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def snapshot(*, auto_refresh=True):
        nonlocal calls
        calls += 1
        return _snapshot()

    monkeypatch.setattr("hermes_cli.finance_watchlist.get_watchlist_snapshot_cached", snapshot)
    client, headers = _client(tmp_path)

    invalid = client.post(
        "/api/actions/snapshot/runs",
        headers=headers,
        json={"input": {"unexpected": True}},
    )
    first = client.post(
        "/api/actions/snapshot/runs",
        headers={**headers, "idempotency-key": "same"},
        json={"input": {}},
    )
    second = client.post(
        "/api/actions/snapshot/runs",
        headers={**headers, "idempotency-key": "same"},
        json={"input": {}},
    )
    conflict = client.post(
        "/api/actions/snapshot/runs",
        headers={**headers, "idempotency-key": "same"},
        json={"input": {"auto_refresh": False}},
    )
    _wait_for_terminal(client, first.json()["run_id"])

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "RUN_INPUT_INVALID"
    assert second.json()["run_id"] == first.json()["run_id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "RUN_IDEMPOTENCY_CONFLICT"
    assert calls == 1


def test_invalid_service_output_fails_without_leaking_details(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.get_watchlist_snapshot_cached",
        lambda *, auto_refresh=True: {"secret": "provider payload"},
    )
    client, headers = _client(tmp_path)

    accepted = client.post("/api/actions/snapshot/runs", headers=headers, json={"input": {}})
    terminal = _wait_for_terminal(client, accepted.json()["run_id"])

    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "RUN_OUTPUT_INVALID"
    assert "provider payload" not in json.dumps(terminal)


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


def test_running_service_action_can_be_cancelled_cooperatively(monkeypatch, tmp_path: Path) -> None:
    release = threading.Event()

    def slow_snapshot(*, auto_refresh=True):
        release.wait(timeout=2)
        return _snapshot()

    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.get_watchlist_snapshot_cached",
        slow_snapshot,
    )
    client, headers = _client(tmp_path)
    accepted = client.post("/api/actions/snapshot/runs", headers=headers, json={"input": {}})
    run_id = accepted.json()["run_id"]

    cancellation = client.delete(f"/api/runs/{run_id}", headers=headers)
    terminal = _wait_for_terminal(client, run_id)
    release.set()

    assert cancellation.status_code == 202
    assert terminal["status"] == "cancelled"
    assert terminal["result"] is None
