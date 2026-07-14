from __future__ import annotations

from pathlib import Path

from hermes_cli.apps.manifest import parse_manifest

from .happ_fixtures import manifest_data


def runtime_app(tmp_path: Path):
    root = tmp_path / "app"
    for directory in ("dist/assets", "source", "prompts", "schemas"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "dist/index.html").write_text(
        '<!doctype html><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (root / "dist/assets/app.js").write_text("window.appReady = true", encoding="utf-8")
    (root / "dist/assets/Chart.js").write_text("window.Chart = {}", encoding="utf-8")
    (root / "icon.png").write_bytes(b"png")
    (root / "source/main.ts").write_text("export {}", encoding="utf-8")
    (root / "prompts/analyze.md").write_text("分析股票。", encoding="utf-8")
    for name in (
        "refresh.input.json",
        "refresh.output.json",
        "analyze.input.json",
        "analyze.output.json",
    ):
        (root / "schemas" / name).write_text("{}", encoding="utf-8")
    manifest = parse_manifest(manifest_data())
    return root, manifest, manifest.permissions
