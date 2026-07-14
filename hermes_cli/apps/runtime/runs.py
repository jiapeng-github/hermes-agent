"""Runtime v1 run state machine for allowlisted application actions."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ..models import AppManifest, ServiceAction
from .service import ServiceActionRegistry


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class RuntimeRunError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


class RunRecord:
    def __init__(self, run_id: str, action_id: str):
        now = _utc_now()
        self.run_id = run_id
        self.action_id = action_id
        self.status = "queued"
        self.result: Any = None
        self.error: dict[str, Any] | None = None
        self.created_at = now
        self.updated_at = now
        self.events: list[dict[str, Any]] = []
        self.cancel_requested = threading.Event()
        self._condition = threading.Condition()

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            if self.status in TERMINAL_STATUSES:
                raise RuntimeError("cannot append events after a terminal event")
            event = {
                "protocol_version": 1,
                "run_id": self.run_id,
                "seq": len(self.events) + 1,
                "timestamp": _utc_now(),
                "type": event_type,
                "payload": payload,
            }
            self.events.append(event)
            self.updated_at = event["timestamp"]
            self._condition.notify_all()
            return event

    def terminal(
        self,
        status: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        with self._condition:
            if self.status in TERMINAL_STATUSES:
                return
            event = {
                "protocol_version": 1,
                "run_id": self.run_id,
                "seq": len(self.events) + 1,
                "timestamp": _utc_now(),
                "type": event_type,
                "payload": payload,
            }
            self.events.append(event)
            self.status = status
            self.result = result
            self.error = error
            self.updated_at = event["timestamp"]
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "run_id": self.run_id,
                "action_id": self.action_id,
                "status": self.status,
                "latest_seq": len(self.events),
                "result": self.result,
                "error": self.error,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        with self._condition:
            return list(self.events[seq:])

    def wait_after(self, seq: int, timeout: float) -> list[dict[str, Any]]:
        with self._condition:
            if len(self.events) <= seq and self.status not in TERMINAL_STATUSES:
                self._condition.wait(timeout=timeout)
            return list(self.events[seq:])


class ActionRuntime:
    """Validate, execute, retain, and replay runs for one AppHost."""

    def __init__(
        self,
        manifest: AppManifest,
        app_root: Path,
        service_registry: ServiceActionRegistry,
    ):
        self.manifest = manifest
        self.app_root = app_root
        self.service_registry = service_registry
        self._runs: dict[str, RunRecord] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[float, str, str]] = {}
        self._pending: dict[str, int] = {}
        self._semaphores = {
            action_id: threading.BoundedSemaphore(action.max_concurrent_runs)
            for action_id, action in manifest.actions.items()
        }
        self._validators = {
            action_id: (
                self._load_validator(action.input_schema),
                self._load_validator(action.output_schema),
            )
            for action_id, action in manifest.actions.items()
        }
        self._lock = threading.Lock()

    def start(
        self,
        action_id: str,
        input_data: Any,
        *,
        session: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        action = self.manifest.actions.get(action_id)
        if action is None:
            raise RuntimeRunError(404, "RUN_ACTION_NOT_FOUND", "action was not found")
        if not isinstance(action, ServiceAction):
            raise RuntimeRunError(
                503,
                "RUN_ACTION_UNAVAILABLE",
                "this action kind is not available in the current runtime",
                retryable=True,
            )
        if action.handler not in self.service_registry.names:
            raise RuntimeRunError(403, "RUN_ACTION_FORBIDDEN", "action handler is not inherited")

        input_validator = self._validators[action_id][0]
        issues = sorted(input_validator.iter_errors(input_data), key=lambda issue: list(issue.path))
        if issues:
            issue = issues[0]
            raise RuntimeRunError(
                400,
                "RUN_INPUT_INVALID",
                "action input does not match its schema",
                details={"path": list(issue.path), "message": issue.message[:500]},
            )
        canonical_input = json.dumps(
            input_data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized_key = _validate_idempotency_key(idempotency_key)
        now = time.monotonic()

        with self._lock:
            self._cleanup_idempotency(now)
            if normalized_key is not None:
                scope = (session, action_id, normalized_key)
                existing = self._idempotency.get(scope)
                if existing is not None:
                    _expires_at, previous_input, run_id = existing
                    if previous_input != canonical_input:
                        raise RuntimeRunError(
                            409,
                            "RUN_IDEMPOTENCY_CONFLICT",
                            "idempotency key was already used with different input",
                        )
                    return self._accepted_response(self._runs[run_id])

            run_id = str(uuid.uuid4())
            record = RunRecord(run_id, action_id)
            queue_position = self._pending.get(action_id, 0)
            self._pending[action_id] = queue_position + 1
            record.append(
                "run.accepted",
                {"action_id": action_id, "queue_position": queue_position},
            )
            self._runs[run_id] = record
            if normalized_key is not None:
                self._idempotency[(session, action_id, normalized_key)] = (
                    now + IDEMPOTENCY_TTL_SECONDS,
                    canonical_input,
                    run_id,
                )

        worker = threading.Thread(
            target=self._execute,
            args=(record, action, input_data),
            name=f"app-run-{run_id[:8]}",
            daemon=True,
        )
        worker.start()
        return self._accepted_response(record)

    def get(self, run_id: str) -> RunRecord:
        try:
            parsed = str(uuid.UUID(run_id))
        except (ValueError, AttributeError) as exc:
            raise RuntimeRunError(404, "RUN_NOT_FOUND", "run was not found") from exc
        with self._lock:
            record = self._runs.get(parsed)
        if record is None:
            raise RuntimeRunError(404, "RUN_NOT_FOUND", "run was not found")
        return record

    def cancel(self, run_id: str) -> tuple[int, dict[str, Any]]:
        record = self.get(run_id)
        snapshot = record.snapshot()
        if snapshot["status"] in TERMINAL_STATUSES:
            return 200, snapshot
        record.cancel_requested.set()
        return 202, record.snapshot()

    def _execute(
        self,
        record: RunRecord,
        action: ServiceAction,
        input_data: dict[str, Any],
    ) -> None:
        semaphore = self._semaphores[record.action_id]
        acquired = False
        while not acquired:
            if record.cancel_requested.wait(0.05):
                self._cancel(record)
                self._dequeue(record.action_id)
                return
            acquired = semaphore.acquire(timeout=0.05)
        self._dequeue(record.action_id)
        try:
            if record.cancel_requested.is_set():
                self._cancel(record)
                return
            record.status = "running"
            record.append("run.started", {"attempt": 1})
            record.append(
                "status",
                {"phase": "running", "message": "正在更新应用数据", "progress": 0.1},
            )
            operation_id = str(uuid.uuid4())
            record.append(
                "operation.started",
                {"operation_id": operation_id, "kind": "service", "label": action.title},
            )

            result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

            def invoke() -> None:
                try:
                    result_queue.put((True, self.service_registry.invoke(action.handler, input_data)))
                except BaseException as exc:
                    result_queue.put((False, exc))

            operation = threading.Thread(target=invoke, name=f"service-{record.run_id[:8]}", daemon=True)
            operation.start()
            deadline = time.monotonic() + action.timeout_seconds
            heartbeat_at = time.monotonic() + 15
            while operation.is_alive():
                operation.join(timeout=0.1)
                if record.cancel_requested.is_set():
                    self._cancel(record)
                    return
                now = time.monotonic()
                if now >= deadline:
                    self._fail(
                        record,
                        "RUN_TIMEOUT",
                        "action exceeded its configured timeout",
                        retryable=True,
                    )
                    return
                if now >= heartbeat_at:
                    record.append("heartbeat", {})
                    heartbeat_at = now + 15

            succeeded, value = result_queue.get_nowait()
            if not succeeded:
                if isinstance(value, (KeyError, TypeError, ValueError)):
                    self._fail(record, "RUN_ACTION_FAILED", str(value)[:1000] or "action failed")
                else:
                    self._fail(
                        record,
                        "RUN_ACTION_FAILED",
                        "the application service could not complete the action",
                        retryable=True,
                    )
                return

            output_validator = self._validators[record.action_id][1]
            output_issues = list(output_validator.iter_errors(value))
            if output_issues:
                self._fail(
                    record,
                    "RUN_OUTPUT_INVALID",
                    "service output did not match the application contract",
                )
                return
            record.append(
                "operation.completed",
                {"operation_id": operation_id, "summary": "数据已更新"},
            )
            record.append("data.snapshot", {"data": value})
            record.terminal(
                "completed",
                "run.completed",
                {"result": value},
                result=value,
            )
        finally:
            semaphore.release()

    def _load_validator(self, relative: str) -> Draft202012Validator:
        schema = json.loads((self.app_root / relative).read_text(encoding="utf-8"))
        return Draft202012Validator(schema)

    def _dequeue(self, action_id: str) -> None:
        with self._lock:
            self._pending[action_id] = max(0, self._pending.get(action_id, 1) - 1)

    def _accepted_response(self, record: RunRecord) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "status": record.snapshot()["status"],
            "events_url": f"/api/runs/{record.run_id}/events",
        }

    def _cleanup_idempotency(self, now: float) -> None:
        self._idempotency = {
            key: value for key, value in self._idempotency.items() if value[0] > now
        }

    @staticmethod
    def _cancel(record: RunRecord) -> None:
        record.terminal(
            "cancelled",
            "run.cancelled",
            {"reason": "应用请求取消", "requested_by": "app"},
        )

    @staticmethod
    def _fail(
        record: RunRecord,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        error = {"code": code, "message": message, "retryable": retryable}
        record.terminal("failed", "run.failed", {"error": error}, error=error)


def _validate_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 200 or any(ord(character) < 32 for character in normalized):
        raise RuntimeRunError(400, "RUN_IDEMPOTENCY_INVALID", "invalid idempotency key")
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["ActionRuntime", "RunRecord", "RuntimeRunError", "TERMINAL_STATUSES"]
