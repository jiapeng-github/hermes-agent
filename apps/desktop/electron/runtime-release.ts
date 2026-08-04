import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

import type { ValidatedRuntimeRelease } from './desktop-release'

export const RUNTIME_BUNDLE_SCHEMA_VERSION = 1

export interface RuntimeBundleManifest {
  cache_bundled: boolean
  files: Record<string, string>
  product: 'stocksense-runtime'
  python: string
  python_bundled: boolean
  revision: string
  schema_version: number
  source_bundled: boolean
  target: string
  version: string
}

const SHA256_RE = /^[a-f0-9]{64}$/i
const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function runtimeTarget(platform = process.platform, arch = process.arch): string | null {
  if (platform === 'win32' && arch === 'x64') {
    return 'windows-x64'
  }

  if (platform === 'darwin' && arch === 'arm64') {
    return 'macos-arm64'
  }

  return null
}

export function currentRuntimeRevision(marker: unknown): string | null {
  if (!isPlainObject(marker)) {
    return null
  }

  for (const key of ['runtimeRevision', 'pinnedCommit']) {
    const value = typeof marker[key] === 'string' ? marker[key].trim().toLowerCase() : ''

    if (/^[a-f0-9]{7,64}$/.test(value)) {
      return value
    }
  }

  return null
}

export function validateRuntimeBundle(
  root: string,
  expected: ValidatedRuntimeRelease,
  expectedTarget: string
): RuntimeBundleManifest {
  const manifestPath = path.join(root, 'manifest.json')
  const raw = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as unknown

  if (!isPlainObject(raw) || !isPlainObject(raw.files)) {
    throw new Error('Runtime bundle manifest is invalid.')
  }

  const manifest = raw as unknown as RuntimeBundleManifest

  if (
    manifest.schema_version !== RUNTIME_BUNDLE_SCHEMA_VERSION ||
    manifest.product !== 'stocksense-runtime' ||
    manifest.target !== expectedTarget ||
    typeof manifest.version !== 'string' ||
    typeof manifest.revision !== 'string' ||
    manifest.version !== expected.version ||
    !SEMVER_RE.test(manifest.version) ||
    manifest.revision.toLowerCase() !== expected.revision ||
    manifest.source_bundled !== true ||
    manifest.cache_bundled !== true
  ) {
    throw new Error('Runtime bundle metadata does not match the signed release plan.')
  }

  const installScript = expectedTarget === 'windows-x64' ? 'install.ps1' : 'install.sh'
  const required = ['hermes-agent-source.zip', installScript, 'uv-cache']

  for (const relative of required) {
    const resolved = path.resolve(root, relative)

    if (!resolved.startsWith(`${path.resolve(root)}${path.sep}`) || !fs.existsSync(resolved)) {
      throw new Error(`Runtime bundle is missing ${relative}.`)
    }
  }

  let cacheFileCount = 0

  for (const [relative, digest] of Object.entries(manifest.files)) {
    if (
      !relative ||
      path.isAbsolute(relative) ||
      relative.split('/').includes('..') ||
      typeof digest !== 'string' ||
      !SHA256_RE.test(digest)
    ) {
      throw new Error('Runtime bundle manifest contains an unsafe file entry.')
    }

    const resolved = path.resolve(root, ...relative.split('/'))

    if (
      !resolved.startsWith(`${path.resolve(root)}${path.sep}`) ||
      !fs.statSync(resolved, { throwIfNoEntry: false })?.isFile()
    ) {
      throw new Error(`Runtime bundle manifest references a missing file: ${relative}.`)
    }

    const actual = crypto.createHash('sha256').update(fs.readFileSync(resolved)).digest('hex')

    if (actual !== digest.toLowerCase()) {
      throw new Error(`Runtime bundle file verification failed: ${relative}.`)
    }

    if (relative.startsWith('uv-cache/')) {
      cacheFileCount += 1
    }
  }

  if (!manifest.files['hermes-agent-source.zip'] || !manifest.files[installScript] || cacheFileCount === 0) {
    throw new Error('Runtime bundle manifest does not cover its required payload.')
  }

  return manifest
}
