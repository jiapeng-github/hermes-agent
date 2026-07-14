from __future__ import annotations

from pathlib import Path

from hermes_cli.apps.catalog import (
    COMPANY_ANALYSIS_APP_ID,
    COMPANY_ANALYSIS_SERVICE_HANDLERS,
    INDUSTRY_MONITOR_APP_ID,
    INDUSTRY_MONITOR_SERVICE_HANDLERS,
    WATCHLIST_APP_ID,
    WATCHLIST_SERVICE_HANDLERS,
)
from hermes_cli.apps.runtime.service import (
    builtin_finance_service_registry,
    watchlist_service_registry,
)


def _services(tmp_path: Path):
    return watchlist_service_registry(
        app_id=WATCHLIST_APP_ID,
        app_data=tmp_path / "app-data",
        inherited_handlers=WATCHLIST_SERVICE_HANDLERS,
    )


def _builtin_services(tmp_path: Path, app_id: str, handlers: tuple[str, ...]):
    return builtin_finance_service_registry(
        app_id=app_id,
        app_data=tmp_path / "app-data" / app_id,
        inherited_handlers=handlers,
    )


def test_industry_app_delegates_snapshot_and_refresh(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple] = []
    snapshot = {"ok": True, "status": "ready", "indices": []}
    monkeypatch.setattr(
        "hermes_cli.finance_industry_monitor.get_industry_monitor_snapshot_cached",
        lambda *, auto_refresh=True: calls.append(("snapshot", auto_refresh)) or snapshot,
    )
    monkeypatch.setattr(
        "hermes_cli.finance_industry_monitor.start_industry_monitor_refresh",
        lambda *, force=False: calls.append(("refresh", force))
        or {"refresh_id": "industry-1", "status": "running", "sections": {}},
    )
    services = _builtin_services(
        tmp_path,
        INDUSTRY_MONITOR_APP_ID,
        INDUSTRY_MONITOR_SERVICE_HANDLERS,
    )

    assert services.invoke("finance.industry.snapshot", {"auto_refresh": False}) == snapshot
    assert services.invoke("finance.industry.refresh", {})["refresh_id"] == "industry-1"
    assert calls == [("snapshot", False), ("refresh", True)]


def test_company_app_delegates_cached_analysis_and_refresh(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple] = []
    snapshot = {"ok": True, "status": "ready", "query": "300750"}
    monkeypatch.setattr(
        "hermes_cli.finance_company_analysis.get_company_analysis_snapshot_cached",
        lambda query, *, auto_refresh=True: calls.append(("analysis", query, auto_refresh))
        or snapshot,
    )
    monkeypatch.setattr(
        "hermes_cli.finance_company_analysis.start_company_analysis_refresh",
        lambda query, *, force=False: calls.append(("refresh", query, force))
        or {"refresh_id": "company-1", "query": query, "status": "running", "sections": {}},
    )
    services = _builtin_services(
        tmp_path,
        COMPANY_ANALYSIS_APP_ID,
        COMPANY_ANALYSIS_SERVICE_HANDLERS,
    )

    assert services.invoke(
        "finance.company.analysis",
        {"query": "300750", "auto_refresh": False},
    ) == snapshot
    assert services.invoke("finance.company.refresh", {"query": "300750"})[
        "refresh_id"
    ] == "company-1"
    assert calls == [
        ("analysis", "300750", False),
        ("refresh", "300750", True),
    ]


def test_app_snapshot_and_legacy_page_share_every_gate4_metric(monkeypatch, tmp_path: Path) -> None:
    snapshot = {
        "ok": True,
        "source": "mx-ds-mcp",
        "status": "ready",
        "as_of": "2026-07-13",
        "indices": [
            {"name": "上证指数", "value": 3512.68, "change_percent": 0.82},
            {"name": "创业板指", "value": 2386.91, "change_percent": 1.68},
        ],
        "items": [
            {
                "code": "300750",
                "name": "宁德时代",
                "price": 218.5,
                "change_percent": 3.45,
                "main_net_flow_yi": 5.6,
                "sector": "新能源",
            }
        ],
        "sectors": [
            {"name": "新能源", "stock_count": 1, "avg_change_percent": 3.45, "main_net_flow_yi": 5.6}
        ],
        "summary": {
            "total": 1,
            "priced": 1,
            "rising": 1,
            "falling": 0,
            "flat": 0,
            "main_net_flow_yi": 5.6,
            "strongest_sector": {"name": "新能源", "avg_change_percent": 3.45},
            "weakest_sector": {"name": "新能源", "avg_change_percent": 3.45},
            "headline": "自选股上涨",
        },
        "gaps": [],
    }
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.get_watchlist_snapshot_cached",
        lambda *, auto_refresh=True: snapshot,
    )

    from hermes_cli.finance_watchlist import get_watchlist_snapshot_cached

    legacy = get_watchlist_snapshot_cached(auto_refresh=False)
    application = _services(tmp_path).invoke(
        "finance.watchlist.snapshot",
        {"auto_refresh": False},
    )

    assert application == legacy
    assert application["indices"] == legacy["indices"]
    assert application["items"] == legacy["items"]
    assert application["sectors"] == legacy["sectors"]
    assert application["summary"] == legacy["summary"]
    assert application["gaps"] == legacy["gaps"]


def test_app_mutations_detail_and_analysis_delegate_to_existing_domain(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.start_watchlist_refresh",
        lambda *, force=False: calls.append(("refresh", force)) or {"refresh_id": "r1", "status": "running", "sections": {}},
    )
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.add_watchlist_stock",
        lambda query: calls.append(("add", query)) or {"ok": True, "added": True},
    )
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.remove_watchlist_stock",
        lambda code: calls.append(("remove", code)) or {"ok": True, "removed": True},
    )
    monkeypatch.setattr(
        "hermes_cli.finance_watchlist.get_watchlist_stock_detail",
        lambda code, *, force=False: calls.append(("detail", code, force))
        or {"ok": True, "status": "ready", "stock": {}, "kline": [], "technicals": {}, "summary": "ok"},
    )
    monkeypatch.setattr(
        "hermes_cli.finance_company_analysis.get_company_analysis_snapshot_cached",
        lambda query: calls.append(("analysis", query)) or {"ok": True, "query": query},
    )
    services = _services(tmp_path)

    services.invoke("finance.watchlist.refresh", {})
    services.invoke("finance.watchlist.add", {"query": "宁德时代"})
    services.invoke("finance.watchlist.remove", {"code": "300750"})
    services.invoke("finance.watchlist.detail", {"code": "300750", "force": True})
    services.invoke("finance.company.analysis", {"query": "300750"})

    assert calls == [
        ("refresh", True),
        ("add", "宁德时代"),
        ("remove", "300750"),
        ("detail", "300750", True),
        ("analysis", "300750"),
    ]
