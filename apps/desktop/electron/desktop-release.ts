import crypto from 'node:crypto'

export const DESKTOP_RELEASE_PROTOCOL_VERSION = 2

export interface DesktopReleaseServiceConfig {
  allowInsecureHttp?: boolean
  automaticUpdatesEnabled?: boolean
  backgroundDownloadEnabled?: boolean
  channel?: string
  endpoint?: string
  flavor?: string
  signingKeys?: Record<string, string>
}

export interface ValidatedDesktopRelease {
  deliveryMode: 'auto' | 'manual'
  feedUrl?: string
  installerUrl?: string
  mandatory: boolean
  notes: string
  sha256?: string
  sizeBytes?: number
  version: string
}

export interface ValidatedRuntimeRelease {
  artifactUrl: string
  notes: string
  required: boolean
  revision: string
  sha256: string
  sizeBytes: number
  version: string
}

export interface ValidatedDesktopManagedConfig {
  revision: number
  sha256: string
  url: string
}

export interface DesktopReleaseCheck {
  available: boolean
  managedConfig?: ValidatedDesktopManagedConfig
  message?: string
  release?: ValidatedDesktopRelease
  releaseId?: string
  runtime?: ValidatedRuntimeRelease
  supported: boolean
}

const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/
const SHA256_RE = /^[a-f0-9]{64}$/i
const REVISION_RE = /^[a-f0-9]{40,64}$/i
const ED25519_SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex')

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
    return JSON.stringify(value)
  }

  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`
  }

  if (!value || typeof value !== 'object') {
    throw new Error('Release payload contains an unsupported value.')
  }

  const record = value as Record<string, unknown>

  return `{${Object.keys(record)
    .sort()
    .map(key => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeSemver(value: unknown): string | null {
  const normalized = typeof value === 'string' ? value.trim() : ''

  return SEMVER_RE.test(normalized) ? normalized : null
}

function compareSemver(left: string, right: string): number {
  const leftCore = left.split(/[+-]/, 1)[0].split('.').map(Number)
  const rightCore = right.split(/[+-]/, 1)[0].split('.').map(Number)

  for (let index = 0; index < 3; index += 1) {
    const delta = leftCore[index] - rightCore[index]

    if (delta !== 0) {
      return delta
    }
  }

  const leftPrerelease = left.split('+', 1)[0].split('-').slice(1).join('-')
  const rightPrerelease = right.split('+', 1)[0].split('-').slice(1).join('-')

  if (!leftPrerelease && rightPrerelease) {
    return 1
  }

  if (leftPrerelease && !rightPrerelease) {
    return -1
  }

  return leftPrerelease.localeCompare(rightPrerelease, undefined, { numeric: true })
}

function publicKeyFromBase64(value: string): crypto.KeyObject | null {
  try {
    const raw = Buffer.from(value, 'base64')

    if (raw.length !== 32) {
      return null
    }

    return crypto.createPublicKey({
      format: 'der',
      key: Buffer.concat([ED25519_SPKI_PREFIX, raw]),
      type: 'spki'
    })
  } catch {
    return null
  }
}

function verifyEnvelope(payload: Record<string, unknown>, signingKeys: Record<string, string>): boolean {
  const signature = typeof payload.signature === 'string' ? payload.signature.trim() : ''
  const keyId = typeof payload.signature_key_id === 'string' ? payload.signature_key_id.trim() : ''
  const publicKey = keyId ? publicKeyFromBase64(signingKeys[keyId] || '') : null

  if (!signature || !publicKey) {
    return false
  }

  const unsignedPayload = { ...payload }
  delete unsignedPayload.signature

  try {
    return crypto.verify(null, Buffer.from(canonicalJson(unsignedPayload)), publicKey, Buffer.from(signature, 'base64'))
  } catch {
    return false
  }
}

function parseInstaller(value: unknown): Pick<ValidatedDesktopRelease, 'installerUrl' | 'sha256' | 'sizeBytes'> | null {
  if (!isPlainObject(value)) {
    return null
  }

  const installerUrl = typeof value.url === 'string' ? value.url.trim() : ''
  const sha256 = typeof value.sha256 === 'string' ? value.sha256.trim() : ''
  const sizeBytes = Number(value.size_bytes)

  try {
    const url = new URL(installerUrl)

    if (
      !['http:', 'https:'].includes(url.protocol) ||
      !SHA256_RE.test(sha256) ||
      !Number.isSafeInteger(sizeBytes) ||
      sizeBytes <= 0
    ) {
      return null
    }
  } catch {
    return null
  }

  return { installerUrl, sha256: sha256.toLowerCase(), sizeBytes }
}

function parseRuntime(value: unknown): ValidatedRuntimeRelease | null | undefined {
  if (value === undefined) {
    return undefined
  }

  if (!isPlainObject(value)) {
    return null
  }

  if (value.available !== true) {
    return undefined
  }

  const version = normalizeSemver(value.version)
  const revision = typeof value.revision === 'string' ? value.revision.trim().toLowerCase() : ''
  const artifact = parseInstaller(value.artifact)

  if (!version || !REVISION_RE.test(revision) || !artifact) {
    return null
  }

  try {
    if (new URL(artifact.installerUrl).protocol !== 'https:') {
      return null
    }
  } catch {
    return null
  }

  return {
    artifactUrl: artifact.installerUrl,
    notes: typeof value.notes === 'string' ? value.notes.trim() : '',
    required: value.required === true,
    revision,
    sha256: artifact.sha256,
    sizeBytes: artifact.sizeBytes,
    version
  }
}

function parseManagedConfig(value: unknown, signingKeys: Record<string, string>): ValidatedDesktopManagedConfig | null {
  if (!isPlainObject(value) || !verifyEnvelope(value, signingKeys)) {
    return null
  }

  const revision = Number(value.revision)
  const sha256 = typeof value.sha256 === 'string' ? value.sha256.trim().toLowerCase() : ''
  const rawUrl = typeof value.url === 'string' ? value.url.trim() : ''

  try {
    if (
      !Number.isSafeInteger(revision) ||
      revision < 1 ||
      !SHA256_RE.test(sha256) ||
      new URL(rawUrl).protocol !== 'https:'
    ) {
      return null
    }
  } catch {
    return null
  }

  return { revision, sha256, url: rawUrl }
}

function parseRelease(
  payload: Record<string, unknown>,
  currentVersion: string,
  signingKeys: Record<string, string>
): DesktopReleaseCheck {
  const protocolVersion = Number(payload.protocol_version)

  if (![1, DESKTOP_RELEASE_PROTOCOL_VERSION].includes(protocolVersion) || !isPlainObject(payload.update)) {
    return { message: '桌面版本服务返回了不兼容的协议。', supported: false, available: false }
  }

  const hasManagedConfig = payload.managed_config !== undefined
  const managedConfig = hasManagedConfig ? parseManagedConfig(payload.managed_config, signingKeys) : undefined

  if (hasManagedConfig && !managedConfig) {
    return { message: '桌面版本服务返回了无效的受管配置描述。', supported: false, available: false }
  }

  const update = payload.update
  const runtime = protocolVersion >= 2 ? parseRuntime(payload.runtime) : undefined

  if (runtime === null) {
    return { message: '桌面版本服务返回了无效的 Runtime 更新描述。', supported: false, available: false }
  }

  const releaseId = typeof payload.release_id === 'string' ? payload.release_id.trim() : ''

  if (update.available !== true) {
    return {
      available: Boolean(runtime),
      ...(managedConfig ? { managedConfig } : {}),
      ...(releaseId ? { releaseId } : {}),
      ...(runtime ? { runtime } : {}),
      supported: true
    }
  }

  const deliveryMode = update.delivery_mode

  if (deliveryMode !== 'manual' && deliveryMode !== 'auto') {
    return { message: '当前安装包不支持此更新交付方式。', supported: false, available: false }
  }

  const version = normalizeSemver(update.version)
  const installer = parseInstaller(update.installer)

  if (!version || compareSemver(version, currentVersion) <= 0) {
    return { message: '桌面版本服务返回了无效的更新信息。', supported: false, available: false }
  }

  if (deliveryMode === 'manual' && !installer) {
    return { message: '桌面版本服务未提供可验证的安装包。', supported: false, available: false }
  }

  const feedUrl = typeof update.feed_url === 'string' ? update.feed_url.trim() : ''

  if (deliveryMode === 'auto') {
    try {
      if (new URL(feedUrl).protocol !== 'https:') {
        throw new Error('feed must use HTTPS')
      }
    } catch {
      return { message: '桌面版本服务未提供安全的自动更新地址。', supported: false, available: false }
    }
  }

  return {
    available: true,
    ...(managedConfig ? { managedConfig } : {}),
    ...(releaseId ? { releaseId } : {}),
    release: {
      ...(installer || {}),
      deliveryMode,
      ...(deliveryMode === 'auto' ? { feedUrl } : {}),
      mandatory: update.mandatory === true,
      notes: typeof update.notes === 'string' ? update.notes.trim() : '',
      version
    },
    ...(runtime ? { runtime } : {}),
    supported: true
  }
}

export function normalizeDesktopReleaseServiceConfig(raw: unknown): DesktopReleaseServiceConfig | null {
  if (!isPlainObject(raw)) {
    return null
  }

  const endpoint = typeof raw.endpoint === 'string' ? raw.endpoint.trim() : ''
  const signingKeys: Record<string, string> = {}

  if (isPlainObject(raw.signingKeys)) {
    for (const [key, value] of Object.entries(raw.signingKeys)) {
      if (typeof value === 'string') {
        signingKeys[key] = value
      }
    }
  }

  if (!endpoint || Object.keys(signingKeys).length === 0) {
    return null
  }

  try {
    const url = new URL(endpoint)

    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && raw.allowInsecureHttp === true)) {
      return null
    }
  } catch {
    return null
  }

  return {
    allowInsecureHttp: raw.allowInsecureHttp === true,
    automaticUpdatesEnabled: raw.automaticUpdatesEnabled === true,
    backgroundDownloadEnabled: raw.backgroundDownloadEnabled === true,
    channel: typeof raw.channel === 'string' && raw.channel.trim() ? raw.channel.trim() : 'stable',
    endpoint,
    flavor: typeof raw.flavor === 'string' && raw.flavor.trim() ? raw.flavor.trim() : 'split',
    signingKeys
  }
}

export function buildDesktopReleaseCheckUrl(
  config: DesktopReleaseServiceConfig,
  {
    arch,
    currentRuntimeRevision,
    currentVersion,
    platform
  }: { arch: string; currentRuntimeRevision?: string | null; currentVersion: string; platform: string }
): string {
  const url = new URL(config.endpoint || '')
  url.searchParams.set('arch', arch)
  url.searchParams.set('channel', config.channel || 'stable')
  url.searchParams.set('current_version', currentVersion)
  url.searchParams.set('flavor', config.flavor || 'split')
  url.searchParams.set('platform', platform)

  if (currentRuntimeRevision) {
    url.searchParams.set('current_runtime_revision', currentRuntimeRevision)
  }

  return url.toString()
}

export function validateDesktopReleaseCheck(
  raw: unknown,
  { currentVersion, signingKeys }: { currentVersion: string; signingKeys: Record<string, string> }
): DesktopReleaseCheck {
  if (!isPlainObject(raw) || !verifyEnvelope(raw, signingKeys)) {
    return { message: '桌面版本服务的签名验证失败。', supported: false, available: false }
  }

  return parseRelease(raw, currentVersion, signingKeys)
}
