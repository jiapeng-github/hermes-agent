from __future__ import annotations

import pytest

from hermes_cli.apps.runtime.mcp import _render_arguments


def test_render_arguments_supports_embedded_input_tokens() -> None:
    rendered = _render_arguments(
        {
            "query": "查询股票 {{input.query}}，日期 {{input.date}}",
            "limit": "{{input.limit}}",
        },
        {"query": "600519", "date": "2026-08-08", "limit": 5},
    )

    assert rendered == {
        "query": "查询股票 600519，日期 2026-08-08",
        "limit": 5,
    }


def test_render_arguments_rejects_missing_embedded_input() -> None:
    with pytest.raises(ValueError, match="input field 'query'"):
        _render_arguments("查询股票 {{input.query}}", {})
