from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "github-app-converter"
    / "scripts"
    / "inventory_repo.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("github_app_converter_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_detects_frontend_backend_and_redacts_remote_urls(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "src").mkdir()
    (tmp_path / "server").mkdir()
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    (tmp_path / "src" / "main.tsx").write_text(
        'fetch("https://api.example.com/data?token=do-not-report")', encoding="utf-8"
    )
    (tmp_path / "server" / "index.js").write_text("export default {};", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"react": "1", "vite": "1", "express": "1"},
                "scripts": {"build": "vite build", "postinstall": "node setup.js"},
            }
        ),
        encoding="utf-8",
    )

    report = module.inventory_repository(tmp_path)

    assert report["suggested_class"] == "B"
    assert report["frameworks"] == ["react", "vite"]
    assert "src/main.tsx" in report["frontend_entries"]
    assert "express" in report["backend_markers"]
    assert "server/" in report["backend_markers"]
    assert report["lifecycle_scripts"] == ["postinstall"]
    assert report["remote_origins"] == ["https://api.example.com"]
    assert "do-not-report" not in json.dumps(report)


def test_inventory_reports_credentials_without_reading_them(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "index.html").write_text("<main>App</main>", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=must-not-appear", encoding="utf-8")

    report = module.inventory_repository(tmp_path)

    assert report["suggested_class"] == "D"
    assert report["credential_like_paths"] == [".env"]
    assert "must-not-appear" not in json.dumps(report)


def test_inventory_is_bounded_and_skips_dependency_trees(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("ignored", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    (tmp_path / "a.js").write_text("a", encoding="utf-8")
    (tmp_path / "b.js").write_text("b", encoding="utf-8")

    report = module.inventory_repository(tmp_path, max_files=2)

    assert report["files_scanned"] == 2
    assert report["truncated"] is True
    assert all("node_modules" not in marker for marker in report["frontend_entries"])
    assert any(marker["code"] == "inventory_truncated" for marker in report["risk_markers"])
