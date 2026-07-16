from __future__ import annotations

import json

from hermes_cli import stock_mcp


def _defaults(path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mcp_servers": {
                    "mx-ds-mcp": {
                        "url": "https://mxapi.eastmoney.com/mxds/mcp",
                        "headers": {"em_api_key": ""},
                        "tools": {"include": []},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_install_bundled_mx_mcp_adds_server_without_a_bundled_key(monkeypatch, tmp_path) -> None:
    defaults = tmp_path / "stock-mcp-defaults.json"
    _defaults(defaults)
    config = {"mcp_servers": {"other": {"url": "https://example.test/mcp"}}}
    saved_configs = []

    monkeypatch.setattr(stock_mcp, "load_config", lambda: config)
    monkeypatch.setattr(stock_mcp, "save_config", saved_configs.append)

    assert stock_mcp.install_bundled_mx_mcp(defaults) is True
    assert config["mcp_servers"]["mx-ds-mcp"]["url"] == stock_mcp.MX_SERVER_URL
    assert config["mcp_servers"]["mx-ds-mcp"]["headers"] == {"em_api_key": ""}
    assert saved_configs == [config]


def test_install_bundled_mx_mcp_preserves_existing_server(monkeypatch, tmp_path) -> None:
    defaults = tmp_path / "stock-mcp-defaults.json"
    _defaults(defaults)
    existing = {"url": "https://internal.example/mcp", "enabled": False}
    config = {"mcp_servers": {"mx-ds-mcp": existing}}

    monkeypatch.setattr(stock_mcp, "load_config", lambda: config)
    monkeypatch.setattr(stock_mcp, "save_config", lambda value: (_ for _ in ()).throw(AssertionError(value)))

    assert stock_mcp.install_bundled_mx_mcp(defaults) is False
    assert config["mcp_servers"]["mx-ds-mcp"] is existing
