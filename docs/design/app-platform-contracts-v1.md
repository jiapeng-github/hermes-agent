# Hermes App Platform Contracts v1

Status: **Gate 1 frozen**
Contract version: `1.0.0`
Frozen on: `2026-07-12`
Scope: phase-1 local desktop runtime

## Frozen product decisions

1. Phase 1 is local-only. It does not expose or depend on a remote Gateway.
2. User applications contain browser assets, prompts, and schemas only. They
   cannot ship custom backend code.
3. The first vertical pilot is Watchlist.
4. Phase 1 supports `.happ` export and two-phase import.
5. Creating and modifying an application starts from a new-chat template
   powered by the `app-builder` Skill; there is no separate form wizard.
6. Applications request capabilities in their manifest. Trust, lineage, and
   permission grants are runtime-owned state and are never self-declared.
7. `service` actions are reserved for exact handlers inherited from a
   runtime-owned built-in application lineage. User-created and imported apps
   receive no service-handler allowlist.

## Authoritative contracts

| Contract | Authoritative file | Version boundary |
|---|---|---|
| App Manifest | `hermes_cli/apps/contracts/app-manifest.schema.json` | `schema_version` |
| `.happ` metadata | `hermes_cli/apps/contracts/happ-package.schema.json` | `format_version` |
| `.happ` archive semantics | `hermes_cli/apps/contracts/happ-format-v1.md` | `format_version` |
| Management API | `hermes_cli/apps/contracts/management-api.openapi.yaml` | OpenAPI `info.version` |
| Runtime event payload | `hermes_cli/apps/contracts/runtime-event.schema.json` | `protocol_version` |
| Runtime stream semantics | `hermes_cli/apps/contracts/runtime-event-protocol-v1.md` | `protocol_version` |

`hermes_cli/apps/contracts/CONTRACTS.lock.json` stores the SHA-256 digest of
every authoritative file. Contract tests verify the lock, JSON Schema
validity, OpenAPI references and invariants, representative manifests, and
Runtime event examples.

## Compatibility policy

- Frozen v1 schemas reject unknown properties. Adding or changing a manifest,
  package, or event property therefore requires the matching version boundary
  to increment.
- An OpenAPI change is compatible only when existing operations, parameters,
  response codes, and schemas remain valid for existing clients. Removing or
  tightening any existing surface requires a new major management API version.
- Documentation that changes normative `.happ` or Runtime behavior is a
  contract change even when no JSON/YAML file changes.
- Implementations may be stricter only for environmental conditions such as
  unavailable MCP servers. They may not reinterpret a structurally valid
  contract or silently broaden permission grants.
- Any contract edit requires: a version decision, updated compatibility notes,
  regenerated lock digests, passing contract tests, and an explicit design
  review. Regenerating the lock alone is not approval.

## Gate 1 acceptance record

- [x] Product decisions above are represented in the contracts.
- [x] Manifest Schema fixes the allowed client capabilities and action kinds.
- [x] `.happ` fixes archive layout, canonical checksums, safety limits,
  export exclusions, conflict behavior, and two-phase import.
- [x] OpenAPI fixes the local management resources, concurrency headers,
  idempotency, error envelope, and package lifecycle.
- [x] Runtime v1 fixes authentication boundaries, SSE framing, event payloads,
  ordering, replay, retention, cancellation, and unique terminal state.
- [x] Contract files are packaged with `hermes_cli` and protected by tests and
  a content lock.

Gate 2 implementation must consume these files rather than creating parallel
wire shapes in the desktop renderer or backend.
