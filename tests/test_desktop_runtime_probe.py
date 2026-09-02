"""Behavioral tests for the desktop runtime-import probe.

The Electron main process gates "is the existing Hermes install usable" on a
Python ``-c`` snippet embedded in ``apps/desktop/electron/backend-probes.ts``
(``HERMES_RUNTIME_IMPORT_PROBE_LINES``). A shallow version of that probe
(``import yaml; import dotenv; import hermes_cli.config``) let a TORN install
pass usability: ``hermes_cli/apps/catalog.py`` had been overwritten with a
newer-tree version importing a sibling module that was never written, the
backend then died at lifespan startup with
``ModuleNotFoundError: No module named 'hermes_cli.apps.activity'``, and
because the install still "looked" usable the desktop skipped first-run
bootstrap on every launch -- an unbootable app with no self-heal.

These tests extract the REAL probe lines from the TypeScript source (so the
snippet can never drift from its tests) and execute them against synthetic
``hermes_cli`` fixtures with this venv's interpreter:

* torn: catalog.py present but importing a missing sibling -> probe FAILS
* old:  apps subsystem absent (self-consistent legacy install) -> probe PASSES
* healthy: complete apps chain -> probe PASSES

The torn case routing to probe-failure is what makes the desktop classify the
runtime unusable and re-run bootstrap (which re-extracts the bundled source).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_TS = REPO_ROOT / "apps" / "desktop" / "electron" / "backend-probes.ts"


def _extract_probe_lines() -> list[str]:
    """Pull the probe snippet lines verbatim out of backend-probes.ts.

    Anchored on the named constant so a rename/move of the snippet breaks
    this test loudly instead of silently testing a stale copy.
    """
    source = PROBE_TS.read_text(encoding="utf-8")
    anchor = re.search(
        r"HERMES_RUNTIME_IMPORT_PROBE_LINES = \[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert anchor is not None, (
        "HERMES_RUNTIME_IMPORT_PROBE_LINES is missing from "
        "apps/desktop/electron/backend-probes.ts -- was the probe snippet "
        "renamed or inlined? Update this test to match."
    )

    lines: list[str] = []
    for raw in anchor.group(1).splitlines():
        match = re.match(r"^\s*'([^']*)',?\s*$", raw)
        if match:
            lines.append(match.group(1))

    assert lines, "No quoted probe lines found inside HERMES_RUNTIME_IMPORT_PROBE_LINES."
    return lines


def _write_fixture(root: Path, *, apps_catalog: str | None, apps_init: bool) -> None:
    """Materialize a minimal hermes_cli package under ``root``.

    ``apps_catalog``: contents for ``hermes_cli/apps/catalog.py``; ``None``
    omits the whole apps subsystem (the "older install" shape).
    """
    pkg = root / "hermes_cli"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # The probe's first layer imports hermes_cli.config; an empty module
    # satisfies it (yaml/dotenv come from the interpreter's own env).
    (pkg / "config.py").write_text("", encoding="utf-8")
    if apps_catalog is None:
        return
    (pkg / "apps").mkdir(parents=True, exist_ok=True)
    if apps_init:
        (pkg / "apps" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "apps" / "catalog.py").write_text(apps_catalog, encoding="utf-8")


def _run_probe(fixture_root: Path, workdir: Path) -> subprocess.CompletedProcess[str]:
    # cwd must NOT be the repo root: ``python -c`` puts cwd first on
    # sys.path, which would shadow the fixture with the real hermes_cli.
    env = {**os.environ, "PYTHONPATH": str(fixture_root)}
    env.pop("PYTHONHOME", None)
    return subprocess.run(
        [sys.executable, "-c", "\n".join(_extract_probe_lines())],
        capture_output=True,
        text=True,
        cwd=str(workdir),
        env=env,
        timeout=60,
    )


def test_probe_fails_on_torn_apps_catalog() -> None:
    """catalog.py present but importing a never-written sibling -> non-zero."""
    with tempfile.TemporaryDirectory(prefix="hermes-probe-torn-") as tmp:
        root = Path(tmp)
        fixture = root / "fixture"
        _write_fixture(
            fixture,
            apps_catalog="from .activity import AppActivityStore\n",
            apps_init=True,
        )
        result = _run_probe(fixture, root)

        assert result.returncode != 0, (
            "Torn install (catalog.py imports missing hermes_cli.apps.activity) "
            "must FAIL the probe so the desktop re-runs bootstrap.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "activity" in result.stderr


def test_probe_tolerates_installs_without_the_apps_subsystem() -> None:
    """No apps/catalog.py at all (older era) -> self-consistent, probe passes."""
    with tempfile.TemporaryDirectory(prefix="hermes-probe-old-") as tmp:
        root = Path(tmp)
        fixture = root / "fixture"
        _write_fixture(fixture, apps_catalog=None, apps_init=False)
        result = _run_probe(fixture, root)

        assert result.returncode == 0, (
            "An older install without hermes_cli/apps/catalog.py is "
            "self-consistent and must PASS the probe (missing/stale marker "
            "must not force a healthy install into bootstrap).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def test_probe_passes_on_a_healthy_apps_chain() -> None:
    """Complete, importable apps chain -> probe passes."""
    with tempfile.TemporaryDirectory(prefix="hermes-probe-ok-") as tmp:
        root = Path(tmp)
        fixture = root / "fixture"
        _write_fixture(
            fixture,
            apps_catalog="ACTIVITY = object()\n",
            apps_init=True,
        )
        result = _run_probe(fixture, root)

        assert result.returncode == 0, (
            "A healthy apps chain must pass the probe.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
