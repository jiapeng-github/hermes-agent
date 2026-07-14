"""Profile-aware filesystem layout for local Hermes applications."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from hermes_constants import get_hermes_home

from .models import APP_ID_PATTERN, SEMVER_PATTERN


def _validated_app_id(app_id: str) -> str:
    if not re.fullmatch(APP_ID_PATTERN, app_id):
        raise ValueError(f"invalid app id: {app_id!r}")
    return app_id


def _validated_version(version: str) -> str:
    if not re.fullmatch(SEMVER_PATTERN, version):
        raise ValueError(f"invalid app version: {version!r}")
    return version


def _validated_import_id(import_id: str) -> str:
    try:
        parsed = uuid.UUID(import_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid import plan id") from exc
    if str(parsed) != import_id.lower():
        raise ValueError("import plan id must use canonical UUID form")
    return str(parsed)


@dataclass(frozen=True, slots=True)
class AppPaths:
    """All app paths rooted in one active Hermes profile."""

    hermes_home: Path

    @classmethod
    def active_profile(cls) -> "AppPaths":
        return cls(get_hermes_home())

    @property
    def root(self) -> Path:
        return self.hermes_home / "apps"

    @property
    def registry(self) -> Path:
        return self.root / "registry.json"

    @property
    def packages(self) -> Path:
        return self.root / "packages"

    @property
    def import_plans(self) -> Path:
        return self.root / ".imports"

    @property
    def staging(self) -> Path:
        return self.root / ".staging"

    @property
    def locks(self) -> Path:
        return self.root / ".locks"

    @property
    def registry_lock(self) -> Path:
        return self.locks / "registry.lock"

    @property
    def app_data(self) -> Path:
        return self.hermes_home / "app-data"

    def app_package(self, app_id: str) -> Path:
        return self.packages / _validated_app_id(app_id)

    def versions(self, app_id: str) -> Path:
        return self.app_package(app_id) / "versions"

    def version(self, app_id: str, version: str) -> Path:
        return self.versions(app_id) / _validated_version(version)

    def app_runtime_data(self, app_id: str) -> Path:
        return self.app_data / _validated_app_id(app_id)

    def import_plan(self, import_id: str) -> Path:
        return self.import_plans / _validated_import_id(import_id)

    def ensure(self) -> None:
        for path in (
            self.root,
            self.packages,
            self.import_plans,
            self.staging,
            self.locks,
            self.app_data,
        ):
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass
__all__ = ["AppPaths"]
