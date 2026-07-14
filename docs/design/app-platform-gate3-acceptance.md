# Hermes App Platform Gate 3 Acceptance

Status: **Gate 3 accepted**
Scope: CLI + Skill fixture application lifecycle
Updated: `2026-07-13`

## Frozen boundary

Gate 3 consumes the Gate 1 Manifest, `.happ`, Management OpenAPI, and Runtime
event contracts without changing their bytes or version. It does not enable a
remote Gateway, custom application backend code, or real Agent/MCP Action
Gateway execution.

Application creation remains a CLI + Skill edge capability. No core model tool
was added and no conversation system prompt or toolset is rebuilt.

## Implemented lifecycle

- `hermes apps list/init/inspect/checkout/validate/build/publish/rollback/export/import`
  is registered as a built-in CLI tree with stable JSON output.
- `AppManager` is the single business facade for CLI and the future management
  router. CLI code does not duplicate Registry or package transitions.
- Init produces either a pinned React + TypeScript + Vite dashboard workspace
  or a dependency-free vanilla workspace. Checkout copies an immutable source
  version into a separate writable workspace.
- Build writes into an isolated directory, applies AppHost static validation,
  and atomically replaces `dist/` only after success. Checked-out package
  scripts require explicit `--allow-scripts`.
- Validate checks Manifest semantics, runtime and SDK compatibility, referenced
  files, Draft 2020-12 Action schemas, external schema references, package
  limits, credential-like files, symlinks, CSP compatibility, remote executable
  resources, local asset completeness, source maps, and unused permissions.
- Publish revalidates the workspace, creates and re-reads a deterministic
  `.happ`, installs one immutable version under the Registry lock, records the
  development session, and preserves only still-valid permission grants.
- Updates must be newer than the active version inside the Registry lock.
  Historical activation is possible only through rollback.
- Export is deterministic for one installed version and can explicitly remove
  source by rewriting only the portable Manifest. Runtime data, grants,
  credentials, logs, caches, and sessions are outside package content.
- Import remains two-phase: Analyze makes no installed change; Confirm requires
  the exact plan SHA-256, conflict decision, and permission subset.
- Rollback changes only active Registry state. Version directories and
  `<HERMES_HOME>/app-data` remain unchanged.

## Skill

`skills/app-builder/` contains a concise workflow Skill, UI metadata, an exact
CLI reference, and a Runtime contract reference. It preserves local-only,
static-frontend, least-permission, immutable-version, explicit Import Confirm,
and no-core-tool boundaries. The Skill validator passes.

## Fixture acceptance

The fixture workflow exercises real argparse and the same Manager used by the
CLI:

1. Create and validate a vanilla v0.1.0 workspace.
2. Publish v0.1.0 and record its development session.
3. Checkout a writable modification workspace.
4. Attempt to publish v0.2.0 with a missing Action schema.
5. Observe a stable validation error and confirm v0.1.0 remains active.
6. Repair, build, validate, and publish v0.2.0 while retaining v0.1.0.
7. Export a reproducible `.happ` and Analyze it in a second Profile.
8. Confirm the Import Plan explicitly and verify v0.2.0 is installed there.
9. Roll the first Profile back to v0.1.0 and verify application data is
   byte-identical.

The dashboard template also completes a real offline Vite production build
when the repository frontend dependencies are present.

## Verification record

Repository-standard focused regression completed with `184 passed`, `0 failed`,
and one environment-conditioned AppHost listener skip. The listener was already
accepted separately in Gate 2. Ruff passes for all App Platform, CLI, and test
files. The real `hermes apps --help` and an isolated-Profile
`hermes apps list --json` process smoke test also pass.

`uv lock` updated the lockfile after promoting `jsonschema` from a
development-only dependency to a production dependency. `uv lock --check`
resolved the locked 233-package graph without changes. Gate 3 is accepted.
