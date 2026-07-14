# `hermes apps` CLI

Use `--json` for every agent-driven call. A nonzero exit means the operation did not complete; parse the stable `error.code`, `error.message`, `error.retryable`, and `error.details` object from stderr.

## Workspace lifecycle

```bash
hermes apps init --id local.stockagent.example --template dashboard --directory ./example --json
hermes apps build ./example --json
hermes apps validate ./example --json
hermes apps publish ./example --session-id SESSION_ID --json
```

`dashboard` creates React, TypeScript, and Vite files under `source/`. Install its pinned dependencies from that directory before Build. `vanilla` is dependency-free and is built during Init.

Build performs an atomic `dist/` replacement. Checked-out workspaces require `--allow-scripts` before package scripts can execute. Do not use that flag until the scripts and dependency lock have been reviewed.

Validation checks Manifest semantics, Action JSON Schemas, SDK compatibility, paths, symlinks, package limits, credential-like files, CSP compatibility, remote resources, source maps, permission minimization, and referenced build files.

## Inspect and modify

```bash
hermes apps list --query watchlist --json
hermes apps inspect local.stockagent.watchlist --json
hermes apps checkout local.stockagent.watchlist --version 1.0.0 --directory ./watchlist-1.1 --json
hermes apps rollback local.stockagent.watchlist --version 1.0.0 --json
```

`inspect` returns `app`, `versions`, `development_session`, `active_path`, and the installed file inventory. Never write to `active_path`.

## Export

```bash
hermes apps export local.stockagent.watchlist --output ./watchlist.happ --json
hermes apps export local.stockagent.watchlist --version 1.0.0 --no-include-source --output ./watchlist-runtime-only.happ --json
```

Use `--force` only when the user explicitly approves replacing the destination.

## Two-phase import

Analyze makes no installed application change:

```bash
hermes apps import ./watchlist.happ --json
```

Review `import_id`, `expires_at`, `package_sha256`, `signature_state`, `requested_permissions`, `conflict`, and `warnings`. Confirm only after the user selects grants and one conflict mode:

```bash
hermes apps import \
  --confirm IMPORT_ID \
  --package-sha256 SHA256_FROM_PLAN \
  --conflict-mode install \
  --grant-mcp mx-ds-mcp \
  --storage-mode persistent \
  --storage-quota-mb 10 \
  --json
```

Use `--grant-agent` only when approved. Repeat `--grant-mcp SERVER` for each approved server. For `copy`, add `--copy-id NEW_REVERSE_DNS_ID`. Use `--discard IMPORT_ID --json` to cancel and delete staged bytes.

Never combine a package path with `--confirm`, and never invent the plan SHA-256.
