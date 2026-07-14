# Hermes AppHost Threat Model v1

Status: **Gate 2 accepted**
Scope: phase-1 local desktop AppHost and `.happ` import
Updated: `2026-07-12`

## Security objective

An untrusted browser application may render its own packaged frontend and call
only the actions and storage capabilities explicitly requested by its frozen
Manifest and granted by the user. It must never obtain Hermes management
credentials, model or MCP credentials, another application's identity or
data, arbitrary local files, a generic agent endpoint, terminal access, or
custom server-side code execution.

Gate 2 establishes the boundary but does not connect actions to real Agent or
MCP execution. That adapter remains disabled until every invariant and attack
test in this document passes.

## Assets

- Hermes dashboard session tokens, Runtime cookies, launch codes, CSRF tokens,
  API keys, MCP credentials, prompts, and hidden reasoning.
- Profile-scoped application packages, grants, registry revisions, versions,
  source trees, and application data.
- Integrity and availability of the local Hermes backend and other AppHosts.
- User intent at import, permission grant, launch, update, and copy time.

## Trust boundaries

1. **Desktop to management API.** The desktop holds the existing authenticated
   management credential. Browser applications never receive it.
2. **Browser to per-app AppHost.** One `app_id` uses one dedicated loopback
   origin. Identity comes only from an HttpOnly Runtime cookie minted after a
   one-time launch-code exchange.
3. **AppHost to Action Gateway.** The gateway will accept only Manifest actions
   that also pass persisted grants and runtime policy. This boundary is closed
   during Gate 2.
4. **`.happ` to installed package.** Archive bytes are hostile until the
   analyze phase validates paths, limits, metadata, checksums, Manifest, and
   capability policy. Confirm revalidates the same bytes before atomic install.
5. **Profile boundary.** Registry, packages, import plans, and app data resolve
   from the active `HERMES_HOME`; no global application registry exists.

## Attacker model

The design assumes an attacker can author a malicious `.happ`, control every
byte of its HTML/JavaScript and metadata, send arbitrary HTTP requests to
loopback, host a public website visited by the user, race analyze and confirm,
and tamper with staged files between those phases. It also assumes accidental
package corruption, crashes, retries, and concurrent Hermes processes.

A process already executing as the same OS user can read Hermes files and
debug browser processes; defending against full same-user compromise is out of
scope. AppHost still avoids creating ambient credentials or network exposure
that would make such compromise easier.

## Threats and required controls

| Threat | Required control |
|---|---|
| DNS rebinding or hostile Host | Bind only `127.0.0.1`; require the exact Host and port; reject non-loopback peers |
| Cross-site request forgery | HttpOnly SameSite=Strict cookie plus exact Origin, `Sec-Fetch-Site`, and short-lived CSRF token on every mutation |
| Launch URL replay | At least 256 random bits; store only a digest; 30-second TTL; consume exactly once; redirect to a clean URL |
| Cross-app confused deputy | Dedicated origin and session store per app; unique cookie name per AppHost because browser cookies ignore ports; browser never supplies `app_id` |
| Credential or prompt disclosure | Bootstrap contains only public descriptors and grants; sanitize errors; disable AppHost access logs; `Referrer-Policy: no-referrer` |
| Remote script, frame, or persisted worker abuse | Strict self-only CSP, no CORS, `worker-src 'none'`, `frame-ancestors 'none'`, `object-src 'none'`, no `eval`, no CDN dependencies |
| Static path escape | Lexical validation, exact-case resolution, canonical containment, symlink rejection, immutable installed versions |
| Generic backend access | AppHost exposes only frozen Runtime routes; no proxy to dashboard `/api`, WebSocket, terminal, files, or configuration |
| Zip Slip and special files | Validate the complete central directory before streaming extraction; reject traversal, duplicates, links, devices, and executable modes |
| Decompression denial of service | Frozen compressed, uncompressed, entry, per-file, and compression-ratio limits enforced before and during streaming |
| Analyze/confirm TOCTOU | Persist the package digest in an immutable plan; confirm hashes and fully revalidates staged package bytes |
| Manifest privilege escalation | Reject authority fields, custom backend code, undeclared MCP/Agent use, and all imported `service` actions |
| Permission escalation at confirm | Grants must be an equal or narrower subset of Manifest requests; signature state never grants capability |
| Version overwrite or race | Profile-scoped cross-process lock, immutable version directory, checksum conflict check, atomic rename, atomic registry revision |
| Partial install after crash | Install from same-filesystem staging; update registry only after rename; roll back the moved version if registry commit fails |

## AppHost invariants

- The listener address is exactly `127.0.0.1`; wildcard, IPv6 wildcard, LAN,
  and hostname binds are rejected.
- The expected origin includes the random port. Host and Origin comparisons
  are exact after standards-based parsing; suffix and substring matches are
  forbidden.
- Launch-code, Runtime-session, and CSRF expiry use the process monotonic
  clock; wall-clock rollback cannot extend their authority.
- Runtime cookies are session cookies with `HttpOnly`, `SameSite=Strict`, and
  `Path=/`. Cookie names are unique per AppHost because cookies do not isolate
  by port. They are not dashboard cookies and their authority dies with
  AppHost state.
- CSRF tokens are HMAC-bound to one Runtime session and a ten-minute time
  bucket. Only the current and immediately previous bucket are accepted.
- Static HTML and API responses receive the frozen security headers. AppHost
  emits no `Access-Control-Allow-Origin` header. Static responses use
  `Cache-Control: no-store`, and workers are disabled so a later reuse of the
  same ephemeral port cannot inherit code from a previous application. The
  entry response sends `Clear-Site-Data: "storage"`; applications must use
  namespaced Runtime storage instead of ambient localStorage or IndexedDB.
- A missing, expired, malformed, or foreign credential fails closed without
  revealing whether an action, package, or other application exists.

## `.happ` invariants

- Analyze never creates or changes an installed version or registry entry.
- Import-plan directories contain only the uploaded package and plan metadata;
  plan IDs are UUIDs, expire after 15 minutes, and are profile scoped.
- Confirm never trusts analyze-time extraction. It reopens and revalidates the
  staged archive into a fresh directory.
- The checksums file names every regular package file except itself and the
  optional signature, exactly once and in canonical order.
- `install`, `update`, and `copy` are explicit conflict modes. The same version
  with a different package checksum is never overwritten.
- Installed package versions exclude transport metadata (`happ.json`,
  `checksums.json`, and `signature.json`) and are treated as immutable.
- Permission grants, Runtime data, credentials, logs, and trust decisions are
  never imported from archive content.

## Gate 2 attack-test map

| Surface | Test module |
|---|---|
| Launch code, cookies, CSRF, Host, Origin, cross-app session | `tests/apps/test_runtime_auth.py` |
| CSP, MIME, traversal, exact case, symlink, route isolation | `tests/apps/test_runtime_static.py` |
| Zip Slip, links, duplicate paths, checksum, bombs, limits | `tests/apps/test_package.py` |
| Analyze/confirm separation, expiry, tamper, grants, conflicts, atomic install | `tests/apps/test_imports.py` |
| Profile paths, registry revision, immutable versions, concurrent lock | `tests/apps/test_registry.py` |

## Residual risk and next gate

Application JavaScript is intentionally untrusted and can misuse capabilities
the user chose to grant. Permission copy must therefore be specific and
revocable, action inputs and outputs must be schema- and size-limited, and the
future Action Gateway must add concurrency, timeout, cancellation, event
sanitization, and rate controls. Those execution controls are required before
real Agent or MCP adapters are enabled. Imported source is inert data: Hermes
must never automatically run `package.json` scripts, shell hooks, test commands,
or dependency installers from a `.happ` package.

## Acceptance record

Repository-standard App Platform regression on `2026-07-12` completed with
`121 passed`, `0 failed`, and `1 skipped`. The skipped case is the only test
that opens a real random `127.0.0.1` listener, which the managed sandbox blocks
with `EPERM`. The same
`test_real_apphost_binds_random_ipv4_loopback_and_stops` case then passed in
the approved host environment (`1 passed`, `0 failed`), proving the listener
binds to IPv4 loopback, serves the isolated AppHost, stops, and releases its
port. TestClient coverage for launch exchange, Host, Origin, cookie, CSRF,
cross-app isolation, CSP, and static confinement also passed.

Gate 2 is accepted. The Action Gateway intentionally remains hard-disabled
with `APP_ACTION_GATEWAY_DISABLED`; Gate 2 makes the boundary eligible for the
next implementation gate but does not itself connect user applications to
real Agent or MCP execution.
