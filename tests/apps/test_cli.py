from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from hermes_cli.apps.cli import apps_command
from hermes_cli.apps.manager import AppManager
from hermes_cli.apps.paths import AppPaths
from hermes_cli.subcommands.apps import build_apps_parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_apps_parser(subparsers, cmd_apps=lambda _args: None)
    return parser


def _run(
    parser: argparse.ArgumentParser,
    manager: AppManager,
    capsys,
    arguments: list[str],
) -> tuple[int, dict]:
    args = parser.parse_args(["apps", *arguments, "--json"])
    exit_code = apps_command(args, manager=manager)
    captured = capsys.readouterr()
    stream = captured.out if exit_code == 0 else captured.err
    return exit_code, json.loads(stream)


def _set_version(workspace: Path, version: str) -> None:
    manifest_path = workspace / "app.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_apps_parser_exposes_frozen_gate3_lifecycle() -> None:
    parser = _parser()
    apps_parser = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ).choices["apps"]
    actions = next(
        action
        for action in apps_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert {
        "list",
        "init",
        "inspect",
        "checkout",
        "validate",
        "build",
        "publish",
        "rollback",
        "export",
        "import",
    }.issubset(actions.choices)


def test_cli_fixture_completes_create_modify_export_import_and_rollback(
    tmp_path: Path,
    capsys,
) -> None:
    parser = _parser()
    primary = AppManager(AppPaths(tmp_path / "primary"))
    workspace = tmp_path / "workspace-v1"

    code, initialized = _run(
        parser,
        primary,
        capsys,
        [
            "init",
            "--id",
            "local.stockagent.cli-fixture",
            "--template",
            "vanilla",
            "--directory",
            str(workspace),
        ],
    )
    assert code == 0
    assert initialized["workspace"] == str(workspace)

    code, validation = _run(parser, primary, capsys, ["validate", str(workspace)])
    assert code == 0
    assert validation["valid"] is True

    code, published_v1 = _run(
        parser,
        primary,
        capsys,
        ["publish", str(workspace), "--session-id", "cli-create"],
    )
    assert code == 0
    assert published_v1["app"]["version"] == "0.1.0"

    edit = tmp_path / "workspace-v2"
    code, checked_out = _run(
        parser,
        primary,
        capsys,
        [
            "checkout",
            "local.stockagent.cli-fixture",
            "--directory",
            str(edit),
        ],
    )
    assert code == 0
    assert checked_out["workspace"] == str(edit)
    _set_version(edit, "0.2.0")

    output_schema = edit / "schemas/analyze.output.json"
    output_schema.unlink()
    code, failed_publish = _run(
        parser,
        primary,
        capsys,
        ["publish", str(edit), "--session-id", "cli-failed-modify"],
    )
    assert code == 1
    assert failed_publish["error"]["code"] == "APP_MANIFEST_INVALID"
    assert primary.registry.get("local.stockagent.cli-fixture").active_version == "0.1.0"
    output_schema.write_text(
        json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        ),
        encoding="utf-8",
    )

    code, built = _run(parser, primary, capsys, ["build", str(edit)])
    assert code == 0
    assert built["files"] >= 3
    code, published_v2 = _run(
        parser,
        primary,
        capsys,
        ["publish", str(edit), "--session-id", "cli-modify"],
    )
    assert code == 0
    assert published_v2["app"]["version"] == "0.2.0"

    code, listed = _run(parser, primary, capsys, ["list"])
    assert code == 0
    assert [item["id"] for item in listed["items"]] == [
        "local.stockagent.cli-fixture",
        "ai.hermes.industry-monitor",
        "ai.hermes.company-analysis",
        "ai.hermes.watchlist",
    ]
    code, inspected = _run(
        parser,
        primary,
        capsys,
        ["inspect", "local.stockagent.cli-fixture"],
    )
    assert code == 0
    assert inspected["development_session"] == "cli-modify"

    package = tmp_path / "cli-fixture.happ"
    code, exported = _run(
        parser,
        primary,
        capsys,
        [
            "export",
            "local.stockagent.cli-fixture",
            "--output",
            str(package),
        ],
    )
    assert code == 0
    assert exported["source_included"] is True

    secondary = AppManager(AppPaths(tmp_path / "secondary"))
    code, plan = _run(parser, secondary, capsys, ["import", str(package)])
    assert code == 0
    assert secondary.registry.get("local.stockagent.cli-fixture") is None
    code, imported = _run(
        parser,
        secondary,
        capsys,
        [
            "import",
            "--confirm",
            plan["import_id"],
            "--package-sha256",
            plan["package_sha256"],
            "--conflict-mode",
            "install",
        ],
    )
    assert code == 0
    assert imported["app"]["version"] == "0.2.0"

    code, rolled_back = _run(
        parser,
        primary,
        capsys,
        [
            "rollback",
            "local.stockagent.cli-fixture",
            "--version",
            "0.1.0",
        ],
    )
    assert code == 0
    assert rolled_back["version"] == "0.1.0"
