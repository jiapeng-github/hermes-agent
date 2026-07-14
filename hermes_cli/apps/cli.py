"""CLI adapter for the AppManager domain facade."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .errors import AppDomainError
from .manager import AppManager
from .models import AppPermissions
from .package import ImportConfirmation


def apps_command(args, *, manager: AppManager | None = None) -> int:
    """Execute one parsed ``hermes apps`` operation."""
    app_manager = manager or AppManager()
    try:
        payload = _execute(args, app_manager)
    except AppDomainError as exc:
        _print_error(args, exc)
        return 1
    except (OSError, ValueError, ValidationError) as exc:
        _print_error(
            args,
            AppDomainError("APP_REQUEST_INVALID", str(exc) or "invalid application request"),
        )
        return 1

    if isinstance(payload, _CommandResult):
        _print_payload(args, payload.payload, payload.message)
        return payload.exit_code
    _print_payload(args, payload, _human_message(getattr(args, "apps_action", ""), payload))
    return 0


class _CommandResult:
    def __init__(self, payload: Any, *, message: str, exit_code: int = 0):
        self.payload = payload
        self.message = message
        self.exit_code = exit_code


def _execute(args, manager: AppManager) -> Any:
    action = args.apps_action
    if action in {"list", "ls"}:
        return manager.list_apps(query=args.query)
    if action == "init":
        target = Path(args.directory) if args.directory else Path.cwd() / args.app_id.rsplit(".", 1)[-1]
        workspace = manager.workspaces.init(
            target,
            app_id=args.app_id,
            template=args.template,
            name=args.name,
        )
        return {"workspace": str(workspace), "app_id": args.app_id, "template": args.template}
    if action == "inspect":
        return manager.inspect(args.app_id)
    if action == "checkout":
        version_suffix = args.version or "active"
        target = (
            Path(args.directory)
            if args.directory
            else Path.cwd() / f"{args.app_id.rsplit('.', 1)[-1]}-{version_suffix}"
        )
        workspace = manager.workspaces.checkout(
            args.app_id,
            target,
            version=args.version,
        )
        return {"workspace": str(workspace), "app_id": args.app_id, "version": args.version}
    if action == "validate":
        report = manager.validate(args.workspace)
        return _CommandResult(
            report.model_dump(mode="json"),
            message=(
                f"Validation passed for {report.app_id} {report.version}"
                if report.valid
                else f"Validation failed with {len(report.issues)} issue(s)"
            ),
            exit_code=0 if report.valid else 1,
        )
    if action == "build":
        if args.timeout < 1 or args.timeout > 1800:
            raise AppDomainError("APP_REQUEST_INVALID", "build timeout must be 1-1800 seconds")
        return manager.workspaces.build(
            args.workspace,
            allow_scripts=args.allow_scripts,
            timeout_seconds=args.timeout,
        ).model_dump(mode="json")
    if action == "publish":
        return manager.publish(args.workspace, session_id=args.session_id)
    if action == "rollback":
        return manager.rollback(args.app_id, args.version)
    if action == "export":
        output = Path(args.output) if args.output else Path.cwd() / f"{args.app_id.rsplit('.', 1)[-1]}.happ"
        result = manager.export(
            args.app_id,
            output,
            version=args.version,
            include_source=args.include_source,
            overwrite=args.force,
        )
        return {
            "path": str(result.path),
            "package_sha256": result.package_sha256,
            "size": result.size,
            "source_included": result.source_included,
        }
    if action == "import":
        return _execute_import(args, manager)
    raise AppDomainError("APP_REQUEST_INVALID", f"unsupported apps action: {action}")


def _execute_import(args, manager: AppManager) -> Any:
    modes = sum(bool(value) for value in (args.package, args.confirm, args.discard))
    if modes != 1:
        raise AppDomainError(
            "APP_REQUEST_INVALID",
            "provide exactly one package path, --confirm IMPORT_ID, or --discard IMPORT_ID",
        )
    if args.package:
        plan = manager.analyze_import(args.package)
        return _CommandResult(
            plan.public_dict(),
            message=(
                f"Import analyzed; review plan {plan.import_id} before Confirm. "
                f"SHA-256: {plan.package_sha256}"
            ),
        )
    if args.discard:
        manager.get_import_plan(args.discard)
        manager.discard_import(args.discard)
        return _CommandResult(
            {"discarded": True, "import_id": args.discard},
            message=f"Discarded Import Plan {args.discard}",
        )
    if not args.package_sha256 or not args.conflict_mode:
        raise AppDomainError(
            "APP_REQUEST_INVALID",
            "Confirm requires --package-sha256 and --conflict-mode",
        )
    grants = AppPermissions.model_validate(
        {
            "agent": args.grant_agent,
            "mcp_servers": args.grant_mcp,
            "storage": {
                "mode": args.storage_mode,
                "quota_mb": args.storage_quota_mb,
            },
        }
    )
    confirmation = ImportConfirmation(
        package_sha256=args.package_sha256,
        conflict_mode=args.conflict_mode,
        copy_app_id=args.copy_id,
        grants=grants,
    )
    return manager.confirm_import(args.confirm, confirmation)


def _print_payload(args, payload: Any, message: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(message)


def _print_error(args, error: AppDomainError) -> None:
    payload = {
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "details": error.details,
        }
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
    else:
        print(f"{error.code}: {error.message}", file=sys.stderr)


def _human_message(action: str, payload: Any) -> str:
    if action in {"list", "ls"}:
        items = payload["items"]
        if not items:
            return "No applications installed in the active Profile."
        return "\n".join(
            f"{item['id']}  {item['version']}  {item['status']}  {item['name']}"
            for item in items
        )
    if action == "init":
        return f"Created {payload['app_id']} workspace at {payload['workspace']}"
    if action == "checkout":
        return f"Checked out {payload['app_id']} to {payload['workspace']}"
    if action == "build":
        return f"Built {payload['files']} file(s) into {payload['dist']}"
    if action == "publish":
        app = payload["app"]
        return f"Published {app['id']} {app['version']} to App Market"
    if action == "rollback":
        return f"Activated {payload['id']} {payload['version']}"
    if action == "export":
        return f"Exported .happ to {payload['path']} ({payload['package_sha256']})"
    if action == "inspect":
        app = payload["app"]
        return f"{app['id']} {app['version']} ({app['status']})\n{payload['active_path']}"
    if action == "import":
        app = payload.get("app", {})
        if app:
            return f"Imported {app['id']} {app['version']}"
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


__all__ = ["apps_command"]
