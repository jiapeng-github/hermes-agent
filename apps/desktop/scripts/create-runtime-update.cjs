'use strict'

const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const APP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(APP_ROOT, '..', '..')
const OFFLINE_ROOT = path.join(APP_ROOT, 'build', 'offline-runtime')
const RELEASE_ROOT = path.join(APP_ROOT, 'release', 'runtime')
const TARGETS = {
  'macos-arm64': { artifactPlatform: 'mac', script: 'install.sh', uv: 'uv' },
  'windows-x64': { artifactPlatform: 'win', script: 'install.ps1', uv: 'uv.exe' }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || REPO_ROOT,
    encoding: options.encoding,
    stdio: options.stdio || 'inherit'
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}`)
  return result.stdout
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

function packageVersion() {
  return JSON.parse(fs.readFileSync(path.join(APP_ROOT, 'package.json'), 'utf8')).version
}

function gitRevision() {
  const override = String(process.env.GITHUB_SHA || '').trim().toLowerCase()
  if (/^[a-f0-9]{40,64}$/.test(override)) return override
  return String(run('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: 'pipe' })).trim().toLowerCase()
}

function assertPreparedOfflineRuntime(targetName, offlineRoot) {
  const manifestPath = path.join(offlineRoot, 'manifest.json')
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  if (manifest.bundled !== true || manifest.target !== targetName) {
    throw new Error(`Offline runtime ${targetName} must be prepared before creating its Runtime update.`)
  }
}

function createRuntimeUpdate(targetName, { offlineRoot = OFFLINE_ROOT, outputRoot = RELEASE_ROOT } = {}) {
  const target = TARGETS[targetName]
  if (!target) throw new Error(`Unsupported Runtime update target: ${targetName || '<none>'}`)
  assertPreparedOfflineRuntime(targetName, offlineRoot)

  const version = packageVersion()
  const revision = gitRevision()
  const staging = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-runtime-update-'))
  const output = path.resolve(
    outputRoot,
    `StockSense-Runtime-${version}-${target.artifactPlatform}-${targetName.endsWith('x64') ? 'x64' : 'arm64'}.zip`
  )

  try {
    for (const relative of ['bin', target.script, 'hermes-agent-source.zip', 'uv-cache']) {
      const source = path.join(offlineRoot, relative)
      const destination = path.join(staging, relative)
      fs.cpSync(source, destination, { recursive: true, verbatimSymlinks: true })
    }

    const files = Object.fromEntries(
      walkFiles(staging).map(file => [path.relative(staging, file).replaceAll(path.sep, '/'), sha256(file)])
    )
    const manifest = {
      cache_bundled: true,
      files,
      product: 'stocksense-runtime',
      python: '3.11',
      python_bundled: false,
      revision,
      schema_version: 1,
      source_bundled: true,
      target: targetName,
      version
    }
    fs.writeFileSync(path.join(staging, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
    fs.mkdirSync(path.dirname(output), { recursive: true })
    fs.rmSync(output, { force: true })
    run('tar', ['-a', '-cf', output, '-C', staging, '.'])
    process.stdout.write(`Created Runtime update: ${output}\n`)
    return { manifest, output }
  } finally {
    fs.rmSync(staging, { force: true, recursive: true })
  }
}

function main(args = process.argv.slice(2)) {
  const targetIndex = args.indexOf('--target')
  const target = targetIndex >= 0 ? args[targetIndex + 1] : null
  const inputIndex = args.indexOf('--input')
  const outputIndex = args.indexOf('--output')
  createRuntimeUpdate(target, {
    ...(inputIndex >= 0 ? { offlineRoot: path.resolve(args[inputIndex + 1]) } : {}),
    ...(outputIndex >= 0 ? { outputRoot: path.resolve(args[outputIndex + 1]) } : {})
  })
}

if (require.main === module) main()

module.exports = { TARGETS, createRuntimeUpdate }
