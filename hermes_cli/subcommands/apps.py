"""Argument parser for profile-scoped Hermes Web applications."""

from __future__ import annotations

import argparse
from collections.abc import Callable


def build_apps_parser(subparsers, *, cmd_apps: Callable) -> None:
    """Attach the ``hermes apps`` lifecycle command tree."""
    parser = subparsers.add_parser(
        "apps",
        help="Create, validate, publish, import, and version local Web applications",
        description=(
            "Manage profile-scoped static Web applications for the Hermes App Runtime. "
            "Application code never receives desktop management credentials."
        ),
    )
    actions = parser.add_subparsers(dest="apps_action", required=True)

    list_parser = actions.add_parser("list", aliases=["ls"], help="List installed applications")
    list_parser.add_argument("--query", help="Filter by id, name, or description")
    _add_json(list_parser)

    init_parser = actions.add_parser("init", help="Create a mutable application workspace")
    init_parser.add_argument("--id", required=True, dest="app_id", help="Reverse-DNS application id")
    init_parser.add_argument("--name", help="Display name (defaults to the id suffix)")
    init_parser.add_argument(
        "--template",
        choices=["dashboard", "vanilla"],
        default="dashboard",
        help="Workspace template (default: dashboard)",
    )
    init_parser.add_argument("--directory", help="Destination directory")
    _add_json(init_parser)

    inspect_parser = actions.add_parser("inspect", help="Inspect one installed application")
    inspect_parser.add_argument("app_id")
    _add_json(inspect_parser)

    checkout_parser = actions.add_parser(
        "checkout",
        help="Copy one immutable installed version into a mutable workspace",
    )
    checkout_parser.add_argument("app_id")
    checkout_parser.add_argument("--version", help="Version to check out (default: active)")
    checkout_parser.add_argument("--directory", help="Destination directory")
    _add_json(checkout_parser)

    validate_parser = actions.add_parser("validate", help="Run the frozen publish gate")
    validate_parser.add_argument("workspace")
    _add_json(validate_parser)

    build_parser = actions.add_parser("build", help="Build source into an atomic dist directory")
    build_parser.add_argument("workspace")
    build_parser.add_argument(
        "--allow-scripts",
        action="store_true",
        help="Allow package build scripts in a checked-out workspace",
    )
    build_parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    _add_json(build_parser)

    publish_parser = actions.add_parser("publish", help="Validate and atomically publish a version")
    publish_parser.add_argument("workspace")
    publish_parser.add_argument("--session-id", help="Development conversation/session id")
    _add_json(publish_parser)

    rollback_parser = actions.add_parser("rollback", help="Activate an installed historical version")
    rollback_parser.add_argument("app_id")
    rollback_parser.add_argument("--version", required=True)
    _add_json(rollback_parser)

    export_parser = actions.add_parser("export", help="Export an installed version as .happ")
    export_parser.add_argument("app_id")
    export_parser.add_argument("--version", help="Version to export (default: active)")
    export_parser.add_argument("--output", help="Destination .happ path")
    export_parser.add_argument(
        "--include-source",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include editable source (default: yes when available)",
    )
    export_parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    _add_json(export_parser)

    import_parser = actions.add_parser(
        "import",
        help="Analyze a .happ or explicitly confirm/discard an existing Import Plan",
    )
    import_parser.add_argument("package", nargs="?", help="Package path for the Analyze phase")
    import_mode = import_parser.add_mutually_exclusive_group()
    import_mode.add_argument("--confirm", metavar="IMPORT_ID", help="Confirm an analyzed Import Plan")
    import_mode.add_argument("--discard", metavar="IMPORT_ID", help="Discard an Import Plan")
    import_parser.add_argument("--package-sha256", help="Exact SHA-256 returned by Analyze")
    import_parser.add_argument(
        "--conflict-mode",
        choices=["install", "update", "copy"],
        help="Explicit conflict decision for Confirm",
    )
    import_parser.add_argument("--copy-id", help="New reverse-DNS id when conflict mode is copy")
    import_parser.add_argument("--grant-agent", action="store_true")
    import_parser.add_argument("--grant-mcp", action="append", default=[], metavar="SERVER")
    import_parser.add_argument(
        "--storage-mode",
        choices=["none", "session", "persistent"],
        default="none",
    )
    import_parser.add_argument("--storage-quota-mb", type=int, default=0)
    _add_json(import_parser)

    parser.set_defaults(func=cmd_apps)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print stable machine-readable JSON")


__all__ = ["build_apps_parser"]
