# Hermes App Platform Gate 4 Acceptance

Status: **Gate 4 accepted**
Scope: built-in Watchlist application parity and default-entry cutover
Updated: `2026-07-13`

## Frozen boundary

Gate 4 consumes the frozen Manifest, Management OpenAPI, and Runtime Event
Protocol v1 files without changing them or their content lock. It remains
local-only. User and imported applications still cannot inherit first-party
service handlers or ship custom backend code.

No Agent core tool, conversation prompt, SessionDB surface, or remote Gateway
path was added.

## Built-in pilot

`ai.hermes.watchlist` is bundled as a static HTML/CSS/JavaScript application.
Its Manifest declares six exact first-party service actions:

| Application action | Runtime-owned handler | Existing domain source |
|---|---|---|
| Snapshot | `finance.watchlist.snapshot` | `get_watchlist_snapshot_cached` |
| Refresh | `finance.watchlist.refresh` | `start_watchlist_refresh` |
| Add stock | `finance.watchlist.add` | `add_watchlist_stock` |
| Remove stock | `finance.watchlist.remove` | `remove_watchlist_stock` |
| Detail and K-line | `finance.watchlist.detail` | `get_watchlist_stock_detail` |
| Company analysis | `finance.company.analysis` | `get_company_analysis_snapshot_cached` |

The Registry owns `builtin` lineage and the exact inherited handler set. A
user package cannot declare or replace that lineage. The bundled application
passes the same Manifest, path, CSP, local-resource, Action Schema, package
limit, and permission-minimization checks used before publishing user apps.

## Runtime

- AppHost enables Action Gateway only when the Manager supplies a runtime-owned
  service registry. Existing user/imported paths remain closed by default.
- Inputs and terminal results are validated against the action's Draft 2020-12
  schemas. Provider exceptions and invalid output do not cross the boundary.
- Runs implement accepted, started, status, operation, data snapshot, and one
  terminal event with contiguous sequence numbers. Idempotency, concurrency,
  timeout, cooperative cancellation, snapshot reads, SSE replay, and
  Last-Event-ID validation are runtime-owned.
- Persistent Runtime storage is app-scoped, quota-bound, key-sanitized, and
  protected by the existing runtime cookie, same-origin, and CSRF boundary.
- One AppHost is reused per Profile and app version, idles out after 30 minutes,
  and is stopped during backend shutdown.

## Data parity and migration

The application and retained desktop page call the same Python domain
functions. Contract tests compare indices, quotes, sector aggregation, summary,
gaps, mutations, detail/K-line, and company analysis without maintaining a
second parser or financial calculation path.

On first read, an existing `<HERMES_HOME>/finance/watchlist.json` is copied
idempotently to
`<HERMES_HOME>/app-data/ai.hermes.watchlist/storage/watchlist.json`. The legacy
file is left byte-identical as a rollback copy. Both the browser application
and old desktop route then read and write the new Profile-scoped canonical
file.

## Desktop cutover and rollback

The sidebar and command-palette Watchlist entries now request a one-time local
launch URL and open it through Electron's validated external opener. If AppHost
launch or browser handoff fails, navigation falls back automatically to the
retained `/watchlist` desktop route. The old page also exposes an Application
button, so the two implementations remain available for one version cycle.

## UI acceptance

The browser application provides index cards, breadth and flow summaries,
sortable watchlist rows, add/remove, sector performance, cache-aware refresh,
K-line detail, technical levels, and company analysis. It has a sticky header,
explicit light/dark tokens, 980 px and 640 px responsive breakpoints, and a
contained horizontal table scroller on narrow screens.

Chrome Playwright inspection against a real loopback AppHost confirmed a
1512-pixel desktop viewport with no document overflow, a header fixed at top,
five live watchlist rows with the empty state hidden, no console errors, and a
nonblank 1712 x 600 device-pixel K-line canvas inside a bounded dialog. The
temporary host expiration also exercised the non-destructive detail error
state. Narrow-layout and explicit-dark behavior are locked by bundle/CSS
contract tests; full cross-platform visual screenshots remain Gate 5 work.

## Verification record

- Repository-standard focused regression: `205 passed`, `0 failed`.
- Gate 4 core rerun after final UI adjustments: `20 passed`, `0 failed`.
- Desktop Vitest: `2 passed`; TypeScript and touched-file ESLint pass.
- Ruff, static JavaScript syntax, bundle validation, and `git diff --check`
  pass.
- `uv lock --check` resolves the unchanged 233-package graph.
- Frozen contract lock and OpenAPI/Manifest/Runtime examples remain green.

Gate 4 is accepted. Gate 5 remains unchecked and owns macOS, Windows, Linux,
mobile-width screenshot matrix, browser-open behavior, import/export, uninstall,
and release-package regression.
