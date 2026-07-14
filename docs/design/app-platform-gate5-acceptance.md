# App Platform Gate 5 Acceptance

Date: 2026-07-13

Gate 5 freezes release hardening for the phase-1 local App Platform. Remote
Gateway support and custom application backends remain outside the phase-1
boundary.

## Delivered surface

- The desktop sidebar and command palette expose Application Market directly
  below Skills and Tools. The market has a sticky header, search, responsive
  cards, browser launch, app-builder session handoff, two-phase import review,
  export, and uninstall controls.
- Electron owns `.happ` open/save dialogs and streams package bytes directly to
  the authenticated local backend. Renderer code receives only an Import Plan
  or save result. Package operations reject remote/non-loopback backends,
  symlinks, unsafe destinations, oversized bytes, and stalled requests.
- Browser launch accepts only one-time `http://127.0.0.1:<port>/launch/...`
  AppHost URLs before delegating to the operating-system browser.
- The frozen management API now serves detail, export, analyze/get/discard/
  confirm import, uninstall, and app-data deletion. Uninstall stops AppHost,
  rejects built-ins, preserves data by default, and rolls package/data paths
  back if the registry commit fails.
- Concurrent first-list requests reuse the winning atomic built-in installation
  instead of surfacing a version conflict.
- Wheel and sdist metadata include all contracts and first-party application
  assets. The post-Gate-5 finance migration wheel was inspected and contains
  all three built-in application bundles.

## Cross-platform matrix

- macOS, Windows, and Linux path rules cover Unicode, spaces, `.happ` extension
  normalization, Profile isolation, and traversal-shaped identifiers.
- The existing desktop platform suite covers backend ports, Windows PATH and
  child process behavior, WSL, native window bounds, update/uninstall scripts,
  and packaged runtime resolution. AppHost additionally binds a real random
  IPv4 loopback port and releases it after stop.
- Browser opening is table-tested for darwin, win32, and linux through the same
  OS shell adapter. App launch and package transport cannot use remote URLs.
- Export replacement is recoverable on final-rename failure; uninstall registry
  failure restores both package and data directories.

## Verification record

- App Platform, finance parity, and packaging regression: 172 passed, 1 skipped.
- Existing Electron platform regression: 308 passed, 1 skipped.
- Gate 5 Electron app bridge/browser tests: 10 passed.
- Desktop Application Market and launch Vitest: 4 passed.
- Final contract/lifecycle/packaging rerun: 29 passed, 1 skipped.
- TypeScript, touched-file ESLint, Ruff, `uv lock --check`, desktop production
  build, postbuild assertions, and `git diff --check` pass.
- Real wheel build succeeds and includes the frozen contracts plus built-in
  watchlist HTML, JavaScript, CSS, icon, Manifest, and Action schemas.
- Browser DOM inspection at 1440 x 900 confirms three cards, sticky header at
  top, no horizontal overflow, no button overlap, and no text overflow.

The in-app browser refused the additional 640-pixel localhost viewport by local
security policy, and the locked macOS session prevented native screenshot
capture. No bypass was attempted. Narrow behavior remains covered by the
responsive CSS contract (`640px` and `980px` breakpoints), component tests, and
the production build; the frozen Gate 5 criteria do not depend on retaining a
screenshot artifact.

Gate 5 is accepted. The phase-1 local App Platform release gates are complete.

## Post-Gate-5 finance application migration

Date: 2026-07-14

- `ai.hermes.industry-monitor` and `ai.hermes.company-analysis` join
  `ai.hermes.watchlist` as runtime-owned default applications in Application
  Market. All three install atomically per Profile and report `builtin` trust.
- Industry Monitor inherits only `finance.industry.snapshot` and
  `finance.industry.refresh`. Its browser UI keeps the cached-first asynchronous
  refresh model and presents market breadth, dynamic topic/industry rotation,
  main-fund strength, northbound turnover, and research views.
- Company Analysis inherits only `finance.company.analysis` and
  `finance.company.refresh`. Its browser UI supports company-name or stock-code
  search, financial/profitability visuals, valuation, capital quality, peers,
  complete risk bullets, and compact research cards with a full-content dialog.
- The legacy desktop sidebar rows, command-palette commands, and React routes
  for Industry Monitor, Company Analysis, and Watchlist were removed. Financial
  experiences now have one discoverable entry point: Application Market.
- The market remains metadata-only until a user opens an application; opening
  starts the same loopback-only AppHost and delegates to the operating-system
  browser.

Migration verification:

- App Platform, finance, and packaging regression: 168 passed, 2 skipped.
- Built-in AppHost service-registry matrix: 3 passed.
- Desktop Application Market and launch Vitest: 4 passed.
- Electron app browser/package bridge: 10 passed.
- TypeScript, touched-file ESLint, Ruff, production build, postbuild assertions,
  JSON Schema validation, JavaScript syntax checks, and `git diff --check` pass.
- A real wheel build contains 37 first-party catalog files: 10 Industry Monitor,
  10 Company Analysis, and 17 Watchlist files.

The in-app browser again rejected the localhost visual-preview URL under its
local navigation policy. No bypass was attempted. Responsive behavior is
covered by the `640px` and `980px` CSS contracts, application-market component
tests, DOM/content checks, and the production build.
