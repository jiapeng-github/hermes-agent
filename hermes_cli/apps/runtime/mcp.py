"""Restricted MCP execution for portable AppHost actions.

Portable applications may call only a tool and server declared in their
Manifest and granted at installation.  The app package never supplies a
connection string, headers, or executable backend code; those remain in the
user's normal MCP configuration.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any

from hermes_cli.config import load_config

from ..models import McpAction


_INPUT_TOKEN = re.compile(r"^\{\{input\.([A-Za-z_][A-Za-z0-9_]*)\}\}$")
_INPUT_TOKEN_ANYWHERE = re.compile(r"\{\{input\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def invoke_mcp_action(action: McpAction, input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute one HTTP MCP tool using only local, user-owned configuration."""
    return asyncio.run(_invoke_mcp_action(action, input_data))


async def _invoke_mcp_action(action: McpAction, input_data: dict[str, Any]) -> dict[str, Any]:
    server = _configured_server(action.server)
    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", "2025-03-26")
    url = str(server.get("url") or "").strip()
    if not url:
        raise ValueError(f"MCP server {action.server!r} does not have an HTTP URL")

    try:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise RuntimeError("MCP HTTP runtime is unavailable") from exc

    arguments = _render_arguments(action.arguments_template, input_data)
    timeout = float(action.timeout_seconds)
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(timeout, read=timeout),
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(action.tool, arguments=arguments)
    return _tool_result_payload(result)


def _configured_server(name: str) -> dict[str, Any]:
    servers = load_config().get("mcp_servers") or {}
    server = servers.get(name) if isinstance(servers, Mapping) else None
    if not isinstance(server, Mapping) or server.get("enabled") is False:
        raise ValueError(f"MCP server {name!r} is not configured or enabled")
    return dict(server)


def _resolve_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    try:
        from tools.mcp_tool import _interpolate_env_vars

        headers = _interpolate_env_vars(dict(headers))
    except Exception:
        pass
    return {str(key): str(value) for key, value in headers.items() if value is not None}


def _render_arguments(template: Any, input_data: Mapping[str, Any]) -> Any:
    if isinstance(template, dict):
        return {str(key): _render_arguments(value, input_data) for key, value in template.items()}
    if isinstance(template, list):
        return [_render_arguments(value, input_data) for value in template]
    if isinstance(template, str):
        match = _INPUT_TOKEN.fullmatch(template)
        if match is not None:
            key = match.group(1)
            if key not in input_data:
                raise ValueError(f"input field {key!r} is required by arguments_template")
            return input_data[key]
        if _INPUT_TOKEN_ANYWHERE.search(template):
            def replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in input_data:
                    raise ValueError(f"input field {key!r} is required by arguments_template")
                return str(input_data[key])

            return _INPUT_TOKEN_ANYWHERE.sub(replace, template)
    return template


def _tool_result_payload(result: Any) -> dict[str, Any]:
    texts = [
        str(getattr(block, "text", block))
        for block in (getattr(result, "content", None) or [])
    ]
    body = "\n".join(text for text in texts if text).strip()
    if not body:
        return {"data": []}
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return {"data": [], "message": body}
    return value if isinstance(value, dict) else {"data": value}


__all__ = ["invoke_mcp_action"]
