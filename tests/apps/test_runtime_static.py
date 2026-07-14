from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_cli.apps.runtime.auth import RuntimeAuth
from hermes_cli.apps.runtime.host import create_apphost_app
from hermes_cli.apps.runtime.static import (
    CONTENT_SECURITY_POLICY,
    StaticAssetNotFound,
    StaticAssetResolver,
)

from .runtime_fixtures import runtime_app


def _launched_client(tmp_path: Path):
    root, manifest, grants = runtime_app(tmp_path)
    auth = RuntimeAuth()
    origin = "http://127.0.0.1:49152"
    app = create_apphost_app(
        manifest,
        root,
        grants,
        expected_origin=origin,
        runtime_auth=auth,
        allow_test_client=True,
    )
    client = TestClient(app, base_url=origin, follow_redirects=False)
    code = auth.issue_launch_code()
    assert client.get(f"/__hermes/launch/{code}").status_code == 302
    return client, root, manifest


def test_static_entry_has_strict_headers_and_no_cors(tmp_path: Path) -> None:
    client, _root, _manifest = _launched_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in response.headers["content-security-policy"]
    assert "http:" not in response.headers["content-security-policy"]
    assert "worker-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["clear-site-data"] == '"storage"'


def test_versioned_asset_has_safe_mime_and_private_cache(tmp_path: Path) -> None:
    client, _root, _manifest = _launched_client(tmp_path)

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "clear-site-data" not in response.headers


def test_static_assets_require_runtime_session(tmp_path: Path) -> None:
    root, manifest, grants = runtime_app(tmp_path)
    app = create_apphost_app(
        manifest,
        root,
        grants,
        expected_origin="http://127.0.0.1:49152",
        allow_test_client=True,
    )
    client = TestClient(app, base_url="http://127.0.0.1:49152")

    assert client.get("/").status_code == 401
    assert client.get("/assets/app.js").status_code == 401


def test_spa_route_falls_back_to_entry(tmp_path: Path) -> None:
    client, _root, _manifest = _launched_client(tmp_path)

    response = client.get("/portfolio/300750")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_exact_case_is_required(tmp_path: Path) -> None:
    client, _root, _manifest = _launched_client(tmp_path)

    assert client.get("/assets/Chart.js").status_code == 200
    assert client.get("/assets/chart.js").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "../route",
        "../icon.png",
        "assets/../../icon.png",
        "/absolute",
        "assets\\app.js",
    ],
)
def test_resolver_rejects_path_escape(tmp_path: Path, path: str) -> None:
    root, manifest, _grants = runtime_app(tmp_path)
    resolver = StaticAssetResolver(root, manifest.entry)

    with pytest.raises(StaticAssetNotFound):
        resolver.resolve(path)


def test_resolver_rejects_symlinked_asset(tmp_path: Path) -> None:
    root, manifest, _grants = runtime_app(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("secret", encoding="utf-8")
    linked = root / "dist/assets/link.js"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    resolver = StaticAssetResolver(root, manifest.entry)

    with pytest.raises(StaticAssetNotFound):
        resolver.resolve("assets/link.js")


def test_dotless_symlink_does_not_fall_back_to_spa_entry(tmp_path: Path) -> None:
    root, manifest, _grants = runtime_app(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    linked = root / "dist/assets/link"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    resolver = StaticAssetResolver(root, manifest.entry)

    with pytest.raises(StaticAssetNotFound):
        resolver.resolve("assets/link")
