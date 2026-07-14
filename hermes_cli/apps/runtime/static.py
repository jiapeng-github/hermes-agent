"""Static-file confinement and AppHost response security headers."""

from __future__ import annotations

import mimetypes
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'none'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "serial=(), bluetooth=(), clipboard-read=()"
    ),
}


class StaticAssetNotFound(FileNotFoundError):
    pass


class _StaticAssetMissing(StaticAssetNotFound):
    pass


class _StaticAssetUnsafe(StaticAssetNotFound):
    pass


@dataclass(frozen=True, slots=True)
class StaticAsset:
    path: Path
    media_type: str
    is_entry: bool


class StaticAssetResolver:
    """Resolve browser paths under one immutable `dist/` tree."""

    def __init__(self, app_root: Path, entry: str):
        self.app_root = app_root.resolve(strict=True)
        self.dist_root = (self.app_root / "dist").resolve(strict=True)
        self.dist_root.relative_to(self.app_root)
        if (self.app_root / "dist").is_symlink() or not self.dist_root.is_dir():
            raise ValueError("application dist root must be a real directory")
        entry_path = PurePosixPath(entry)
        if not entry_path.parts or entry_path.parts[0] != "dist":
            raise ValueError("application entry must live under dist/")
        self.entry_relative = PurePosixPath(*entry_path.parts[1:]).as_posix()
        self.entry = self._resolve_exact(self.entry_relative)

    def resolve(self, request_path: str) -> StaticAsset:
        if request_path == "/":
            raw = ""
        elif request_path.startswith("/"):
            raise _StaticAssetUnsafe(request_path)
        else:
            raw = request_path
        if not raw:
            return StaticAsset(self.entry, "text/html", True)
        if raw.startswith(("api/", "__hermes/")):
            raise _StaticAssetUnsafe(raw)
        try:
            candidate = self._resolve_exact(raw)
        except _StaticAssetMissing:
            if "." not in PurePosixPath(raw).name:
                return StaticAsset(self.entry, "text/html", True)
            raise
        return StaticAsset(candidate, _media_type(candidate), candidate == self.entry)

    def _resolve_exact(self, relative: str) -> Path:
        if (
            not relative
            or relative != unicodedata.normalize("NFC", relative)
            or "\x00" in relative
            or "\\" in relative
            or relative.startswith("/")
        ):
            raise _StaticAssetUnsafe(relative)
        components = relative.split("/")
        if any(component in {"", ".", ".."} for component in components):
            raise _StaticAssetUnsafe(relative)

        current = self.dist_root
        for component in components:
            if not current.is_dir() or current.is_symlink():
                raise _StaticAssetUnsafe(relative)
            try:
                exact_names = {entry.name for entry in current.iterdir()}
            except OSError as exc:
                raise _StaticAssetUnsafe(relative) from exc
            if component not in exact_names:
                if component.casefold() in {name.casefold() for name in exact_names}:
                    raise _StaticAssetUnsafe(relative)
                raise _StaticAssetMissing(relative)
            current = current / component
            if current.is_symlink():
                raise _StaticAssetUnsafe(relative)
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(self.dist_root)
        except (OSError, ValueError) as exc:
            raise _StaticAssetUnsafe(relative) from exc
        if not resolved.is_file():
            raise _StaticAssetMissing(relative)
        return resolved


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    overrides = {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".wasm": "application/wasm",
        ".webmanifest": "application/manifest+json",
    }
    if suffix in overrides:
        return overrides[suffix]
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "SECURITY_HEADERS",
    "StaticAsset",
    "StaticAssetNotFound",
    "StaticAssetResolver",
]
