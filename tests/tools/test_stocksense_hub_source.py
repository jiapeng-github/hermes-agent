from __future__ import annotations

import zipfile
from pathlib import Path

from tools.stocksense_hub_source import StockSenseHubSource


class _Response:
    def __init__(self, data: dict):
        self.data = data


class _Client:
    def list_skills(self, **_params):
        return _Response({
            "items": [
                {
                    "id": "hub-skill",
                    "name": "Hub skill",
                    "summary": "A tested skill",
                    "version": "1.0.0",
                    "verified": True,
                }
            ]
        })

    def get_skill(self, skill_id: str, *, version: str):
        return _Response({
            "id": skill_id,
            "name": "Hub skill",
            "summary": "A tested skill",
            "version": version,
            "verified": True,
        })

    def resolve_skill(self, skill_id: str, *, version: str):
        return {
            "detail_url": "https://market.example/skills/hub-skill",
            "artifact": {"kind": "skill_bundle", "sha256": "0" * 64},
        }

    def download_artifact(self, _artifact, destination: Path):
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(
                "SKILL.md",
                "---\nname: Hub skill\ndescription: A tested skill\n---\nUse the hub skill.\n",
            )
        return "0" * 64


def test_hub_source_adapts_remote_skill_into_existing_bundle_pipeline():
    source = StockSenseHubSource(_Client())

    result = source.search("market")
    bundle = source.fetch(result[0].identifier)

    assert result[0].identifier == "stocksense-hub/hub-skill/1.0.0"
    assert result[0].trust_level == "trusted"
    assert bundle is not None
    assert bundle.source == "stocksense-hub"
    assert bundle.files["SKILL.md"].startswith(b"---")
