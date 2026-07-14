# App Runtime contract notes

The authoritative files are packaged under `hermes_cli/apps/contracts/`. Do not change them while implementing an application.

## Package structure

Publishable workspace content uses:

```text
app.yaml
icon.png | icon.webp | icon.jpg | assets/<icon>
dist/
source/          # editable applications only
prompts/         # Agent actions
schemas/         # Draft 2020-12 Action schemas
assets/
tests/
screenshots/
```

Do not add runtime server code, `.env`, credentials, package caches, `node_modules`, logs, or application data.

## Action selection

- **MCP:** Fix `server` and `tool` in the Manifest. Browser input may fill only validated arguments. Request the exact server in `permissions.mcp_servers`.
- **Agent:** Keep the prompt byte-stable for the version. Treat browser input as untrusted content. Default to stateless mode and set timeout, iteration, concurrency, cache, and output schema limits.
- **Service:** Reserved for exact runtime-owned built-in lineage. User-created, copied, and imported applications cannot declare it.

Every referenced prompt and schema must remain inside the application root. Do not use absolute paths, `..`, symlinks, or case-colliding names.

## Permissions

Request the minimum set in `app.yaml`. Publication preserves only previously granted capabilities that remain a subset of the new request; newly requested capabilities remain ungranted. Import Confirm grants only the exact subset chosen by the user.

Keep persistent storage at 10 MB or less unless the data model demonstrates a larger need. Never store secrets or duplicate Hermes configuration.

## Browser boundary

AppHost applies a self-only CSP and rejects inline scripts, inline styles, remote executable resources, frames, objects, workers, cross-origin requests, invalid Host headers, and mutations without Origin and CSRF proof. Use external local CSS and JavaScript files under `dist/`.

Application JavaScript receives only Runtime bootstrap descriptors and declared actions. It must never receive the desktop management token, model credentials, MCP credentials, local filesystem access, or generic Hermes API access.
