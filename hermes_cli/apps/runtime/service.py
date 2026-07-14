"""Allowlisted first-party service actions for built-in applications."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ServiceHandler = Callable[[dict[str, Any], "ServiceContext"], Any]


@dataclass(frozen=True, slots=True)
class ServiceContext:
    app_id: str
    app_data: Path


class ServiceActionRegistry:
    """Expose only the exact handlers inherited by one built-in lineage."""

    def __init__(
        self,
        handlers: Mapping[str, ServiceHandler],
        *,
        context: ServiceContext,
    ):
        self._handlers = dict(handlers)
        self.context = context

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def invoke(self, handler: str, input_data: dict[str, Any]) -> Any:
        selected = self._handlers.get(handler)
        if selected is None:
            raise PermissionError("service handler is not inherited by this application")
        return selected(input_data, self.context)


def builtin_finance_service_registry(
    *,
    app_id: str,
    app_data: Path,
    inherited_handlers: tuple[str, ...],
) -> ServiceActionRegistry:
    available: dict[str, ServiceHandler] = {
        "finance.industry.snapshot": _industry_snapshot,
        "finance.industry.refresh": _industry_refresh,
        "finance.company.analysis": _company_analysis,
        "finance.company.refresh": _company_refresh,
        "finance.watchlist.snapshot": _watchlist_snapshot,
        "finance.watchlist.refresh": _watchlist_refresh,
        "finance.watchlist.add": _watchlist_add,
        "finance.watchlist.remove": _watchlist_remove,
        "finance.watchlist.detail": _watchlist_detail,
    }
    missing = sorted(set(inherited_handlers) - set(available))
    if missing:
        raise RuntimeError(f"unknown built-in service handler: {missing[0]}")
    return ServiceActionRegistry(
        {name: available[name] for name in inherited_handlers},
        context=ServiceContext(app_id=app_id, app_data=app_data),
    )


def watchlist_service_registry(
    *,
    app_id: str,
    app_data: Path,
    inherited_handlers: tuple[str, ...],
) -> ServiceActionRegistry:
    """Compatibility alias retained for Gate 4 callers and plugins."""

    return builtin_finance_service_registry(
        app_id=app_id,
        app_data=app_data,
        inherited_handlers=inherited_handlers,
    )


def _industry_snapshot(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_industry_monitor import get_industry_monitor_snapshot_cached

    return get_industry_monitor_snapshot_cached(
        auto_refresh=input_data.get("auto_refresh", True)
    )


def _industry_refresh(_input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_industry_monitor import start_industry_monitor_refresh

    return start_industry_monitor_refresh(force=True)


def _watchlist_snapshot(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_watchlist import get_watchlist_snapshot_cached

    return get_watchlist_snapshot_cached(auto_refresh=input_data.get("auto_refresh", True))


def _watchlist_refresh(_input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_watchlist import start_watchlist_refresh

    return start_watchlist_refresh(force=True)


def _watchlist_add(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_watchlist import add_watchlist_stock

    return add_watchlist_stock(input_data["query"])


def _watchlist_remove(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_watchlist import remove_watchlist_stock

    return remove_watchlist_stock(input_data["code"])


def _watchlist_detail(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_watchlist import get_watchlist_stock_detail

    return get_watchlist_stock_detail(
        input_data["code"],
        force=input_data.get("force", False),
    )


def _company_analysis(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_company_analysis import get_company_analysis_snapshot_cached

    options = (
        {"auto_refresh": input_data["auto_refresh"]}
        if "auto_refresh" in input_data
        else {}
    )
    return get_company_analysis_snapshot_cached(input_data["query"], **options)


def _company_refresh(input_data: dict[str, Any], _context: ServiceContext) -> Any:
    from hermes_cli.finance_company_analysis import start_company_analysis_refresh

    return start_company_analysis_refresh(input_data["query"], force=True)


__all__ = [
    "ServiceActionRegistry",
    "ServiceContext",
    "builtin_finance_service_registry",
    "watchlist_service_registry",
]
