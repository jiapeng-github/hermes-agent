from __future__ import annotations

import json

from hermes_cli import stock_mcp


def _defaults(path, api_key: str = "test-key") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mcp_servers": {
                    "mx-ds-mcp": {
                        "url": "https://mxapi.eastmoney.com/mxds/mcp",
                        "headers": {"em_api_key": "${EM_API_KEY}"},
                        "tools": {"include": []},
                    }
                },
                "default_env": {"EM_API_KEY": api_key},
            }
        ),
        encoding="utf-8",
    )


def test_install_bundled_mx_mcp_adds_server_and_key_without_exposing_secret(monkeypatch, tmp_path) -> None:
    defaults = tmp_path / "stock-mcp-defaults.json"
    _defaults(defaults)
    config = {"mcp_servers": {"other": {"url": "https://example.test/mcp"}}}
    saved_configs = []
    saved_env = []

    monkeypatch.setattr(stock_mcp, "load_config", lambda: config)
    monkeypatch.setattr(stock_mcp, "save_config", saved_configs.append)
    monkeypatch.setattr(stock_mcp, "get_env_value", lambda key: None)
    monkeypatch.setattr(stock_mcp, "save_env_value", lambda key, value: saved_env.append((key, value)))

    assert stock_mcp.install_bundled_mx_mcp(defaults) is True
    assert config["mcp_servers"]["mx-ds-mcp"]["url"] == stock_mcp.MX_SERVER_URL
    assert saved_configs == [config]
    assert saved_env == [("EM_API_KEY", "test-key")]


def test_install_bundled_mx_mcp_preserves_existing_server_and_key(monkeypatch, tmp_path) -> None:
    defaults = tmp_path / "stock-mcp-defaults.json"
    _defaults(defaults)
    existing = {"url": "https://internal.example/mcp", "enabled": False}
    config = {"mcp_servers": {"mx-ds-mcp": existing}}

    monkeypatch.setattr(stock_mcp, "load_config", lambda: config)
    monkeypatch.setattr(stock_mcp, "save_config", lambda value: (_ for _ in ()).throw(AssertionError(value)))
    monkeypatch.setattr(stock_mcp, "get_env_value", lambda key: "existing-key")
    monkeypatch.setattr(stock_mcp, "save_env_value", lambda *args: (_ for _ in ()).throw(AssertionError(args)))

    assert stock_mcp.install_bundled_mx_mcp(defaults) is False
    assert config["mcp_servers"]["mx-ds-mcp"] is existing
