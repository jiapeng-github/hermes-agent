from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hermes_cli.hub.client import (
    HubCache,
    HubClient,
    HubConfig,
    HubError,
)


def _config(private_key: Ed25519PrivateKey | None = None) -> HubConfig:
    trusted_keys = {}
    if private_key is not None:
        trusted_keys["test-key"] = base64.b64encode(
            private_key.public_key().public_bytes_raw()
        ).decode()
    return HubConfig(
        enabled=True,
        base_url="http://127.0.0.1:18080/api/v1",
        channel="stable",
        request_timeout_seconds=5,
        catalog_cache_minutes=5,
        offline_cache_hours=24,
        require_artifact_signature=True,
        trusted_keys=trusted_keys,
    )


def _descriptor(private_key: Ed25519PrivateKey, content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    signed = "\n".join([
        "skill_bundle",
        "example-skill",
        "1.0.0",
        digest,
        str(len(content)),
    ]).encode()
    return {
        "kind": "skill_bundle",
        "artifact_id": "example-skill",
        "version": "1.0.0",
        "sha256": digest,
        "size_bytes": len(content),
        "download_url": "http://127.0.0.1:18080/artifacts/example.zip",
        "expires_at": "2099-01-01T00:00:00Z",
        "signature": {
            "algorithm": "ed25519",
            "key_id": "test-key",
            "value": base64.b64encode(private_key.sign(signed)).decode(),
        },
    }


def test_catalog_uses_fresh_cache_before_revalidating(tmp_path: Path):
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("if-none-match") == '"hub-v1"':
            return httpx.Response(304, request=request)
        return httpx.Response(
            200,
            headers={"etag": '"hub-v1"'},
            json={"items": [{"id": "one"}]},
            request=request,
        )

    client = HubClient(
        _config(),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    first = client.list_skills(q="stock")
    second = client.list_skills(q="stock")

    assert first.data["items"][0]["id"] == "one"
    assert second.cache_state == "fresh"
    assert len(calls) == 1


def test_artifact_download_requires_valid_signature_and_digest(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    content = b"hub bundle"
    descriptor = _descriptor(private_key, content)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    client = HubClient(
        _config(private_key),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    target = tmp_path / "artifact.zip"

    assert (
        client.download_artifact(descriptor, target)
        == hashlib.sha256(content).hexdigest()
    )
    assert target.read_bytes() == content

    descriptor["signature"] = {
        **descriptor["signature"],
        "value": base64.b64encode(b"invalid").decode(),
    }
    with pytest.raises(HubError, match="签名"):
        client.download_artifact(descriptor, tmp_path / "other.zip")


def test_artifact_download_resolves_relative_url_against_configured_hub(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    content = b"hub bundle"
    descriptor = _descriptor(private_key, content)
    descriptor["download_url"] = "/app-api/hub/v1/artifacts/example.zip"
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=content, request=request)

    client = HubClient(
        replace(_config(private_key), base_url="https://hub.example/app-api/hub/v1"),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    client.download_artifact(descriptor, tmp_path / "artifact.zip")

    assert str(requests[0].url) == "https://hub.example/app-api/hub/v1/artifacts/example.zip"


def test_artifact_download_repairs_legacy_same_origin_http_url(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    content = b"hub bundle"
    descriptor = _descriptor(private_key, content)
    descriptor["download_url"] = (
        "http://hub.example:48080/app-api/hub/v1/artifacts/example.zip?token=legacy"
    )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=content, request=request)

    client = HubClient(
        replace(_config(private_key), base_url="https://hub.example/app-api/hub/v1"),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    client.download_artifact(descriptor, tmp_path / "artifact.zip")

    assert str(requests[0].url) == (
        "https://hub.example/app-api/hub/v1/artifacts/example.zip?token=legacy"
    )


def test_artifact_download_rejects_network_path_url(tmp_path: Path):
    private_key = Ed25519PrivateKey.generate()
    descriptor = _descriptor(private_key, b"hub bundle")
    descriptor["download_url"] = "//untrusted.example/artifacts/example.zip"

    client = HubClient(
        replace(_config(private_key), base_url="https://hub.example/app-api/hub/v1"),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("unexpected artifact request")
            )
        ),
    )

    with pytest.raises(HubError, match="地址不安全"):
        client.download_artifact(descriptor, tmp_path / "artifact.zip")


def test_hub_config_ignores_invalid_numeric_values():
    value = HubConfig.from_mapping({
        "enabled": True,
        "base_url": "https://hub.example",
        "request_timeout_seconds": "invalid",
    })

    assert value.request_timeout_seconds == 15


def test_remote_http_hub_requires_explicit_opt_in():
    with pytest.raises(HubError, match="HTTPS"):
        HubConfig.from_mapping({
            "enabled": True,
            "base_url": "http://175.24.139.183:48080/app-api/hub/v1",
        }).validate()

    HubConfig.from_mapping({
        "enabled": True,
        "base_url": "http://175.24.139.183:48080/app-api/hub/v1",
        "allow_insecure_http": True,
    }).validate()


def test_managed_hub_config_overrides_a_stale_localhost_user_value(tmp_path, monkeypatch):
    home = tmp_path / "home"
    managed = tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    (home / "config.yaml").write_text(
        "hub:\n  base_url: http://127.0.0.1:48080/app-api/hub/v1\n",
        encoding="utf-8",
    )
    (managed / "config.yaml").write_text(
        "hub:\n  enabled: true\n  base_url: https://hub.stocksense.example/app-api/hub/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))

    from hermes_cli import managed_scope
    import hermes_cli.config as config_module

    config_module._LOAD_CONFIG_CACHE.clear()
    config_module._RAW_CONFIG_CACHE.clear()
    managed_scope.invalidate_managed_cache()

    try:
        value = HubConfig.from_mapping(config_module.load_config().get("hub"))
        assert value.base_url == "https://hub.stocksense.example/app-api/hub/v1"
    finally:
        config_module._LOAD_CONFIG_CACHE.clear()
        config_module._RAW_CONFIG_CACHE.clear()
        managed_scope.invalidate_managed_cache()


def test_disabled_hub_never_attempts_network(tmp_path: Path):
    client = HubClient(
        HubConfig.from_mapping({"enabled": False}),
        cache=HubCache(tmp_path / "cache"),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("unexpected request")
            )
        ),
    )

    with pytest.raises(HubError, match="尚未启用"):
        client.list_apps()
