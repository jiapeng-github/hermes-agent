# Framework mapping

Prefer the smallest StockSense-native frontend that preserves the requested behavior. The source framework is evidence, not a requirement.

| Source pattern | Default treatment | Notes |
|---|---|---|
| Static HTML/CSS/JS | Adapt | Move inline code/styles into local files and remove remote executable resources. |
| React/Vite | Adapt selectively | Prefer a fresh `dashboard` template and reviewed components. Keep dependencies minimal. |
| Vue/Svelte client SPA | Adapt or reconstruct | Keep only if the build chain is small and AppHost constraints are met; otherwise translate into the standard template. |
| Next.js/Nuxt/SvelteKit SSR | Reconstruct client surface | Remove server routes, SSR, middleware, image proxies, and server actions. |
| Electron/Tauri/native desktop | Reconstruct web surface | Native APIs, sidecars, file access, and bundled servers are unsupported. |
| Browser extension | Reconstruct ordinary web surface | Extension permissions, content scripts, background workers, and page injection are unsupported. |
| Full-stack monorepo | Isolate or reconstruct | Never package backend workspaces. Reuse only reviewed, separable frontend code. |
| Python/Node backend UI | Reconstruct | Replace eligible data and analysis behavior with declared MCP/Agent actions. |
| Prebuilt/minified bundle only | Usually reconstruct | Do not rely on opaque code. Require source and license for direct adaptation. |

## Backend replacement rules

- Fixed financial market or company data query: use a fixed `mx-ds-mcp` server/tool action when the tool contract fits.
- Natural-language analysis or synthesis: use an Agent action with a stable prompt, strict schema, bounded timeout/iterations/concurrency, and untrusted-input delimiters.
- Preferences and small collections: use App storage; do not create a database service.
- OAuth/login/account systems: remove or redesign around local App state and Hermes-managed capabilities. Do not collect credentials in the App.
- File upload: support only when the frozen Runtime contract and declared action schema explicitly allow it; otherwise omit.
- Realtime sockets, background jobs, queues, webhooks, and scheduled servers: unsupported in an imported/user App. Consider StockSense scheduled tasks as a separate platform feature, not App backend code.

## Frontend hardening checklist

- No inline script/style/event handlers.
- No remote scripts, styles, fonts, frames, objects, workers, or cross-origin fetches.
- No secret/config injection into browser bundles.
- No dynamic code evaluation or HTML injection from action results.
- All assets are local, attributable, and included in package validation.
- Runtime calls reference only Manifest-declared action IDs.
- Empty, loading, partial, denied, timeout, and malformed-result states are visible and usable.
- Layout works in supported desktop browsers at narrow and wide widths.
