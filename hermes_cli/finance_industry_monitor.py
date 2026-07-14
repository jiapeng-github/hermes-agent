"""Industry-monitor snapshot backed by the configured MX Data MCP server.

This module is deliberately feature-specific: the desktop page needs a compact
financial snapshot, not a general "call any MCP tool" API surface.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
import contextvars
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from hermes_cli.config import load_config
from hermes_constants import get_hermes_home


MX_SERVER_NAME = "mx-ds-mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"

MARKET_SAMPLE_QUERY = (
    "筛选今日A股中位于涨幅前80、跌幅前80或主力净流入前80的股票，合并去重后返回，"
    "字段包括代码、名称、涨跌幅、成交额、主力净额、热门板块、申万行业分类、概念。"
)
INDICES_QUERY = (
    "查询上证指数、创业板指、沪深300、科创50、北证50最新点位、今日涨跌幅、成交额，"
    "只返回表格。"
)
MARKET_OVERVIEW_QUERY = (
    "查询今日A股上涨家数、下跌家数、平盘家数、涨停家数、跌停家数、全市场成交额；"
    "同时查询北向资金今日成交总额、沪股通成交总额、深股通成交总额及近20个交易日"
    "每日数据，单位亿元，分别返回表格。"
)

NOISY_TOPIC_TAGS = {
    "融资融券",
    "深股通",
    "沪股通",
    "富时罗素",
    "MSCI中国",
    "昨日高振幅",
    "昨日首板",
    "昨日触板",
    "昨日炸板",
    "最近多板",
    "近期新高",
    "历史新高",
    "百日新高",
    "昨日高换手",
    "题材股",
    "趋势股",
    "小盘股",
    "中盘股",
    "大盘股",
    "中盘成长",
    "深成500",
    "中证500",
    "创业板综",
    "破增发价股",
    "超跌股",
    "2025年报预增",
}

_MONEY_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(万亿|亿元|亿|万元|万|元)?")
_DATE_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")

_CACHE_LOCK = threading.RLock()
_CACHE_BY_HOME: Dict[str, Dict[str, Any]] = {}
_ACTIVE_REFRESH_BY_HOME: Dict[str, str] = {}
_REFRESH_JOBS: Dict[str, Dict[str, Any]] = {}
_REFRESH_SECTIONS = ["indices", "breadth", "heatmap", "fund-flow", "northbound", "research"]
_CACHE_MAX_AGE = timedelta(minutes=5)
_DISK_CACHE_NAME = "finance-industry-monitor.json"


def get_industry_monitor_snapshot_cached(*, auto_refresh: bool = True) -> Dict[str, Any]:
    """Return a cached snapshot immediately, optionally kicking off refresh."""

    home_key = _cache_key()
    with _CACHE_LOCK:
        cached = deepcopy(_CACHE_BY_HOME.get(home_key))
        if cached is None:
            cached = _load_disk_cache(home_key)
            if cached is not None:
                _CACHE_BY_HOME[home_key] = deepcopy(cached)
        active_id = _ACTIVE_REFRESH_BY_HOME.get(home_key)
        active_job = deepcopy(_REFRESH_JOBS.get(active_id)) if active_id else None

    if auto_refresh and (cached is None or _cache_is_stale(cached)) and not _is_running(active_job):
        active_job = start_industry_monitor_refresh(force=False)

    if cached is None:
        snapshot = _loading_snapshot()
    else:
        snapshot = cached

    snapshot = deepcopy(snapshot)
    snapshot["refresh"] = _refresh_meta(active_job, cache_state="warm" if cached else "empty")
    return snapshot


def start_industry_monitor_refresh(*, force: bool = False) -> Dict[str, Any]:
    """Start a background refresh for the current profile/home."""

    home_key = _cache_key()
    with _CACHE_LOCK:
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
        name=f"industry-monitor-refresh-{refresh_id[:8]}",
        daemon=True,
    )
    thread.start()
    return deepcopy(job)


def get_industry_monitor_refresh_status(refresh_id: str) -> Dict[str, Any]:
    with _CACHE_LOCK:
        job = deepcopy(_REFRESH_JOBS.get(refresh_id))
    if not job:
        return {
            "refresh_id": refresh_id,
            "status": "not-found",
            "started_at": None,
            "completed_at": None,
            "error": "Refresh job not found.",
            "sections": {},
        }
    return job


def _run_refresh_job(home_key: str, refresh_id: str) -> None:
    try:
        snapshot = load_industry_monitor_snapshot(
            on_partial=lambda partial, sections: _publish_partial_snapshot(
                home_key,
                refresh_id,
                partial,
                sections,
            )
        )
        snapshot["cached_at"] = _now_iso()
        success = bool(snapshot.get("ok"))
        with _CACHE_LOCK:
            previous = _CACHE_BY_HOME.get(home_key)
            if previous and previous.get("research") and not snapshot.get("research"):
                snapshot["research"] = deepcopy(previous["research"])
            if success or home_key not in _CACHE_BY_HOME:
                _CACHE_BY_HOME[home_key] = deepcopy(snapshot)
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "success" if success else "failed"
                job["completed_at"] = _now_iso()
                job["error"] = None if success else (snapshot.get("summary", {}).get("headline") or "Refresh failed.")
                job["sections"] = (
                    _section_states(
                        snapshot,
                        research_state="success" if snapshot.get("research") else "failed",
                    )
                    if success
                    else {section: "failed" for section in _REFRESH_SECTIONS}
                )
            if _ACTIVE_REFRESH_BY_HOME.get(home_key) == refresh_id:
                _ACTIVE_REFRESH_BY_HOME.pop(home_key, None)
        if success:
            _write_disk_cache(home_key, snapshot)
    except Exception as exc:
        with _CACHE_LOCK:
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "failed"
                job["completed_at"] = _now_iso()
                job["error"] = str(exc)
                job["sections"] = {section: "failed" for section in _REFRESH_SECTIONS}
            if _ACTIVE_REFRESH_BY_HOME.get(home_key) == refresh_id:
                _ACTIVE_REFRESH_BY_HOME.pop(home_key, None)


def _refresh_meta(job: Optional[Dict[str, Any]], *, cache_state: str) -> Dict[str, Any]:
    running = _is_running(job)
    return {
        "refreshing": running,
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


def _cache_key() -> str:
    return str(get_hermes_home())


def _cache_path(home_key: str) -> Path:
    return Path(home_key) / "cache" / _DISK_CACHE_NAME


def _load_disk_cache(home_key: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(_cache_path(home_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("indices") is not None else None


def _write_disk_cache(home_key: str, snapshot: Dict[str, Any]) -> None:
    path = _cache_path(home_key)
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _cache_is_stale(snapshot: Dict[str, Any]) -> bool:
    value = snapshot.get("generated_at") or snapshot.get("cached_at")
    if not value:
        return True
    try:
        generated_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - generated_at > _CACHE_MAX_AGE


def _publish_partial_snapshot(
    home_key: str,
    refresh_id: str,
    snapshot: Dict[str, Any],
    sections: Dict[str, str],
) -> None:
    snapshot["cached_at"] = _now_iso()
    with _CACHE_LOCK:
        previous = _CACHE_BY_HOME.get(home_key)
        if previous and previous.get("research") and not snapshot.get("research"):
            snapshot["research"] = deepcopy(previous["research"])
        _CACHE_BY_HOME[home_key] = deepcopy(snapshot)
        job = _REFRESH_JOBS.get(refresh_id)
        if job:
            job["sections"] = dict(sections)


def load_industry_monitor_snapshot(
    *,
    on_partial: Optional[Callable[[Dict[str, Any], Dict[str, str]], None]] = None,
) -> Dict[str, Any]:
    """Return a JSON-serialisable industry monitor snapshot."""

    try:
        return asyncio.run(_load_industry_monitor_snapshot(on_partial=on_partial))
    except Exception as exc:
        return {
            "ok": False,
            "source": MX_SERVER_NAME,
            "status": "error",
            "generated_at": _now_iso(),
            "as_of": None,
            "market_turnover_yi": None,
            "market_breadth": None,
            "market_sample_size": 0,
            "indices": [],
            "industry_heatmap": [],
            "topic_heatmap": [],
            "fund_flow": [],
            "pressure": [],
            "northbound": None,
            "research": [],
            "summary": {
                "headline": "行业监控数据暂不可用",
                "details": [str(exc)],
            },
            "gaps": [
                {
                    "key": "snapshot",
                    "title": "行业监控快照获取失败",
                    "message": str(exc),
                    "severity": "error",
                }
            ],
        }


async def _load_industry_monitor_snapshot(
    *,
    on_partial: Optional[Callable[[Dict[str, Any], Dict[str, str]], None]] = None,
) -> Dict[str, Any]:
    server = _mx_server_config()
    if not server:
        return _missing_server_snapshot()

    try:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        return _dependency_gap_snapshot(exc)

    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", MCP_PROTOCOL_VERSION)
    url = str(server.get("url") or "").strip()
    if not url:
        return _missing_server_snapshot("妙想 MCP Server 缺少 HTTP URL 配置。")

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
                sample_payload, indices_payload, market_payload = await asyncio.gather(
                    _call_json_safe(session, "mx_stocks_screener", MARKET_SAMPLE_QUERY),
                    _call_json_safe(session, "mx_index_block_finance_data", INDICES_QUERY),
                    _call_json_safe(
                        session,
                        "mx_comprehensive_finance_data",
                        MARKET_OVERVIEW_QUERY,
                    ),
                )

                market_rows = _rows_from_screener_payload(sample_payload)
                gainer_rows, loser_rows, inflow_rows = _split_market_sample(market_rows)
                heatmap = _build_industry_heatmap(gainer_rows, loser_rows, inflow_rows)
                topics = _build_topic_heatmap(gainer_rows, loser_rows, inflow_rows)
                fund_flow = _rank_groups(_aggregate_rows(inflow_rows, "hot_block"), 10, "main")
                pressure = _rank_groups(_aggregate_rows(loser_rows, "hot_block"), 8, "pressure")
                indices, index_as_of, index_turnover = _parse_indices(indices_payload)
                breadth, breadth_as_of, breadth_turnover = _parse_market_breadth(market_payload)
                northbound, north_as_of = _parse_northbound(market_payload)
                market_turnover = breadth_turnover or index_turnover
                as_of = _latest_date(
                    [
                        index_as_of,
                        breadth_as_of,
                        north_as_of,
                        _rows_as_of(market_rows),
                    ]
                )
                gaps = _build_gaps(
                    gainer_rows=gainer_rows,
                    loser_rows=loser_rows,
                    inflow_rows=inflow_rows,
                    indices=indices,
                    breadth=breadth,
                    northbound=northbound,
                )
                snapshot = _build_snapshot(
                    as_of=as_of,
                    breadth=breadth,
                    gaps=gaps,
                    heatmap=heatmap,
                    indices=indices,
                    market_rows=market_rows,
                    market_turnover=market_turnover,
                    northbound=northbound,
                    fund_flow=fund_flow,
                    pressure=pressure,
                    research=[],
                    topics=topics,
                )
                if on_partial:
                    on_partial(
                        deepcopy(snapshot),
                        _section_states(snapshot, research_state="refreshing"),
                    )
                research = await _load_research(session, topics, fund_flow)

    return {**snapshot, "research": research, "generated_at": _now_iso()}


def _build_snapshot(
    *,
    as_of: Optional[str],
    breadth: Optional[Dict[str, Any]],
    gaps: List[Dict[str, str]],
    heatmap: List[Dict[str, Any]],
    indices: List[Dict[str, Any]],
    market_rows: List[Dict[str, Any]],
    market_turnover: Optional[float],
    northbound: Optional[Dict[str, Any]],
    fund_flow: List[Dict[str, Any]],
    pressure: List[Dict[str, Any]],
    research: List[Dict[str, Any]],
    topics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "ok": bool(indices or heatmap or topics or fund_flow or northbound or breadth),
        "source": MX_SERVER_NAME,
        "status": "partial" if gaps else "ok",
        "generated_at": _now_iso(),
        "as_of": as_of,
        "market_turnover_yi": market_turnover,
        "market_breadth": breadth,
        "market_sample_size": len(market_rows),
        "indices": indices,
        "industry_heatmap": heatmap,
        "topic_heatmap": topics,
        "fund_flow": fund_flow,
        "pressure": pressure,
        "northbound": northbound,
        "research": research,
        "summary": _build_summary(topics, fund_flow, pressure, northbound, breadth),
        "gaps": gaps,
        "methodology": {
            "title": "动态热点聚合口径",
            "description": (
                "妙想 MCP 一次返回涨幅前80、跌幅前80或主力净流入前80的动态并集样本，"
                "不使用固定行业篮子。一级行业取申万分类首段，热点题材取热门板块和高信号概念；"
                "市场广度与北向成交来自综合行情。"
            ),
        },
    }


def _section_states(snapshot: Dict[str, Any], *, research_state: str) -> Dict[str, str]:
    return {
        "indices": "success" if snapshot.get("indices") else "failed",
        "breadth": "success" if snapshot.get("market_breadth") else "failed",
        "heatmap": (
            "success"
            if snapshot.get("industry_heatmap") or snapshot.get("topic_heatmap")
            else "failed"
        ),
        "fund-flow": "success" if snapshot.get("fund_flow") else "failed",
        "northbound": "success" if snapshot.get("northbound") else "failed",
        "research": research_state,
    }


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
    return {str(k): str(v) for k, v in headers.items() if v is not None}


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


def _rows_from_screener_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not tables:
        return []
    table = tables[0] if isinstance(tables, list) else {}
    columns = [str(c) for c in (table.get("columns") or [])]
    items = table.get("items") or []

    def col(label: str) -> int:
        for index, name in enumerate(columns):
            if label in name:
                return index
        return -1

    indices = {
        "code": col("代码"),
        "name": col("名称"),
        "change_percent": col("涨跌幅"),
        "turnover": col("成交额"),
        "main_net_inflow": col("主力净额"),
        "hot_blocks": col("热门板块"),
        "industry": col("申万行业分类"),
        "concepts": col("概念"),
    }
    as_of = _extract_date(" ".join(columns))
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, list):
            continue
        row: Dict[str, Any] = {"as_of": as_of}
        for key, index in indices.items():
            row[key] = item[index] if 0 <= index < len(item) else ""
        row["change_percent_value"] = _parse_percent(row.get("change_percent"))
        row["turnover_yi"] = _parse_money_yi(row.get("turnover"))
        row["main_net_inflow_yi"] = _parse_money_yi(row.get("main_net_inflow"))
        rows.append(row)
    return rows


def _split_market_sample(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    gainers = sorted(
        (row for row in rows if (row.get("change_percent_value") or 0.0) > 0),
        key=lambda row: row.get("change_percent_value") or 0.0,
        reverse=True,
    )[:80]
    losers = sorted(
        (row for row in rows if (row.get("change_percent_value") or 0.0) < 0),
        key=lambda row: row.get("change_percent_value") or 0.0,
    )[:80]
    inflows = sorted(
        (row for row in rows if (row.get("main_net_inflow_yi") or 0.0) > 0),
        key=lambda row: row.get("main_net_inflow_yi") or 0.0,
        reverse=True,
    )[:80]
    return gainers, losers, inflows


def _aggregate_rows(rows: List[Dict[str, Any]], dimension: str) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = defaultdict(_empty_bucket)
    for row in rows:
        for key in _dimension_keys(row, dimension):
            bucket = buckets[key]
            bucket["name"] = key
            bucket["sample_count"] += 1
            bucket["turnover_yi"] += row.get("turnover_yi") or 0.0
            bucket["main_net_inflow_yi"] += row.get("main_net_inflow_yi") or 0.0
            bucket["change_sum"] += row.get("change_percent_value") or 0.0
            leader = _leader(row)
            if leader and leader not in bucket["leaders"] and len(bucket["leaders"]) < 4:
                bucket["leaders"].append(leader)
    return buckets


def _empty_bucket() -> Dict[str, Any]:
    return {
        "name": "",
        "sample_count": 0,
        "turnover_yi": 0.0,
        "main_net_inflow_yi": 0.0,
        "change_sum": 0.0,
        "leaders": [],
    }


def _dimension_keys(row: Dict[str, Any], dimension: str) -> Iterable[str]:
    if dimension == "industry":
        industry = str(row.get("industry") or "").split("-")[0].strip()
        if industry:
            yield industry
        return
    if dimension == "hot_block":
        for tag in _split_tags(row.get("hot_blocks")):
            if tag and tag not in NOISY_TOPIC_TAGS:
                yield tag
        return
    if dimension == "concept":
        for tag in _split_tags(row.get("concepts")):
            if tag and tag not in NOISY_TOPIC_TAGS:
                yield tag


def _rank_groups(
    groups: Dict[str, Dict[str, Any]],
    limit: int,
    mode: str,
    *,
    category: str = "",
    side: str = "",
) -> List[Dict[str, Any]]:
    def sort_key(entry: Tuple[str, Dict[str, Any]]) -> Tuple[float, float, float]:
        bucket = entry[1]
        if mode == "main":
            return (
                bucket["main_net_inflow_yi"],
                bucket["sample_count"],
                bucket["turnover_yi"],
            )
        if mode == "pressure":
            return (
                abs(min(bucket["main_net_inflow_yi"], 0.0)),
                bucket["sample_count"],
                bucket["turnover_yi"],
            )
        return (
            bucket["sample_count"],
            bucket["main_net_inflow_yi"],
            bucket["turnover_yi"],
        )

    ranked = []
    for _, bucket in sorted(groups.items(), key=sort_key, reverse=True):
        if mode == "pressure" and bucket["main_net_inflow_yi"] >= 0:
            continue
        sample_count = max(int(bucket["sample_count"]), 1)
        ranked.append(
            {
                "name": bucket["name"],
                "category": category,
                "side": side,
                "sample_count": bucket["sample_count"],
                "avg_change_percent": round(bucket["change_sum"] / sample_count, 2),
                "turnover_yi": round(bucket["turnover_yi"], 2),
                "main_net_inflow_yi": round(bucket["main_net_inflow_yi"], 2),
                "leaders": bucket["leaders"],
            }
        )
        if len(ranked) >= limit:
            break
    return ranked


def _build_industry_heatmap(
    gainers: List[Dict[str, Any]],
    losers: List[Dict[str, Any]],
    inflows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    candidates = [
        *_rank_groups(_aggregate_rows(gainers, "industry"), 8, "count", category="industry", side="hot"),
        *_rank_groups(_aggregate_rows(inflows, "industry"), 6, "main", category="industry", side="fund"),
        *_rank_groups(_aggregate_rows(losers, "industry"), 6, "pressure", category="industry", side="cold"),
    ]
    for item in candidates:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        result.append(item)
        if len(result) >= 16:
            break
    return result


def _build_topic_heatmap(
    gainers: List[Dict[str, Any]],
    losers: List[Dict[str, Any]],
    inflows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    hot_blocks = _aggregate_rows(gainers, "hot_block")
    concepts = _aggregate_rows(gainers, "concept")
    inflow_blocks = _aggregate_rows(inflows, "hot_block")
    loser_blocks = _aggregate_rows(losers, "hot_block")
    candidates = [
        *_rank_groups(hot_blocks, 10, "count", category="topic", side="hot"),
        *_rank_groups(concepts, 8, "count", category="topic", side="hot"),
        *_rank_groups(inflow_blocks, 8, "main", category="topic", side="fund"),
        *_rank_groups(loser_blocks, 5, "pressure", category="topic", side="cold"),
    ]
    for item in candidates:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        result.append(item)
        if len(result) >= 20:
            break
    return result


async def _load_research(session: Any, topics: List[Dict[str, Any]], fund_flow: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    topic_names = [item["name"] for item in [*topics[:4], *fund_flow[:3]]]
    deduped: List[str] = []
    for name in topic_names:
        if name not in deduped:
            deduped.append(name)
    if not deduped:
        return []
    query = (
        "查询最近7天"
        + "、".join(deduped[:6])
        + "相关的研报观点、新闻催化、资金流向和风险提示，返回标题、完整摘要、发布时间、来源。"
    )
    payload = await _call_json(session, "mx_finance_search_news", query)
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not tables:
        return []
    table = tables[0]
    columns = [str(c) for c in (table.get("columns") or [])]

    def col(label: str) -> int:
        for index, name in enumerate(columns):
            if label in name:
                return index
        return -1

    idx = {
        "title": col("标题"),
        "summary": col("摘要"),
        "published_at": col("发布时间"),
        "source": col("来源"),
        "url": col("跳转链接"),
    }
    out: List[Dict[str, Any]] = []
    for item in table.get("items") or []:
        if not isinstance(item, list):
            continue
        title = _item_at(item, idx["title"])
        summary = _item_at(item, idx["summary"])
        if not title and not summary:
            continue
        out.append(
            {
                "title": title,
                "summary": _trim_text(summary, 1600),
                "published_at": _item_at(item, idx["published_at"]),
                "source": _item_at(item, idx["source"]),
                "url": _item_at(item, idx["url"]) or None,
            }
        )
        if len(out) >= 6:
            break
    return out


def _parse_indices(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[float]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not tables:
        return [], None, None
    indices: Dict[str, Dict[str, Any]] = {}
    as_of: Optional[str] = None
    market_turnover: Optional[float] = None
    for table in tables:
        columns = [str(c) for c in (table.get("columns") or [])]
        if not columns:
            continue
        as_of = as_of or _extract_date(" ".join(columns))
        items = table.get("items") or []
        if any("全部A股" in c for c in columns):
            market_turnover = market_turnover or _extract_market_turnover(columns, items)
        if len(columns) < 2:
            continue
        names = columns[1:]
        values_by_label: Dict[str, List[Any]] = {}
        for row in items:
            if isinstance(row, list) and row:
                values_by_label[str(row[0])] = row[1:]
        for index, name in enumerate(names):
            if "全部A股" in name:
                continue
            entry = indices.setdefault(
                name,
                {
                    "name": _clean_security_name(name),
                    "code": _extract_code(name),
                    "value": None,
                    "change_percent": None,
                    "turnover": None,
                },
            )
            for label, values in values_by_label.items():
                value = values[index] if index < len(values) else None
                if "最新价" in label or "收盘价" in label:
                    entry["value"] = _parse_number(value)
                elif "涨跌幅" in label:
                    entry["change_percent"] = _parse_percent(value)
                elif "成交额" in label:
                    entry["turnover"] = str(value) if value is not None else None
    order = ["上证指数", "创业板指", "沪深300", "科创50", "北证50"]
    rows = list(indices.values())
    rows.sort(key=lambda item: order.index(item["name"]) if item["name"] in order else len(order))
    return rows[:5], as_of, market_turnover


def _extract_market_turnover(columns: List[str], items: List[Any]) -> Optional[float]:
    for row in items:
        if not isinstance(row, list) or len(row) < 2:
            continue
        if "成交额" in str(row[0]):
            return _parse_money_yi(row[1])
    return None


def _parse_market_breadth(
    payload: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[float]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not tables:
        return None, None, None

    values: Dict[str, int] = {}
    as_of: Optional[str] = None
    market_turnover: Optional[float] = None
    labels = {
        "上涨家数": "advancers",
        "下跌家数": "decliners",
        "平盘家数": "flat",
        "涨停家数": "limit_up",
        "跌停家数": "limit_down",
    }
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        if not any("全部A股" in column for column in columns):
            continue
        as_of = _latest_date([as_of, _extract_date(" ".join(columns))])
        for item in table.get("items") or []:
            if not isinstance(item, list) or len(item) < 2:
                continue
            label = str(item[0])
            if "成交额" in label:
                market_turnover = market_turnover or _parse_money_yi(item[1])
                continue
            for source_label, key in labels.items():
                if source_label in label:
                    values[key] = _parse_int(item[1])
                    break

    if not values:
        return None, as_of, market_turnover
    advancers = values.get("advancers", 0)
    decliners = values.get("decliners", 0)
    flat = values.get("flat", 0)
    directional_total = advancers + decliners
    advance_ratio = advancers / directional_total * 100 if directional_total else 0.0
    breadth = {
        "as_of": as_of,
        "advancers": advancers,
        "decliners": decliners,
        "flat": flat,
        "limit_up": values.get("limit_up", 0),
        "limit_down": values.get("limit_down", 0),
        "total": advancers + decliners + flat,
        "advance_ratio": round(advance_ratio, 1),
        "sentiment_label": _breadth_label(advance_ratio),
    }
    return breadth, as_of, market_turnover


def _parse_northbound(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not tables:
        return None, None
    rows: List[Dict[str, Any]] = []
    for table in tables:
        columns = [str(c) for c in (table.get("columns") or [])]
        if not any("北向资金成交总额" in c for c in columns):
            continue
        idx_date = _find_col(columns, "交易日期")
        idx_total = _find_col(columns, "北向资金成交总额")
        idx_sh = _find_col(columns, "沪股通-成交总额")
        idx_sz = _find_col(columns, "深股通-成交总额")
        for item in table.get("items") or []:
            if not isinstance(item, list):
                continue
            date = _item_at(item, idx_date)
            total = _parse_million_yi(_item_at(item, idx_total))
            sh = _parse_million_yi(_item_at(item, idx_sh))
            sz = _parse_million_yi(_item_at(item, idx_sz))
            if date and total:
                rows.append(
                    {
                        "date": date,
                        "total_yi": round(total, 2),
                        "sh_yi": round(sh, 2),
                        "sz_yi": round(sz, 2),
                    }
                )
    if not rows:
        return None, None
    rows = _dedupe_series(sorted(rows, key=lambda row: row["date"], reverse=True))[:20]
    current = rows[0]
    avg_total = sum(row["total_yi"] for row in rows) / len(rows)
    activity_ratio = current["total_yi"] / avg_total if avg_total else 0.0
    sz_share = current["sz_yi"] / current["total_yi"] * 100 if current["total_yi"] else 0.0
    current = {
        **current,
        "sz_share_percent": round(sz_share, 1),
        "activity_ratio": round(activity_ratio, 2),
        "activity_label": _activity_label(activity_ratio),
        "bias_label": _northbound_bias(sz_share),
    }
    return {
        "current": current,
        "average_total_yi": round(avg_total, 2),
        "series": list(reversed(rows)),
        "note": (
            "当前妙想 MCP 返回北向成交额数据，未返回净买入金额。本模块展示交易活跃度与"
            "沪深通道结构，不代表资金净流入方向。"
        ),
    }, current["date"]


def _dedupe_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row["date"] in seen:
            continue
        seen.add(row["date"])
        out.append(row)
    return out


def _build_summary(
    topics: List[Dict[str, Any]],
    fund_flow: List[Dict[str, Any]],
    pressure: List[Dict[str, Any]],
    northbound: Optional[Dict[str, Any]],
    breadth: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    top_topic = topics[0]["name"] if topics else "热点题材"
    top_flow = fund_flow[0]["name"] if fund_flow else "主力资金"
    top_pressure = pressure[0]["name"] if pressure else "弱势板块"
    breadth_prefix = f"市场呈{breadth['sentiment_label']}格局，" if breadth else ""
    headline = (
        f"{breadth_prefix}热点集中在{top_topic}，资金线索偏向{top_flow}，"
        f"{top_pressure}承压。"
    )
    details = []
    if breadth:
        details.append(
            f"上涨{breadth['advancers']}家、下跌{breadth['decliners']}家，"
            f"涨停{breadth['limit_up']}家、跌停{breadth['limit_down']}家。"
        )
    if fund_flow:
        details.append(
            f"{top_flow}在动态样本中资金强度居前，样本聚合净额约"
            f"{fund_flow[0]['main_net_inflow_yi']:.1f}亿元。"
        )
    if northbound and northbound.get("current"):
        current = northbound["current"]
        details.append(
            f"北向成交总额{current['total_yi']:.1f}亿元，深股通占比{current['sz_share_percent']:.1f}%，"
            f"活跃度为{current['activity_label']}。"
        )
    return {"headline": headline, "details": details}


def _build_gaps(
    *,
    gainer_rows: List[Dict[str, Any]],
    loser_rows: List[Dict[str, Any]],
    inflow_rows: List[Dict[str, Any]],
    indices: List[Dict[str, Any]],
    breadth: Optional[Dict[str, Any]],
    northbound: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    gaps: List[Dict[str, str]] = []
    if not gainer_rows:
        gaps.append(_gap("gainers", "涨幅榜数据缺失", "妙想 MCP 未返回今日 A 股涨幅榜样本。", "warning"))
    if not loser_rows:
        gaps.append(_gap("losers", "跌幅榜数据缺失", "妙想 MCP 未返回今日 A 股跌幅榜样本。", "warning"))
    if not inflow_rows:
        gaps.append(_gap("fund-flow", "主力资金榜缺失", "妙想 MCP 未返回主力净流入样本。", "warning"))
    if not indices:
        gaps.append(_gap("indices", "指数概览缺失", "妙想 MCP 未返回核心指数行情。", "warning"))
    if not breadth:
        gaps.append(_gap("breadth", "市场广度缺失", "妙想 MCP 未返回上涨、下跌及涨跌停家数。", "warning"))
    if not northbound:
        gaps.append(
            _gap(
                "northbound",
                "北向成交数据缺失",
                "妙想 MCP 未返回北向成交总额、沪股通成交额或深股通成交额。",
                "warning",
            )
        )
    return gaps


def _gap(key: str, title: str, message: str, severity: str) -> Dict[str, str]:
    return {"key": key, "title": title, "message": message, "severity": severity}


def _missing_server_snapshot(message: str = "未找到已启用的 mx-ds-mcp 配置。") -> Dict[str, Any]:
    return {
        "ok": False,
        "source": MX_SERVER_NAME,
        "status": "missing-server",
        "generated_at": _now_iso(),
        "as_of": None,
        "market_turnover_yi": None,
        "market_breadth": None,
        "market_sample_size": 0,
        "indices": [],
        "industry_heatmap": [],
        "topic_heatmap": [],
        "fund_flow": [],
        "pressure": [],
        "northbound": None,
        "research": [],
        "summary": {"headline": "妙想 MCP 尚未可用", "details": [message]},
        "gaps": [_gap("mcp", "妙想 MCP 未配置", message, "error")],
    }


def _dependency_gap_snapshot(exc: Exception) -> Dict[str, Any]:
    message = f"MCP HTTP 客户端依赖不可用：{exc}"
    return {
        "ok": False,
        "source": MX_SERVER_NAME,
        "status": "dependency-missing",
        "generated_at": _now_iso(),
        "as_of": None,
        "market_turnover_yi": None,
        "market_breadth": None,
        "market_sample_size": 0,
        "indices": [],
        "industry_heatmap": [],
        "topic_heatmap": [],
        "fund_flow": [],
        "pressure": [],
        "northbound": None,
        "research": [],
        "summary": {"headline": "MCP 依赖缺失", "details": [message]},
        "gaps": [_gap("mcp-dependency", "MCP 依赖缺失", message, "error")],
    }


def _loading_snapshot() -> Dict[str, Any]:
    return {
        "ok": False,
        "source": MX_SERVER_NAME,
        "status": "refreshing",
        "generated_at": _now_iso(),
        "cached_at": None,
        "as_of": None,
        "market_turnover_yi": None,
        "market_breadth": None,
        "market_sample_size": 0,
        "indices": [],
        "industry_heatmap": [],
        "topic_heatmap": [],
        "fund_flow": [],
        "pressure": [],
        "northbound": None,
        "research": [],
        "summary": {
            "headline": "行业监控数据正在刷新",
            "details": ["首次加载会在后台连接妙想 MCP，页面会在快照完成后自动更新。"],
        },
        "gaps": [],
        "methodology": {
            "title": "动态热点聚合口径",
            "description": (
                "妙想 MCP 返回涨幅、跌幅与主力净流入信号的动态并集样本，"
                "页面先展示行情和轮动，再异步补充研报。"
            ),
        },
    }


def _find_col(columns: List[str], label: str) -> int:
    for index, name in enumerate(columns):
        if label in name:
            return index
    return -1


def _item_at(item: List[Any], index: int) -> str:
    if index < 0 or index >= len(item):
        return ""
    value = item[index]
    return "" if value is None else str(value)


def _leader(row: Dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip()
    change = row.get("change_percent")
    if not name:
        return ""
    return f"{name}({change}%)" if change not in (None, "") else name


def _split_tags(value: Any) -> List[str]:
    return [tag.strip() for tag in re.split(r"[,，、]", str(value or "")) if tag.strip()]


def _parse_percent(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    match = _MONEY_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_int(value: Any) -> int:
    number = _parse_number(value)
    return int(number) if number is not None else 0


def _parse_money_yi(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    text = str(value).replace(",", "").strip()
    match = _MONEY_RE.search(text)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit == "万亿":
        return number * 10000
    if unit in {"亿元", "亿"}:
        return number
    if unit in {"万元", "万"}:
        return number / 10000
    if unit == "元":
        return number / 100000000
    return number / 100000000 if abs(number) > 1000000 else number


def _parse_million_yi(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", "")) / 100
    except ValueError:
        return _parse_money_yi(value)


def _extract_date(text: str) -> Optional[str]:
    match = _DATE_RE.search(text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _rows_as_of(rows: List[Dict[str, Any]]) -> Optional[str]:
    for row in rows:
        if row.get("as_of"):
            return str(row["as_of"])
    return None


def _latest_date(values: Iterable[Optional[str]]) -> Optional[str]:
    dates = [value for value in values if value]
    return max(dates) if dates else None


def _clean_security_name(name: str) -> str:
    return re.sub(r"\([^)]*\)", "", name).strip()


def _extract_code(name: str) -> Optional[str]:
    match = re.search(r"\(([^)]*)\)", name)
    return match.group(1) if match else None


def _activity_label(ratio: float) -> str:
    if ratio >= 1.12:
        return "高活跃"
    if ratio <= 0.88:
        return "低活跃"
    return "正常"


def _breadth_label(advance_ratio: float) -> str:
    if advance_ratio >= 65:
        return "普涨"
    if advance_ratio >= 55:
        return "偏强"
    if advance_ratio <= 35:
        return "普跌"
    if advance_ratio <= 45:
        return "偏弱"
    return "均衡"


def _northbound_bias(sz_share: float) -> str:
    if sz_share >= 53:
        return "偏深市成长"
    if sz_share <= 47:
        return "偏沪市价值"
    return "沪深均衡"


def _trim_text(value: Any, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
