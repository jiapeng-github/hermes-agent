"""Launch-code, Runtime cookie, CSRF, Host, Origin, and peer policy."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit


LAUNCH_CODE_TTL_SECONDS = 30
SESSION_TTL_SECONDS = 12 * 60 * 60
CSRF_BUCKET_SECONDS = 10 * 60
RUNTIME_COOKIE_PREFIX = "hermes_app_session_"
CSRF_HEADER_NAME = "X-Hermes-App-CSRF"


@dataclass(frozen=True, slots=True)
class _RuntimeSession:
    expires_at: float


class RuntimeAuth:
    """In-memory authority owned by exactly one AppHost."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        launch_ttl_seconds: int = LAUNCH_CODE_TTL_SECONDS,
        session_ttl_seconds: int = SESSION_TTL_SECONDS,
    ):
        self._clock = clock
        self._launch_ttl = launch_ttl_seconds
        self._session_ttl = session_ttl_seconds
        self._csrf_key = secrets.token_bytes(32)
        self.cookie_name = f"{RUNTIME_COOKIE_PREFIX}{secrets.token_hex(8)}"
        self._launch_codes: dict[str, float] = {}
        self._sessions: dict[str, _RuntimeSession] = {}
        self._lock = threading.Lock()

    def issue_launch_code(self) -> str:
        """Return a 256-bit code while retaining only its SHA-256 digest."""
        with self._lock:
            self._cleanup_locked()
            while True:
                code = secrets.token_urlsafe(32)
                digest = _digest(code)
                if digest not in self._launch_codes:
                    self._launch_codes[digest] = self._clock() + self._launch_ttl
                    return code

    def exchange_launch_code(self, code: str) -> str | None:
        """Consume one unexpired code and mint a Runtime session secret."""
        if not code or len(code) > 256:
            return None
        digest = _digest(code)
        with self._lock:
            self._cleanup_locked()
            expires_at = self._launch_codes.pop(digest, None)
            if expires_at is None or expires_at <= self._clock():
                return None
            while True:
                session = secrets.token_urlsafe(32)
                session_digest = _digest(session)
                if session_digest not in self._sessions:
                    self._sessions[session_digest] = _RuntimeSession(
                        expires_at=self._clock() + self._session_ttl
                    )
                    return session

    def authenticate(self, session: str | None) -> bool:
        if not session or len(session) > 256:
            return False
        digest = _digest(session)
        with self._lock:
            self._cleanup_locked()
            record = self._sessions.get(digest)
            return record is not None and record.expires_at > self._clock()

    def csrf_token(self, session: str) -> str | None:
        if not self.authenticate(session):
            return None
        bucket = int(self._clock() // CSRF_BUCKET_SECONDS)
        return self._csrf_for_bucket(session, bucket)

    def validate_csrf(self, session: str, token: str | None) -> bool:
        if not token or len(token) > 256 or not self.authenticate(session):
            return False
        bucket_text, separator, _mac = token.partition(".")
        if not separator or not bucket_text.isascii() or not bucket_text.isdigit():
            return False
        bucket = int(bucket_text)
        current = int(self._clock() // CSRF_BUCKET_SECONDS)
        if bucket not in {current, current - 1}:
            return False
        expected = self._csrf_for_bucket(session, bucket)
        return hmac.compare_digest(token.encode(), expected.encode())

    def revoke(self, session: str) -> None:
        with self._lock:
            self._sessions.pop(_digest(session), None)

    def close(self) -> None:
        with self._lock:
            self._launch_codes.clear()
            self._sessions.clear()
            self._csrf_key = secrets.token_bytes(32)

    def _csrf_for_bucket(self, session: str, bucket: int) -> str:
        session_digest = _digest(session)
        message = f"{session_digest}:{bucket}".encode()
        mac = hmac.new(self._csrf_key, message, hashlib.sha256).hexdigest()
        return f"{bucket}.{mac}"

    def _cleanup_locked(self) -> None:
        now = self._clock()
        self._launch_codes = {
            digest: expires_at
            for digest, expires_at in self._launch_codes.items()
            if expires_at > now
        }
        self._sessions = {
            digest: record
            for digest, record in self._sessions.items()
            if record.expires_at > now
        }


class RuntimeRequestPolicy:
    """Exact loopback origin policy for one random AppHost port."""

    def __init__(self, expected_origin: str, *, allow_test_client: bool = False):
        parsed = urlsplit(expected_origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AppHost origin must be http://127.0.0.1:<port>")
        self.expected_origin = f"http://127.0.0.1:{parsed.port}"
        self.expected_host = f"127.0.0.1:{parsed.port}"
        self.allow_test_client = allow_test_client

    def valid_host(self, host_header: str | None) -> bool:
        if not host_header or len(host_header) > 128:
            return False
        return hmac.compare_digest(
            host_header.strip().lower().encode(),
            self.expected_host.encode(),
        )

    def valid_origin(self, origin_header: str | None) -> bool:
        if not origin_header or len(origin_header) > 256:
            return False
        try:
            parsed = urlsplit(origin_header)
            normalized = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        except (TypeError, ValueError):
            return False
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return False
        return hmac.compare_digest(normalized.encode(), self.expected_origin.encode())

    def valid_peer(self, peer_host: str | None) -> bool:
        if self.allow_test_client and peer_host == "testclient":
            return True
        if not peer_host:
            return False
        try:
            return ipaddress.ip_address(peer_host).is_loopback
        except ValueError:
            return False


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "CSRF_HEADER_NAME",
    "RUNTIME_COOKIE_PREFIX",
    "RuntimeAuth",
    "RuntimeRequestPolicy",
]
