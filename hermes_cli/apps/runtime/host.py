"""Per-app ASGI surface and loopback uvicorn lifecycle."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from ..manifest import validate_manifest_files
from ..models import AppManifest, AppPermissions
from ..permissions import validate_permission_grants
from .auth import (
    CSRF_HEADER_NAME,
    RuntimeAuth,
    RuntimeRequestPolicy,
)
from .static import SECURITY_HEADERS, StaticAssetNotFound, StaticAssetResolver
from .runs import ActionRuntime, RuntimeRunError, TERMINAL_STATUSES
from .service import ServiceActionRegistry
from .storage import RuntimeStorage


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PUBLIC_PATHS = frozenset({"/api/health"})


def create_apphost_app(
    manifest: AppManifest,
    app_root: Path,
    granted_permissions: AppPermissions,
    *,
    expected_origin: str,
    runtime_auth: RuntimeAuth | None = None,
    locale: str = "zh-CN",
    theme: str = "auto",
    allow_test_client: bool = False,
    touch: Callable[[], None] | None = None,
    service_registry: ServiceActionRegistry | None = None,
    storage_root: Path | None = None,
) -> FastAPI:
    """Create the same-origin Runtime for one immutable app version."""
    validate_permission_grants(manifest.permissions, granted_permissions)
    validate_manifest_files(manifest, app_root)
    auth = runtime_auth or RuntimeAuth()
    policy = RuntimeRequestPolicy(
        expected_origin,
        allow_test_client=allow_test_client,
    )
    assets = StaticAssetResolver(app_root, manifest.entry)
    action_runtime = (
        ActionRuntime(manifest, app_root, service_registry)
        if service_registry is not None
        else None
    )
    storage = RuntimeStorage(
        granted_permissions.storage.mode,
        granted_permissions.storage.quota_mb,
        storage_root or app_root / ".runtime-storage",
    )
    app = FastAPI(
        title="Hermes AppHost",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime_auth = auth
    app.state.request_policy = policy
    app.state.manifest = manifest

    @app.middleware("http")
    async def runtime_boundary(request: Request, call_next):
        if touch is not None:
            touch()
        peer = request.client.host if request.client else None
        if not policy.valid_peer(peer):
            return _secured_error(403, "RUNTIME_PEER_REJECTED", "request is not from loopback")
        if not policy.valid_host(request.headers.get("host")):
            return _secured_error(400, "RUNTIME_HOST_REJECTED", "invalid AppHost Host header")

        origin = request.headers.get("origin")
        if origin is not None and not policy.valid_origin(origin):
            return _secured_error(403, "RUNTIME_ORIGIN_REJECTED", "invalid AppHost Origin")

        is_launch = request.url.path.startswith(("/launch/", "/__hermes/launch/"))
        is_public = is_launch or request.url.path in _PUBLIC_PATHS
        session = request.cookies.get(auth.cookie_name)
        if not is_public:
            if not auth.authenticate(session):
                return _secured_error(401, "RUNTIME_SESSION_REQUIRED", "Runtime session required")
            request.state.runtime_session = session

        if request.method in _MUTATING_METHODS:
            if not policy.valid_origin(origin):
                return _secured_error(403, "RUNTIME_ORIGIN_REQUIRED", "same-origin request required")
            fetch_site = request.headers.get("sec-fetch-site")
            if fetch_site is not None and fetch_site != "same-origin":
                return _secured_error(403, "RUNTIME_FETCH_SITE_REJECTED", "cross-site request rejected")
            if not session or not auth.validate_csrf(
                session,
                request.headers.get(CSRF_HEADER_NAME),
            ):
                return _secured_error(403, "RUNTIME_CSRF_REJECTED", "invalid CSRF token")

        try:
            response = await call_next(request)
        except Exception:
            return _secured_error(
                500,
                "RUNTIME_INTERNAL_ERROR",
                "AppHost could not complete the request",
            )
        return _apply_security_headers(response, api_path=request.url.path.startswith(("/api/", "/__hermes/")))

    @app.get("/launch/{code}", include_in_schema=False)
    async def exchange_launch(code: str) -> Response:
        session = auth.exchange_launch_code(code)
        if session is None:
            return _secured_error(404, "RUNTIME_LAUNCH_INVALID", "launch link is invalid or expired")
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            auth.cookie_name,
            session,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    app.add_api_route(
        "/__hermes/launch/{code}",
        exchange_launch,
        methods=["GET"],
        include_in_schema=False,
    )

    @app.get("/__hermes/bootstrap")
    async def bootstrap(request: Request) -> JSONResponse:
        session = request.state.runtime_session
        csrf = auth.csrf_token(session)
        if csrf is None:
            return _secured_error(401, "RUNTIME_SESSION_REQUIRED", "Runtime session required")
        actions = {
            action_id: {
                "kind": action.kind,
                "title": action.title,
                "input_schema": action.input_schema,
                "output_schema": action.output_schema,
            }
            for action_id, action in manifest.actions.items()
        }
        return JSONResponse(
            {
                "protocol_version": 1,
                "sdk_version": manifest.sdk_version,
                "app_id": manifest.id,
                "app_version": manifest.version,
                "locale": locale,
                "theme": theme,
                "permissions": granted_permissions.model_dump(mode="json"),
                "actions": actions,
                "csrf_token": csrf,
            }
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol_version": 1}

    @app.post("/api/actions/{action_id}/runs")
    async def start_action(action_id: str, request: Request) -> JSONResponse:
        if action_runtime is None:
            return _secured_error(
                503,
                "APP_ACTION_GATEWAY_DISABLED",
                "Action Gateway is unavailable for this application lineage",
            )
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return _secured_error(400, "RUN_INPUT_INVALID", "request body must be JSON")
        if not isinstance(body, dict) or set(body) != {"input"}:
            return _secured_error(
                400,
                "RUN_INPUT_INVALID",
                "request body must contain only the input field",
            )
        try:
            accepted = action_runtime.start(
                action_id,
                body["input"],
                session=request.state.runtime_session,
                idempotency_key=request.headers.get("idempotency-key"),
            )
        except RuntimeRunError as exc:
            return _runtime_error(exc)
        return JSONResponse(accepted, status_code=202)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> JSONResponse:
        if action_runtime is None:
            return _secured_error(404, "RUN_NOT_FOUND", "run was not found")
        try:
            return JSONResponse(action_runtime.get(run_id).snapshot())
        except RuntimeRunError as exc:
            return _runtime_error(exc)

    @app.get("/api/runs/{run_id}/events")
    async def stream_run_events(run_id: str, request: Request) -> Response:
        if action_runtime is None:
            return _secured_error(404, "RUN_NOT_FOUND", "run was not found")
        try:
            record = action_runtime.get(run_id)
            after = _last_event_id(request.headers.get("last-event-id"))
        except RuntimeRunError as exc:
            return _runtime_error(exc)
        snapshot = record.snapshot()
        if after > snapshot["latest_seq"]:
            return _secured_error(
                400,
                "RUN_EVENT_SEQUENCE_INVALID",
                "Last-Event-ID is newer than the retained run",
            )

        async def event_stream():
            seq = after
            while True:
                events = await asyncio.to_thread(record.wait_after, seq, 15.0)
                for event in events:
                    seq = event["seq"]
                    yield _encode_sse(event)
                state = record.snapshot()["status"]
                if state in TERMINAL_STATUSES and seq >= record.snapshot()["latest_seq"]:
                    return

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/runs/{run_id}")
    async def cancel_run(run_id: str) -> JSONResponse:
        if action_runtime is None:
            return _secured_error(404, "RUN_NOT_FOUND", "run was not found")
        try:
            status_code, snapshot = action_runtime.cancel(run_id)
            return JSONResponse(snapshot, status_code=status_code)
        except RuntimeRunError as exc:
            return _runtime_error(exc)

    @app.get("/api/storage/{key}")
    async def get_storage(key: str) -> JSONResponse:
        try:
            return JSONResponse({"value": storage.get(key)})
        except RuntimeRunError as exc:
            return _runtime_error(exc)

    @app.put("/api/storage/{key}")
    async def put_storage(key: str, request: Request) -> JSONResponse:
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"value"}:
                raise RuntimeRunError(
                    400,
                    "STORAGE_VALUE_INVALID",
                    "request body must contain only the value field",
                )
            storage.put(key, body["value"])
            return JSONResponse({"ok": True})
        except RuntimeRunError as exc:
            return _runtime_error(exc)
        except (ValueError, json.JSONDecodeError):
            return _secured_error(400, "STORAGE_VALUE_INVALID", "request body must be JSON")

    @app.delete("/api/storage/{key}")
    async def delete_storage(key: str) -> JSONResponse:
        try:
            return JSONResponse({"deleted": storage.delete(key)})
        except RuntimeRunError as exc:
            return _runtime_error(exc)

    @app.api_route("/{asset_path:path}", methods=["GET", "HEAD"])
    async def static_asset(asset_path: str) -> Response:
        try:
            asset = assets.resolve(asset_path)
        except StaticAssetNotFound:
            return _secured_error(404, "RUNTIME_ASSET_NOT_FOUND", "asset not found")
        response = FileResponse(asset.path, media_type=asset.media_type)
        response.headers["Cache-Control"] = "no-store"
        if asset.is_entry:
            # Ephemeral ports can be reused by a different app in a later
            # process. Apps persist state through Runtime storage, not ambient
            # browser databases tied only to host+port.
            response.headers["Clear-Site-Data"] = '"storage"'
        return response

    return app


class AppHost:
    """Own one random loopback listener and its in-memory Runtime authority."""

    def __init__(
        self,
        manifest: AppManifest,
        app_root: Path,
        granted_permissions: AppPermissions,
        *,
        idle_timeout_seconds: int = 30 * 60,
        service_registry: ServiceActionRegistry | None = None,
        storage_root: Path | None = None,
    ):
        self.manifest = manifest
        self.app_root = app_root
        self.granted_permissions = granted_permissions
        self.idle_timeout_seconds = idle_timeout_seconds
        self.service_registry = service_registry
        self.storage_root = storage_root
        self.runtime_auth = RuntimeAuth()
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._origin: str | None = None
        self._last_activity = time.monotonic()
        self._activity_lock = threading.Lock()

    @property
    def origin(self) -> str:
        if self._origin is None:
            raise RuntimeError("AppHost is not running")
        return self._origin

    def start(self, *, timeout_seconds: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
        except BaseException:
            listener.close()
            raise
        try:
            port = listener.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            app = create_apphost_app(
                self.manifest,
                self.app_root,
                self.granted_permissions,
                expected_origin=origin,
                runtime_auth=self.runtime_auth,
                touch=self._touch,
                service_registry=self.service_registry,
                storage_root=self.storage_root,
            )
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=server.run,
                kwargs={"sockets": [listener]},
                name=f"hermes-apphost-{self.manifest.id}",
                daemon=True,
            )
        except BaseException:
            listener.close()
            raise
        self._socket = listener
        self._server = server
        self._thread = thread
        self._origin = origin
        thread.start()
        deadline = time.monotonic() + timeout_seconds
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            self.stop()
            raise RuntimeError("AppHost failed to start on loopback")

    def issue_launch_url(self) -> str:
        code = self.runtime_auth.issue_launch_code()
        return f"{self.origin}/launch/{quote(code, safe='')}"

    def is_idle(self) -> bool:
        with self._activity_lock:
            return time.monotonic() - self._last_activity >= self.idle_timeout_seconds

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        server = self._server
        thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self.runtime_auth.close()
        self._server = None
        self._thread = None
        self._socket = None
        self._origin = None

    def _touch(self) -> None:
        with self._activity_lock:
            self._last_activity = time.monotonic()


def _secured_error(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if details:
        error["details"] = details
    response = JSONResponse(
        {"error": error},
        status_code=status_code,
    )
    return _apply_security_headers(response, api_path=True)


def _apply_security_headers(response: Response, *, api_path: bool) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if api_path:
        response.headers["Cache-Control"] = "no-store"
    return response


def _runtime_error(exc: RuntimeRunError) -> JSONResponse:
    return _secured_error(
        exc.status_code,
        exc.code,
        exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )


def _last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    if not value.isascii() or not value.isdigit():
        raise RuntimeRunError(400, "RUN_EVENT_SEQUENCE_INVALID", "invalid Last-Event-ID")
    return int(value)


def _encode_sse(event: dict[str, Any]) -> bytes:
    payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {payload}\n\n".encode("utf-8")


__all__ = ["AppHost", "create_apphost_app"]
