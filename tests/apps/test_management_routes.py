from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path

from hermes_cli.apps.catalog import WATCHLIST_APP_ID
from hermes_cli.apps.manager import AppManager


def test_authenticated_management_launch_and_stop_routes(monkeypatch, _isolate_hermes_home) -> None:
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


def test_package_export_import_uninstall_and_data_lifecycle(
    tmp_path: Path,
    _isolate_hermes_home,
) -> None:
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
            },
        )
        deleted_data = client.delete(f"/api/apps/{app_id}/data")

    assert detail.status_code == 200
    assert detail.json()["id"] == app_id
    assert exported.status_code == 200
    assert exported.content.startswith(b"PK\x03\x04")
    assert removed.status_code == 204
    assert preserved_after_uninstall == '{"kept":true}'
    assert analyzed.status_code == 201
    assert confirmed.status_code == 201
    assert confirmed.json()["id"] == app_id
    assert deleted_data.status_code == 204
    assert not data.exists()


def test_builtin_uninstall_is_rejected(_isolate_hermes_home) -> None:
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    with TestClient(app) as client:
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        response = client.delete(f"/api/apps/{WATCHLIST_APP_ID}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APP_VERSION_CONFLICT"
