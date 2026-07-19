# StockSense Desktop ☤

<p align="center">
  <a href="https://github.com/NousResearch/hermes-agent/releases"><img src="https://img.shields.io/badge/Download-macOS%20%C2%B7%20Windows%20%C2%B7%20Linux-FFD700?style=for-the-badge" alt="Download"></a>
  <a href="https://hermes-agent.nousresearch.com/docs/"><img src="https://img.shields.io/badge/Docs-hermes--agent.nousresearch.com-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/NousResearch/hermes-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

**The native desktop app for [StockSense](../../README.md) — the self-improving AI agent from [Nous Research](https://nousresearch.com).** Same agent, same skills, same memory as the CLI and gateway, in a polished native window — chat with streaming tool output, side-by-side previews, a file browser, voice, and settings, no terminal required. Available for **macOS, Windows, and Linux**.

<table>
<tr><td><b>Chat with the full agent</b></td><td>Streaming responses, live tool activity, structured tool summaries, and the same conversation history as every other StockSense surface.</td></tr>
<tr><td><b>Side-by-side previews</b></td><td>Render web pages, files, and tool outputs in a right-hand pane while you keep chatting.</td></tr>
<tr><td><b>File browser</b></td><td>Explore and preview the working directory without leaving the app.</td></tr>
<tr><td><b>Voice</b></td><td>Talk to StockSense and hear it back.</td></tr>
<tr><td><b>Settings & onboarding</b></td><td>Manage providers, models, tools, and credentials from a real UI. First-run setup gets you to your first message in seconds.</td></tr>
<tr><td><b>Stays current</b></td><td>Built-in updates pull the latest agent and rebuild the app in place.</td></tr>
</table>

---

## Install

### Install with StockSense (recommended)

Already have the StockSense CLI? Just run:

```bash
stocksense desktop
```

It builds and launches the GUI against your existing install — same config, keys, sessions, and skills. On first launch StockSense walks you through picking a provider and model; nothing else to configure.

### Prebuilt installers

Prebuilt installers are built and distributed via [the StockSense Desktop website.](https://hermes-agent.nousresearch.com/).

---

## Updating

The app checks for updates in the background and offers a one-click update when one is ready. You can also update any time from the CLI:

```bash
hermes update
```

---

## Requirements

The installer handles everything for you (Python 3.11+, a portable Git, ripgrep).

---

## Development

Want to hack on the app itself? Install workspace deps from the repo root once, then run the dev server from this directory:

```bash
npm install          # from repo root — links apps/desktop, web, apps/shared
cd apps/desktop
npm run dev          # Vite renderer + Electron, which boots the Python backend
```

Point the app at a specific source checkout, or sandbox it away from your real config:

```bash
HERMES_DESKTOP_HERMES_ROOT=/path/to/clone npm run dev
HERMES_HOME=/tmp/throwaway npm run dev
npm run dev:fake-boot   # exercise the startup overlay with deterministic delays
```

### Building installers

```bash
npm run dist:mac          # macOS arm64 offline DMG + zip
npm run dist:mac:thin     # macOS arm64 network-bootstrap DMG + zip
npm run dist:win          # Windows x64 offline NSIS exe
npm run dist:win:thin     # Windows x64 network-bootstrap NSIS exe
npm run pack         # unpacked app under release/ (no installer)
```

The release matrix intentionally supports only `macos-arm64` and `windows-x64`. `STOCKSENSE_BUNDLE_RUNTIME` controls whether release builds include the native runtime. It defaults to `1`; set it to `0` for the original lightweight installer that downloads dependencies on first launch. The `:thin` commands above are cross-platform shortcuts for the `0` setting. Artifacts include an `offline` or `network` suffix so the two flavors do not overwrite each other.

Every release includes the pinned Hermes source archive and platform installer, so first launch never depends on cloning or downloading source from GitHub. Offline release commands additionally prepare uv, Python 3.11, and the locked Python dependency cache before Electron Builder runs. Because Python runtimes and wheels are platform-specific, prepare and package offline installers on their matching native host; cross-building the Windows offline installer from macOS is not supported. Thin installers omit platform Python resources and download only the runtime dependencies during bootstrap.

On Apple Silicon macOS, `npm run dist:win:thin` can cross-build the Windows x64 NSIS installer when Wine and Rosetta 2 are available. The build stages `win32-x64` native Node bindings explicitly instead of copying the macOS host bindings. If GitHub downloads time out, use the Electron and Electron Builder binary mirrors:

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/ \
npm run dist:win:thin
```

This cross-build path intentionally produces the `network` flavor. Run `npm run dist:win` on a Windows x64 host when the installer must include the Windows Python runtime and wheel cache.

The bundled runtime is used on first launch before any network fallback. Node workspace dependencies, Playwright Chromium, ripgrep, and ffmpeg are not installed during desktop bootstrap. Default apps open in the user's system browser, so no browser binary is required in the installer; browser automation dependencies remain an on-demand installation. Installers are built and uploaded to GitHub Releases manually. macOS/Windows signing and notarization happen automatically when the relevant credentials are present in the environment (`CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_*` for macOS, `WIN_CSC_*` for Windows).

Downloaded release inputs are retained under `build/offline-runtime-prep/<target>` so a failed release preparation can resume without downloading Python and completed wheels again. The final verified resource tree is assembled under `build/offline-runtime` only after `uv sync` succeeds.

Equivalent parameter form:

```bash
STOCKSENSE_BUNDLE_RUNTIME=1 npm run dist:mac  # offline, also the default
STOCKSENSE_BUNDLE_RUNTIME=0 npm run dist:mac  # network bootstrap
```

### How it works

The packaged app ships the Electron shell and a native React chat surface. On first launch it can install the StockSense runtime into `HERMES_HOME` (`~/.hermes`, or `%LOCALAPPDATA%\hermes` on Windows) — the **same layout a CLI install uses**, so the two are interchangeable. Backend resolution first honours `HERMES_DESKTOP_HERMES_ROOT`, then a completed managed install, then a probed `hermes` on `PATH` (unless `HERMES_DESKTOP_IGNORE_EXISTING=1` is set), and finally an explicit `HERMES_DESKTOP_HERMES` command override for packagers/troubleshooting. The renderer (React, in `src/`) talks to a headless backend the app launches for you — a `hermes serve` process that serves the `tui_gateway` JSON-RPC/WebSocket API — through the framework-agnostic client in [`apps/shared`](../shared/) (the same client the web dashboard consumes), and reuses the agent runtime rather than embedding `hermes --tui`. The app is **self-contained**: it runs its own `hermes serve` backend and never opens or requires the web dashboard UI. (For backward compatibility, a runtime that predates the `serve` command automatically falls back to a headless `dashboard --no-open` — see `electron/backend-command.cjs` — so mid-upgrade installs never break.) The install, backend-resolution, and self-update logic all live in `electron/main.cjs`.

### Verification

Run before opening a PR (lint may surface pre-existing warnings but must exit cleanly):

```bash
npm run fix
npm run typecheck
npm run lint
npm run test:desktop:all
```

### Troubleshooting

Boot logs land in `HERMES_HOME/logs/desktop.log` (includes backend output and recent Python tracebacks) — check it first if the app reports a boot failure.

**macOS / Linux:**

```bash
# Force a clean first-launch setup
rm "$HOME/.hermes/hermes-agent/.hermes-bootstrap-complete"
# Rebuild a broken Python venv
rm -rf "$HOME/.hermes/hermes-agent/venv"
# Reset a stuck macOS microphone prompt (macOS only)
tccutil reset Microphone com.nousresearch.hermes
```

**Windows (PowerShell):**

```powershell
# Force a clean first-launch setup
Remove-Item "$env:LOCALAPPDATA\hermes\hermes-agent\.hermes-bootstrap-complete"
# Rebuild a broken Python venv
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\hermes\hermes-agent\venv"
```

> The default Hermes home on Windows is `%LOCALAPPDATA%\hermes`. Set the `HERMES_HOME` env var if you've relocated it.

---

## Community

- 💬 [Discord](https://discord.gg/NousResearch)
- 📖 [Documentation](https://hermes-agent.nousresearch.com/docs/)
- 🐛 [Issues](https://github.com/NousResearch/hermes-agent/issues)

---

## License

MIT — see [LICENSE](../../LICENSE).

Built by [Nous Research](https://nousresearch.com).
