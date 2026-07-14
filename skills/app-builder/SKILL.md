---
name: app-builder
description: Create, modify, repair, validate, publish, roll back, export, or import profile-scoped Hermes Web applications for the App Market. Use when the user invokes /app-builder, asks for a reusable browser application backed by Hermes Runtime actions, asks to change an existing App Market application, or needs a .happ package lifecycle operation.
---

# Hermes App Builder

Build versioned static Web applications whose View layer runs in the system browser and whose declared capabilities are mediated by Hermes App Runtime.

Before invoking the CLI, read [references/cli.md](references/cli.md). Before creating or changing `app.yaml`, actions, schemas, or permissions, read [references/runtime-contract.md](references/runtime-contract.md).

## Preserve the product boundary

- Keep phase 1 local to the desktop. Do not design or claim remote Gateway support.
- Never ship or start custom Python, Node, shell, database, proxy, or other backend services as application runtime code.
- Use `hermes apps` through terminal and file capabilities. Do not add a core model tool.
- Never place credentials, cookies, bearer tokens, model keys, MCP keys, `.env` files, or absolute user paths in source, dist, prompts, schemas, screenshots, or manifests.
- Treat installed version directories as immutable. Modify only an `init` or `checkout` workspace.
- Keep application data in Runtime storage. Publishing and rollback must not manipulate `<HERMES_HOME>/app-data`.

## Select one operation

Choose exactly one path:

1. **Create** when no `app_id` exists.
2. **Modify** when an installed `app_id` and active version exist.
3. **Repair** when a workspace or validation report exists but publication failed.
4. **Package** when the request is specifically import, export, or rollback.

Ask only when application identity, core workflow, required data source, or destructive data migration cannot be inferred safely.

## Create

1. Normalize a reverse-DNS id. Prefer `local.stockagent.{slug}` unless the user supplied a valid id.
2. Select `dashboard` for data-rich React applications or `vanilla` for small dependency-free tools.
3. Run `hermes apps init --id {app_id} --template {template} --directory {workspace} --json`.
4. Replace the sample Manifest action before feature work. Request only capabilities required by the product.
5. Implement under `source/`; produce `dist/` with no CDN, remote script, inline script, inline style, source map, or credential.
6. Add Draft 2020-12 input and output schemas for every action.
7. Use MCP actions for deterministic data retrieval and Agent actions only for analysis, explanation, synthesis, or generation.

For a dashboard workspace, install dependencies only in its generated `source/` directory. Never auto-install or execute scripts from an imported or checked-out package without reviewing them and receiving explicit user intent.

## Modify

1. Run `hermes apps inspect {app_id} --json` and verify active version, source availability, permissions, and development session.
2. Run `hermes apps checkout {app_id} --version {version} --directory {workspace} --json`.
3. Preserve existing workflows and storage shape unless the request explicitly changes them.
4. Increment patch for fixes, minor for compatible features, and major for breaking contracts or data changes.
5. Keep existing grants narrow. A new Manifest request is not automatically granted by publication.
6. Never edit or delete the previous installed version; it is the rollback target.

## Repair

1. Read the latest `hermes apps validate {workspace} --json` report.
2. Repair the workspace in place and rerun build and validation.
3. Do not recreate a workspace unless its metadata or filesystem boundary is corrupted.
4. If publication fails, leave the workspace intact and verify the previous active version remains unchanged.

## Build and validate

Complete every applicable check before publication:

1. Run typecheck and application tests.
2. Run `hermes apps build {workspace} --json`. Use `--allow-scripts` only after explicitly reviewing checked-out build scripts.
3. Run `hermes apps validate {workspace} --json` until `valid` is true.
4. Run through AppHost rather than `file://` when Runtime launch is available.
5. Capture desktop and mobile screenshots in light and dark themes with Playwright.
6. Verify nonblank output, stable layout, keyboard access, no overlap, loading, cached, empty, partial-data, permission, offline, and error states.
7. Treat `APP_ACTION_GATEWAY_DISABLED` as a platform gate when encountered; do not claim live Agent/MCP execution until that adapter is enabled.

Do not publish a partial or failing build.

## Publish and report

1. Run `hermes apps publish {workspace} --session-id {session_id} --json`.
2. Confirm the response contains the expected id, version, checksum, active version, and `market_visible: true`.
3. For modifications, run `hermes apps inspect {app_id} --json` and confirm the previous version remains listed.
4. Report only the application name, version, key capabilities, requested permissions, and App Market availability.

Never claim publication succeeded until the CLI succeeds.

## Package operations

- Export with `hermes apps export`; app data, credentials, grants, logs, caches, and Runtime sessions are always excluded.
- Keep source in editable local exports unless the user explicitly requests `--no-include-source`.
- Import is always two-phase. Analyze first, show the immutable plan, then wait for explicit permission and conflict decisions before Confirm.
- Treat unsigned imports as local untrusted applications. Never restore built-in or service authority from a copied package.
- Roll back with `hermes apps rollback`; verify application data remains unchanged.

## Failure behavior

- Continue fixing validation and build errors within the current task.
- Report exact missing dependencies or permissions without weakening validation.
- Preserve the workspace after any failed publish.
- Never edit Registry JSON or installed package files directly to bypass a conflict.
