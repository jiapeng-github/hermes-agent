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
const TARGETS = {
  'macos-arm64': { arch: 'arm64', platform: 'darwin', script: 'install.sh', uv: 'uv' },
  'windows-x64': { arch: 'x64', platform: 'win32', script: 'install.ps1', uv: 'uv.exe' }
}
const FALSE_VALUES = new Set(['0', 'false', 'no', 'off', 'network', 'thin'])
const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on', 'offline', 'bundled'])
const SOURCE_ARCHIVE_PATHS = [
  '.env.example',
  'LICENSE',
  'MANIFEST.in',
  'acp_adapter',
  'acp_registry',
  'agent',
  'batch_runner.py',
  'cli-config.yaml.example',
  'cli.py',
  'constraints-termux.txt',
  'cron',
  'gateway',
  'hermes',
  'hermes_bootstrap.py',
  'hermes_cli',
  'hermes_constants.py',
  'hermes_logging.py',
  'hermes_state.py',
  'hermes_time.py',
  'locales',
  'mcp_serve.py',
  'mini_swe_runner.py',
  'model_tools.py',
  'optional-mcps',
  'optional-skills',
  'package-lock.json',
  'package.json',
  'plugins',
  'providers',
  'pyproject.toml',
  'run_agent.py',
  'scripts',
  'setup.py',
  'skills',
  'tools',
  'toolset_distributions.py',
  'toolsets.py',
  'trajectory_compressor.py',
  'tui_gateway',
  'utils.py',
  'uv.lock'
]

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
    source_bundled: sourceBundled,
    browser_tools_bundled: false,
    python: '3.11',
    files
  }
  fs.writeFileSync(path.join(outputRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
}

function preparePlaceholder() {
  fs.rmSync(OUTPUT_ROOT, { recursive: true, force: true })
  fs.mkdirSync(OUTPUT_ROOT, { recursive: true })
  writeManifest(null, false, { sourceBundled: false })
}

function prepareSourceBundle(targetName, outputRoot = OUTPUT_ROOT) {
  const target = TARGETS[targetName]
  if (!target) throw new Error(`Unsupported source bundle target: ${targetName || '<none>'}`)

  fs.rmSync(outputRoot, { recursive: true, force: true })
  fs.mkdirSync(outputRoot, { recursive: true })
  fs.copyFileSync(path.join(REPO_ROOT, 'scripts', target.script), path.join(outputRoot, target.script))
  run('git', [
    'archive',
    '--format=zip',
    `--output=${path.join(outputRoot, 'hermes-agent-source.zip')}`,
    'HEAD',
    '--',
    ...SOURCE_ARCHIVE_PATHS
  ])
  writeManifest(targetName, false, { outputRoot, sourceBundled: true })
  console.log(`[prepare-offline-runtime] prepared bundled source for ${targetName} at ${outputRoot}`)
}

function defaultTarget() {
  if (process.platform === 'win32' && process.arch === 'x64') return 'windows-x64'
  if (process.platform === 'darwin' && process.arch === 'arm64') return 'macos-arm64'
  return null
}

function bundleRuntimeEnabled(value = process.env.STOCKSENSE_BUNDLE_RUNTIME) {
  if (value == null || String(value).trim() === '') return true
  const normalized = String(value).trim().toLowerCase()
  if (TRUE_VALUES.has(normalized)) return true
  if (FALSE_VALUES.has(normalized)) return false
  throw new Error(
    `Invalid STOCKSENSE_BUNDLE_RUNTIME=${JSON.stringify(value)}; use 1 for an offline bundle or 0 for a network installer.`
  )
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
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-runtime-'))
  const runtimeEnv = {
    ...process.env,
    UV_CACHE_DIR: prepUvCache,
    UV_HTTP_TIMEOUT: process.env.UV_HTTP_TIMEOUT || '300',
    UV_NO_CONFIG: '1',
    UV_PYTHON_BIN_DIR: path.join(prepRoot, 'bin'),
    UV_PYTHON_INSTALL_DIR: prepPython,
    UV_PROJECT_ENVIRONMENT: path.join(tempRoot, 'venv')
  }
  try {
    run(uvSource, ['python', 'install', '3.11'], { env: runtimeEnv })
    runWithRetries(uvSource, ['sync', '--extra', 'all', '--locked', '--python', '3.11'], { env: runtimeEnv })
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
  if (args.includes('--package-mode') && !bundleRuntimeEnabled()) {
    prepareSourceBundle(target)
    console.log('[prepare-offline-runtime] network installer selected; bundled runtime omitted, source included')
    return
  }
  prepareBundle(target)
}

if (require.main === module) {
  main()
}

module.exports = {
  SOURCE_ARCHIVE_PATHS,
  TARGETS,
  bundleRuntimeEnabled,
  defaultTarget,
  main,
  prepareSourceBundle,
  rebaseCopiedSymlinks
}
