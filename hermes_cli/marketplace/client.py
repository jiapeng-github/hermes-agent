"""Safe, profile-local client for the StockSense remote marketplace."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urljoin, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from hermes_constants import get_hermes_home
from utils import atomic_json_write


logger = logging.getLogger(__name__)

_MAX_CATALOG_BYTES = 5 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 52_428_800
_MAX_ICON_BYTES = 512 * 1024
_CACHE_SCHEMA_VERSION = 1


class MarketplaceError(RuntimeError):
    """Stable market failure propagated through the local management API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class MarketplaceConfig:
    enabled: bool
    base_url: str
    channel: str
    request_timeout_seconds: int
    catalog_cache_minutes: int
    offline_cache_hours: int
    require_artifact_signature: bool
    trusted_keys: dict[str, str]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MarketplaceConfig":
        raw = value if isinstance(value, Mapping) else {}
        keys = raw.get("trusted_keys")

        def bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(raw.get(name, default))
            except (TypeError, ValueError):
                value = default
            return min(max(value, minimum), maximum)

        return cls(
            enabled=bool(raw.get("enabled", False)),
            base_url=str(raw.get("base_url") or "").strip().rstrip("/"),
            channel=str(raw.get("channel") or "stable").strip() or "stable",
            request_timeout_seconds=bounded_int("request_timeout_seconds", 15, 3, 60),
            catalog_cache_minutes=bounded_int("catalog_cache_minutes", 5, 1, 60),
            offline_cache_hours=bounded_int("offline_cache_hours", 24, 1, 168),
            require_artifact_signature=bool(
                raw.get("require_artifact_signature", True)
            ),
            trusted_keys={str(key): str(item) for key, item in (keys or {}).items()}
            if isinstance(keys, Mapping)
            else {},
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            raise MarketplaceError("MARKET_DISABLED", "市场服务地址尚未配置")
        if parsed.scheme != "https" and not _is_loopback_url(self.base_url):
            raise MarketplaceError("MARKET_DISABLED", "市场服务必须使用 HTTPS")


@dataclass(frozen=True, slots=True)
class MarketplaceResponse:
    data: dict[str, Any]
    cache_state: str
    stored_at: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "http" and (parsed.hostname or "").lower() in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def _safe_remote_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if _is_loopback_url(value):
        return value
    raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场制品下载地址不安全")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class MarketplaceCache:
    """Small ETag-aware JSON cache scoped to the active Hermes profile."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (get_hermes_home() / "marketplace" / "cache")

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            raw = path.read_bytes()
            if len(raw) > _MAX_CATALOG_BYTES:
                return None
            value = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != _CACHE_SCHEMA_VERSION
        ):
            return None
        if not isinstance(value.get("payload"), dict):
            return None
        return value

    def write(self, key: str, *, etag: str | None, payload: Mapping[str, Any]) -> None:
        atomic_json_write(
            self._path(key),
            {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "etag": etag,
                "stored_at": _utc_now().isoformat(),
                "payload": dict(payload),
            },
            mode=0o600,
            sort_keys=True,
        )


class MarketplaceClient:
    """Fetch catalog metadata and verified artifacts without exposing it to the renderer."""

    def __init__(
        self,
        config: MarketplaceConfig,
        *,
        cache: MarketplaceCache | None = None,
        client: httpx.Client | None = None,
        client_version: str = "unknown",
        runtime_version: str = "1.0.0",
    ) -> None:
        config.validate()
        self.config = config
        self.cache = cache or MarketplaceCache()
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(config.request_timeout_seconds),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._client_version = client_version
        self._runtime_version = runtime_version

    @classmethod
    def from_active_config(cls) -> "MarketplaceClient":
        from hermes_cli.config import load_config

        config = MarketplaceConfig.from_mapping(load_config().get("marketplace"))
        return cls(config)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MarketplaceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_skills(self, **params: str | int | bool | None) -> MarketplaceResponse:
        self._require_enabled()
        return self._catalog_get("/skills", params)

    def get_skill(
        self, skill_id: str, *, version: str | None = None
    ) -> MarketplaceResponse:
        self._require_enabled()
        params: dict[str, str | int | bool | None] = {
            "channel": self.config.channel,
            "version": version,
        }
        return self._catalog_get(f"/skills/{quote(skill_id, safe='')}", params)

    def resolve_skill(
        self, skill_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        self._require_enabled()
        return self._resolve("skills", skill_id, version=version)

    def list_apps(self, **params: str | int | bool | None) -> MarketplaceResponse:
        self._require_enabled()
        return self._catalog_get("/apps", params)

    def list_categories(self, kind: str) -> MarketplaceResponse:
        self._require_enabled()
        if kind not in {"skill", "app"}:
            raise MarketplaceError("MARKET_UNAVAILABLE", "市场分类类型无效")
        return self._catalog_get("/categories", {"type": kind})

    def get_app(
        self, market_app_id: str, *, version: str | None = None
    ) -> MarketplaceResponse:
        self._require_enabled()
        params: dict[str, str | int | bool | None] = {
            "channel": self.config.channel,
            "version": version,
        }
        return self._catalog_get(f"/apps/{quote(market_app_id, safe='')}", params)

    def resolve_app(
        self, market_app_id: str, *, version: str | None = None
    ) -> dict[str, Any]:
        self._require_enabled()
        return self._resolve("apps", market_app_id, version=version)

    def download_artifact(
        self, descriptor: Mapping[str, Any], destination: Path
    ) -> str:
        """Download one resolved artifact after validating its descriptor and digest."""
        self._require_enabled()
        expected_sha256 = str(descriptor.get("sha256") or "")
        if len(expected_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in expected_sha256
        ):
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场制品摘要无效")
        expected_size = descriptor.get("size_bytes")
        if (
            not isinstance(expected_size, int)
            or expected_size < 1
            or expected_size > _MAX_ARTIFACT_BYTES
        ):
            raise MarketplaceError("MARKET_ARTIFACT_TOO_LARGE", "市场制品大小无效")
        self._verify_descriptor(descriptor)
        expires_at = _parse_timestamp(descriptor.get("expires_at"))
        if expires_at is None or expires_at <= _utc_now():
            raise MarketplaceError(
                "MARKET_ARTIFACT_EXPIRED", "市场制品下载票据已过期", retryable=True
            )
        url = _safe_remote_url(str(descriptor.get("download_url") or ""))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场制品暂存路径已存在")

        digest = hashlib.sha256()
        written = 0
        temp_path: Path | None = None
        try:
            with self._client.stream(
                "GET", url, headers={"Accept": "application/octet-stream"}
            ) as response:
                if response.is_redirect:
                    raise MarketplaceError(
                        "MARKET_ARTIFACT_REJECTED", "市场制品下载不允许重定向"
                    )
                self._raise_for_status(response)
                content_length = response.headers.get("content-length")
                if content_length and (
                    not content_length.isdigit() or int(content_length) != expected_size
                ):
                    raise MarketplaceError(
                        "MARKET_ARTIFACT_HASH_MISMATCH", "市场制品大小与目录不一致"
                    )
                fd, name = tempfile.mkstemp(
                    prefix=".market-", suffix=".download", dir=str(destination.parent)
                )
                temp_path = Path(name)
                with os.fdopen(fd, "wb") as handle:
                    for chunk in response.iter_bytes(64 * 1024):
                        written += len(chunk)
                        if written > _MAX_ARTIFACT_BYTES or written > expected_size:
                            raise MarketplaceError(
                                "MARKET_ARTIFACT_TOO_LARGE", "市场制品超过允许大小"
                            )
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            actual_sha256 = digest.hexdigest()
            if written != expected_size or not hmac.compare_digest(
                actual_sha256, expected_sha256
            ):
                raise MarketplaceError(
                    "MARKET_ARTIFACT_HASH_MISMATCH", "市场制品摘要校验失败"
                )
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, destination)
            temp_path = None
            return actual_sha256
        except httpx.HTTPError as exc:
            raise MarketplaceError(
                "MARKET_UNAVAILABLE", "市场制品下载失败", retryable=True
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def fetch_icon(self, value: str) -> tuple[bytes, str]:
        """Fetch a small same-market icon for the local gateway to proxy."""
        self._require_enabled()
        url = urljoin(f"{self.config.base_url}/", value)
        parsed = urlparse(url)
        market_host = urlparse(self.config.base_url).hostname
        if not _safe_remote_url(url) or parsed.hostname != market_host:
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场图标地址不安全")
        try:
            response = self._client.get(
                url,
                headers={
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/svg+xml"
                },
            )
            if response.is_redirect:
                raise MarketplaceError(
                    "MARKET_ARTIFACT_REJECTED", "市场图标下载不允许重定向"
                )
            self._raise_for_status(response)
        except MarketplaceError:
            raise
        except httpx.HTTPError as exc:
            raise MarketplaceError(
                "MARKET_UNAVAILABLE", "市场图标下载失败", retryable=True
            ) from exc
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if (
            not content_type.startswith("image/")
            or len(response.content) > _MAX_ICON_BYTES
        ):
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场图标格式或大小无效")
        return response.content, content_type

    def _catalog_get(
        self,
        path: str,
        params: Mapping[str, str | int | bool | None],
    ) -> MarketplaceResponse:
        filtered = {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in params.items()
            if value is not None and value != ""
        }
        filtered.setdefault("channel", self.config.channel)
        cache_key = f"{path}?" + "&".join(
            f"{key}={filtered[key]}" for key in sorted(filtered)
        )
        cached = self.cache.read(cache_key)
        if cached and self._fresh_cache(cached):
            return MarketplaceResponse(
                cached["payload"], "fresh", cached.get("stored_at")
            )
        headers = self._headers()
        if cached and isinstance(cached.get("etag"), str):
            headers["If-None-Match"] = cached["etag"]
        try:
            response = self._client.get(
                f"{self.config.base_url}{path}", params=filtered, headers=headers
            )
            if response.status_code == 304 and cached:
                return MarketplaceResponse(
                    cached["payload"], "fresh", cached.get("stored_at")
                )
            self._raise_for_status(response)
            if len(response.content) > _MAX_CATALOG_BYTES:
                raise MarketplaceError("MARKET_UNAVAILABLE", "市场目录响应过大")
            payload = response.json()
            if not isinstance(payload, dict):
                raise MarketplaceError("MARKET_UNAVAILABLE", "市场目录响应格式无效")
            self.cache.write(
                cache_key, etag=response.headers.get("etag"), payload=payload
            )
            return MarketplaceResponse(payload, "fresh", _utc_now().isoformat())
        except MarketplaceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            if cached and self._usable_stale_cache(cached):
                return MarketplaceResponse(
                    cached["payload"], "stale", cached.get("stored_at")
                )
            raise MarketplaceError(
                "MARKET_UNAVAILABLE", "市场服务暂时不可用", retryable=True
            ) from exc

    def _resolve(
        self, kind: str, item_id: str, *, version: str | None
    ) -> dict[str, Any]:
        body = {
            "version": version,
            "channel": self.config.channel,
            "platform": _market_platform(),
        }
        try:
            response = self._client.post(
                f"{self.config.base_url}/{kind}/{quote(item_id, safe='')}/resolve",
                headers=self._headers(),
                json={key: value for key, value in body.items() if value is not None},
            )
            self._raise_for_status(response)
            value = response.json()
        except MarketplaceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise MarketplaceError(
                "MARKET_UNAVAILABLE", "市场制品解析失败", retryable=True
            ) from exc
        if not isinstance(value, dict):
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场制品描述格式无效")
        return value

    def _verify_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        signature = descriptor.get("signature")
        if signature is None and not self.config.require_artifact_signature:
            return
        if not isinstance(signature, Mapping):
            raise MarketplaceError("MARKET_SIGNATURE_INVALID", "市场制品缺少签名")
        if signature.get("algorithm") != "ed25519":
            raise MarketplaceError(
                "MARKET_SIGNATURE_INVALID", "市场制品签名算法不受支持"
            )
        key_id = str(signature.get("key_id") or "")
        encoded_key = self.config.trusted_keys.get(key_id)
        if not encoded_key:
            raise MarketplaceError(
                "MARKET_SIGNATURE_INVALID", "市场制品签名密钥不受信任"
            )
        try:
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(encoded_key, validate=True)
            )
            signed = "\n".join([
                str(descriptor.get("kind") or ""),
                str(descriptor.get("artifact_id") or ""),
                str(descriptor.get("version") or ""),
                str(descriptor.get("sha256") or ""),
                str(descriptor.get("size_bytes") or ""),
            ]).encode("utf-8")
            key.verify(
                base64.b64decode(str(signature.get("value") or ""), validate=True),
                signed,
            )
        except (ValueError, InvalidSignature) as exc:
            raise MarketplaceError(
                "MARKET_SIGNATURE_INVALID", "市场制品签名校验失败"
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-StockSense-Client-Version": self._client_version,
            "X-StockSense-Runtime-Version": self._runtime_version,
        }

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            remote = response.json()
        except ValueError:
            remote = {}
        error = remote.get("error") if isinstance(remote, dict) else {}
        code = (
            str(error.get("code") or "MARKET_UNAVAILABLE")
            if isinstance(error, Mapping)
            else "MARKET_UNAVAILABLE"
        )
        message = (
            str(error.get("message") or "市场服务请求失败")
            if isinstance(error, Mapping)
            else "市场服务请求失败"
        )
        raise MarketplaceError(
            code,
            message,
            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
            details=error.get("details")
            if isinstance(error, Mapping) and isinstance(error.get("details"), Mapping)
            else {},
        )

    def _usable_stale_cache(self, entry: Mapping[str, Any]) -> bool:
        stored_at = _parse_timestamp(entry.get("stored_at"))
        return (
            stored_at is not None
            and stored_at + timedelta(hours=self.config.offline_cache_hours)
            > _utc_now()
        )

    def _fresh_cache(self, entry: Mapping[str, Any]) -> bool:
        stored_at = _parse_timestamp(entry.get("stored_at"))
        return (
            stored_at is not None
            and stored_at + timedelta(minutes=self.config.catalog_cache_minutes)
            > _utc_now()
        )

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise MarketplaceError("MARKET_DISABLED", "远程市场尚未启用")


def _market_platform() -> str:
    import platform

    machine = platform.machine().lower()
    if platform.system() == "Windows" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if platform.system() == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    return f"{platform.system().lower()}-{machine or 'unknown'}"
