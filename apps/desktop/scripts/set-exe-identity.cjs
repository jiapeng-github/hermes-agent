#!/usr/bin/env node
// set-exe-identity.cjs — stamp the Hermes icon + version metadata onto the
// built Hermes.exe using rcedit, completely decoupled from electron-builder's
// signing path.
//
// WHY THIS EXISTS
// ---------------
// apps/desktop/package.json sets build.win.signExecutable=false. Modern
// electron-builder still applies icon and version resources with its pure-JS
// resedit path while skipping signing and winCodeSign downloads. This script
// remains as a Windows-host fallback for older builder installations.
//
// HOW IT RUNS
// -----------
// It is invoked by the electron-builder `afterPack` hook on Windows hosts.
// Cross-builds use electron-builder's platform-independent resource editor,
// because rcedit's Wine launcher is not reliable across Wine distributions.
//
// Also runnable standalone for ad-hoc re-stamping:
//   node scripts/set-exe-identity.cjs <path-to-Hermes.exe>
//
// Exits 0 on success, non-zero on failure when run as a CLI. As a hook,
// stampExeIdentity() resolves on success and rejects on failure; the caller
// (after-pack.cjs) swallows the rejection so a stamp failure never fails an
// otherwise-good build (worst case: stock icon, not a broken app).

const path = require('node:path')
const fs = require('node:fs')

// Stamp the Hermes icon + identity onto `exe`. Resolves on success, throws on
// failure. `desktopRoot` defaults to this script's package root so the icon and
// the rcedit dependency resolve regardless of cwd.
async function stampExeIdentity(exe, desktopRoot = path.resolve(__dirname, '..')) {
  if (!exe || !fs.existsSync(exe)) {
    throw new Error(`target exe not found: ${exe}`)
  }

  // Icon lives at apps/desktop/assets/icon.ico
  const icon = path.join(desktopRoot, 'assets', 'icon.ico')
  if (!fs.existsSync(icon)) {
    throw new Error(`icon not found: ${icon}`)
  }

  // rcedit is a direct devDependency of apps/desktop, so it resolves whether
  // we're run from the desktop dir or the repo root (workspace hoist).
  // rcedit@5 exports a NAMED `rcedit` function (CommonJS: { rcedit }), not a
  // default export.
  const mod = require('rcedit')
  const rcedit = typeof mod === 'function' ? mod : mod.rcedit
  if (typeof rcedit !== 'function') {
    throw new Error(`unexpected rcedit export shape: ${typeof mod} keys=${Object.keys(mod)}`)
  }

  console.log(`[set-exe-identity] stamping ${exe}`)
  console.log(`[set-exe-identity] icon: ${icon}`)

  await rcedit(exe, {
    icon,
    'version-string': {
      ProductName: 'StockSense',
      FileDescription: 'StockSense',
      CompanyName: 'Nous Research',
      LegalCopyright: 'Copyright (c) 2026 Nous Research'
    }
  })

  console.log('[set-exe-identity] done — Hermes icon + identity stamped')
}

module.exports = { stampExeIdentity }

// CLI entry point: `node scripts/set-exe-identity.cjs <exe>`.
if (require.main === module) {
  const exe = process.argv[2]
  if (!exe) {
    console.error('[set-exe-identity] usage: set-exe-identity.cjs <path-to-exe>')
    process.exit(2)
  }
  stampExeIdentity(exe).catch(err => {
    console.error(`[set-exe-identity] ${err.message}`)
    process.exit(1)
  })
}
