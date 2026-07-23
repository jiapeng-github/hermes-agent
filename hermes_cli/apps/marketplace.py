"""Asynchronous remote-market application acquisition.

Remote packages are never installed directly.  A completed operation returns
the existing :class:`ImportPlan`; the caller must still submit the normal
two-phase import confirmation with the requested permissions.
"""

from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_cli.marketplace import MarketplaceClient, MarketplaceError

from .errors import AppDomainError
from .manager import AppManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _market_error(error: MarketplaceError) -> AppDomainError:
    return AppDomainError(
        error.code,
        error.message,
        retryable=error.retryable,
        details=error.details,
    )


@dataclass(slots=True)
class _Operation:
    id: str
    market_app_id: str
    version: str | None
    state: str = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    import_plan: dict[str, Any] | None = None
    error: AppDomainError | None = None
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "operation_id": self.id,
            "market_app_id": self.market_app_id,
            "version": self.version,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.import_plan is not None:
            value["import_plan"] = self.import_plan
        if self.error is not None:
            value["error"] = {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
                "details": self.error.details,
            }
        return value


class AppMarketplaceOperations:
    """Coordinate async market downloads with the local `.happ` importer."""

    def __init__(self, client: MarketplaceClient | None = None) -> None:
        self.client = client or MarketplaceClient.from_active_config()
        self._operations: dict[str, _Operation] = {}
        self._lock = threading.Lock()

    def list_apps(self, **params: str | int | bool | None) -> dict[str, Any]:
        try:
            response = self.client.list_apps(**params)
        except MarketplaceError as exc:
            raise _market_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def get_app(
        self, market_app_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        try:
            response = self.client.get_app(market_app_id, version=version)
        except MarketplaceError as exc:
            raise _market_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def list_categories(self) -> dict[str, Any]:
        try:
            response = self.client.list_categories("app")
        except MarketplaceError as exc:
            raise _market_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def get_icon(
        self, market_app_id: str, *, version: str | None = None
    ) -> tuple[bytes, str]:
        detail = self.get_app(market_app_id, version=version)
        item = detail.get("item") if isinstance(detail.get("item"), dict) else detail
        icon_url = item.get("icon_url") if isinstance(item, dict) else None
        if not isinstance(icon_url, str) or not icon_url:
            raise AppDomainError(
                "APP_NOT_FOUND", "market application does not provide an icon"
            )
        try:
            return self.client.fetch_icon(icon_url)
        except MarketplaceError as exc:
            raise _market_error(exc) from exc

    def start_install(
        self, market_app_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        if not market_app_id or len(market_app_id) > 200:
            raise AppDomainError(
                "APP_REQUEST_INVALID", "market application id is invalid"
            )
        operation = _Operation(
            id=str(uuid.uuid4()), market_app_id=market_app_id, version=version
        )
        with self._lock:
            self._operations[operation.id] = operation
        threading.Thread(target=self._run, args=(operation.id,), daemon=True).start()
        return operation.public()

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise AppDomainError(
                    "APP_NOT_FOUND", "market install operation was not found"
                )
            return operation.public()

    def cancel(self, operation_id: str) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise AppDomainError(
                    "APP_NOT_FOUND", "market install operation was not found"
                )
            if operation.state in {"completed", "failed", "cancelled"}:
                return
            operation.cancel_requested = True
            operation.updated_at = _now()

    def _run(self, operation_id: str) -> None:
        manager = AppManager()
        manager.paths.ensure()
        staging_dir: Path | None = None
        import_id: str | None = None
        try:
            self._set_state(operation_id, "resolving")
            operation = self._operation(operation_id)
            resolved = self.client.resolve_app(
                operation.market_app_id, version=operation.version
            )
            artifact = resolved.get("artifact")
            if not isinstance(artifact, dict) or artifact.get("kind") != "happ":
                raise AppDomainError("MARKET_ARTIFACT_REJECTED", "市场应用制品类型无效")
            self._ensure_not_cancelled(operation_id)

            self._set_state(operation_id, "downloading")
            staging_dir = manager.paths.staging / f"market-{operation_id}"
            staging_dir.mkdir(mode=0o700)
            package_path = staging_dir / "application.happ"
            self.client.download_artifact(artifact, package_path)
            self._ensure_not_cancelled(operation_id)

            self._set_state(operation_id, "analyzing")
            plan = manager.analyze_import(package_path)
            import_id = plan.import_id
            self._ensure_not_cancelled(operation_id)
            with self._lock:
                current = self._operations[operation_id]
                current.import_plan = plan.public_dict()
                current.state = "completed"
                current.updated_at = _now()
        except MarketplaceError as exc:
            self._fail(operation_id, _market_error(exc))
        except AppDomainError as exc:
            self._fail(operation_id, exc)
        except Exception:
            self._fail(
                operation_id,
                AppDomainError(
                    "MARKET_UNAVAILABLE", "市场应用安装准备失败", retryable=True
                ),
            )
        finally:
            if (
                self._operation(operation_id).state == "cancelled"
                and import_id is not None
            ):
                try:
                    manager.discard_import(import_id)
                except AppDomainError:
                    pass
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

    def _operation(self, operation_id: str) -> _Operation:
        with self._lock:
            return self._operations[operation_id]

    def _set_state(self, operation_id: str, state: str) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            operation.state = state
            operation.updated_at = _now()

    def _ensure_not_cancelled(self, operation_id: str) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            if not operation.cancel_requested:
                return
            operation.state = "cancelled"
            operation.updated_at = _now()
        raise AppDomainError("APP_REQUEST_CANCELLED", "市场应用安装已取消")

    def _fail(self, operation_id: str, error: AppDomainError) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None or operation.state == "cancelled":
                return
            operation.error = error
            operation.state = "failed"
            operation.updated_at = _now()
