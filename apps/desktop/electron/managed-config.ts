import fs from 'node:fs'
import path from 'node:path'

export interface ManagedConfigMetadata {
  downloadedAt: string
  revision: number
  schemaVersion: 1
  sha256: string
}

export interface StockSenseManagedConfig {
  hub: Record<string, boolean | number | string | Record<string, string>>
}

const HUB_BOOLEAN_KEYS = new Set([
  'allow_community_sources',
  'allow_insecure_http',
  'enabled',
  'require_artifact_signature'
])
const HUB_INTEGER_KEYS = new Set(['catalog_cache_minutes', 'offline_cache_hours', 'request_timeout_seconds'])
const HUB_STRING_KEYS = new Set(['base_url', 'channel'])
const HUB_KEYS = new Set([...HUB_BOOLEAN_KEYS, ...HUB_INTEGER_KEYS, ...HUB_STRING_KEYS, 'trusted_keys'])

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isValidHubUrl(value: string, allowInsecureHttp: boolean): boolean {
  try {
    const url = new URL(value)

    return url.protocol === 'https:' || (allowInsecureHttp && url.protocol === 'http:')
  } catch {
    return false
  }
}

function normalizeTrustedKeys(value: unknown): Record<string, string> | null {
  if (!isPlainObject(value)) {
    return null
  }

  const trustedKeys: Record<string, string> = {}

  for (const [key, rawValue] of Object.entries(value)) {
    if (
      !/^[A-Za-z0-9._-]{1,128}$/.test(key) ||
      typeof rawValue !== 'string' ||
      Buffer.from(rawValue, 'base64').length !== 32
    ) {
      return null
    }

    trustedKeys[key] = rawValue
  }

  return trustedKeys
}

// This is intentionally strict. Remote managed configuration is product policy,
// not a second user config.yaml channel: only documented Hub connection fields
// are accepted, and an accidental server-side extra key fails closed.
export function normalizeStockSenseManagedConfig(raw: unknown): StockSenseManagedConfig | null {
  if (!isPlainObject(raw) || Object.keys(raw).length !== 1 || !isPlainObject(raw.hub)) {
    return null
  }

  const sourceHub = raw.hub
  const hub: StockSenseManagedConfig['hub'] = {}

  for (const [key, value] of Object.entries(sourceHub)) {
    if (!HUB_KEYS.has(key)) {
      return null
    }

    if (HUB_BOOLEAN_KEYS.has(key)) {
      if (typeof value !== 'boolean') {
        return null
      }

      hub[key] = value
      continue
    }

    if (HUB_INTEGER_KEYS.has(key)) {
      if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
        return null
      }

      hub[key] = value
      continue
    }

    if (HUB_STRING_KEYS.has(key)) {
      if (typeof value !== 'string' || !value.trim()) {
        return null
      }

      hub[key] = value.trim()
      continue
    }

    const trustedKeys = normalizeTrustedKeys(value)

    if (!trustedKeys) {
      return null
    }

    hub.trusted_keys = trustedKeys
  }

  if (typeof hub.enabled !== 'boolean' || typeof hub.base_url !== 'string') {
    return null
  }

  if (!isValidHubUrl(hub.base_url, hub.allow_insecure_http === true)) {
    return null
  }

  return { hub }
}

export function managedConfigPaths(rootDir: string) {
  return {
    configPath: path.join(rootDir, 'config.yaml'),
    metadataPath: path.join(rootDir, 'managed-config.json')
  }
}

export function hasPersistedManagedConfig(rootDir: string): boolean {
  return fs.existsSync(managedConfigPaths(rootDir).configPath)
}

export function hasSecurePersistedManagedConfig(rootDir: string): boolean {
  try {
    const raw = JSON.parse(fs.readFileSync(managedConfigPaths(rootDir).configPath, 'utf8'))
    const config = normalizeStockSenseManagedConfig(raw)

    return Boolean(config && new URL(String(config.hub.base_url)).protocol === 'https:')
  } catch {
    return false
  }
}

export function readManagedConfigMetadata(rootDir: string): ManagedConfigMetadata | null {
  try {
    const value = JSON.parse(fs.readFileSync(managedConfigPaths(rootDir).metadataPath, 'utf8'))

    if (
      !isPlainObject(value) ||
      value.schemaVersion !== 1 ||
      typeof value.revision !== 'number' ||
      !Number.isSafeInteger(value.revision) ||
      value.revision < 1 ||
      typeof value.sha256 !== 'string' ||
      !/^[a-f0-9]{64}$/i.test(value.sha256) ||
      typeof value.downloadedAt !== 'string'
    ) {
      return null
    }

    return {
      downloadedAt: value.downloadedAt,
      revision: value.revision,
      schemaVersion: 1,
      sha256: value.sha256.toLowerCase()
    }
  } catch {
    return null
  }
}

function writeFileAtomic(targetPath: string, data: string) {
  const tmpPath = `${targetPath}.${process.pid}.${Date.now()}.tmp`
  fs.writeFileSync(tmpPath, data, 'utf8')
  fs.renameSync(tmpPath, targetPath)
}

export function persistStockSenseManagedConfig(
  rootDir: string,
  config: StockSenseManagedConfig,
  { revision, sha256 }: Pick<ManagedConfigMetadata, 'revision' | 'sha256'>
): ManagedConfigMetadata {
  fs.mkdirSync(rootDir, { recursive: true })

  const metadata: ManagedConfigMetadata = {
    downloadedAt: new Date().toISOString(),
    revision,
    schemaVersion: 1,
    sha256
  }
  const { configPath, metadataPath } = managedConfigPaths(rootDir)

  // JSON is a YAML subset, so Hermes' managed config loader accepts this as
  // config.yaml without adding a serializer or a new runtime dependency.
  writeFileAtomic(configPath, `${JSON.stringify(config, null, 2)}\n`)
  writeFileAtomic(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`)

  return metadata
}
