"""Asynchronous remote-Hub application acquisition.

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

from hermes_cli.hub import HubClient, HubError

from .errors import AppDomainError
from .manager import AppManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hub_error(error: HubError) -> AppDomainError:
    return AppDomainError(
        error.code,
        error.message,
        retryable=error.retryable,
        details=error.details,
    )


@dataclass(slots=True)
class _Operation:
    id: str
    hub_app_id: str
    version: str | None
    category: str | None = None
    state: str = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    import_plan: dict[str, Any] | None = None
    error: AppDomainError | None = None
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "operation_id": self.id,
            "hub_app_id": self.hub_app_id,
            "version": self.version,
            "category": self.category,
            "state": self.state,
            "progress": _operation_progress(self.state),
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


def _operation_progress(state: str) -> int:
    return {
        "queued": 5,
        "resolving": 20,
        "downloading": 55,
        "analyzing": 82,
        "completed": 100,
        "failed": 0,
        "cancelled": 0,
    }.get(state, 0)


class AppHubOperations:
    """Coordinate async Hub downloads with the local `.happ` importer."""

    def __init__(self, client: HubClient | None = None) -> None:
        self.client = client or HubClient.from_active_config()
        self._operations: dict[str, _Operation] = {}
        self._lock = threading.Lock()

    def list_apps(self, **params: str | int | bool | None) -> dict[str, Any]:
        try:
            response = self.client.list_apps(**params)
        except HubError as exc:
            raise _hub_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def get_app(
        self, hub_app_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        try:
            response = self.client.get_app(hub_app_id, version=version)
        except HubError as exc:
            raise _hub_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def list_categories(self) -> dict[str, Any]:
        try:
            response = self.client.list_categories("app")
        except HubError as exc:
            raise _hub_error(exc) from exc
        return {
            **response.data,
            "cache_state": response.cache_state,
            "cached_at": response.stored_at,
        }

    def get_icon(
        self, hub_app_id: str, *, version: str | None = None
    ) -> tuple[bytes, str]:
        detail = self.get_app(hub_app_id, version=version)
        item = detail.get("item") if isinstance(detail.get("item"), dict) else detail
        icon_url = item.get("icon_url") if isinstance(item, dict) else None
        if not isinstance(icon_url, str) or not icon_url:
            raise AppDomainError(
                "APP_NOT_FOUND", "hub application does not provide an icon"
            )
        try:
            return self.client.fetch_icon(icon_url)
        except HubError as exc:
            raise _hub_error(exc) from exc

    def get_preview_image(
        self, hub_app_id: str, *, version: str | None = None
    ) -> tuple[bytes, str]:
        # Preview URLs are usually short-lived object-storage signatures. Always
        # refresh app metadata before proxying the image so a local catalog cache
        # cannot turn an otherwise healthy preview into a 503 after expiry.
        refresh_app = getattr(self.client, "refresh_app", None)
        try:
            detail = (
                self._app_response(refresh_app(hub_app_id, version=version))
                if callable(refresh_app)
                else self.get_app(hub_app_id, version=version)
            )
        except HubError as exc:
            raise _hub_error(exc) from exc
        item = detail.get("item") if isinstance(detail.get("item"), dict) else detail
        preview_url = item.get("preview_image_url") if isinstance(item, dict) else None
        if not isinstance(preview_url, str) or not preview_url:
            raise AppDomainError(
                "APP_NOT_FOUND", "hub application does not provide a preview image"
            )
        try:
            return self.client.fetch_preview_image(preview_url)
        except HubError as exc:
            raise _hub_error(exc) from exc

    def _app_response(self, response: Any) -> dict[str, Any]:
        """Normalize a HubResponse-like value for preview metadata access."""
        data = getattr(response, "data", response)
        return data if isinstance(data, dict) else {}

    def start_install(
        self, hub_app_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        if not hub_app_id or len(hub_app_id) > 200:
            raise AppDomainError(
                "APP_REQUEST_INVALID", "hub application id is invalid"
            )
        try:
            detail = self.client.get_app(hub_app_id, version=version).data
        except HubError as exc:
            raise _hub_error(exc) from exc
        item = detail.get("item") if isinstance(detail.get("item"), dict) else detail
        delivery = item.get("delivery") if isinstance(item, dict) else None
        if isinstance(delivery, dict) and delivery.get("type") == "external":
            raise AppDomainError(
                "HUB_EXTERNAL_INSTALL_REQUIRED",
                str(delivery.get("message") or "外部安装，请联系运维人员。"),
            )
        category = item.get("category") if isinstance(item, dict) else None
        operation = _Operation(
            id=str(uuid.uuid4()),
            hub_app_id=hub_app_id,
            version=version,
            category=category if isinstance(category, str) and category else None,
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
                    "APP_NOT_FOUND", "hub install operation was not found"
                )
            return operation.public()

    def cancel(self, operation_id: str) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise AppDomainError(
                    "APP_NOT_FOUND", "hub install operation was not found"
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
                operation.hub_app_id, version=operation.version
            )
            artifact = resolved.get("artifact")
            if not isinstance(artifact, dict) or artifact.get("kind") != "happ":
                raise AppDomainError("HUB_ARTIFACT_REJECTED", "中心应用制品类型无效")
            self._ensure_not_cancelled(operation_id)

            self._set_state(operation_id, "downloading")
            staging_dir = manager.paths.staging / f"hub-{operation_id}"
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
        except HubError as exc:
            self._fail(operation_id, _hub_error(exc))
        except AppDomainError as exc:
            self._fail(operation_id, exc)
        except Exception:
            self._fail(
                operation_id,
                AppDomainError(
                    "HUB_UNAVAILABLE", "中心应用安装准备失败", retryable=True
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
        raise AppDomainError("APP_REQUEST_CANCELLED", "中心应用安装已取消")

    def _fail(self, operation_id: str, error: AppDomainError) -> None:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None or operation.state == "cancelled":
                return
            operation.error = error
            operation.state = "failed"
            operation.updated_at = _now()
