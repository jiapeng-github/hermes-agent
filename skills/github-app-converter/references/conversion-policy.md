# Conversion policy

Use this policy after the read-only repository inventory. A repository may move to a more restrictive class as inspection reveals new facts.

## Class A: direct adaptation

Appropriate when all essential behavior can run as static browser code plus declared StockSense Runtime actions.

Typical evidence:

- static HTML/CSS/JavaScript or a conventional client-only React/Vue/Svelte/Vite application;
- no required server-side rendering, custom authentication service, database, daemon, queue, or native module;
- remote data calls have a small, explicit mapping to approved MCP or Agent actions;
- license permits the intended adaptation and distribution.

Reuse reviewed source selectively. Rebuild the package and Manifest through `app-builder`; never wrap an existing `dist/` blindly.

## Class B: runtime replacement

Appropriate when the frontend is separable but depends on a backend that can be replaced without changing the product's essential purpose.

Create an endpoint mapping table with these columns:

| Source behavior | Inputs | Outputs | State | StockSense replacement | Permission | Difference |
|---|---|---|---|---|---|---|

Allowable replacements are fixed-tool MCP actions, bounded Agent actions, small App storage, and versioned local assets. Reject generic HTTP proxy actions and dynamic MCP server/tool selection from browser input.

## Class C: reconstruction

Use when implementation reuse would preserve unsafe architecture or cost more than rebuilding the user-visible behavior. Examples include server-rendered frameworks tightly coupled to database sessions, desktop/native shells, complex monorepos, or generated/minified-only source.

Treat screenshots, public documentation, and reviewed behavior as requirements. Build a new App with `app-builder`. Reuse code or assets only when license and provenance are clear.

## Class D: blocked

Stop conversion when any essential condition remains unresolved:

- missing or incompatible redistribution license;
- secrets, suspicious persistence/exfiltration behavior, obfuscated executable payloads, or unclear provenance;
- essential custom backend, arbitrary outbound networking, native executable, browser extension privilege, iframe, worker, or unsupported runtime;
- dependency or asset cannot be redistributed and has no acceptable replacement;
- repository cannot be pinned to an immutable commit.

Explain the blocker and propose a clean-room reconstruction or narrower App only when that alternative is legitimate.

## Approval checkpoints

Explicit user approval is required before:

- executing repository or dependency scripts;
- installing dependencies from an unreviewed lockfile;
- adding Agent/MCP/storage permissions;
- materially reducing or changing promised behavior;
- publishing, replacing an installed App, or exporting a distributable package.

Approval does not override AppHost restrictions or permit custom backend code.
