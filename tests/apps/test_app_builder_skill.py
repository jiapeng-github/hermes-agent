from __future__ import annotations

from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills/app-builder"


def _frontmatter() -> dict[str, str]:
    content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    _prefix, marker, remainder = content.partition("---\n")
    assert marker
    raw, marker, _body = remainder.partition("---\n")
    assert marker
    return yaml.safe_load(raw)


def test_app_builder_skill_has_discoverable_trigger_metadata() -> None:
    metadata = _frontmatter()
    interface = yaml.safe_load(
        (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
    )["interface"]

    assert metadata["name"] == "app-builder"
    assert "create" in metadata["description"].lower()
    assert "modify" in metadata["description"].lower()
    assert "$app-builder" in interface["default_prompt"]


def test_app_builder_skill_preserves_frozen_product_and_security_boundaries() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    cli = (SKILL_ROOT / "references/cli.md").read_text(encoding="utf-8")
    runtime = (SKILL_ROOT / "references/runtime-contract.md").read_text(
        encoding="utf-8"
    )

    assert "Do not design or claim remote Gateway support" in skill
    assert "Never ship or start custom Python, Node, shell" in skill
    assert "Do not add a core model tool" in skill
    assert "Import is always two-phase" in skill
    assert "Analyze makes no installed application change" in cli
    assert "Never combine a package path with `--confirm`" in cli
    assert "User-created, copied, and imported applications cannot declare it" in runtime


def test_app_builder_skill_references_exist_and_stay_small() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert (SKILL_ROOT / "references/cli.md").is_file()
    assert (SKILL_ROOT / "references/runtime-contract.md").is_file()
    assert len(skill.splitlines()) < 500
