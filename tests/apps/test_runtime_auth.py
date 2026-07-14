from __future__ import annotations

import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from hermes_cli.apps.runtime.auth import (
    CSRF_HEADER_NAME,
    RUNTIME_COOKIE_PREFIX,
    RuntimeAuth,
    RuntimeRequestPolicy,
)
from hermes_cli.apps.runtime.host import AppHost, create_apphost_app

from .runtime_fixtures import runtime_app


class FloatClock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _client(tmp_path: Path, *, port: int = 49152, clock: FloatClock | None = None):
    root, manifest, grants = runtime_app(tmp_path)
    auth = RuntimeAuth(clock=clock or FloatClock())
    origin = f"http://127.0.0.1:{port}"
    app = create_apphost_app(
        manifest,
        root,
        grants,
        expected_origin=origin,
        runtime_auth=auth,
        allow_test_client=True,
    )
    client = TestClient(app, base_url=origin, follow_redirects=False)
    return client, auth, origin


def _launch(client: TestClient, auth: RuntimeAuth):
    code = auth.issue_launch_code()
    response = client.get(f"/__hermes/launch/{code}")
    assert response.status_code == 302
    return code, response


def test_launch_code_is_single_use_and_only_digest_is_retained() -> None:
    clock = FloatClock()
    auth = RuntimeAuth(clock=clock)
    code = auth.issue_launch_code()

    assert code not in repr(auth.__dict__)
    session = auth.exchange_launch_code(code)

    assert session is not None
    assert auth.exchange_launch_code(code) is None


def test_launch_code_expires_after_thirty_seconds() -> None:
    clock = FloatClock()
    auth = RuntimeAuth(clock=clock)
    code = auth.issue_launch_code()
    clock.now += 31

    assert auth.exchange_launch_code(code) is None


def test_launch_exchange_sets_strict_httponly_cookie_and_cleans_url(tmp_path: Path) -> None:
    client, auth, _origin = _client(tmp_path)
    code, response = _launch(client, auth)

    cookie = response.headers["set-cookie"].lower()
    assert auth.cookie_name in cookie
    assert auth.cookie_name.startswith(RUNTIME_COOKIE_PREFIX)
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert response.headers["location"] == "/"
    assert code not in response.headers["location"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_bootstrap_requires_runtime_cookie_and_exposes_no_credentials(tmp_path: Path) -> None:
    client, auth, _origin = _client(tmp_path)
    assert client.get("/__hermes/bootstrap").status_code == 401
    _launch(client, auth)

    response = client.get("/__hermes/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["app_id"] == "ai.hermes.watchlist"
    assert "csrf_token" in body
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "session_token" not in serialized
    assert "handler" not in serialized


@pytest.mark.parametrize(
    "host",
    ["evil.example:49152", "127.0.0.1.evil.example:49152", "localhost:49152"],
)
def test_dns_rebinding_host_header_is_rejected(tmp_path: Path, host: str) -> None:
    client, _auth, _origin = _client(tmp_path)

    response = client.get("/api/health", headers={"host": host})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RUNTIME_HOST_REJECTED"


def test_cross_origin_request_is_rejected_even_for_get(tmp_path: Path) -> None:
    client, auth, _origin = _client(tmp_path)
    _launch(client, auth)

    response = client.get(
        "/__hermes/bootstrap",
        headers={"origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RUNTIME_ORIGIN_REJECTED"


def test_mutation_requires_origin_and_csrf(tmp_path: Path) -> None:
    client, auth, origin = _client(tmp_path)
    _launch(client, auth)
    bootstrap = client.get("/__hermes/bootstrap").json()

    no_origin = client.post("/api/actions/refresh_quotes/runs", json={"input": {}})
    no_csrf = client.post(
        "/api/actions/refresh_quotes/runs",
        json={"input": {}},
        headers={"origin": origin},
    )
    valid = client.post(
        "/api/actions/refresh_quotes/runs",
        json={"input": {}},
        headers={
            "origin": origin,
            "sec-fetch-site": "same-origin",
            CSRF_HEADER_NAME: bootstrap["csrf_token"],
        },
    )

    assert no_origin.status_code == 403
    assert no_csrf.status_code == 403
    assert valid.status_code == 503
    assert valid.json()["error"]["code"] == "APP_ACTION_GATEWAY_DISABLED"


def test_csrf_is_session_bound_and_short_lived(tmp_path: Path) -> None:
    clock = FloatClock()
    client, auth, origin = _client(tmp_path, clock=clock)
    _launch(client, auth)
    csrf = client.get("/__hermes/bootstrap").json()["csrf_token"]
    clock.now += 21 * 60

    response = client.post(
        "/api/actions/refresh_quotes/runs",
        headers={"origin": origin, CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RUNTIME_CSRF_REJECTED"


def test_csrf_from_previous_runtime_session_is_rejected(tmp_path: Path) -> None:
    client, auth, origin = _client(tmp_path)
    _launch(client, auth)
    first_csrf = client.get("/__hermes/bootstrap").json()["csrf_token"]
    _launch(client, auth)

    response = client.post(
        "/api/actions/refresh_quotes/runs",
        headers={"origin": origin, CSRF_HEADER_NAME: first_csrf},
    )

    assert response.status_code == 403


def test_cross_site_fetch_metadata_is_rejected(tmp_path: Path) -> None:
    client, auth, origin = _client(tmp_path)
    _launch(client, auth)
    csrf = client.get("/__hermes/bootstrap").json()["csrf_token"]

    response = client.post(
        "/api/actions/refresh_quotes/runs",
        headers={
            "origin": origin,
            "sec-fetch-site": "cross-site",
            CSRF_HEADER_NAME: csrf,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RUNTIME_FETCH_SITE_REJECTED"


def test_runtime_cookie_from_one_apphost_cannot_authenticate_another(tmp_path: Path) -> None:
    client_a, auth_a, _origin_a = _client(tmp_path / "a", port=49152)
    _launch(client_a, auth_a)
    stolen = client_a.cookies.get(auth_a.cookie_name)

    client_b, auth_b, _origin_b = _client(tmp_path / "b", port=49153)
    assert auth_a.cookie_name != auth_b.cookie_name
    client_b.cookies.set(auth_a.cookie_name, stolen)

    assert client_b.get("/__hermes/bootstrap").status_code == 401


def test_generic_management_api_is_not_exposed_by_apphost(tmp_path: Path) -> None:
    client, auth, _origin = _client(tmp_path)
    _launch(client, auth)

    response = client.get("/api/config")

    assert response.status_code == 404


def test_request_policy_rejects_non_loopback_peers() -> None:
    policy = RuntimeRequestPolicy("http://127.0.0.1:49152")

    assert policy.valid_peer("127.0.0.1") is True
    assert policy.valid_peer("::1") is True
    assert policy.valid_peer("192.168.1.10") is False
    assert policy.valid_peer("evil.example") is False
    assert policy.valid_peer(None) is False


def test_real_apphost_binds_random_ipv4_loopback_and_stops(tmp_path: Path) -> None:
    root, manifest, grants = runtime_app(tmp_path)
    host = AppHost(manifest, root, grants)
    port: int | None = None
    try:
        host.start()
    except PermissionError as exc:
        pytest.skip(f"loopback listeners unavailable in this sandbox: {exc}")
    try:
        parsed = urlsplit(host.origin)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port is not None
        port = parsed.port
        launch_url = host.issue_launch_url()
        response = httpx.get(launch_url, follow_redirects=False, timeout=2)
        assert response.status_code == 302
        assert response.headers["location"] == "/"
    finally:
        host.stop()

    assert port is not None
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()
