"""Install StockSense's bundled 妙想 MCP configuration without clobbering users."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_cli.config import get_env_value, load_config, save_config, save_env_value


MX_SERVER_NAME = "mx-ds-mcp"
MX_SERVER_URL = "https://mxapi.eastmoney.com/mxds/mcp"
MX_API_KEY_ENV = "EM_API_KEY"


def _read_defaults(path: str | Path) -> Dict[str, Any]:
    """Read the signed installer resource and reject an unexpected payload."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read bundled 妙想 MCP defaults: {exc}") from exc

    server = (payload.get("mcp_servers") or {}).get(MX_SERVER_NAME)
    if not isinstance(server, dict) or server.get("url") != MX_SERVER_URL:
        raise ValueError("Bundled 妙想 MCP defaults are invalid.")
    return payload


def install_bundled_mx_mcp(defaults_path: str | Path) -> bool:
    """Merge the bundled server once; existing user server and key always win."""
    payload = _read_defaults(defaults_path)
    default_server = payload["mcp_servers"][MX_SERVER_NAME]
    config = load_config()
    servers = config.get("mcp_servers")
    changed = False

    if not isinstance(servers, dict):
        servers = {}
        config["mcp_servers"] = servers

    if MX_SERVER_NAME not in servers:
        servers[MX_SERVER_NAME] = copy.deepcopy(default_server)
        changed = True

    api_key = str((payload.get("default_env") or {}).get(MX_API_KEY_ENV) or "").strip()
    if api_key and not get_env_value(MX_API_KEY_ENV):
        save_env_value(MX_API_KEY_ENV, api_key)

    if changed:
        save_config(config)
    return changed


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install the bundled StockSense 妙想 MCP configuration.")
    parser.add_argument("--defaults", required=True, help="Path to the packaged MCP defaults JSON resource")
    args = parser.parse_args(argv)
    install_bundled_mx_mcp(args.defaults)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
