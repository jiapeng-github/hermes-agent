from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path

from hermes_cli.apps.catalog import INDUSTRY_MONITOR_APP_ID, WATCHLIST_APP_ID


def test_authenticated_management_launch_and_stop_routes(
    monkeypatch, _isolate_hermes_home
) -> None:
    from hermes_cli.apps.manager import AppManager
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    launch = {
        "launch_id": "91dfb287-c638-4cc9-9a12-0cb61dcbab55",
        "url": "http://127.0.0.1:49182/launch/one-time",
        "expires_at": "2026-07-13T10:00:30+00:00",
    }
    stopped: list[str] = []
    monkeypatch.setattr(AppManager, "launch", lambda self, app_id, supervisor: launch)
    monkeypatch.setattr(
        AppManager,
        "stop",
        lambda self, app_id, supervisor: stopped.append(app_id),
    )

    with TestClient(app) as client:
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        response = client.post(f"/api/apps/{WATCHLIST_APP_ID}/launch", json={})
        stop = client.post(f"/api/apps/{WATCHLIST_APP_ID}/stop")

    assert response.status_code == 201
    assert response.json() == launch
    assert stop.status_code == 204
    assert stopped == [WATCHLIST_APP_ID]


def test_management_routes_remain_behind_dashboard_auth(_isolate_hermes_home) -> None:
    from hermes_cli.web_server import app

    with TestClient(app) as client:
        response = client.post(f"/api/apps/{WATCHLIST_APP_ID}/launch", json={})

    assert response.status_code == 401


def test_authenticated_app_activity_routes_are_read_only_and_issue_launch_urls(
    monkeypatch,
    _isolate_hermes_home,
) -> None:
    from hermes_cli.apps.manager import AppManager
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    timeline = {
        "session": {
            "app_id": WATCHLIST_APP_ID,
            "session_id": "session-1",
            "app_name": "自选股盯盘看板",
            "created_at": 1.0,
            "updated_at": 2.0,
        },
        "artifacts": [],
        "runs": [],
    }
    launch = {
        "launch_id": "91dfb287-c638-4cc9-9a12-0cb61dcbab55",
        "url": "http://127.0.0.1:49182/launch/one-time?next=%2F__hermes%2Fartifacts%2Fartifact-1",
        "expires_at": "2026-08-02T10:00:30+00:00",
    }
    monkeypatch.setattr(
        AppManager,
        "get_activity_session",
        lambda self, session_id: timeline,
    )
    monkeypatch.setattr(
        AppManager,
        "launch_activity_artifact",
        lambda self, artifact_id, supervisor: launch,
    )

    with TestClient(app) as client:
        unauthenticated = client.get("/api/app-activity/sessions/session-1")
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        session = client.get("/api/app-activity/sessions/session-1")
        artifact = client.post("/api/app-activity/artifacts/artifact-1/launch")

    assert unauthenticated.status_code == 401
    assert session.status_code == 200
    assert session.json() == timeline
    assert artifact.status_code == 201
    assert artifact.json() == launch


def test_package_export_import_uninstall_and_data_lifecycle(
    tmp_path: Path,
    _isolate_hermes_home,
) -> None:
    from hermes_cli.apps.manager import AppManager
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    manager = AppManager()
    app_id = "local.stockagent.lifecycle"
    workspace = manager.workspaces.init(
        tmp_path / "portable app",
        app_id=app_id,
        template="vanilla",
        name="Portable App",
    )
    manager.publish(workspace)
    data = manager.paths.app_runtime_data(app_id) / "storage" / "state.json"
    data.parent.mkdir(parents=True)
    data.write_text('{"kept":true}', encoding="utf-8")

    with TestClient(app) as client:
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        detail = client.get(f"/api/apps/{app_id}")
        exported = client.post(
            f"/api/apps/{app_id}/export",
            json={"include_source": True},
        )
        removed = client.delete(f"/api/apps/{app_id}")
        analyzed = client.post(
            "/api/apps/imports",
            files={
                "package": (
                    "portable app.happ",
                    exported.content,
                    "application/vnd.hermes.app+zip",
                )
            },
        )
        plan = analyzed.json()
        preserved_after_uninstall = data.read_text(encoding="utf-8")
        confirmed = client.post(
            f"/api/apps/imports/{plan['import_id']}/confirm",
            json={
                "package_sha256": plan["package_sha256"],
                "conflict_mode": "install",
                "copy_app_id": None,
                "grants": plan["requested_permissions"],
                "category": "fundamental",
            },
        )
        deleted_data = client.delete(f"/api/apps/{app_id}/data")

    assert detail.status_code == 200
    assert detail.json()["id"] == app_id
    assert detail.json()["lineage"] == "user"
    assert detail.json()["installed_at"]
    assert exported.status_code == 200
    assert exported.content.startswith(b"PK\x03\x04")
    assert removed.status_code == 204
    assert preserved_after_uninstall == '{"kept":true}'
    assert analyzed.status_code == 201
    assert confirmed.status_code == 201
    assert confirmed.json()["id"] == app_id
    assert confirmed.json()["category"] == "fundamental"
    assert deleted_data.status_code == 204
    assert not data.exists()


def test_removed_builtin_uninstall_returns_not_found(_isolate_hermes_home) -> None:
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    with TestClient(app) as client:
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        response = client.delete(f"/api/apps/{INDUSTRY_MONITOR_APP_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APP_NOT_FOUND"


def test_hub_routes_are_authenticated_and_can_be_explicitly_disabled(
    monkeypatch, _isolate_hermes_home,
) -> None:
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
    from hermes_cli.hub import HubClient, HubConfig

    monkeypatch.setattr(
        HubClient,
        "from_active_config",
        classmethod(
            lambda cls: cls(HubConfig.from_mapping({"enabled": False}))
        ),
    )
    if hasattr(app.state, "app_hub_operations"):
        delattr(app.state, "app_hub_operations")

    with TestClient(app) as client:
        unauthenticated = client.get("/api/apps/hub")
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        disabled = client.get("/api/apps/hub")
        legacy_route = client.get("/api/apps/market")

    assert unauthenticated.status_code == 401
    assert disabled.status_code == 503
    assert disabled.json()["error"]["code"] == "HUB_DISABLED"
    assert legacy_route.status_code == 404
