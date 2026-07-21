// Resolve electronDist at runtime (#38673, #47917): electron-builder 26.8.x can
// re-unpack a broken Electron.app; reusing the installed dist dodges that.
// npm workspace hoisting is non-deterministic — require.resolve finds electron
// wherever it landed. Dist present → -c.electronDist=<abs>/dist; absent → let
// electron-builder fetch via @electron/get (electronVersion + ELECTRON_MIRROR).
//
// Cross-platform builds (e.g. --win on darwin) must NOT reuse the local Electron
// dist — the host platform's binary doesn't match the target.

import fs from "node:fs"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)

function electronDistDir() {
  try {
    return path.join(path.dirname(require.resolve("electron/package.json")), "dist")
  } catch {
    return null
  }
}

function distBinary(dist) {
  if (process.platform === "darwin") {
    return path.join(dist, "Electron.app", "Contents", "MacOS", "Electron")
  }
  if (process.platform === "win32") {
    return path.join(dist, "electron.exe")
  }
  return path.join(dist, "electron")
}

function electronBuilderCli() {
  const pkgJson = require.resolve("electron-builder/package.json")
  const bin = require(pkgJson).bin
  const rel = typeof bin === "string" ? bin : bin["electron-builder"]
  return path.join(path.dirname(pkgJson), rel)
}

function runtimeFlavor() {
  const manifestPath = path.resolve(__dirname, "..", "build", "offline-runtime", "manifest.json")
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"))
    return manifest && manifest.bundled === true ? "offline" : "network"
  } catch {
    return "network"
  }
}

const args = process.argv.slice(2)

// Detect cross-platform build: if any target platform flag differs from the
// host platform, skip the local electron dist.
const crossTarget = args.some(a => {
  if (a === '--win' || a === '--linux') return process.platform !== 'win32'
  if (a === '--mac' || a === '--macos') return process.platform !== 'darwin'
  return false
})
const noCross = !args.includes('--win') && !args.includes('--linux') && !args.includes('--mac')

const dist = electronDistDir()
const builderArgs = []
if (!args.some(arg => arg.includes("artifactName"))) {
  const flavor = runtimeFlavor()
  builderArgs.push(`-c.artifactName=StockSense-\${version}-\${os}-\${arch}-${flavor}.\${ext}`)
  console.log(`[run-electron-builder] packaging ${flavor} runtime flavor`)
}
if (dist && fs.existsSync(distBinary(dist)) && (noCross || !crossTarget)) {
  builderArgs.push(`-c.electronDist=${dist}`)
} else if (crossTarget) {
  console.warn(
    "[run-electron-builder] cross-platform build detected; letting electron-builder " +
      "fetch the target platform's Electron binary via @electron/get."
  )
} else {
  console.warn(
    "[run-electron-builder] no local electron dist; electron-builder will fetch " +
      "via @electron/get (electronVersion + ELECTRON_MIRROR)."
  )
}
builderArgs.push(...args)

const result = spawnSync(process.execPath, [electronBuilderCli(), ...builderArgs], {
  stdio: "inherit",
})
if (result.error) {
  console.error(`[run-electron-builder] spawn failed: ${result.error.message}`)
  process.exit(1)
}
process.exit(result.status == null ? 1 : result.status)
