"""Allowlisted service actions for trusted application runtimes."""

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


__all__ = [
    "ServiceActionRegistry",
    "ServiceContext",
]
