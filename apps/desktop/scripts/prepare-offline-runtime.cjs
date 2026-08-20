'use strict'

const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const APP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(APP_ROOT, '..', '..')
const OUTPUT_ROOT = path.join(APP_ROOT, 'build', 'offline-runtime')
const PREP_CACHE_ROOT = path.join(APP_ROOT, 'build', 'offline-runtime-prep')
const PYTHON_VERSION = '3.11'
const TARGETS = {
  'macos-arm64': { arch: 'arm64', platform: 'darwin', script: 'install.sh', uv: 'uv' },
  'windows-x64': { arch: 'x64', platform: 'win32', script: 'install.ps1', uv: 'uv.exe' }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || REPO_ROOT,
    env: options.env || process.env,
    stdio: 'inherit'
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}`)
  }
}

function runWithRetries(command, args, options = {}, attempts = 3) {
  let lastError = null
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      run(command, args, options)
      return
    } catch (error) {
      lastError = error
      if (attempt < attempts) {
        console.warn(`[prepare-offline-runtime] attempt ${attempt}/${attempts} failed; retrying with cached downloads`)
      }
    }
  }
  throw lastError
}

function resolveCommand(name) {
  const command = process.platform === 'win32' ? 'where.exe' : 'which'
  const result = spawnSync(command, [name], { encoding: 'utf8' })
  if (result.status !== 0) return null
  return result.stdout.split(/\r?\n/).map(value => value.trim()).find(Boolean) || null
}

function walkFiles(root) {
  const files = []
  const stack = [root]
  while (stack.length) {
    const current = stack.pop()
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolute = path.join(current, entry.name)
      if (entry.isDirectory()) stack.push(absolute)
      else if (entry.isFile()) files.push(absolute)
    }
  }
  return files.sort()
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function rebaseCopiedSymlinks(sourceRoot, destinationRoot) {
  const stack = [destinationRoot]
  while (stack.length) {
    const current = stack.pop()
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const destination = path.join(current, entry.name)
      if (entry.isDirectory()) {
        stack.push(destination)
        continue
      }
      if (!entry.isSymbolicLink()) continue
      const linkTarget = fs.readlinkSync(destination)
      if (!path.isAbsolute(linkTarget)) continue
      const relativeSourceTarget = path.relative(sourceRoot, linkTarget)
      if (relativeSourceTarget.startsWith('..') || path.isAbsolute(relativeSourceTarget)) continue
      const rebasedTarget = path.join(destinationRoot, relativeSourceTarget)
      fs.unlinkSync(destination)
      fs.symlinkSync(path.relative(path.dirname(destination), rebasedTarget), destination)
    }
  }
}

// uv maintains a minor-version junction next to its patch-version directories
// on Windows. actions/cache can restore that junction in a form uv cannot
// replace (os error 267), while the patch installation and uv cache remain
// reusable. Remove only this derived link before asking uv to recreate it.
function removeCachedWindowsMinorPythonLink(pythonRoot) {
  if (!fs.existsSync(pythonRoot)) return false
  const minorLinkPattern = /^cpython-\d+\.\d+-windows-(?:x86_64|aarch64)-none$/
  for (const entry of fs.readdirSync(pythonRoot, { withFileTypes: true })) {
    if (!minorLinkPattern.test(entry.name)) continue
    const candidate = path.join(pythonRoot, entry.name)
    try {
      fs.unlinkSync(candidate)
    } catch (error) {
      if (error.code !== 'EISDIR' && error.code !== 'EPERM') throw error
      fs.rmSync(candidate, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 })
    }
    console.log(`[prepare-offline-runtime] removed cached Windows Python minor link: ${entry.name}`)
    return true
  }
  return false
}

function createRuntimeEnv({ prepUvCache, prepPython, tempRoot, baseEnv = process.env }) {
  const runtimeEnv = {
    ...baseEnv,
    UV_CACHE_DIR: prepUvCache,
    UV_HTTP_TIMEOUT: baseEnv.UV_HTTP_TIMEOUT || '300',
    UV_PYTHON_INSTALL_DIR: prepPython,
    UV_PYTHON_INSTALL_BIN: '0',
    UV_PROJECT_ENVIRONMENT: path.join(tempRoot, 'venv')
  }
  // The lockfile includes [tool.uv] resolution settings from pyproject.toml.
  // Disabling project config makes `uv sync --locked` reject that lockfile.
  delete runtimeEnv.UV_NO_CONFIG
  return runtimeEnv
}

// Tiny ARM64 launcher stubs that pip vendors into distlib/setuptools
// (`t64-arm.exe`, `w64-arm.exe`, `cli-arm64.exe`, `gui-arm64.exe`). They are
// dead weight on the x64 runtime AND prime antivirus quarantine bait -- when
// an AV silently removes them post-install, the desktop's whole-bundle SHA
// verification (17k+ files, all-or-nothing) rejects the ENTIRE offline
// runtime and first-launch silently falls back to the network path. Drop
// them from the bundle so the manifest never records them in the first
// place; a file the AV later quarantines that is not in the manifest cannot
// invalidate it.
//
// Matched by basename ANYWHERE in the bundle, not just site-packages: the
// stubs also ride inside uv-cache/archive-v0/<hash>/setuptools wheel
// snapshots (observed in the field: one quarantined
// uv-cache/archive-v0/.../setuptools/cli-arm64.exe invalidated the whole
// runtime). Removing them from the unpacked cache is safe -- uv installs
// from archive-v0 by directory copy without a per-file manifest, and the
// x64 runtime never executes ARM64 launchers either way.
const ANTIVIRUS_BAIT_BASENAMES = new Set(['t64-arm.exe', 'w64-arm.exe', 'cli-arm64.exe', 'gui-arm64.exe'])

function removeAntivirusBaitFiles(root, { walk = walkFiles } = {}) {
  const removed = []
  for (const file of walk(root)) {
    if (!ANTIVIRUS_BAIT_BASENAMES.has(path.basename(file))) continue
    fs.rmSync(file, { force: true })
    removed.push(path.relative(root, file))
  }
  if (removed.length > 0) {
    console.log(`[prepare-offline-runtime] removed ${removed.length} antivirus-bait launcher stub(s)`)
  }
  return removed
}

function writeManifest(target, bundled, { outputRoot = OUTPUT_ROOT, sourceBundled = bundled } = {}) {
  const files = bundled || sourceBundled
    ? Object.fromEntries(
        walkFiles(outputRoot)
          .filter(file => path.basename(file) !== 'manifest.json')
          .map(file => [path.relative(outputRoot, file).replaceAll(path.sep, '/'), sha256(file)])
      )
    : {}
  const manifest = {
    schema_version: 1,
    target,
    bundled,
    cache_bundled: bundled,
    product: 'stocksense-offline-runtime',
    python_bundled: bundled,
    source_bundled: sourceBundled,
    browser_tools_bundled: false,
    python: PYTHON_VERSION,
    files
  }
  fs.writeFileSync(path.join(outputRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
}

function preparePlaceholder() {
  fs.rmSync(OUTPUT_ROOT, { recursive: true, force: true })
  fs.mkdirSync(OUTPUT_ROOT, { recursive: true })
  writeManifest(null, false, { sourceBundled: false })
}

function defaultTarget() {
  if (process.platform === 'win32' && process.arch === 'x64') return 'windows-x64'
  if (process.platform === 'darwin' && process.arch === 'arm64') return 'macos-arm64'
  return null
}

function prepareBundle(targetName) {
  const target = TARGETS[targetName]
  if (!target) throw new Error(`Unsupported offline runtime target: ${targetName || '<none>'}`)
  if (process.platform !== target.platform || process.arch !== target.arch) {
    throw new Error(
      `${targetName} offline resources must be prepared on ${target.platform}/${target.arch}; ` +
        `current host is ${process.platform}/${process.arch}.`
    )
  }

  const uvSource = process.env.STOCKSENSE_UV_BINARY || resolveCommand(target.uv)
  if (!uvSource || !fs.existsSync(uvSource)) {
    throw new Error('uv is required to prepare the offline desktop runtime.')
  }

  const prepRoot = path.join(PREP_CACHE_ROOT, targetName)
  const prepPython = path.join(prepRoot, 'python')
  const prepUvCache = path.join(prepRoot, 'uv-cache')
  if (!fs.existsSync(prepRoot) && fs.existsSync(path.join(OUTPUT_ROOT, 'python'))) {
    fs.mkdirSync(prepRoot, { recursive: true })
    fs.renameSync(path.join(OUTPUT_ROOT, 'python'), prepPython)
    if (fs.existsSync(path.join(OUTPUT_ROOT, 'uv-cache'))) {
      fs.renameSync(path.join(OUTPUT_ROOT, 'uv-cache'), prepUvCache)
    }
  }
  fs.mkdirSync(prepRoot, { recursive: true })
  if (target.platform === 'win32') {
    removeCachedWindowsMinorPythonLink(prepPython)
  }
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-runtime-'))
  const runtimeEnv = createRuntimeEnv({ prepUvCache, prepPython, tempRoot })
  try {
    run(uvSource, ['python', 'install', PYTHON_VERSION], { env: runtimeEnv })
    runWithRetries(uvSource, ['sync', '--extra', 'all', '--locked', '--python', PYTHON_VERSION], { env: runtimeEnv })
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }

  fs.rmSync(OUTPUT_ROOT, { recursive: true, force: true })
  fs.mkdirSync(path.join(OUTPUT_ROOT, 'bin'), { recursive: true })
  fs.copyFileSync(uvSource, path.join(OUTPUT_ROOT, 'bin', target.uv))
  fs.copyFileSync(path.join(REPO_ROOT, 'scripts', target.script), path.join(OUTPUT_ROOT, target.script))
  run('git', ['archive', '--format=zip', `--output=${path.join(OUTPUT_ROOT, 'hermes-agent-source.zip')}`, 'HEAD'])
  fs.cpSync(prepPython, path.join(OUTPUT_ROOT, 'python'), { recursive: true, verbatimSymlinks: true })
  fs.cpSync(prepUvCache, path.join(OUTPUT_ROOT, 'uv-cache'), { recursive: true, verbatimSymlinks: true })
  rebaseCopiedSymlinks(prepPython, path.join(OUTPUT_ROOT, 'python'))
  rebaseCopiedSymlinks(prepUvCache, path.join(OUTPUT_ROOT, 'uv-cache'))

  // Must run BEFORE writeManifest: the manifest hashes whatever is on disk,
  // so the stubs have to be gone for the bundle (and its per-file hash set)
  // to never mention them at all.
  removeAntivirusBaitFiles(OUTPUT_ROOT)

  writeManifest(targetName, true, { sourceBundled: true })
  console.log(`[prepare-offline-runtime] prepared ${targetName} at ${OUTPUT_ROOT}`)
}

function main(args = process.argv.slice(2)) {
  if (args.includes('--placeholder')) {
    preparePlaceholder()
    return
  }
  const targetIndex = args.indexOf('--target')
  const target = targetIndex >= 0 ? args[targetIndex + 1] : process.env.STOCKSENSE_RUNTIME_TARGET || defaultTarget()
  prepareBundle(target)
}

if (require.main === module) {
  main()
}

module.exports = {
  ANTIVIRUS_BAIT_BASENAMES,
  TARGETS,
  createRuntimeEnv,
  defaultTarget,
  main,
  removeAntivirusBaitFiles,
  removeCachedWindowsMinorPythonLink,
  rebaseCopiedSymlinks
}
