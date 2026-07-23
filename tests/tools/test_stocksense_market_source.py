from __future__ import annotations

import zipfile
from pathlib import Path

from tools.stocksense_market_source import StockSenseMarketSource


class _Response:
    def __init__(self, data: dict):
        self.data = data


class _Client:
    def list_skills(self, **_params):
        return _Response({
            "items": [
                {
                    "id": "market-skill",
                    "name": "Market skill",
                    "summary": "A tested skill",
                    "version": "1.0.0",
                    "verified": True,
                }
            ]
        })

    def get_skill(self, skill_id: str, *, version: str):
        return _Response({
            "id": skill_id,
            "name": "Market skill",
            "summary": "A tested skill",
            "version": version,
            "verified": True,
        })

    def resolve_skill(self, skill_id: str, *, version: str):
        return {
            "detail_url": "https://market.example/skills/market-skill",
            "artifact": {"kind": "skill_bundle", "sha256": "0" * 64},
        }

    def download_artifact(self, _artifact, destination: Path):
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(
                "SKILL.md",
                "---\nname: Market skill\ndescription: A tested skill\n---\nUse the market skill.\n",
            )
        return "0" * 64


def test_market_source_adapts_remote_skill_into_existing_bundle_pipeline():
    source = StockSenseMarketSource(_Client())

    result = source.search("market")
    bundle = source.fetch(result[0].identifier)

    assert result[0].identifier == "stocksense-market/market-skill/1.0.0"
    assert result[0].trust_level == "trusted"
    assert bundle is not None
    assert bundle.source == "stocksense-market"
    assert bundle.files["SKILL.md"].startswith(b"---")
