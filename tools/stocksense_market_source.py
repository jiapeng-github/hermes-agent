"""StockSense remote marketplace adapter for the existing Skills Hub.

The marketplace only supplies signed skill bundles.  Installation remains in
``hermes_cli.skills_hub`` so every remote skill passes the normal quarantine,
scan, approval and lock-file path.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from hermes_cli.marketplace import (
    MarketplaceClient,
    MarketplaceConfig,
    MarketplaceError,
)

from tools.skills_hub import (
    SkillBundle,
    SkillMeta,
    SkillSource,
    _referenced_support_paths,
    _validate_bundle_rel_path,
)


_SOURCE_ID = "stocksense-market"
_MAX_BUNDLE_FILES = 200
_MAX_BUNDLE_FILE_BYTES = 1_000_000


def _identifier(skill_id: str, version: str) -> str:
    return f"{_SOURCE_ID}/{skill_id}/{version}"


def _parse_identifier(value: str) -> tuple[str, str] | None:
    parts = value.split("/", 2)
    if len(parts) != 3 or parts[0] != _SOURCE_ID or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("items")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _skill_meta(
    item: dict[str, Any],
    *,
    fallback_id: str | None = None,
    fallback_version: str | None = None,
) -> SkillMeta | None:
    skill_id = str(item.get("id") or fallback_id or "").strip()
    version = str(item.get("version") or fallback_version or "").strip()
    if not skill_id or not version:
        return None
    tags = item.get("tags")
    return SkillMeta(
        name=str(item.get("name") or skill_id),
        description=str(item.get("summary") or item.get("description") or ""),
        source=_SOURCE_ID,
        identifier=_identifier(skill_id, version),
        trust_level="trusted" if item.get("verified") else "community",
        tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
        extra={
            "market_skill_id": skill_id,
            "version": version,
            "category": str(item.get("category") or ""),
            "publisher": str(item.get("publisher") or ""),
            "compatibility": item.get("compatibility")
            if isinstance(item.get("compatibility"), dict)
            else {},
            "permissions": item.get("permissions")
            if isinstance(item.get("permissions"), list)
            else [],
        },
    )


class StockSenseMarketSource(SkillSource):
    """Read remote StockSense skills through a configured marketplace client."""

    def __init__(self, client: MarketplaceClient) -> None:
        self.client = client

    @classmethod
    def from_active_config(cls) -> "StockSenseMarketSource | None":
        from hermes_cli.config import load_config

        config = MarketplaceConfig.from_mapping(load_config().get("marketplace"))
        if not config.enabled:
            return None
        return cls(MarketplaceClient(config))

    def source_id(self) -> str:
        return _SOURCE_ID

    def search(self, query: str, limit: int = 10) -> list[SkillMeta]:
        response = self.client.list_skills(
            q=query,
            page_size=min(max(limit, 1), 50),
            compatible_only=True,
        )
        return [
            meta
            for item in _items(response.data)
            if (meta := _skill_meta(item)) is not None
        ]

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        parsed = _parse_identifier(identifier)
        if parsed is None:
            return None
        skill_id, version = parsed
        response = self.client.get_skill(skill_id, version=version)
        item = (
            response.data.get("item")
            if isinstance(response.data.get("item"), dict)
            else response.data
        )
        return (
            _skill_meta(item, fallback_id=skill_id, fallback_version=version)
            if isinstance(item, dict)
            else None
        )

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        parsed = _parse_identifier(identifier)
        if parsed is None:
            return None
        skill_id, version = parsed
        resolved = self.client.resolve_skill(skill_id, version=version)
        artifact = resolved.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("kind") != "skill_bundle":
            raise MarketplaceError("MARKET_ARTIFACT_REJECTED", "市场技能制品类型无效")

        metadata = self.inspect(identifier)
        if metadata is None:
            return None
        with tempfile.TemporaryDirectory(prefix="stocksense-skill-") as directory:
            archive = Path(directory) / "skill.zip"
            self.client.download_artifact(artifact, archive)
            files = self._read_bundle(archive)
        return SkillBundle(
            name=metadata.name,
            files=files,
            source=_SOURCE_ID,
            identifier=identifier,
            trust_level=metadata.trust_level,
            metadata={
                **metadata.extra,
                "market_skill_id": skill_id,
                "source_url": str(resolved.get("detail_url") or ""),
                "artifact_sha256": str(artifact.get("sha256") or ""),
            },
        )

    @staticmethod
    def _read_bundle(archive: Path) -> dict[str, bytes]:
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = [info for info in bundle.infolist() if not info.is_dir()]
                if not members or len(members) > _MAX_BUNDLE_FILES:
                    raise MarketplaceError(
                        "MARKET_ARTIFACT_REJECTED", "市场技能包文件数量无效"
                    )
                files: dict[str, bytes] = {}
                for info in members:
                    try:
                        path = _validate_bundle_rel_path(info.filename)
                    except ValueError as exc:
                        raise MarketplaceError(
                            "MARKET_ARTIFACT_REJECTED", "市场技能包包含不安全路径"
                        ) from exc
                    if (
                        info.is_dir()
                        or info.file_size > _MAX_BUNDLE_FILE_BYTES
                        or (info.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise MarketplaceError(
                            "MARKET_ARTIFACT_REJECTED", "市场技能包包含不受支持的文件"
                        )
                    files[path] = bundle.read(info)
        except zipfile.BadZipFile as exc:
            raise MarketplaceError(
                "MARKET_ARTIFACT_REJECTED", "市场技能包不是有效 ZIP 文件"
            ) from exc

        skill_md = files.get("SKILL.md")
        if skill_md is None:
            raise MarketplaceError(
                "MARKET_ARTIFACT_REJECTED", "市场技能包缺少 SKILL.md"
            )
        try:
            referenced = _referenced_support_paths(skill_md.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise MarketplaceError(
                "MARKET_ARTIFACT_REJECTED", "市场技能说明必须是 UTF-8 文本"
            ) from exc
        if referenced is None or not referenced.issubset(files):
            raise MarketplaceError(
                "MARKET_ARTIFACT_REJECTED", "市场技能包引用了无效支持文件"
            )
        return {
            "SKILL.md": skill_md,
            **{path: files[path] for path in sorted(referenced)},
        }
