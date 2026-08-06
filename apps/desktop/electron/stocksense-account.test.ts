import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { createStockSenseAccountManager, StockSenseAccountError } from './stocksense-account'

const serviceConfig = {
  accountBaseUrl: 'https://account.example/v1',
  enabled: true,
  inferenceBaseUrl: 'https://inference.example/v1',
  privacyVersion: '2026-08-01',
  required: true,
  timeoutMs: 2_000
}

function safeStorage(available = true) {
  return {
    decryptString: (value: Buffer) =>
      Buffer.from(value.toString('utf8').split('').reverse().join(''), 'utf8').toString(),
    encryptString: (value: string) => Buffer.from(value.split('').reverse().join(''), 'utf8'),
    isEncryptionAvailable: () => available
  }
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ code: status < 400 ? 0 : `HTTP_${status}`, data }), {
    headers: { 'Content-Type': 'application/json' },
    status
  })
}

function loginPayload(userId: string, mobile: string, overrides: Record<string, unknown> = {}) {
  return {
    accessToken: `access-${userId}`,
    accessTokenExpiresAt: Date.now() + 60 * 60 * 1000,
    account: {
      mobileMasked: `${mobile.slice(0, 3)}****${mobile.slice(-4)}`,
      pointsBalance: 1200,
      pointsUpdatedAt: '2026-08-05T08:00:00Z',
      status: 'ACTIVE',
      userId
    },
    modelCatalog: [
      {
        default: true,
        displayName: 'StockSense Pro',
        enabled: true,
        id: 'stocksense-pro',
        inputPointsPerMillion: 8,
        outputPointsPerMillion: 24
      }
    ],
    modelCredential: {
      apiKey: `model-${userId}`,
      baseUrl: 'https://inference.example/v1',
      defaultModel: 'stocksense-pro',
      providerSlug: 'custom:stocksense'
    },
    refreshToken: `refresh-${userId}`,
    refreshTokenExpiresAt: Date.now() + 30 * 24 * 60 * 60 * 1000,
    ...overrides
  }
}

function managerOptions(
  rootDir: string,
  fetch: (input: string, init?: RequestInit) => Promise<Response>,
  getActiveProfile: () => string | null = () => 'research'
) {
  return {
    appVersion: '0.20.0-test',
    deviceId: 'desktop-test-device',
    fetch,
    getActiveProfile,
    getServiceConfig: () => serviceConfig,
    profileMapPath: path.join(rootDir, 'account-profiles.json'),
    safeStorage: safeStorage(),
    sessionPath: path.join(rootDir, 'account-session.json')
  }
}

test('requires sign-in before backend startup and rejects unavailable secure storage', async () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-account-gate-'))

  try {
    const manager = createStockSenseAccountManager({
      ...managerOptions(rootDir, async () => jsonResponse({})),
      safeStorage: safeStorage(false)
    })

    const status = await manager.getStatus()

    assert.equal(status.phase, 'unauthenticated')
    assert.equal(status.secureStorageAvailable, false)
    assert.equal(status.error?.code, 'SECURE_STORAGE_UNAVAILABLE')
    assert.equal(manager.canStartBackend(), false)
    assert.equal(manager.canPrewarmBackend(), false)
    assert.throws(
      () => manager.assertBackendAccess(),
      (error: unknown) => error instanceof StockSenseAccountError && error.code === 'ACCOUNT_SIGN_IN_REQUIRED'
    )
    await assert.rejects(
      manager.login('13800138000', '123456'),
      (error: unknown) => error instanceof StockSenseAccountError && error.code === 'SECURE_STORAGE_UNAVAILABLE'
    )
  } finally {
    fs.rmSync(rootDir, { force: true, recursive: true })
  }
})

test('stores credentials encrypted and restores an authenticated account after restart', async () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-account-session-'))
  const calls: Array<{ body: Record<string, unknown>; path: string }> = []

  const fetch = async (input: string, init?: RequestInit) => {
    const url = new URL(input)
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    calls.push({ body, path: url.pathname })

    if (url.pathname.endsWith('/sms/login')) {
      return jsonResponse(loginPayload('user-a', body.mobile))
    }

    return jsonResponse({})
  }

  try {
    const options = managerOptions(rootDir, fetch)
    const manager = createStockSenseAccountManager(options)
    const status = await manager.login('13800138000', '123456')

    assert.equal(status.phase, 'authenticated')
    assert.equal(status.profile, 'research')
    assert.equal(status.account?.mobileMasked, '138****8000')
    assert.deepEqual(manager.backendEnvironment(), { STOCKSENSE_MODEL_API_KEY: 'model-user-a' })
    assert.equal(manager.canStartBackend(), true)
    assert.equal(manager.canPrewarmBackend(), false)
    assert.doesNotThrow(() => manager.assertBackendAccess('research'))
    assert.throws(
      () => manager.assertBackendAccess('other'),
      (error: unknown) => error instanceof StockSenseAccountError && error.code === 'ACCOUNT_PROFILE_FORBIDDEN'
    )

    const stored = fs.readFileSync(options.sessionPath, 'utf8')

    assert.equal(stored.includes('access-user-a'), false)
    assert.equal(stored.includes('refresh-user-a'), false)
    assert.equal(stored.includes('model-user-a'), false)
    assert.equal(calls[0].body.privacyVersion, '2026-08-01')

    const restarted = createStockSenseAccountManager(options)
    const restored = await restarted.getStatus()

    assert.equal(restored.phase, 'authenticated')
    assert.equal(restored.profile, 'research')
    assert.deepEqual(restarted.backendEnvironment(), { STOCKSENSE_MODEL_API_KEY: 'model-user-a' })
  } finally {
    fs.rmSync(rootDir, { force: true, recursive: true })
  }
})

test('isolates subsequent accounts into deterministic hashed profiles', async () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-account-profiles-'))

  const fetch = async (input: string, init?: RequestInit) => {
    const url = new URL(input)
    const body = init?.body ? JSON.parse(String(init.body)) : {}

    if (url.pathname.endsWith('/sms/login')) {
      return body.mobile === '13800138000'
        ? jsonResponse(loginPayload('user-a', body.mobile))
        : jsonResponse(loginPayload('user-b', body.mobile))
    }

    return jsonResponse({})
  }

  try {
    const manager = createStockSenseAccountManager(managerOptions(rootDir, fetch))
    const first = await manager.login('13800138000', '123456')
    await manager.logout()
    const second = await manager.login('13900139000', '654321')

    assert.equal(first.profile, 'research')
    assert.match(String(second.profile), /^stocksense-[a-f0-9]{12}$/)
    assert.notEqual(second.profile, first.profile)

    const mapping = fs.readFileSync(path.join(rootDir, 'account-profiles.json'), 'utf8')

    assert.equal(mapping.includes('user-a'), false)
    assert.equal(mapping.includes('user-b'), false)
  } finally {
    fs.rmSync(rootDir, { force: true, recursive: true })
  }
})

test('rotates model credentials during token refresh and preserves masked mobile data', async () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-account-refresh-'))

  const fetch = async (input: string, init?: RequestInit) => {
    const url = new URL(input)

    if (url.pathname.endsWith('/sms/login')) {
      return jsonResponse(
        loginPayload('user-a', '13800138000', {
          accessTokenExpiresAt: Date.now() - 1
        })
      )
    }

    if (url.pathname.endsWith('/token/refresh')) {
      return jsonResponse({
        accessToken: 'access-user-a-rotated',
        accessTokenExpiresAt: Date.now() + 60 * 60 * 1000,
        modelCredential: {
          apiKey: 'model-user-a-rotated',
          baseUrl: 'https://inference-next.example/v1',
          defaultModel: 'stocksense-pro',
          providerSlug: 'custom:stocksense'
        },
        refreshToken: 'refresh-user-a-rotated',
        refreshTokenExpiresAt: Date.now() + 30 * 24 * 60 * 60 * 1000
      })
    }

    if (url.pathname.endsWith('/me')) {
      return jsonResponse({ pointsBalance: 975, status: 'ACTIVE', userId: 'user-a' })
    }

    if (url.pathname.endsWith('/model-catalog')) {
      return jsonResponse(loginPayload('user-a', '13800138000').modelCatalog)
    }

    return jsonResponse({})
  }

  try {
    const manager = createStockSenseAccountManager(managerOptions(rootDir, fetch))
    await manager.login('13800138000', '123456')
    const refreshed = await manager.refreshAccount()

    assert.equal(refreshed.account?.mobileMasked, '138****8000')
    assert.equal(refreshed.account?.pointsBalance, 975)
    assert.equal(refreshed.modelCredential?.baseUrl, 'https://inference-next.example/v1')
    assert.deepEqual(manager.backendEnvironment(), { STOCKSENSE_MODEL_API_KEY: 'model-user-a-rotated' })
  } finally {
    fs.rmSync(rootDir, { force: true, recursive: true })
  }
})
