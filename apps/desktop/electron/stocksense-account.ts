import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import type { StockSenseAccountServiceConfig } from './managed-config'

const SESSION_SCHEMA_VERSION = 1
const PROFILE_MAP_SCHEMA_VERSION = 1
const ACCESS_TOKEN_FALLBACK_MS = 2 * 60 * 60 * 1000
const REFRESH_TOKEN_FALLBACK_MS = 30 * 24 * 60 * 60 * 1000
const TOKEN_EXPIRY_SKEW_MS = 30_000
const MOBILE_RE = /^1[3-9]\d{9}$/
const SMS_CODE_RE = /^\d{6}$/
const PROFILE_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/

export interface StockSenseSafeStorage {
  decryptString: (value: Buffer) => string
  encryptString: (value: string) => Buffer
  isEncryptionAvailable: () => boolean
}

export interface StockSenseAccountSummary {
  mobileMasked: string
  pointsBalance: number
  pointsUpdatedAt: string | null
  recentPointsSpent: number | null
  status: string
  userId: string
}

export interface StockSenseModelCatalogItem {
  default: boolean
  displayName: string
  enabled: boolean
  id: string
  inputPointsPerMillion: number | null
  outputPointsPerMillion: number | null
}

export interface StockSenseModelCredentialSummary {
  available: boolean
  baseUrl: string
  defaultModel: string
  providerSlug: string
}

export interface StockSenseAccountStatus {
  account: StockSenseAccountSummary | null
  deviceName: string
  error: StockSenseAccountErrorPayload | null
  gateEnabled: boolean
  modelCatalog: StockSenseModelCatalogItem[]
  modelCredential: StockSenseModelCredentialSummary | null
  phase: 'authenticated' | 'unauthenticated'
  profile: string | null
  secureStorageAvailable: boolean
}

export interface StockSenseAccountErrorPayload {
  code: string
  message: string
  retryAfterSeconds: number | null
  retryable: boolean
}

export interface StockSenseAccountOperation<T> {
  data?: T
  error?: StockSenseAccountErrorPayload
  ok: boolean
}

interface StoredModelCredential extends StockSenseModelCredentialSummary {
  apiKey: string
}

interface StoredAccountSession {
  accessToken: string
  accessTokenExpiresAt: number
  account: StockSenseAccountSummary
  modelCatalog: StockSenseModelCatalogItem[]
  modelCredential: StoredModelCredential | null
  profile: string
  refreshToken: string
  refreshTokenExpiresAt: number
}

interface StoredProfileMap {
  profiles: Record<string, string>
  schemaVersion: 1
}

interface AccountManagerOptions {
  appVersion: string
  deviceId: string
  fetch: (input: string, init?: RequestInit) => Promise<Response>
  getActiveProfile: () => null | string
  getServiceConfig: () => StockSenseAccountServiceConfig
  log?: (message: string) => void
  profileMapPath: string
  safeStorage: StockSenseSafeStorage
  sessionPath: string
}

export class StockSenseAccountError extends Error {
  code: string
  retryAfterSeconds: number | null
  retryable: boolean

  constructor(
    code: string,
    message: string,
    { retryAfterSeconds = null, retryable = false }: { retryAfterSeconds?: number | null; retryable?: boolean } = {}
  ) {
    super(message)
    this.name = 'StockSenseAccountError'
    this.code = code
    this.retryAfterSeconds = retryAfterSeconds
    this.retryable = retryable
  }

  toPayload(): StockSenseAccountErrorPayload {
    return {
      code: this.code,
      message: this.message,
      retryAfterSeconds: this.retryAfterSeconds,
      retryable: this.retryable
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function finiteNumber(value: unknown): number | null {
  const parsed = Number(value)

  return Number.isFinite(parsed) ? parsed : null
}

function stringValue(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }

    if (typeof value === 'number' && Number.isFinite(value)) {
      return String(value)
    }
  }

  return ''
}

function expiryTime(raw: unknown, expiresIn: unknown, fallbackMs: number): number {
  const numeric = finiteNumber(raw)

  if (numeric !== null) {
    return numeric < 10_000_000_000 ? numeric * 1000 : numeric
  }

  if (typeof raw === 'string') {
    const parsed = Date.parse(raw)

    if (Number.isFinite(parsed)) {
      return parsed
    }
  }

  const seconds = finiteNumber(expiresIn)

  return Date.now() + (seconds && seconds > 0 ? seconds * 1000 : fallbackMs)
}

function maskMobile(mobile: string): string {
  return MOBILE_RE.test(mobile) ? `${mobile.slice(0, 3)}****${mobile.slice(-4)}` : mobile
}

function normalizeAccount(raw: unknown, fallbackMobile = ''): StockSenseAccountSummary {
  const source = isRecord(raw) ? raw : {}
  const points = isRecord(source.points) ? source.points : {}
  const userId = stringValue(source.userId, source.id, source.user_id)

  if (!userId) {
    throw new StockSenseAccountError('ACCOUNT_RESPONSE_INVALID', '账号服务返回的数据缺少用户标识。')
  }

  return {
    mobileMasked:
      stringValue(source.mobileMasked, source.maskedMobile, source.mobile_masked) || maskMobile(fallbackMobile),
    pointsBalance:
      finiteNumber(source.pointsBalance) ??
      finiteNumber(source.pointBalance) ??
      finiteNumber(source.points_balance) ??
      finiteNumber(points.balance) ??
      0,
    pointsUpdatedAt:
      stringValue(source.pointsUpdatedAt, source.points_updated_at, points.updatedAt, points.updated_at) || null,
    recentPointsSpent:
      finiteNumber(source.recentPointsSpent) ??
      finiteNumber(source.recent_points_spent) ??
      finiteNumber(points.recentSpent),
    status: stringValue(source.status) || 'ACTIVE',
    userId
  }
}

function normalizeModelCredential(raw: unknown, fallbackBaseUrl: string): StoredModelCredential | null {
  if (!isRecord(raw)) {
    return null
  }

  const apiKey = stringValue(raw.apiKey, raw.api_key)

  if (!apiKey) {
    return null
  }

  return {
    apiKey,
    available: raw.available !== false,
    baseUrl: stringValue(raw.baseUrl, raw.base_url) || fallbackBaseUrl,
    defaultModel: stringValue(raw.defaultModel, raw.default_model, raw.model),
    providerSlug: stringValue(raw.providerSlug, raw.provider_slug) || 'custom:stocksense'
  }
}

function normalizeModelCatalog(raw: unknown): StockSenseModelCatalogItem[] {
  const source = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.models) ? raw.models : []

  return source.flatMap(item => {
    if (!isRecord(item)) {
      return []
    }

    const id = stringValue(item.id, item.model, item.modelId, item.model_id)

    if (!id) {
      return []
    }

    return [
      {
        default: item.default === true || item.isDefault === true || item.is_default === true,
        displayName: stringValue(item.displayName, item.display_name, item.name) || id,
        enabled: item.enabled !== false && String(item.status || 'ENABLED').toUpperCase() !== 'DISABLED',
        id,
        inputPointsPerMillion: finiteNumber(item.inputPointsPerMillion) ?? finiteNumber(item.input_points_per_million),
        outputPointsPerMillion:
          finiteNumber(item.outputPointsPerMillion) ?? finiteNumber(item.output_points_per_million)
      }
    ]
  })
}

function normalizeError(error: unknown): StockSenseAccountError {
  if (error instanceof StockSenseAccountError) {
    return error
  }

  if (error instanceof Error && error.name === 'AbortError') {
    return new StockSenseAccountError('ACCOUNT_REQUEST_TIMEOUT', '账号服务响应超时，请稍后重试。', { retryable: true })
  }

  return new StockSenseAccountError(
    'ACCOUNT_NETWORK_ERROR',
    error instanceof Error && error.message ? error.message : '无法连接 StockSense 账号服务。',
    { retryable: true }
  )
}

function writeJsonAtomic(filePath: string, value: unknown) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(temporary, filePath)

  if (process.platform !== 'win32') {
    fs.chmodSync(filePath, 0o600)
  }
}

export function createStockSenseAccountManager(options: AccountManagerOptions) {
  let cachedSession: StoredAccountSession | null | undefined

  const encryptionAvailable = () => {
    try {
      return Boolean(options.safeStorage.isEncryptionAvailable())
    } catch {
      return false
    }
  }

  const readSession = (): StoredAccountSession | null => {
    if (cachedSession !== undefined) {
      return cachedSession
    }

    if (!encryptionAvailable()) {
      cachedSession = null

      return cachedSession
    }

    try {
      const envelope = JSON.parse(fs.readFileSync(options.sessionPath, 'utf8'))

      if (envelope?.schemaVersion !== SESSION_SCHEMA_VERSION || typeof envelope?.value !== 'string') {
        throw new Error('unsupported account-session envelope')
      }

      const plaintext = options.safeStorage.decryptString(Buffer.from(envelope.value, 'base64'))
      const parsed = JSON.parse(plaintext)

      if (
        !isRecord(parsed) ||
        !stringValue(parsed.accessToken) ||
        !stringValue(parsed.refreshToken) ||
        !stringValue(parsed.profile) ||
        !isRecord(parsed.account)
      ) {
        throw new Error('invalid account-session payload')
      }

      cachedSession = parsed as unknown as StoredAccountSession
    } catch (error: any) {
      if (error?.code !== 'ENOENT') {
        options.log?.(`[account] could not read encrypted session: ${error instanceof Error ? error.message : error}`)
      }

      cachedSession = null
    }

    return cachedSession
  }

  const writeSession = (session: StoredAccountSession) => {
    if (!encryptionAvailable()) {
      throw new StockSenseAccountError(
        'SECURE_STORAGE_UNAVAILABLE',
        '系统安全存储不可用，StockSense 无法保存登录凭据。请启用系统钥匙串或凭据管理器后重试。'
      )
    }

    const encrypted = options.safeStorage.encryptString(JSON.stringify(session))
    writeJsonAtomic(options.sessionPath, {
      encoding: 'safeStorage',
      schemaVersion: SESSION_SCHEMA_VERSION,
      value: encrypted.toString('base64')
    })
    cachedSession = session
  }

  const clearSession = () => {
    cachedSession = null

    try {
      fs.rmSync(options.sessionPath, { force: true })
    } catch {
      void 0
    }
  }

  const serviceConfig = () => options.getServiceConfig()

  const request = async (
    pathName: string,
    { accessToken, body, method = 'GET' }: { accessToken?: string; body?: unknown; method?: string } = {}
  ) => {
    const config = serviceConfig()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), config.timeoutMs)

    try {
      const response = await options.fetch(`${config.accountBaseUrl}${pathName}`, {
        body: body === undefined ? undefined : JSON.stringify(body),
        headers: {
          Accept: 'application/json',
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          'X-Request-Id': crypto.randomUUID(),
          'X-StockSense-Client-Version': options.appVersion,
          'X-StockSense-Device-Id': options.deviceId
        },
        method,
        signal: controller.signal
      })

      const rawText = await response.text()
      let payload: unknown = {}

      if (rawText) {
        try {
          payload = JSON.parse(rawText)
        } catch {
          throw new StockSenseAccountError('ACCOUNT_RESPONSE_INVALID', '账号服务返回了无法识别的数据。', {
            retryable: response.status >= 500
          })
        }
      }

      const record = isRecord(payload) ? payload : {}
      const apiCode = record.code
      const apiSuccess = apiCode === undefined || apiCode === 0 || apiCode === '0' || apiCode === 'SUCCESS'

      if (!response.ok || !apiSuccess) {
        const errorRecord = isRecord(record.error) ? record.error : record
        const code = stringValue(errorRecord.code, record.code) || `HTTP_${response.status}`
        const retryAfterHeader = finiteNumber(response.headers.get('retry-after'))

        const retryAfterSeconds =
          finiteNumber(errorRecord.retryAfterSeconds) ??
          finiteNumber(errorRecord.retry_after_seconds) ??
          retryAfterHeader

        throw new StockSenseAccountError(
          code,
          stringValue(errorRecord.message, record.message, record.msg) ||
            `账号服务请求失败（HTTP ${response.status}）。`,
          {
            retryAfterSeconds,
            retryable: errorRecord.retryable === true || response.status === 429 || response.status >= 500
          }
        )
      }

      return record.data ?? payload
    } catch (error) {
      throw normalizeError(error)
    } finally {
      clearTimeout(timeout)
    }
  }

  const readProfileMap = (): StoredProfileMap => {
    try {
      const parsed = JSON.parse(fs.readFileSync(options.profileMapPath, 'utf8'))

      if (parsed?.schemaVersion === PROFILE_MAP_SCHEMA_VERSION && isRecord(parsed.profiles)) {
        return { profiles: parsed.profiles as Record<string, string>, schemaVersion: PROFILE_MAP_SCHEMA_VERSION }
      }
    } catch {
      void 0
    }

    return { profiles: {}, schemaVersion: PROFILE_MAP_SCHEMA_VERSION }
  }

  const profileForAccount = (userId: string): string => {
    const accountHash = crypto.createHash('sha256').update(`stocksense-account\0${userId}`).digest('hex')
    const mapping = readProfileMap()
    const existing = mapping.profiles[accountHash]

    if (existing && (existing === 'default' || PROFILE_RE.test(existing))) {
      return existing
    }

    const current = options.getActiveProfile()

    const profile =
      Object.keys(mapping.profiles).length === 0 && current && (current === 'default' || PROFILE_RE.test(current))
        ? current
        : Object.keys(mapping.profiles).length === 0
          ? 'default'
          : `stocksense-${accountHash.slice(0, 12)}`

    mapping.profiles[accountHash] = profile
    writeJsonAtomic(options.profileMapPath, mapping)

    return profile
  }

  const refreshTokens = async (session: StoredAccountSession): Promise<StoredAccountSession> => {
    if (session.refreshTokenExpiresAt <= Date.now() + TOKEN_EXPIRY_SKEW_MS) {
      clearSession()
      throw new StockSenseAccountError('ACCOUNT_TOKEN_EXPIRED', '登录已过期，请重新获取验证码登录。')
    }

    try {
      const data = await request('/token/refresh', {
        body: { deviceId: options.deviceId, refreshToken: session.refreshToken },
        method: 'POST'
      })

      const source = isRecord(data) ? data : {}

      const next: StoredAccountSession = {
        ...session,
        accessToken: stringValue(source.accessToken, source.access_token) || session.accessToken,
        accessTokenExpiresAt: expiryTime(
          source.accessTokenExpiresAt ?? source.access_token_expires_at,
          source.expiresIn ?? source.expires_in,
          ACCESS_TOKEN_FALLBACK_MS
        ),
        refreshToken: stringValue(source.refreshToken, source.refresh_token) || session.refreshToken,
        refreshTokenExpiresAt: expiryTime(
          source.refreshTokenExpiresAt ?? source.refresh_token_expires_at,
          source.refreshExpiresIn ?? source.refresh_expires_in,
          REFRESH_TOKEN_FALLBACK_MS
        ),
        modelCredential:
          normalizeModelCredential(
            source.modelCredential ?? source.model_credential,
            serviceConfig().inferenceBaseUrl
          ) ?? session.modelCredential
      }

      writeSession(next)

      return next
    } catch (error) {
      const normalized = normalizeError(error)

      if (
        ['ACCOUNT_TOKEN_EXPIRED', 'ACCOUNT_DISABLED', 'UNAUTHORIZED', 'HTTP_401', 'HTTP_403'].includes(normalized.code)
      ) {
        clearSession()
      }

      throw normalized
    }
  }

  const ensureAccessToken = async (session: StoredAccountSession): Promise<StoredAccountSession> =>
    session.accessTokenExpiresAt > Date.now() + TOKEN_EXPIRY_SKEW_MS ? session : refreshTokens(session)

  const statusFromSession = (
    session: StoredAccountSession | null,
    error: StockSenseAccountErrorPayload | null = null
  ): StockSenseAccountStatus => {
    const config = serviceConfig()

    return {
      account: session?.account ?? null,
      deviceName: os.hostname(),
      error,
      gateEnabled: config.enabled && config.required,
      modelCatalog: session?.modelCatalog ?? [],
      modelCredential: session?.modelCredential
        ? {
            available: session.modelCredential.available,
            baseUrl: session.modelCredential.baseUrl,
            defaultModel: session.modelCredential.defaultModel,
            providerSlug: session.modelCredential.providerSlug
          }
        : null,
      phase: session ? 'authenticated' : 'unauthenticated',
      profile: session?.profile ?? null,
      secureStorageAvailable: encryptionAvailable()
    }
  }

  const getStatus = async (): Promise<StockSenseAccountStatus> => {
    const config = serviceConfig()

    if (!config.enabled) {
      return statusFromSession(null)
    }

    if (!encryptionAvailable()) {
      return statusFromSession(null, {
        code: 'SECURE_STORAGE_UNAVAILABLE',
        message: '系统安全存储不可用，无法安全登录 StockSense。',
        retryAfterSeconds: null,
        retryable: false
      })
    }

    const session = readSession()

    if (!session) {
      return statusFromSession(null)
    }

    try {
      return statusFromSession(await ensureAccessToken(session))
    } catch (error) {
      return statusFromSession(null, normalizeError(error).toPayload())
    }
  }

  const refreshAccount = async (): Promise<StockSenseAccountStatus> => {
    const current = readSession()

    if (!current) {
      return statusFromSession(null)
    }

    let session = await ensureAccessToken(current)

    try {
      const [accountData, catalogData] = await Promise.all([
        request('/me', { accessToken: session.accessToken }),
        request('/model-catalog', { accessToken: session.accessToken }).catch(error => {
          options.log?.(`[account] model catalog refresh failed: ${normalizeError(error).code}`)

          return null
        })
      ])

      const accountSource = isRecord(accountData) && isRecord(accountData.account) ? accountData.account : accountData
      session = {
        ...session,
        account: normalizeAccount(accountSource, session.account.mobileMasked),
        modelCatalog: catalogData === null ? session.modelCatalog : normalizeModelCatalog(catalogData)
      }

      if (session.account.status.toUpperCase() === 'DISABLED') {
        clearSession()
        throw new StockSenseAccountError('ACCOUNT_DISABLED', '账号已停用，请联系管理员。')
      }

      writeSession(session)

      return statusFromSession(session)
    } catch (error) {
      const normalized = normalizeError(error)

      if (['ACCOUNT_DISABLED', 'HTTP_401', 'HTTP_403'].includes(normalized.code)) {
        clearSession()
      }

      throw normalized
    }
  }

  return {
    allowedProfile(): string | null {
      return readSession()?.profile ?? null
    },

    assertBackendAccess(profile?: null | string) {
      const config = serviceConfig()

      if (!config.enabled || !config.required) {
        return
      }

      const session = readSession()

      if (!session || session.accessTokenExpiresAt <= Date.now() + TOKEN_EXPIRY_SKEW_MS) {
        throw new StockSenseAccountError('ACCOUNT_SIGN_IN_REQUIRED', '请先登录 StockSense 账号。')
      }

      const requested = String(profile || session.profile).trim() || session.profile

      if (requested !== session.profile) {
        throw new StockSenseAccountError('ACCOUNT_PROFILE_FORBIDDEN', '当前账号不能访问其他用户的 Profile。')
      }
    },

    backendEnvironment(): Record<string, string> {
      const session = readSession()

      return session?.modelCredential?.apiKey ? { STOCKSENSE_MODEL_API_KEY: session.modelCredential.apiKey } : {}
    },

    canStartBackend(): boolean {
      const config = serviceConfig()

      if (!config.enabled || !config.required) {
        return true
      }

      const session = readSession()

      return Boolean(session && session.accessTokenExpiresAt > Date.now() + TOKEN_EXPIRY_SKEW_MS)
    },

    canPrewarmBackend(): boolean {
      const config = serviceConfig()

      // With mandatory account gating, the renderer validates /me before it
      // mounts the workspace. Starting Hermes here would race that validation.
      return !config.enabled || !config.required
    },

    getInferenceBaseUrl(): string {
      return readSession()?.modelCredential?.baseUrl || serviceConfig().inferenceBaseUrl
    },

    getStatus,

    async login(mobile: string, code: string): Promise<StockSenseAccountStatus> {
      const normalizedMobile = String(mobile || '').replace(/\s+/g, '')
      const normalizedCode = String(code || '').trim()

      if (!MOBILE_RE.test(normalizedMobile)) {
        throw new StockSenseAccountError('MOBILE_INVALID', '请输入正确的中国大陆手机号码。')
      }

      if (!SMS_CODE_RE.test(normalizedCode)) {
        throw new StockSenseAccountError('SMS_CODE_INVALID', '请输入 6 位短信验证码。')
      }

      if (!encryptionAvailable()) {
        throw new StockSenseAccountError('SECURE_STORAGE_UNAVAILABLE', '系统安全存储不可用，无法安全保存登录凭据。')
      }

      const config = serviceConfig()

      const data = await request('/sms/login', {
        body: {
          clientVersion: options.appVersion,
          code: normalizedCode,
          countryCode: '+86',
          deviceId: options.deviceId,
          deviceName: os.hostname(),
          devicePlatform: process.platform === 'win32' ? 'WINDOWS' : process.platform === 'darwin' ? 'MACOS' : 'OTHER',
          mobile: normalizedMobile,
          privacyVersion: config.privacyVersion
        },
        method: 'POST'
      })

      const source = isRecord(data) ? data : {}
      const accountSource = isRecord(source.account) ? source.account : isRecord(source.user) ? source.user : source
      const account = normalizeAccount(accountSource, normalizedMobile)
      const profile = profileForAccount(account.userId)

      const modelCredential = normalizeModelCredential(
        source.modelCredential ?? source.model_credential,
        config.inferenceBaseUrl
      )

      const session: StoredAccountSession = {
        accessToken: stringValue(source.accessToken, source.access_token),
        accessTokenExpiresAt: expiryTime(
          source.accessTokenExpiresAt ?? source.access_token_expires_at,
          source.expiresIn ?? source.expires_in,
          ACCESS_TOKEN_FALLBACK_MS
        ),
        account,
        modelCatalog: normalizeModelCatalog(source.modelCatalog ?? source.model_catalog),
        modelCredential,
        profile,
        refreshToken: stringValue(source.refreshToken, source.refresh_token),
        refreshTokenExpiresAt: expiryTime(
          source.refreshTokenExpiresAt ?? source.refresh_token_expires_at,
          source.refreshExpiresIn ?? source.refresh_expires_in,
          REFRESH_TOKEN_FALLBACK_MS
        )
      }

      if (!session.accessToken || !session.refreshToken) {
        throw new StockSenseAccountError('ACCOUNT_RESPONSE_INVALID', '账号服务未返回完整的登录凭据。')
      }

      writeSession(session)

      if (session.modelCatalog.length === 0) {
        try {
          return await refreshAccount()
        } catch (error) {
          options.log?.(`[account] post-login refresh deferred: ${normalizeError(error).code}`)
        }
      }

      return statusFromSession(session)
    },

    async logout(): Promise<StockSenseAccountStatus> {
      const session = readSession()

      if (session) {
        try {
          await request('/logout', {
            accessToken: session.accessToken,
            body: { deviceId: options.deviceId, refreshToken: session.refreshToken },
            method: 'POST'
          })
        } catch (error) {
          options.log?.(`[account] remote logout failed; local credentials cleared: ${normalizeError(error).code}`)
        }
      }

      clearSession()

      return statusFromSession(null)
    },

    refreshAccount,

    async sendSms(mobile: string): Promise<{ cooldownSeconds: number }> {
      const normalizedMobile = String(mobile || '').replace(/\s+/g, '')

      if (!MOBILE_RE.test(normalizedMobile)) {
        throw new StockSenseAccountError('MOBILE_INVALID', '请输入正确的中国大陆手机号码。')
      }

      const data = await request('/sms/send', {
        body: {
          countryCode: '+86',
          deviceId: options.deviceId,
          mobile: normalizedMobile,
          scene: 'LOGIN'
        },
        method: 'POST'
      })

      const source = isRecord(data) ? data : {}

      return {
        cooldownSeconds: Math.max(1, Math.round(finiteNumber(source.cooldownSeconds) ?? 60))
      }
    }
  }
}

export function accountOperationError(error: unknown): StockSenseAccountOperation<never> {
  return { error: normalizeError(error).toPayload(), ok: false }
}
