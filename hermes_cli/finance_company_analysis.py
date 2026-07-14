"""Company-analysis snapshot backed by the configured MX Data MCP server.

The desktop page needs a compact, page-specific financial model rather than a
generic MCP proxy. This module keeps the MCP dependency behind a narrow JSON
shape and returns cached snapshots immediately while refreshes run in the
background.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import contextvars
from datetime import datetime, timezone
import json
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple
import uuid

from hermes_cli.config import load_config
from hermes_constants import get_hermes_home


MX_SERVER_NAME = "mx-ds-mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_COMPANY_QUERY = "宁德时代"

PROFILE_QUERY_TEMPLATE = (
    "筛选名称或代码为{query}的A股上市公司，字段包括代码、名称、最新价、涨跌幅、涨跌额、"
    "总市值、市盈率(TTM)、市净率PB、销售毛利率、净资产收益率ROE、主营产品、"
    "申万行业分类、概念、成交额、换手率、量比、最高价、最低价、流通市值，"
    "返回最匹配的前5只，只返回表格。"
)
CURRENT_QUERY_TEMPLATE = (
    "查询{query}最新股价、涨跌幅、涨跌额、总市值、市盈率PE(TTM)、市净率PB、"
    "成交额、近6个交易日收盘价、最高价、最低价，只返回表格。"
)
FINANCIAL_QUERY_TEMPLATE = (
    "查询{query}最近4个季度营业收入、净利润、毛利率、净资产收益率ROE、"
    "经营活动产生的现金流量净额、资产负债率、流动比率、存货周转率，只返回表格。"
)
FINANCIAL_FALLBACK_QUERY_TEMPLATE = (
    "查询{query}最近4个报告期的单季度.营业收入、单季度.净利润、"
    "单季度.经营活动产生的现金流量净额、单季度.销售毛利率、净资产收益率ROE，"
    "优先返回A股表格。"
)
NEWS_QUERY_TEMPLATE = (
    "查询最近90天{query}研报观点、投资亮点、主要风险、风险提示原文和重大事项，"
    "返回标题、完整摘要、发布时间、来源，最多8条。"
)
RISK_QUERY_TEMPLATE = (
    "查询最近180天{query}研报风险提示和主要风险，摘要中优先包含风险提示原文，"
    "返回标题、摘要、发布时间、来源，最多8条。"
)

_CACHE_LOCK = threading.RLock()
_CACHE_BY_QUERY: Dict[str, Dict[str, Any]] = {}
_ACTIVE_REFRESH_BY_QUERY: Dict[str, str] = {}
_REFRESH_JOBS: Dict[str, Dict[str, Any]] = {}
_REFRESH_SECTIONS = ["profile", "financials", "peers", "research"]

_MONEY_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(万亿|亿元|亿|万元|万|元|港元)?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_DATE_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")


def get_company_analysis_snapshot_cached(
    query: str = DEFAULT_COMPANY_QUERY,
    *,
    auto_refresh: bool = True,
) -> Dict[str, Any]:
    """Return a cached company snapshot immediately, optionally refreshing."""

    normalized_query = _normalize_query(query)
    cache_key = _cache_key(normalized_query)
    with _CACHE_LOCK:
        cached = deepcopy(_CACHE_BY_QUERY.get(cache_key))
        active_id = _ACTIVE_REFRESH_BY_QUERY.get(cache_key)
        active_job = deepcopy(_REFRESH_JOBS.get(active_id)) if active_id else None

    if auto_refresh and cached is None and not _is_running(active_job):
        active_job = start_company_analysis_refresh(normalized_query, force=False)

    snapshot = cached if cached is not None else _loading_snapshot(normalized_query)
    snapshot = deepcopy(snapshot)
    snapshot["refresh"] = _refresh_meta(active_job, cache_state="warm" if cached else "empty")
    return snapshot


def start_company_analysis_refresh(
    query: str = DEFAULT_COMPANY_QUERY,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Start a background refresh for a company-analysis snapshot."""

    normalized_query = _normalize_query(query)
    cache_key = _cache_key(normalized_query)
    with _CACHE_LOCK:
        active_id = _ACTIVE_REFRESH_BY_QUERY.get(cache_key)
        active_job = _REFRESH_JOBS.get(active_id) if active_id else None
        if _is_running(active_job) and not force:
            return deepcopy(active_job)

        refresh_id = uuid.uuid4().hex
        job = {
            "refresh_id": refresh_id,
            "cache_key": cache_key,
            "query": normalized_query,
            "status": "running",
            "started_at": _now_iso(),
            "completed_at": None,
            "error": None,
            "sections": {section: "refreshing" for section in _REFRESH_SECTIONS},
        }
        _REFRESH_JOBS[refresh_id] = job
        _ACTIVE_REFRESH_BY_QUERY[cache_key] = refresh_id

    ctx = contextvars.copy_context()
    thread = threading.Thread(
        target=lambda: ctx.run(_run_refresh_job, cache_key, normalized_query, refresh_id),
        name=f"company-analysis-refresh-{refresh_id[:8]}",
        daemon=True,
    )
    thread.start()
    return deepcopy(job)


def get_company_analysis_refresh_status(refresh_id: str) -> Dict[str, Any]:
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


def _run_refresh_job(cache_key: str, query: str, refresh_id: str) -> None:
    try:
        snapshot = load_company_analysis_snapshot(query)
        snapshot["cached_at"] = _now_iso()
        success = bool(snapshot.get("ok"))
        with _CACHE_LOCK:
            if success or cache_key not in _CACHE_BY_QUERY:
                _CACHE_BY_QUERY[cache_key] = deepcopy(snapshot)
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "success" if success else "failed"
                job["completed_at"] = _now_iso()
                job["error"] = None if success else _snapshot_error(snapshot)
                job["sections"] = {
                    section: ("success" if success else "failed") for section in _REFRESH_SECTIONS
                }
            if _ACTIVE_REFRESH_BY_QUERY.get(cache_key) == refresh_id:
                _ACTIVE_REFRESH_BY_QUERY.pop(cache_key, None)
    except Exception as exc:
        with _CACHE_LOCK:
            job = _REFRESH_JOBS.get(refresh_id)
            if job:
                job["status"] = "failed"
                job["completed_at"] = _now_iso()
                job["error"] = str(exc)
                job["sections"] = {section: "failed" for section in _REFRESH_SECTIONS}
            if _ACTIVE_REFRESH_BY_QUERY.get(cache_key) == refresh_id:
                _ACTIVE_REFRESH_BY_QUERY.pop(cache_key, None)


def load_company_analysis_snapshot(query: str = DEFAULT_COMPANY_QUERY) -> Dict[str, Any]:
    """Return a JSON-serialisable company-analysis snapshot."""

    normalized_query = _normalize_query(query)
    try:
        return asyncio.run(_load_company_analysis_snapshot(normalized_query))
    except Exception as exc:
        return _error_snapshot(normalized_query, str(exc))


async def _load_company_analysis_snapshot(query: str) -> Dict[str, Any]:
    server = _mx_server_config()
    if not server:
        return _missing_server_snapshot(query)

    try:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        return _dependency_gap_snapshot(query, exc)

    headers = _resolve_headers(server.get("headers") or {})
    headers.setdefault("mcp-protocol-version", MCP_PROTOCOL_VERSION)
    url = str(server.get("url") or "").strip()
    if not url:
        return _missing_server_snapshot(query, "妙想 MCP Server 缺少 HTTP URL 配置。")

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
                profile_payload = await _call_json(
                    session,
                    "mx_stocks_screener",
                    PROFILE_QUERY_TEMPLATE.format(query=query),
                )
                current_payload = await _call_json(
                    session,
                    "mx_ashare_finance_data",
                    CURRENT_QUERY_TEMPLATE.format(query=query),
                )

                profile = _parse_profile(profile_payload, query)
                current = _parse_current_payload(current_payload, profile)
                quote = _merge_quote(profile, current)
                resolved_name = quote.get("name") or query
                finance_query = _security_query_key(query, quote)
                financial_payload = await _call_json(
                    session,
                    "mx_ashare_finance_data",
                    FINANCIAL_QUERY_TEMPLATE.format(query=finance_query),
                )
                financials = _parse_financials(financial_payload, quote)
                if not _has_financial_trend(financials):
                    fallback_payload = await _call_json(
                        session,
                        "mx_ashare_finance_data",
                        FINANCIAL_FALLBACK_QUERY_TEMPLATE.format(query=finance_query),
                    )
                    fallback_financials = _parse_financials(fallback_payload, quote)
                    if _has_financial_trend(fallback_financials):
                        financials = fallback_financials
                peer_query = _peer_query(resolved_name, quote.get("industry"))

                peers_payload = await _call_json(session, "mx_stocks_screener", peer_query)
                news_payload = await _call_json(
                    session,
                    "mx_finance_search_news",
                    NEWS_QUERY_TEMPLATE.format(query=resolved_name),
                )
                risk_payload = await _call_json(
                    session,
                    "mx_finance_search_news",
                    RISK_QUERY_TEMPLATE.format(query=resolved_name),
                )

    peers = _parse_peers(peers_payload, quote)
    research = _merge_research(_parse_research(news_payload), _parse_research(risk_payload))
    valuation = _build_valuation(quote, current, peers)
    capital = _build_capital(quote)
    rating = _build_rating(quote, financials, valuation, research)
    gaps = _build_gaps(quote, financials, peers, research)
    summary = _build_summary(quote, financials, rating)
    as_of = _latest_date([quote.get("trade_date"), current.get("as_of"), _articles_as_of(research)])
    ok = bool(quote.get("name") or financials.get("quarters") or research.get("articles"))

    return {
        "ok": ok,
        "source": MX_SERVER_NAME,
        "status": "partial" if gaps else "ok",
        "query": query,
        "generated_at": _now_iso(),
        "as_of": as_of,
        "resolved": {
            "name": quote.get("name") or query,
            "code": quote.get("code"),
            "exchange": quote.get("exchange"),
            "industry": quote.get("industry"),
            "business": quote.get("business"),
            "concepts": quote.get("concepts") or [],
        },
        "quote": quote,
        "core_metrics": _build_core_metrics(quote, financials),
        "financial_trend": financials.get("trend"),
        "profitability": financials.get("profitability"),
        "cash_flow": financials.get("cash_flow"),
        "operating_metrics": financials.get("operating_metrics"),
        "valuation": valuation,
        "capital": capital,
        "peers": peers,
        "research": research,
        "rating": rating,
        "summary": summary,
        "gaps": gaps,
        "methodology": {
            "title": "公司分析数据口径",
            "description": (
                "行情、估值、季度财务、同行比较与研报摘要均来自妙想 MCP。"
                "综合评价由页面聚合逻辑根据结构化指标和研报摘要生成，不构成投资建议。"
            ),
        },
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


def _parse_profile(payload: Dict[str, Any], query: str) -> Dict[str, Any]:
    row = _best_profile_row(_screener_rows(payload), query)
    if not row:
        return {}

    def find(*labels: str) -> Any:
        return _find_value(row, *labels)

    code = str(find("代码") or "").strip()
    name = str(find("名称") or find("股票简称") or "").strip()
    industry = str(find("申万行业分类") or find("东财行业总分类") or "").strip()
    concepts = _split_tags(find("概念"))[:8]
    business = _trim_products(find("主营产品"), concepts)
    trade_date = _extract_date(" ".join(row.keys()))

    return {
        "name": name,
        "code": code,
        "exchange": _infer_exchange(code),
        "trade_date": trade_date,
        "price": _parse_number(find("最新价")),
        "change_percent": _parse_percent(find("涨跌幅")),
        "change_amount": _parse_number(find("涨跌额")),
        "market_cap_yi": _parse_money_yi(find("总市值")),
        "float_market_cap_yi": _parse_money_yi(find("流通市值")),
        "pe_ttm": _parse_number(find("市盈率(TTM)", "市盈率TTM")),
        "pb": _parse_number(find("市净率PB", "市净率")),
        "gross_margin_percent": _parse_percent(find("销售毛利率", "毛利率")),
        "roe_percent": _parse_percent(find("净资产收益率ROE", "净资产收益率")),
        "turnover_yi": _parse_money_yi(find("成交额")),
        "turnover_rate_percent": _parse_percent(find("换手率")),
        "volume_ratio": _parse_number(find("量比")),
        "high_price": _parse_number(find("最高价")),
        "low_price": _parse_number(find("最低价")),
        "industry": industry,
        "business": business,
        "concepts": concepts,
    }


def _parse_current_payload(payload: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return {}

    current: Dict[str, Any] = {"price_series": [], "pb_series": []}
    wanted_code = str(profile.get("code") or "")
    wanted_name = str(profile.get("name") or "")
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        items = table.get("items") or []
        if len(columns) < 2:
            continue
        current["as_of"] = current.get("as_of") or _extract_date(" ".join(columns))
        metric_rows = {
            str(row[0]).strip(): row[1:]
            for row in items
            if isinstance(row, list) and row
        }
        security_index = _security_column_index(columns[1:], wanted_code, wanted_name)
        date_columns = columns[1:]
        if security_index is not None:
            for label, values in metric_rows.items():
                value = values[security_index] if security_index < len(values) else None
                if "最新价" in label or "收盘价" in label:
                    current.setdefault("price", _parse_number(value))
                elif "涨跌幅" in label:
                    current.setdefault("change_percent", _parse_percent(value))
                elif "涨跌额" in label:
                    current.setdefault("change_amount", _parse_number(value))
                elif "总市值" in label:
                    current.setdefault("market_cap_yi", _parse_money_yi(value))
                elif "市盈率" in label:
                    current.setdefault("pe_ttm", _parse_number(value))
                elif "市净率" in label:
                    current.setdefault("pb", _parse_number(value))
        price_row = _find_metric_values(metric_rows, "收盘价", "最新价")
        pb_row = _find_metric_values(metric_rows, "市净率")
        if price_row and len(date_columns) >= 2 and _looks_like_date_columns(date_columns):
            current["price_series"] = _series_from_values(date_columns, price_row)
        if pb_row and len(date_columns) >= 2 and _looks_like_date_columns(date_columns):
            current["pb_series"] = _series_from_values(date_columns, pb_row)
    return current


def _parse_financials(payload: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        tables = []

    metric_table: Dict[str, List[Any]] = {}
    periods: List[str] = []
    wanted_code = str(quote.get("code") or "")
    wanted_name = str(quote.get("name") or "")

    for table in sorted(tables, key=lambda table: _financial_table_score(table, wanted_code, wanted_name)):
        columns = [str(column) for column in (table.get("columns") or [])]
        if len(columns) < 2:
            continue
        header = columns[0]
        table_periods = columns[1:]
        rows = {
            str(row[0]).strip(): row[1:]
            for row in (table.get("items") or [])
            if isinstance(row, list) and row
        }
        if rows:
            for key, values in rows.items():
                metric_table.setdefault(key, values)
            if not periods:
                periods = table_periods

    revenue = _metric_series(metric_table, periods, "单季度.营业收入", "营业收入")
    net_profit = _metric_series(metric_table, periods, "单季度.净利润", "归母净利润", "净利润")
    cash_flow = _metric_series(metric_table, periods, "经营活动产生的现金流量净额", "经营活动现金流")
    gross_margin = _metric_series(metric_table, periods, "销售毛利率", "毛利率")
    roe = _metric_series(metric_table, periods, "净资产收益率", "ROE")
    debt_ratio = _metric_series(metric_table, periods, "资产负债率")
    current_ratio = _metric_series(metric_table, periods, "流动比率")
    inventory_turnover = _metric_series(metric_table, periods, "存货周转率")

    latest_period = _latest_series_label(revenue, net_profit, gross_margin, roe)
    latest_revenue = _latest_series_value(revenue)
    latest_profit = _latest_series_value(net_profit)
    latest_gross = _latest_series_value(gross_margin) or quote.get("gross_margin_percent")
    latest_roe = _latest_series_value(roe) or quote.get("roe_percent")

    return {
        "quarters": _series_labels(revenue, net_profit, cash_flow, gross_margin, roe),
        "latest_period": latest_period,
        "latest": {
            "revenue_yi": latest_revenue,
            "net_profit_yi": latest_profit,
            "gross_margin_percent": latest_gross,
            "roe_percent": latest_roe,
            "debt_ratio_percent": _latest_series_value(debt_ratio),
        },
        "trend": {
            "periods": _series_labels(revenue, net_profit),
            "revenue_yi": revenue,
            "net_profit_yi": net_profit,
        },
        "profitability": {
            "periods": _series_labels(gross_margin, roe),
            "gross_margin_percent": gross_margin or _single_point(latest_period, quote.get("gross_margin_percent")),
            "roe_percent": roe or _single_point(latest_period, quote.get("roe_percent")),
        },
        "cash_flow": {
            "periods": _series_labels(cash_flow),
            "operating_cash_flow_yi": cash_flow,
        },
        "operating_metrics": [
            {
                "label": "资产负债率",
                "value": _latest_series_value(debt_ratio),
                "unit": "%",
            },
            {
                "label": "流动比率",
                "value": _latest_series_value(current_ratio),
                "unit": "x",
            },
            {
                "label": "存货周转率",
                "value": _latest_series_value(inventory_turnover),
                "unit": "x",
            },
            {
                "label": "换手率",
                "value": quote.get("turnover_rate_percent"),
                "unit": "%",
            },
        ],
    }


def _security_query_key(fallback: str, quote: Dict[str, Any]) -> str:
    name = str(quote.get("name") or fallback or "").strip()
    code = str(quote.get("code") or "").strip()
    exchange = str(quote.get("exchange") or "").strip()
    if name and code and exchange:
        return f"{name}({code}.{exchange})"
    if code and exchange:
        return f"{code}.{exchange}"
    return name or fallback


def _has_financial_trend(financials: Dict[str, Any]) -> bool:
    trend = financials.get("trend") or {}
    return bool((trend.get("revenue_yi") or []) and (trend.get("net_profit_yi") or []))


def _financial_table_score(table: Dict[str, Any], wanted_code: str, wanted_name: str) -> int:
    columns = [str(column) for column in (table.get("columns") or [])]
    header = columns[0] if columns else str(table.get("sheetName") or "")
    text = f"{header} {table.get('sheetName') or ''}"
    has_hk = "HK" in text
    if wanted_code and wanted_code in text and not has_hk:
        return 0
    if wanted_name and wanted_name in text and not has_hk:
        return 1
    if not has_hk:
        return 2
    if wanted_code and wanted_code in text:
        return 3
    if wanted_name and wanted_name in text:
        return 4
    return 5


def _parse_peers(payload: Dict[str, Any], quote: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _screener_rows(payload)
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    own_code = str(quote.get("code") or "")

    for row in rows:
        code = str(_find_value(row, "代码") or "").strip()
        name = str(_find_value(row, "名称", "股票简称") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "name": name,
                "code": code,
                "is_target": code == own_code,
                "market_cap_yi": _parse_money_yi(_find_value(row, "总市值")),
                "pe_ttm": _parse_number(_find_value(row, "市盈率(TTM)", "市盈率TTM")),
                "pb": _parse_number(_find_value(row, "市净率PB", "市净率")),
                "gross_margin_percent": _parse_percent(_find_value(row, "销售毛利率", "毛利率")),
                "roe_percent": _parse_percent(_find_value(row, "净资产收益率ROE", "净资产收益率")),
                "industry": str(_find_value(row, "申万行业分类", "东财行业总分类") or ""),
            }
        )
        if len(out) >= 8:
            break

    if own_code and not any(peer.get("is_target") for peer in out):
        out.insert(
            0,
            {
                "name": quote.get("name") or "",
                "code": own_code,
                "is_target": True,
                "market_cap_yi": quote.get("market_cap_yi"),
                "pe_ttm": quote.get("pe_ttm"),
                "pb": quote.get("pb"),
                "gross_margin_percent": quote.get("gross_margin_percent"),
                "roe_percent": quote.get("roe_percent"),
                "industry": quote.get("industry") or "",
            },
        )
    return out[:6]


def _parse_research(payload: Dict[str, Any]) -> Dict[str, Any]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list) or not tables:
        return {"articles": [], "highlights": [], "risks": []}

    table = tables[0]
    columns = [str(column) for column in (table.get("columns") or [])]
    idx = {
        "title": _find_col(columns, "标题"),
        "summary": _find_col(columns, "摘要"),
        "published_at": _find_col(columns, "发布时间"),
        "source": _find_col(columns, "来源"),
        "url": _find_col(columns, "跳转链接"),
    }
    articles: List[Dict[str, Any]] = []
    for item in table.get("items") or []:
        if not isinstance(item, list):
            continue
        title = _item_at(item, idx["title"])
        summary = _clean_text(_item_at(item, idx["summary"]))
        if not title and not summary:
            continue
        article = {
            "title": title,
            "summary": _trim_text(summary, 5000),
            "published_at": _item_at(item, idx["published_at"]),
            "source": _item_at(item, idx["source"]),
            "url": _item_at(item, idx["url"]) or None,
        }
        if article not in articles:
            articles.append(article)
        if len(articles) >= 6:
            break

    return {
        "articles": articles,
        "highlights": _extract_research_points(articles, kind="highlight"),
        "risks": _extract_research_points(articles, kind="risk"),
    }


def _merge_research(primary: Dict[str, Any], risk_source: Dict[str, Any]) -> Dict[str, Any]:
    articles: List[Dict[str, Any]] = []
    seen_articles: set[Tuple[str, str]] = set()
    for article in [*(primary.get("articles") or []), *(risk_source.get("articles") or [])]:
        key = (str(article.get("title") or ""), str(article.get("published_at") or ""))
        if key in seen_articles:
            continue
        seen_articles.add(key)
        articles.append(article)
        if len(articles) >= 8:
            break

    risks: List[str] = []
    for item in [*(risk_source.get("risks") or []), *(primary.get("risks") or [])]:
        cleaned = _clean_risk_point(item)
        if not cleaned:
            continue
        existing_index = _matching_risk_index(risks, cleaned)
        if existing_index >= 0:
            if len(cleaned) > len(risks[existing_index]):
                risks[existing_index] = cleaned
            continue
        risks.append(cleaned)
        if len(risks) >= 6:
            break

    return {
        "articles": articles,
        "highlights": primary.get("highlights") or [],
        "risks": risks,
    }


def _clean_risk_point(value: Any) -> str:
    text = _clean_text(value)
    if "风险提示" in text:
        text = text.split("风险提示", 1)[1]
    if any(marker in text for marker in ("投资评级说明", "评级说明", "免责声明", "分析师承诺", "证券市场代表性指数")):
        return ""
    return _trim_text(text.strip(" ：:;；,，。"), 160)


def _matching_risk_index(items: List[str], candidate: str) -> int:
    candidate_key = _risk_key(candidate)
    for index, item in enumerate(items):
        if _risk_key(item) == candidate_key:
            return index
    return -1


def _risk_key(value: str) -> str:
    text = re.sub(r"^\s*\d+\s*[、.．]\s*", "", value)
    text = re.split(r"[:：；;，,。]", text, maxsplit=1)[0]
    return _trim_text(text, 28)


def _merge_quote(profile: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    quote = deepcopy(profile)
    for key in [
        "price",
        "change_percent",
        "change_amount",
        "market_cap_yi",
        "pe_ttm",
        "pb",
    ]:
        if quote.get(key) is None and current.get(key) is not None:
            quote[key] = current[key]
    quote.setdefault("concepts", [])
    return quote


def _build_core_metrics(quote: Dict[str, Any], financials: Dict[str, Any]) -> List[Dict[str, Any]]:
    latest = financials.get("latest") or {}
    return [
        {
            "label": "营业收入",
            "value": latest.get("revenue_yi"),
            "unit": "亿元",
            "caption": financials.get("latest_period") or "最近报告期",
            "tone": "neutral",
        },
        {
            "label": "净利润",
            "value": latest.get("net_profit_yi"),
            "unit": "亿元",
            "caption": financials.get("latest_period") or "最近报告期",
            "tone": "good" if (latest.get("net_profit_yi") or 0) >= 0 else "bad",
        },
        {
            "label": "毛利率",
            "value": latest.get("gross_margin_percent"),
            "unit": "%",
            "caption": "盈利质量",
            "tone": "good" if (latest.get("gross_margin_percent") or 0) >= 20 else "neutral",
        },
        {
            "label": "ROE",
            "value": latest.get("roe_percent") or quote.get("roe_percent"),
            "unit": "%",
            "caption": "资本回报",
            "tone": "good" if ((latest.get("roe_percent") or quote.get("roe_percent") or 0) >= 5) else "neutral",
        },
    ]


def _build_valuation(
    quote: Dict[str, Any],
    current: Dict[str, Any],
    peers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    price = quote.get("price")
    price_points = [point["value"] for point in current.get("price_series") or [] if point.get("value") is not None]
    for key in ("low_price", "high_price"):
        if quote.get(key) is not None:
            price_points.append(quote[key])
    low = min(price_points) if price_points else None
    high = max(price_points) if price_points else None
    percentile = None
    if price is not None and low is not None and high is not None and high > low:
        percentile = max(0.0, min(100.0, (price - low) / (high - low) * 100))

    peer_pes = [peer["pe_ttm"] for peer in peers if peer.get("pe_ttm") and not peer.get("is_target")]
    peer_median_pe = _median(peer_pes)
    signal = "中性"
    if quote.get("pe_ttm") and peer_median_pe:
        if quote["pe_ttm"] <= peer_median_pe * 0.85:
            signal = "低于同行中位"
        elif quote["pe_ttm"] >= peer_median_pe * 1.15:
            signal = "高于同行中位"

    return {
        "price_range": {
            "low": low,
            "high": high,
            "current": price,
            "percentile": round(percentile, 1) if percentile is not None else None,
            "label": "近期价格区间",
        },
        "pe_ttm": quote.get("pe_ttm"),
        "pb": quote.get("pb"),
        "peer_median_pe": peer_median_pe,
        "signal": signal,
    }


def _build_capital(quote: Dict[str, Any]) -> Dict[str, Any]:
    change = quote.get("change_percent")
    turnover = quote.get("turnover_yi")
    activity = "正常"
    if turnover and quote.get("market_cap_yi"):
        ratio = turnover / quote["market_cap_yi"] * 100
        if ratio >= 2:
            activity = "活跃"
        elif ratio <= 0.3:
            activity = "偏冷"
    else:
        ratio = None

    return {
        "turnover_yi": turnover,
        "turnover_rate_percent": quote.get("turnover_rate_percent"),
        "volume_ratio": quote.get("volume_ratio"),
        "activity_label": activity,
        "turnover_to_market_cap_percent": round(ratio, 2) if ratio is not None else None,
        "momentum_label": _momentum_label(change),
    }


def _build_rating(
    quote: Dict[str, Any],
    financials: Dict[str, Any],
    valuation: Dict[str, Any],
    research: Dict[str, Any],
) -> Dict[str, Any]:
    latest = financials.get("latest") or {}
    score = 70
    if (latest.get("gross_margin_percent") or quote.get("gross_margin_percent") or 0) >= 20:
        score += 5
    if (latest.get("roe_percent") or quote.get("roe_percent") or 0) >= 5:
        score += 5
    if (latest.get("net_profit_yi") or 0) > 0:
        score += 4
    if valuation.get("signal") == "低于同行中位":
        score += 4
    elif valuation.get("signal") == "高于同行中位":
        score -= 4
    if len(research.get("risks") or []) >= 3:
        score -= 4
    grade = "A-" if score >= 84 else "B+" if score >= 76 else "B" if score >= 68 else "C+"
    tags = []
    if quote.get("industry"):
        tags.append(str(quote["industry"]).split("-")[0])
    if (latest.get("gross_margin_percent") or quote.get("gross_margin_percent") or 0) >= 20:
        tags.append("盈利韧性")
    if valuation.get("signal") != "中性":
        tags.append(valuation["signal"])
    if quote.get("concepts"):
        tags.extend([str(tag) for tag in quote["concepts"][:2]])

    return {
        "grade": grade,
        "score": score,
        "summary": _rating_summary(quote, latest, valuation, research),
        "tags": tags[:5],
    }


def _build_summary(quote: Dict[str, Any], financials: Dict[str, Any], rating: Dict[str, Any]) -> Dict[str, Any]:
    name = quote.get("name") or "目标公司"
    latest = financials.get("latest") or {}
    details: List[str] = []
    if latest.get("revenue_yi") is not None and latest.get("net_profit_yi") is not None:
        details.append(
            f"最近报告期收入约{latest['revenue_yi']:.1f}亿元，净利润约{latest['net_profit_yi']:.1f}亿元。"
        )
    if quote.get("pe_ttm") is not None:
        details.append(f"当前PE(TTM)约{quote['pe_ttm']:.1f}倍，综合评分为{rating['grade']}。")
    return {
        "headline": f"{name}基本面画像已生成，重点关注盈利质量、估值位置和研报风险。",
        "details": details,
    }


def _build_gaps(
    quote: Dict[str, Any],
    financials: Dict[str, Any],
    peers: List[Dict[str, Any]],
    research: Dict[str, Any],
) -> List[Dict[str, str]]:
    gaps: List[Dict[str, str]] = []
    if not quote.get("name"):
        gaps.append(_gap("profile", "公司画像缺失", "妙想 MCP 未返回匹配的 A 股公司画像。", "warning"))
    if not (financials.get("trend") or {}).get("revenue_yi"):
        gaps.append(_gap("financials", "季度财务缺失", "妙想 MCP 未返回最近季度收入/利润序列。", "warning"))
    if not peers:
        gaps.append(_gap("peers", "同行比较缺失", "妙想 MCP 未返回可比公司列表。", "warning"))
    if not research.get("articles"):
        gaps.append(_gap("research", "研报摘要缺失", "妙想 MCP 未返回最近研报或新闻摘要。", "info"))
    return gaps


def _screener_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return []
    rows: List[Dict[str, Any]] = []
    for table in tables:
        columns = [str(column) for column in (table.get("columns") or [])]
        if not columns:
            continue
        for item in table.get("items") or []:
            if not isinstance(item, list):
                continue
            rows.append({columns[index]: item[index] for index in range(min(len(columns), len(item)))})
    return rows


def _best_profile_row(rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    if not rows:
        return {}
    cleaned_query = query.strip().lower()
    digits = re.sub(r"\D", "", cleaned_query)

    def score(row: Dict[str, Any]) -> int:
        code = str(_find_value(row, "代码") or "").lower()
        name = str(_find_value(row, "名称", "股票简称") or "").lower()
        value = 0
        if digits and code == digits:
            value += 100
        if cleaned_query and cleaned_query == name:
            value += 80
        if cleaned_query and (cleaned_query in name or name in cleaned_query):
            value += 40
        if "a股" in str(_find_value(row, "证券类型") or "").lower():
            value += 10
        return value

    return sorted(rows, key=score, reverse=True)[0]


def _find_value(row: Dict[str, Any], *labels: str) -> Any:
    for label in labels:
        for key, value in row.items():
            normalized = str(key).replace(" ", "").lower()
            target = label.replace(" ", "").lower()
            if target in normalized:
                return value
    return None


def _peer_query(name: str, industry: Any) -> str:
    industry_text = str(industry or "").strip()
    if industry_text:
        primary = industry_text.split("-")[0]
        return (
            f"筛选申万行业分类包含{primary}或与{name}主营业务相近的A股公司，字段包括代码、名称、"
            "总市值、市盈率(TTM)、市净率PB、销售毛利率、净资产收益率ROE、申万行业分类，"
            "按总市值从高到低返回前12只，只返回表格。"
        )
    return (
        f"筛选与{name}主营业务相近的A股上市公司，字段包括代码、名称、总市值、市盈率(TTM)、"
        "市净率PB、销售毛利率、净资产收益率ROE、申万行业分类，返回前12只，只返回表格。"
    )


def _metric_series(metric_table: Dict[str, List[Any]], periods: List[str], *labels: str) -> List[Dict[str, Any]]:
    values = _find_metric_values(metric_table, *labels)
    if not values:
        return []
    series = []
    for index, period in enumerate(periods):
        if index >= len(values):
            continue
        value = _parse_money_or_percent(values[index])
        if value is None:
            continue
        series.append({"period": _short_period(period), "value": value})
    return list(reversed(series[-4:]))


def _find_metric_values(metric_table: Dict[str, List[Any]], *labels: str) -> List[Any]:
    for label in labels:
        target = label.replace(" ", "").lower()
        for key, values in metric_table.items():
            normalized = str(key).replace(" ", "").lower()
            if target in normalized:
                return values
    return []


def _series_from_values(labels: List[str], values: List[Any]) -> List[Dict[str, Any]]:
    series = []
    for index, label in enumerate(labels):
        if index >= len(values):
            continue
        value = _parse_number(values[index])
        if value is None:
            continue
        series.append({"period": _short_date(label), "value": value})
    return list(reversed(series[-8:]))


def _single_point(period: Optional[str], value: Any) -> List[Dict[str, Any]]:
    parsed = _parse_number(value)
    if parsed is None:
        return []
    return [{"period": period or "最新", "value": parsed}]


def _series_labels(*series_list: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for series in series_list:
        for point in series:
            label = str(point.get("period") or "")
            if label and label not in labels:
                labels.append(label)
    return labels


def _latest_series_label(*series_list: List[Dict[str, Any]]) -> Optional[str]:
    for series in series_list:
        if series:
            return str(series[-1].get("period") or "")
    return None


def _latest_series_value(series: List[Dict[str, Any]]) -> Optional[float]:
    if not series:
        return None
    value = series[-1].get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _security_column_index(columns: List[str], code: str, name: str) -> Optional[int]:
    for index, column in enumerate(columns):
        if code and code in column and "HK" not in column:
            return index
        if name and name in column and "HK" not in column:
            return index
    for index, column in enumerate(columns):
        if "HK" not in column:
            return index
    return 0 if columns else None


def _looks_like_date_columns(columns: List[str]) -> bool:
    return sum(1 for column in columns if _extract_date(column)) >= 2


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


def _normalize_query(query: str) -> str:
    value = str(query or "").strip()
    value = re.sub(r"\s+", "", value)
    return value[:80] or DEFAULT_COMPANY_QUERY


def _cache_key(query: str) -> str:
    return f"{get_hermes_home()}::{query.lower()}"


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


def _parse_money_or_percent(value: Any) -> Optional[float]:
    text = str(value or "")
    if "亿" in text or "万" in text or "元" in text:
        parsed = _parse_money_yi(value)
        return parsed if parsed != 0.0 or _number_in_text(value) == 0 else None
    return _parse_percent(value) if "%" in text else _parse_number(value)


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
    if unit in {"元", "港元"}:
        return round(number / 100000000, 4)
    return round(number / 100000000 if abs(number) > 1000000 else number, 4)


def _parse_percent(value: Any) -> Optional[float]:
    parsed = _number_in_text(value)
    return parsed


def _parse_number(value: Any) -> Optional[float]:
    return _number_in_text(value)


def _number_in_text(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _median(values: List[float]) -> Optional[float]:
    clean = sorted(value for value in values if isinstance(value, (int, float)) and value > 0)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 2)
    return round((clean[mid - 1] + clean[mid]) / 2, 2)


def _extract_research_points(articles: List[Dict[str, Any]], *, kind: str) -> List[str]:
    points: List[str] = []
    risk_markers = ("风险", "不及预期", "竞争", "价格", "波动", "下滑", "政策", "落地", "原材料")
    highlight_markers = ("增长", "领先", "龙头", "盈利", "储能", "海外", "技术", "买入", "目标价", "提升")

    for article in articles:
        summary = _clean_text(article.get("summary") or "")
        if kind == "risk":
            risk_section = _risk_section(summary)
            for sentence in _sentences(risk_section):
                if sentence and sentence not in points:
                    points.append(_trim_text(sentence, 120))
                if len(points) >= 6:
                    return points
        markers = risk_markers if kind == "risk" else highlight_markers
        for sentence in _sentences(summary):
            if any(marker in sentence for marker in markers):
                cleaned = _trim_text(sentence, 120 if kind == "risk" else 96)
                if cleaned and cleaned not in points:
                    points.append(cleaned)
            if len(points) >= (6 if kind == "risk" else 5):
                return points
    return points


def _risk_section(text: str) -> str:
    markers = ("风险提示", "主要风险", "风险因素", "风险：")
    for marker in markers:
        if marker in text:
            section = text.split(marker, 1)[1]
            for stop in ("投资评级说明", "评级说明", "免责声明", "分析师承诺", "证券市场代表性指数"):
                if stop in section:
                    section = section.split(stop, 1)[0]
            return section
    return ""


def _sentences(text: str) -> List[str]:
    return [part.strip(" ：:;；,，。") for part in re.split(r"[。；;\n]|(?<=；)|(?<=;)|(?<=。)", text) if len(part.strip()) >= 6]


def _rating_summary(
    quote: Dict[str, Any],
    latest: Dict[str, Any],
    valuation: Dict[str, Any],
    research: Dict[str, Any],
) -> str:
    name = quote.get("name") or "目标公司"
    parts = [f"{name}处于{quote.get('industry') or '所属行业'}。"]
    if latest.get("gross_margin_percent") is not None:
        parts.append(f"最近报告期毛利率约{latest['gross_margin_percent']:.1f}%。")
    if quote.get("pe_ttm") is not None:
        parts.append(f"PE(TTM)约{quote['pe_ttm']:.1f}倍，{valuation.get('signal') or '估值中性'}。")
    if research.get("risks"):
        parts.append("需跟踪研报中提到的需求、价格和竞争风险。")
    return "".join(parts)


def _momentum_label(change: Any) -> str:
    if change is None:
        return "等待行情"
    if change >= 3:
        return "强势上行"
    if change <= -3:
        return "承压回落"
    return "震荡"


def _trim_products(value: Any, concepts: List[str]) -> str:
    text = str(value or "")
    products = re.findall(r"【([^】]{2,40})】", text)
    if products:
        return " / ".join(products[:4])
    if concepts:
        return " / ".join(concepts[:4])
    return _trim_text(_clean_text(text), 80)


def _split_tags(value: Any) -> List[str]:
    return [tag.strip() for tag in re.split(r"[,，、]", str(value or "")) if tag.strip()]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _trim_text(value: Any, max_len: int) -> str:
    text = _clean_text(value)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _short_period(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("年报", "A").replace("一季报", "Q1").replace("中报", "Q2").replace("三季报", "Q3")
    text = text.replace("2026", "26").replace("2025", "25").replace("2024", "24")
    return text


def _short_date(value: Any) -> str:
    text = str(value or "")
    date = _extract_date(text)
    if not date:
        return _trim_text(text, 10)
    return date[5:]


def _extract_date(text: str) -> Optional[str]:
    match = _DATE_RE.search(str(text or ""))
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _latest_date(values: Iterable[Optional[str]]) -> Optional[str]:
    dates = [value for value in values if value]
    return max(dates) if dates else None


def _articles_as_of(research: Dict[str, Any]) -> Optional[str]:
    for article in research.get("articles") or []:
        date = _extract_date(article.get("published_at") or "")
        if date:
            return date
    return None


def _infer_exchange(code: str) -> Optional[str]:
    if not code:
        return None
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    if code.startswith(("8", "4")):
        return "BJ"
    return None


def _gap(key: str, title: str, message: str, severity: str) -> Dict[str, str]:
    return {"key": key, "title": title, "message": message, "severity": severity}


def _snapshot_error(snapshot: Dict[str, Any]) -> str:
    gaps = snapshot.get("gaps") or []
    if gaps:
        return str(gaps[0].get("message") or gaps[0].get("title") or "Refresh failed.")
    return "Refresh failed."


def _missing_server_snapshot(query: str, message: str = "未找到已启用的 mx-ds-mcp 配置。") -> Dict[str, Any]:
    return _empty_snapshot(
        query,
        status="missing-server",
        headline="妙想 MCP 尚未可用",
        gaps=[_gap("mcp", "妙想 MCP 未配置", message, "error")],
    )


def _dependency_gap_snapshot(query: str, exc: Exception) -> Dict[str, Any]:
    message = f"MCP HTTP 客户端依赖不可用：{exc}"
    return _empty_snapshot(
        query,
        status="dependency-missing",
        headline="MCP 依赖缺失",
        gaps=[_gap("mcp-dependency", "MCP 依赖缺失", message, "error")],
    )


def _error_snapshot(query: str, message: str) -> Dict[str, Any]:
    return _empty_snapshot(
        query,
        status="error",
        headline="公司分析数据暂不可用",
        gaps=[_gap("snapshot", "公司分析快照获取失败", message, "error")],
    )


def _loading_snapshot(query: str) -> Dict[str, Any]:
    return _empty_snapshot(
        query,
        status="refreshing",
        headline="公司分析数据正在刷新",
        gaps=[],
        details=["首次加载会在后台连接妙想 MCP，页面会在快照完成后自动更新。"],
    )


def _empty_snapshot(
    query: str,
    *,
    status: str,
    headline: str,
    gaps: List[Dict[str, str]],
    details: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "source": MX_SERVER_NAME,
        "status": status,
        "query": query,
        "generated_at": _now_iso(),
        "cached_at": None,
        "as_of": None,
        "resolved": {
            "name": query,
            "code": None,
            "exchange": None,
            "industry": None,
            "business": None,
            "concepts": [],
        },
        "quote": {
            "name": query,
            "code": None,
            "exchange": None,
            "trade_date": None,
            "price": None,
            "change_percent": None,
            "change_amount": None,
            "market_cap_yi": None,
            "float_market_cap_yi": None,
            "pe_ttm": None,
            "pb": None,
            "gross_margin_percent": None,
            "roe_percent": None,
            "turnover_yi": None,
            "turnover_rate_percent": None,
            "volume_ratio": None,
            "high_price": None,
            "low_price": None,
            "industry": None,
            "business": None,
            "concepts": [],
        },
        "core_metrics": [],
        "financial_trend": {"periods": [], "revenue_yi": [], "net_profit_yi": []},
        "profitability": {"periods": [], "gross_margin_percent": [], "roe_percent": []},
        "cash_flow": {"periods": [], "operating_cash_flow_yi": []},
        "operating_metrics": [],
        "valuation": {
            "price_range": {
                "low": None,
                "high": None,
                "current": None,
                "percentile": None,
                "label": "近期价格区间",
            },
            "pe_ttm": None,
            "pb": None,
            "peer_median_pe": None,
            "signal": "等待数据",
        },
        "capital": {
            "turnover_yi": None,
            "turnover_rate_percent": None,
            "volume_ratio": None,
            "activity_label": "等待数据",
            "turnover_to_market_cap_percent": None,
            "momentum_label": "等待行情",
        },
        "peers": [],
        "research": {"articles": [], "highlights": [], "risks": []},
        "rating": {"grade": "--", "score": None, "summary": "", "tags": []},
        "summary": {"headline": headline, "details": details or []},
        "gaps": gaps,
        "methodology": {
            "title": "公司分析数据口径",
            "description": "行情、估值、季度财务、同行比较与研报摘要均来自妙想 MCP。",
        },
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
