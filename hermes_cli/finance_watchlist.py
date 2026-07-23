"""Persistent A-share watchlist snapshots backed by the MX Data MCP server."""

from __future__ import annotations

import asyncio
import contextvars
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple
import uuid

from hermes_cli.config import load_config
from hermes_constants import get_hermes_home


MX_SERVER_NAME = "mx-ds-mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
MAX_WATCHLIST_SIZE = 30

DEFAULT_WATCHLIST: List[Dict[str, Any]] = []

PROFILE_QUERY_TEMPLATE = (
    "筛选名称或代码为{query}的A股上市公司，字段包括代码、名称、最新价、涨跌幅、"
    "申万行业分类、热门板块，返回最匹配的前5只，只返回表格。"
)
DETAIL_QUERY_TEMPLATE = (
    "查询A股{name}({code}.{exchange})最近60个交易日的日K线，返回交易日期、前复权开盘价、"
    "最高价、最低价、收盘价、成交量、成交额、涨跌幅，只返回表格。"
)
INDICES_QUERY = (
    "查询上证指数、深证成指、创业板指、沪深300、科创50最新点位、今日涨跌幅、成交额，"
    "只返回表格。"
)

_MONEY_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(万亿|亿元|亿|万元|万|元)?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_DATE_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")
_SECURITY_RE = re.compile(r"^(.*?)\((\d{6})\.(SH|SZ|BJ)\)$", re.IGNORECASE)

_STATE_LOCK = threading.RLock()
_CACHE_BY_HOME: Dict[str, Dict[str, Any]] = {}
_ACTIVE_REFRESH_BY_HOME: Dict[str, str] = {}
_REFRESH_JOBS: Dict[str, Dict[str, Any]] = {}
_DETAIL_CACHE: Dict[str, Dict[str, Any]] = {}
_REFRESH_SECTIONS = ["quotes", "indices"]
_SNAPSHOT_MAX_AGE = timedelta(seconds=75)
_DETAIL_MAX_AGE = timedelta(minutes=5)


def get_watchlist_snapshot_cached(*, auto_refresh: bool = True) -> Dict[str, Any]:
    """Return the persisted watchlist immediately and refresh stale quotes."""

    home_key = _home_key()
    entries = _read_entries(home_key)
    with _STATE_LOCK:
        cached = deepcopy(_CACHE_BY_HOME.get(home_key))
        if cached is None:
            cached = _load_snapshot_cache(home_key)
            if cached is not None:
                _CACHE_BY_HOME[home_key] = deepcopy(cached)
        active_id = _ACTIVE_REFRESH_BY_HOME.get(home_key)
        active_job = deepcopy(_REFRESH_JOBS.get(active_id)) if active_id else None

    changed = _snapshot_codes(cached) != [entry["code"] for entry in entries]
    if auto_refresh and (cached is None or changed or _snapshot_is_stale(cached)) and not _is_running(active_job):
        active_job = start_watchlist_refresh(force=False)

    snapshot = _reconcile_snapshot(cached, entries)
    snapshot["refresh"] = _refresh_meta(active_job, cache_state="warm" if cached else "empty")
    return snapshot


def start_watchlist_refresh(*, force: bool = False) -> Dict[str, Any]:
    """Start one background quote refresh for the current Hermes profile."""

    home_key = _home_key()
    with _STATE_LOCK:
        active_id = _ACTIVE_REFRESH_BY_HOME.get(home_key)
        active_job = _REFRESH_JOBS.get(active_id) if active_id else None
        if _is_running(active_job):
            return deepcopy(active_job)

        refresh_id = uuid.uuid4().hex
        job = {
            "refresh_id": refresh_id,
            "home": home_key,
            "status": "running",
            "started_at": _now_iso(),
            "completed_at": None,
            "error": None,
            "sections": {section: "refreshing" for section in _REFRESH_SECTIONS},
        }
        _REFRESH_JOBS[refresh_id] = job
        _ACTIVE_REFRESH_BY_HOME[home_key] = refresh_id

    ctx = contextvars.copy_context()
    thread = threading.Thread(
        target=lambda: ctx.run(_run_refresh_job, home_key, refresh_id),
        name=f"watchlist-refresh-{refresh_id[:8]}",
        daemon=True,
    )
    thread.start()
    return deepcopy(job)


def get_watchlist_refresh_status(refresh_id: str) -> Dict[str, Any]:
    with _STATE_LOCK:
        job = deepcopy(_REFRESH_JOBS.get(refresh_id))
    if job:
        return job
    return {
        "refresh_id": refresh_id,
        "status": "not-found",
        "started_at": None,
        "completed_at": None,
        "error": "Refresh job not found.",
        "sections": {},
    }


def add_watchlist_stock(query: str) -> Dict[str, Any]:
    """Resolve one A-share by name/code, persist it, and refresh quotes."""

    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("请输入股票名称或代码。")
    resolved = resolve_watchlist_stock(normalized)
    if not resolved:
        raise ValueError(f"未找到与“{normalized}”匹配的 A 股股票。")

    home_key = _home_key()
    with _STATE_LOCK:
        entries = _read_entries(home_key)
        existing = next((entry for entry in entries if entry["code"] == resolved["code"]), None)
        if existing:
            return {"ok": True, "added": False, "item": deepcopy(existing)}
        if len(entries) >= MAX_WATCHLIST_SIZE:
            raise ValueError(f"自选股最多支持 {MAX_WATCHLIST_SIZE} 只。")
        entries.append(resolved)
        _write_entries(home_key, entries)

    job = start_watchlist_refresh(force=True)
    return {"ok": True, "added": True, "item": deepcopy(resolved), "refresh": job}


def remove_watchlist_stock(code: str) -> Dict[str, Any]:
    normalized_code = _normalize_code(code)
    home_key = _home_key()
    with _STATE_LOCK:
        entries = _read_entries(home_key)
        next_entries = [entry for entry in entries if entry["code"] != normalized_code]
        removed = len(next_entries) != len(entries)
        if removed:
            _write_entries(home_key, next_entries)
        _DETAIL_CACHE.pop(_detail_cache_key(home_key, normalized_code), None)

    if removed:
        start_watchlist_refresh(force=True)
    return {"ok": True, "removed": removed, "code": normalized_code}


def resolve_watchlist_stock(query: str) -> Optional[Dict[str, Any]]:
    try:
        return asyncio.run(_resolve_watchlist_stock(query))
    except Exception as exc:
        raise ValueError(f"股票解析失败：{exc}") from exc


def get_watchlist_stock_detail(code: str, *, force: bool = False) -> Dict[str, Any]:
    normalized_code = _normalize_code(code)
    home_key = _home_key()
    entries = _read_entries(home_key)
    entry = next((item for item in entries if item["code"] == normalized_code), None)
    if not entry:
        raise ValueError("该股票不在自选股列表中。")

    cache_key = _detail_cache_key(home_key, normalized_code)
    with _STATE_LOCK:
        cached = deepcopy(_DETAIL_CACHE.get(cache_key))
    if cached and not force and not _detail_is_stale(cached):
        return cached

    snapshot = load_watchlist_stock_detail(entry)
    if snapshot.get("ok"):
        with _STATE_LOCK:
            _DETAIL_CACHE[cache_key] = deepcopy(snapshot)
    return snapshot


def load_watchlist_snapshot(entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    selected = deepcopy(entries) if entries is not None else _read_entries(_home_key())
    try:
        return asyncio.run(_load_watchlist_snapshot(selected))
    except Exception as exc:
        return _error_snapshot(selected, str(exc))


def load_watchlist_stock_detail(entry: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return asyncio.run(_load_watchlist_stock_detail(entry))
    except Exception as exc:
        return {
            "ok": False,
            "source": MX_SERVER_NAME,
            "status": "error",
            "generated_at": _now_iso(),
            "as_of": None,
            "stock": _placeholder_quote(entry),
            "kline": [],
            "technicals": _empty_technicals(),
            "summary": f"K 线数据获取失败：{exc}",
        }


def _run_refresh_job(home_key: str, refresh_id: str) -> None:
    try:
        entries = _read_entries(home_key)
        snapshot = load_watchlist_snapshot(entries)
        snapshot["cached_at"] = _now_iso()
        success = bool(snapshot.get("ok"))
        with _STATE_LOCK:
            if success or home_key not in _CACHE_BY_HOME:
                _CACHE_BY_HOME[home_key] = deepcopy(snapshot)
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "success" if success else "failed"
                job["completed_at"] = _now_iso()
                job["error"] = None if success else snapshot.get("summary", {}).get("headline")
                job["sections"] = {
                    "quotes": "success" if success and snapshot.get("items") is not None else "failed",
                    "indices": "success" if snapshot.get("indices") else "failed",
                }
            if _ACTIVE_REFRESH_BY_HOME.get(home_key) == refresh_id:
                _ACTIVE_REFRESH_BY_HOME.pop(home_key, None)
        if success:
            _write_snapshot_cache(home_key, snapshot)
            _merge_entry_metadata(home_key, snapshot.get("items") or [])
    except Exception as exc:
        with _STATE_LOCK:
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "failed"
                job["completed_at"] = _now_iso()
                job["error"] = str(exc)
                job["sections"] = {section: "failed" for section in _REFRESH_SECTIONS}
            if _ACTIVE_REFRESH_BY_HOME.get(home_key) == refresh_id:
                _ACTIVE_REFRESH_BY_HOME.pop(home_key, None)


async def _load_watchlist_snapshot(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not entries:
        return _build_snapshot(entries, [], [], [], None)

    server = _mx_server_config()
    if not server:
        return _missing_server_snapshot(entries)

    try:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        return _error_snapshot(entries, f"MCP HTTP 客户端依赖不可用：{exc}")

    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", MCP_PROTOCOL_VERSION)
    url = str(server.get("url") or "").strip()
    if not url:
        return _missing_server_snapshot(entries, "妙想 MCP Server 缺少 HTTP URL 配置。")

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(30.0, read=120.0),
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                quote_payload, index_payload = await asyncio.gather(
                    _call_json_safe(
                        session,
                        "mx_ashare_finance_data",
                        _watchlist_quote_query(entries),
                    ),
                    _call_json_safe(
                        session,
                        "mx_index_block_finance_data",
                        INDICES_QUERY,
                    ),
                )

    quotes, quote_as_of = _parse_watchlist_quotes(quote_payload, entries)
    indices, index_as_of = _parse_indices(index_payload)
    gaps = []
    missing = [item["name"] for item in quotes if item.get("quote_status") != "ok"]
    if missing:
        gaps.append(
            {
                "key": "quotes",
                "title": "部分行情缺失",
                "message": "、".join(missing[:6]) + " 暂未返回最新行情。",
                "severity": "warning",
            }
        )
    if not indices:
        gaps.append(
            {
                "key": "indices",
                "title": "指数行情缺失",
                "message": "妙想 MCP 未返回核心指数行情。",
                "severity": "warning",
            }
        )
    return _build_snapshot(
        entries,
        quotes,
        indices,
        gaps,
        _latest_date([quote_as_of, index_as_of]),
    )


async def _resolve_watchlist_stock(query: str) -> Optional[Dict[str, Any]]:
    server = _mx_server_config()
    if not server:
        raise ValueError("未找到已启用的 mx-ds-mcp 配置。")

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", MCP_PROTOCOL_VERSION)
    url = str(server.get("url") or "").strip()
    if not url:
        raise ValueError("妙想 MCP Server 缺少 HTTP URL 配置。")

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(30.0, read=120.0),
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                payload = await _call_json(
                    session,
                    "mx_stocks_screener",
                    PROFILE_QUERY_TEMPLATE.format(query=query),
                )
    row = _best_screener_row(_screener_rows(payload), query)
    if not row:
        return None
    code = _normalize_code(_find_value(row, "代码"))
    name = str(_find_value(row, "名称", "股票简称") or "").strip()
    if not code or not name:
        return None
    industry = str(_find_value(row, "申万行业分类", "东财行业总分类") or "").strip()
    return {
        "code": code,
        "name": name,
        "exchange": _infer_exchange(code),
        "industry": industry,
        "added_at": _now_iso(),
    }


async def _load_watchlist_stock_detail(entry: Dict[str, Any]) -> Dict[str, Any]:
    server = _mx_server_config()
    if not server:
        return _missing_detail_snapshot(entry)

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", MCP_PROTOCOL_VERSION)
    url = str(server.get("url") or "").strip()
    if not url:
        return _missing_detail_snapshot(entry, "妙想 MCP Server 缺少 HTTP URL 配置。")

    query = DETAIL_QUERY_TEMPLATE.format(
        name=entry["name"],
        code=entry["code"],
        exchange=entry["exchange"],
    )
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(30.0, read=120.0),
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                payload = await _call_json(session, "mx_ashare_finance_data", query)

    quotes, _ = _parse_watchlist_quotes(payload, [entry])
    quote = quotes[0] if quotes else _placeholder_quote(entry)
    points = _parse_kline(payload, entry["code"])
    if points:
        latest = points[-1]
        quote["price"] = quote.get("price") or latest["close"]
        quote["change_percent"] = (
            quote.get("change_percent")
            if quote.get("change_percent") is not None
            else latest.get("change_percent")
        )
        quote["sparkline"] = [point["close"] for point in points[-8:]]
        quote["as_of"] = latest["date"]
        quote["quote_status"] = "ok"
    technicals = _build_technicals(points)
    return {
        "ok": bool(points),
        "source": MX_SERVER_NAME,
        "status": "ok" if points else "partial",
        "generated_at": _now_iso(),
        "as_of": points[-1]["date"] if points else None,
        "stock": quote,
        "kline": points,
        "technicals": technicals,
        "summary": _detail_summary(quote, technicals),
    }


def _build_snapshot(
    entries: List[Dict[str, Any]],
    quotes: List[Dict[str, Any]],
    indices: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    as_of: Optional[str],
) -> Dict[str, Any]:
    items = quotes if quotes else [_placeholder_quote(entry) for entry in entries]
    sectors = _build_sector_performance(items)
    summary = _build_watchlist_summary(items, sectors)
    return {
        "ok": not entries or any(item.get("quote_status") == "ok" for item in items),
        "source": MX_SERVER_NAME,
        "status": "partial" if gaps else "ok",
        "generated_at": _now_iso(),
        "as_of": as_of,
        "indices": indices,
        "items": items,
        "sectors": sectors,
        "summary": summary,
        "gaps": gaps,
        "methodology": {
            "title": "自选股盯盘口径",
            "description": (
                "最新行情、主力资金、申万行业与日 K 线来自妙想 MCP。"
                "板块表现仅按当前自选股等权聚合，不代表全行业涨跌。"
            ),
        },
    }


def _build_watchlist_summary(
    items: List[Dict[str, Any]],
    sectors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    valid = [item for item in items if item.get("change_percent") is not None]
    rising = sum(1 for item in valid if item["change_percent"] > 0)
    falling = sum(1 for item in valid if item["change_percent"] < 0)
    flat = len(valid) - rising - falling
    net_flow = round(
        sum(item.get("main_net_flow_yi") or 0.0 for item in items),
        2,
    )
    strongest = sectors[0] if sectors else None
    weakest = sectors[-1] if sectors else None
    headline = "自选股暂无实时行情。"
    if valid:
        breadth = "多数上涨" if rising > falling else "多数下跌" if falling > rising else "涨跌均衡"
        headline = f"自选股{breadth}，上涨 {rising} 只、下跌 {falling} 只。"
        if strongest:
            headline += f" {strongest['name']}表现居前。"
    return {
        "total": len(items),
        "priced": len(valid),
        "rising": rising,
        "falling": falling,
        "flat": flat,
        "main_net_flow_yi": net_flow,
        "strongest_sector": strongest,
        "weakest_sector": weakest,
        "headline": headline,
    }


def _build_sector_performance(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for item in items:
        name = str(item.get("sector") or item.get("industry") or "其他").split("-")[0].strip() or "其他"
        bucket = buckets.setdefault(
            name,
            {"name": name, "stock_count": 0, "change_sum": 0.0, "priced": 0, "main_net_flow_yi": 0.0},
        )
        bucket["stock_count"] += 1
        if item.get("change_percent") is not None:
            bucket["change_sum"] += float(item["change_percent"])
            bucket["priced"] += 1
        bucket["main_net_flow_yi"] += item.get("main_net_flow_yi") or 0.0

    sectors = []
    for bucket in buckets.values():
        priced = bucket.pop("priced")
        change_sum = bucket.pop("change_sum")
        sectors.append(
            {
                **bucket,
                "avg_change_percent": round(change_sum / priced, 2) if priced else None,
                "main_net_flow_yi": round(bucket["main_net_flow_yi"], 2),
            }
        )
    sectors.sort(
        key=lambda item: item["avg_change_percent"] if item["avg_change_percent"] is not None else -9999,
        reverse=True,
    )
    return sectors


def _parse_watchlist_quotes(
    payload: Dict[str, Any],
    entries: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return [_placeholder_quote(entry) for entry in entries], None

    items = {entry["code"]: _placeholder_quote(entry) for entry in entries}
    wanted = set(items)
    as_of: Optional[str] = None
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        rows = [row for row in (table.get("items") or []) if isinstance(row, list) and row]
        if len(columns) < 2 or not rows:
            continue
        as_of = _latest_date([as_of, _extract_date(" ".join(columns))])

        security_columns = []
        for index, column in enumerate(columns[1:], start=1):
            parsed = _parse_security_ref(column)
            if parsed and parsed[1] in wanted:
                security_columns.append((index, *parsed))
        if security_columns:
            for row in rows:
                label = str(row[0]).strip()
                for column_index, name, code, exchange in security_columns:
                    if column_index >= len(row):
                        continue
                    target = items[code]
                    target["name"] = name or target["name"]
                    target["exchange"] = exchange
                    target["as_of"] = target.get("as_of") or _extract_date(" ".join(columns))
                    _apply_quote_metric(target, label, row[column_index])

        first_security = _parse_security_ref(columns[0])
        if first_security and first_security[1] in wanted and _looks_like_date_columns(columns[1:]):
            _, code, exchange = first_security
            target = items[code]
            target["exchange"] = exchange
            metric_rows = {str(row[0]).strip(): row[1:] for row in rows}
            close_values = _find_metric_values(metric_rows, "收盘价")
            if close_values:
                target["sparkline"] = _numeric_series(columns[1:], close_values, limit=8)
                if target.get("price") is None and close_values:
                    target["price"] = _parse_number(close_values[0])
            industry_values = _find_metric_values(metric_rows, "所属申万行业", "申万行业")
            industry = next((str(value) for value in industry_values if str(value).strip() not in {"", "-"}), "")
            if industry:
                target["industry"] = industry
                target["sector"] = industry.split("-")[0]
            flow_values = _find_metric_values(metric_rows, "主力净流入")
            if flow_values and target.get("main_net_flow_yi") is None:
                target["main_net_flow_yi"] = _parse_money_yi(flow_values[0])
            change_values = _find_metric_values(metric_rows, "涨跌幅")
            if change_values and target.get("change_percent") is None:
                target["change_percent"] = _parse_percent(change_values[0])

    for target in items.values():
        if target.get("main_net_flow_yi") is None:
            inflow = target.pop("_main_inflow_yi", None)
            outflow = target.pop("_main_outflow_yi", None)
            if inflow is not None or outflow is not None:
                target["main_net_flow_yi"] = round((inflow or 0.0) - (outflow or 0.0), 4)
        else:
            target.pop("_main_inflow_yi", None)
            target.pop("_main_outflow_yi", None)
        target["quote_status"] = "ok" if target.get("price") is not None else "missing"
        if not target.get("sector"):
            target["sector"] = str(target.get("industry") or "其他").split("-")[0]
    return [items[entry["code"]] for entry in entries], as_of


def _apply_quote_metric(target: Dict[str, Any], label: str, value: Any) -> None:
    normalized = label.replace(" ", "")
    if "最新价" in normalized or normalized == "收盘价":
        target["price"] = _parse_number(value)
    elif "涨跌幅" in normalized and "区间" not in normalized:
        target["change_percent"] = _parse_percent(value)
    elif "涨跌额" in normalized:
        target["change_amount"] = _parse_number(value)
    elif "成交额" in normalized and "区间" not in normalized:
        target["turnover_yi"] = _parse_money_yi(value)
    elif "主力净流入" in normalized or "主力净额" in normalized:
        target["main_net_flow_yi"] = _parse_money_yi(value)
    elif "主力流入" in normalized and "净" not in normalized:
        target["_main_inflow_yi"] = _parse_money_yi(value)
    elif "主力流出" in normalized and "净" not in normalized:
        target["_main_outflow_yi"] = _parse_money_yi(value)
    elif "申万行业" in normalized:
        industry = str(value or "").strip()
        if industry and industry != "-":
            target["industry"] = industry
            target["sector"] = industry.split("-")[0]


def _parse_kline(payload: Dict[str, Any], code: str) -> List[Dict[str, Any]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return []

    best: List[Dict[str, Any]] = []
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        if not columns or code not in columns[0] or not _looks_like_date_columns(columns[1:]):
            continue
        metric_rows = {
            str(row[0]).strip(): row[1:]
            for row in (table.get("items") or [])
            if isinstance(row, list) and row
        }
        opens = _find_metric_values(metric_rows, "开盘价")
        highs = _find_metric_values(metric_rows, "最高价")
        lows = _find_metric_values(metric_rows, "最低价")
        closes = _find_metric_values(metric_rows, "收盘价")
        volumes = _find_metric_values(metric_rows, "成交量")
        turnovers = _find_metric_values(metric_rows, "成交额")
        changes = _find_metric_values(metric_rows, "涨跌幅")
        if not all([opens, highs, lows, closes]):
            continue

        points = []
        for index, label in enumerate(columns[1:]):
            if index >= min(len(opens), len(highs), len(lows), len(closes)):
                continue
            date = _extract_date(label)
            open_value = _parse_number(opens[index])
            high_value = _parse_number(highs[index])
            low_value = _parse_number(lows[index])
            close_value = _parse_number(closes[index])
            if not date or None in {open_value, high_value, low_value, close_value}:
                continue
            points.append(
                {
                    "date": date,
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                    "volume": _parse_volume(volumes[index]) if index < len(volumes) else None,
                    "turnover_yi": _parse_money_yi(turnovers[index]) if index < len(turnovers) else None,
                    "change_percent": _parse_percent(changes[index]) if index < len(changes) else None,
                }
            )
        points.sort(key=lambda point: point["date"])
        if len(points) > len(best):
            best = points[-60:]
    return best


def _build_technicals(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not points:
        return _empty_technicals()
    closes = [float(point["close"]) for point in points]
    recent = points[-20:]
    ma5 = sum(closes[-5:]) / min(len(closes), 5)
    ma20 = sum(closes[-20:]) / min(len(closes), 20)
    latest = closes[-1]
    first = closes[0]
    support = min(float(point["low"]) for point in recent)
    resistance = max(float(point["high"]) for point in recent)
    period_change = (latest / first - 1) * 100 if first else None
    amplitude = (resistance / support - 1) * 100 if support else None
    if latest >= ma5 >= ma20:
        trend_label = "多头排列"
    elif latest <= ma5 <= ma20:
        trend_label = "偏弱运行"
    elif latest >= ma20:
        trend_label = "震荡偏强"
    else:
        trend_label = "震荡偏弱"
    return {
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "period_change_percent": round(period_change, 2) if period_change is not None else None,
        "amplitude_percent": round(amplitude, 2) if amplitude is not None else None,
        "trend_label": trend_label,
    }


def _detail_summary(stock: Dict[str, Any], technicals: Dict[str, Any]) -> str:
    name = stock.get("name") or stock.get("code") or "该股票"
    change = stock.get("change_percent")
    change_text = f"当日涨跌 {change:+.2f}%" if change is not None else "当日涨跌暂缺"
    return (
        f"{name}{change_text}，60 日走势为{technicals.get('trend_label') or '等待判断'}；"
        f"近20日支撑约 {technicals.get('support') or '-'}，压力约 {technicals.get('resistance') or '-'}。"
    )


def _parse_indices(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return [], None
    indices: Dict[str, Dict[str, Any]] = {}
    as_of: Optional[str] = None
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        if len(columns) < 2:
            continue
        as_of = _latest_date([as_of, _extract_date(" ".join(columns))])
        metric_rows = {
            str(row[0]).strip(): row[1:]
            for row in (table.get("items") or [])
            if isinstance(row, list) and row
        }
        first_security = _parse_security_ref(columns[0])
        if first_security and _looks_like_date_columns(columns[1:]):
            name, code, _exchange = first_security
            dated_columns = [
                (index, _extract_date(column))
                for index, column in enumerate(columns[1:])
            ]
            dated_columns = [(index, date) for index, date in dated_columns if date]
            if dated_columns:
                latest_index, latest_date = max(dated_columns, key=lambda item: item[1])
                as_of = _latest_date([as_of, latest_date])
                entry = indices.setdefault(
                    name,
                    {"name": name, "code": code, "value": None, "change_percent": None, "turnover": None},
                )
                for label, values in metric_rows.items():
                    value = values[latest_index] if latest_index < len(values) else None
                    _apply_index_metric(entry, label, value)
                continue

        for index, column in enumerate(columns[1:]):
            parsed = _parse_security_ref(column)
            if parsed:
                name, code, _exchange = parsed
            else:
                name, code = _parse_index_ref(column)
                if not name:
                    continue
            entry = indices.setdefault(
                name,
                {"name": name, "code": code, "value": None, "change_percent": None, "turnover": None},
            )
            for label, values in metric_rows.items():
                value = values[index] if index < len(values) else None
                _apply_index_metric(entry, label, value)
    order = ["上证指数", "深证成指", "创业板指", "沪深300", "科创50"]
    rows = list(indices.values())
    rows.sort(key=lambda item: order.index(item["name"]) if item["name"] in order else len(order))
    return rows[:5], as_of


def _apply_index_metric(entry: Dict[str, Any], label: str, value: Any) -> None:
    if any(key in label for key in ("最新价", "收盘价", "最新点位", "指数点位")):
        entry["value"] = _parse_number(value)
    elif "涨跌幅" in label:
        entry["change_percent"] = _parse_percent(value)
    elif "成交额" in label:
        entry["turnover"] = str(value) if value is not None else None


def _parse_index_ref(value: str) -> Tuple[str, str]:
    aliases = {
        "上证指数": "000001",
        "深证成指": "399001",
        "深证成份指数": "399001",
        "创业板指": "399006",
        "沪深300": "000300",
        "科创50": "000688",
    }
    text = str(value).strip()
    for alias, code in aliases.items():
        if alias in text:
            name = "深证成指" if alias == "深证成份指数" else alias
            match = re.search(r"\b(\d{6})\b", text)
            return name, match.group(1) if match else code
    return "", ""


def _watchlist_quote_query(entries: List[Dict[str, Any]]) -> str:
    securities = "、".join(f"{entry['name']}{entry['code']}" for entry in entries)
    return (
        f"查询A股{securities}最新价、涨跌幅、涨跌额、成交额、主力净流入、申万一级行业，"
        "以及近8个交易日收盘价，不返回技术指标，只返回表格。"
    )


def _reconcile_snapshot(
    cached: Optional[Dict[str, Any]],
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if cached is None:
        return _loading_snapshot(entries)
    snapshot = deepcopy(cached)
    cached_items = {item.get("code"): item for item in snapshot.get("items") or []}
    snapshot["items"] = [
        deepcopy(cached_items.get(entry["code"]) or _placeholder_quote(entry))
        for entry in entries
    ]
    snapshot["sectors"] = _build_sector_performance(snapshot["items"])
    snapshot["summary"] = _build_watchlist_summary(snapshot["items"], snapshot["sectors"])
    return snapshot


def _placeholder_quote(entry: Dict[str, Any]) -> Dict[str, Any]:
    industry = str(entry.get("industry") or "")
    return {
        "code": entry["code"],
        "name": entry.get("name") or entry["code"],
        "exchange": entry.get("exchange") or _infer_exchange(entry["code"]),
        "currency": "CNY",
        "industry": industry,
        "sector": industry.split("-")[0] if industry else "其他",
        "price": None,
        "change_percent": None,
        "change_amount": None,
        "turnover_yi": None,
        "main_net_flow_yi": None,
        "sparkline": [],
        "as_of": None,
        "quote_status": "loading",
    }


def _loading_snapshot(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_snapshot(entries, [], [], [], None)


def _error_snapshot(entries: List[Dict[str, Any]], message: str) -> Dict[str, Any]:
    snapshot = _build_snapshot(
        entries,
        [],
        [],
        [{"key": "snapshot", "title": "自选股行情获取失败", "message": message, "severity": "error"}],
        None,
    )
    snapshot["ok"] = False
    snapshot["status"] = "error"
    snapshot["summary"]["headline"] = "自选股行情暂不可用。"
    return snapshot


def _missing_server_snapshot(
    entries: List[Dict[str, Any]],
    message: str = "未找到已启用的 mx-ds-mcp 配置。",
) -> Dict[str, Any]:
    return _error_snapshot(entries, message)


def _missing_detail_snapshot(
    entry: Dict[str, Any],
    message: str = "未找到已启用的 mx-ds-mcp 配置。",
) -> Dict[str, Any]:
    return {
        "ok": False,
        "source": MX_SERVER_NAME,
        "status": "missing-server",
        "generated_at": _now_iso(),
        "as_of": None,
        "stock": _placeholder_quote(entry),
        "kline": [],
        "technicals": _empty_technicals(),
        "summary": message,
    }


def _empty_technicals() -> Dict[str, Any]:
    return {
        "ma5": None,
        "ma20": None,
        "support": None,
        "resistance": None,
        "period_change_percent": None,
        "amplitude_percent": None,
        "trend_label": "等待数据",
    }


def _home_key() -> str:
    return str(get_hermes_home())


def _watchlist_path(home_key: str) -> Path:
    return (
        Path(home_key)
        / "app-data"
        / "ai.hermes.watchlist"
        / "storage"
        / "watchlist.json"
    )


def _legacy_watchlist_path(home_key: str) -> Path:
    return Path(home_key) / "finance" / "watchlist.json"


def _snapshot_cache_path(home_key: str) -> Path:
    return Path(home_key) / "cache" / "finance-watchlist.json"


def _read_entries(home_key: str) -> List[Dict[str, Any]]:
    path = _watchlist_path(home_key)
    legacy = _legacy_watchlist_path(home_key)
    selected = path if path.exists() else legacy
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(raw_items, list):
            entries = [_normalize_entry(item) for item in raw_items if _valid_entry(item)]
            if selected == legacy:
                _write_entries(home_key, entries)
            return entries
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    entries = [
        {**deepcopy(item), "added_at": _now_iso()}
        for item in DEFAULT_WATCHLIST
    ]
    _write_entries(home_key, entries)
    return entries


def _write_entries(home_key: str, entries: List[Dict[str, Any]]) -> None:
    _write_json_atomic(
        _watchlist_path(home_key),
        {"version": 1, "updated_at": _now_iso(), "items": entries},
    )


def _merge_entry_metadata(home_key: str, quotes: List[Dict[str, Any]]) -> None:
    quote_by_code = {quote.get("code"): quote for quote in quotes}
    with _STATE_LOCK:
        entries = _read_entries(home_key)
        changed = False
        for entry in entries:
            quote = quote_by_code.get(entry["code"])
            if not quote:
                continue
            for key in ("name", "exchange", "industry"):
                value = quote.get(key)
                if value and entry.get(key) != value:
                    entry[key] = value
                    changed = True
        if changed:
            _write_entries(home_key, entries)


def _load_snapshot_cache(home_key: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(_snapshot_cache_path(home_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else None


def _write_snapshot_cache(home_key: str, snapshot: Dict[str, Any]) -> None:
    _write_json_atomic(_snapshot_cache_path(home_key), snapshot)


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _snapshot_codes(snapshot: Optional[Dict[str, Any]]) -> List[str]:
    if not snapshot:
        return []
    return [str(item.get("code") or "") for item in snapshot.get("items") or []]


def _snapshot_is_stale(snapshot: Dict[str, Any]) -> bool:
    return _timestamp_is_stale(snapshot.get("generated_at") or snapshot.get("cached_at"), _SNAPSHOT_MAX_AGE)


def _detail_is_stale(snapshot: Dict[str, Any]) -> bool:
    return _timestamp_is_stale(snapshot.get("generated_at"), _DETAIL_MAX_AGE)


def _timestamp_is_stale(value: Any, max_age: timedelta) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - timestamp > max_age


def _detail_cache_key(home_key: str, code: str) -> str:
    return f"{home_key}::{code}"


def _refresh_meta(job: Optional[Dict[str, Any]], *, cache_state: str) -> Dict[str, Any]:
    return {
        "refreshing": _is_running(job),
        "cache_state": cache_state,
        "refresh_id": job.get("refresh_id") if job else None,
        "status": job.get("status") if job else "idle",
        "started_at": job.get("started_at") if job else None,
        "completed_at": job.get("completed_at") if job else None,
        "error": job.get("error") if job else None,
        "sections": job.get("sections") if job else {},
    }


def _is_running(job: Optional[Dict[str, Any]]) -> bool:
    return bool(job and job.get("status") == "running")


def _mx_server_config() -> Optional[Dict[str, Any]]:
    cfg = load_config()
    servers = cfg.get("mcp_servers") or {}
    server = servers.get(MX_SERVER_NAME)
    if not isinstance(server, dict) or server.get("enabled") is False:
        return None
    return server


def _resolve_headers(headers: Dict[str, Any]) -> Dict[str, str]:
    try:
        from tools.mcp_tool import _interpolate_env_vars

        headers = _interpolate_env_vars(headers)
    except Exception:
        pass
    return {str(key): str(value) for key, value in headers.items() if value is not None}


async def _call_json(session: Any, tool: str, query: str) -> Dict[str, Any]:
    result = await session.call_tool(tool, arguments={"query": query})
    text = "\n".join(
        str(getattr(block, "text", block))
        for block in (getattr(result, "content", None) or [])
    ).strip()
    if not text:
        return {"data": []}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"data": [], "message": text}
    return payload if isinstance(payload, dict) else {"data": []}


async def _call_json_safe(session: Any, tool: str, query: str) -> Dict[str, Any]:
    try:
        return await _call_json(session, tool, query)
    except Exception as exc:
        return {"data": [], "message": str(exc)}


def _screener_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return []
    rows = []
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        for item in table.get("items") or []:
            if isinstance(item, list):
                rows.append(
                    {columns[index]: item[index] for index in range(min(len(columns), len(item)))}
                )
    return rows


def _best_screener_row(rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    if not rows:
        return {}
    cleaned = query.strip().lower()
    digits = re.sub(r"\D", "", cleaned)

    def score(row: Dict[str, Any]) -> int:
        code = str(_find_value(row, "代码") or "").lower()
        name = str(_find_value(row, "名称", "股票简称") or "").lower()
        value = 0
        if digits and code == digits:
            value += 100
        if cleaned and cleaned == name:
            value += 80
        if cleaned and (cleaned in name or name in cleaned):
            value += 40
        if "a股" in str(_find_value(row, "证券类型") or "").lower():
            value += 10
        return value

    return max(rows, key=score)


def _find_value(row: Dict[str, Any], *labels: str) -> Any:
    for label in labels:
        target = label.replace(" ", "").lower()
        for key, value in row.items():
            if target in str(key).replace(" ", "").lower():
                return value
    return None


def _find_metric_values(metric_rows: Dict[str, List[Any]], *labels: str) -> List[Any]:
    for label in labels:
        target = label.replace(" ", "").lower()
        for key, values in metric_rows.items():
            if target in str(key).replace(" ", "").lower():
                return values
    return []


def _numeric_series(labels: List[str], values: List[Any], *, limit: int) -> List[float]:
    points = []
    for index, label in enumerate(labels):
        if index >= len(values) or not _extract_date(label):
            continue
        value = _parse_number(values[index])
        if value is not None:
            points.append(value)
    return list(reversed(points[:limit]))


def _parse_security_ref(value: str) -> Optional[Tuple[str, str, str]]:
    match = _SECURITY_RE.match(str(value).strip())
    if not match:
        return None
    name, code, exchange = match.groups()
    return name.strip(), code, exchange.upper()


def _looks_like_date_columns(columns: List[str]) -> bool:
    return sum(1 for column in columns if _extract_date(column)) >= 2


def _normalize_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    code = _normalize_code(item.get("code"))
    return {
        "code": code,
        "name": str(item.get("name") or code).strip(),
        "exchange": str(item.get("exchange") or _infer_exchange(code)).upper(),
        "industry": str(item.get("industry") or "").strip(),
        "added_at": str(item.get("added_at") or _now_iso()),
    }


def _valid_entry(item: Any) -> bool:
    return isinstance(item, dict) and bool(_normalize_code(item.get("code")))


def _normalize_query(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())[:80]


def _normalize_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else ""


def _infer_exchange(code: str) -> str:
    if code.startswith(("4", "8")):
        return "BJ"
    return "SH" if code.startswith(("5", "6", "9")) else "SZ"


def _parse_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    match = _NUMBER_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_percent(value: Any) -> Optional[float]:
    return _parse_number(value)


def _parse_money_yi(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").strip()
    match = _MONEY_RE.search(text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit == "万亿":
        return round(number * 10000, 4)
    if unit in {"亿元", "亿"}:
        return round(number, 4)
    if unit in {"万元", "万"}:
        return round(number / 10000, 4)
    if unit == "元":
        return round(number / 100000000, 4)
    return round(number / 100000000 if abs(number) > 1000000 else number, 4)


def _parse_volume(value: Any) -> Optional[float]:
    number = _parse_number(value)
    if number is None:
        return None
    text = str(value)
    if "亿" in text:
        return number * 100000000
    if "万" in text:
        return number * 10000
    return number


def _extract_date(value: str) -> Optional[str]:
    match = _DATE_RE.search(str(value))
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _latest_date(values: Iterable[Optional[str]]) -> Optional[str]:
    dates = [value for value in values if value]
    return max(dates) if dates else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
