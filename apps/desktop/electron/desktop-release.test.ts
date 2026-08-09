import assert from 'node:assert/strict'
import crypto from 'node:crypto'

import { test } from 'vitest'

import {
  buildDesktopReleaseCheckUrl,
  normalizeDesktopReleaseServiceConfig,
  validateDesktopReleaseCheck
} from './desktop-release'

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
    return JSON.stringify(value)
  }

  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`
  }

  const record = value as Record<string, unknown>

  return `{${Object.keys(record)
    .sort()
    .map(key => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`
}

function rawEd25519PublicKey(key: crypto.KeyObject): string {
  return key.export({ format: 'der', type: 'spki' }).subarray(-32).toString('base64')
}

function signedPayload(privateKey: crypto.KeyObject) {
  const payload: Record<string, unknown> = {
    protocol_version: 1,
    signature_key_id: 'current',
    update: {
      available: true,
      delivery_mode: 'manual',
      installer: {
        sha256: 'a'.repeat(64),
        size_bytes: 1024,
        url: 'https://cdn.stocksense.work/desktop/StockSense-0.20.0-win-x64.exe'
      },
      mandatory: false,
      notes: '修复 Hub 连接。',
      version: '0.20.0'
    }
  }

  payload.signature = crypto.sign(null, Buffer.from(canonicalJson(payload)), privateKey).toString('base64')

  return payload
}

function signedAutoPayload(
  privateKey: crypto.KeyObject,
  feedUrl = 'https://cdn.stocksense.work/desktop/feeds/stable/macos-arm64/offline'
) {
  const payload: Record<string, unknown> = {
    protocol_version: 1,
    signature_key_id: 'current',
    update: {
      available: true,
      delivery_mode: 'auto',
      feed_url: feedUrl,
      mandatory: false,
      notes: '修复 Hub 连接。',
      version: '0.20.0'
    }
  }

  payload.signature = crypto.sign(null, Buffer.from(canonicalJson(payload)), privateKey).toString('base64')

  return payload
}

function signedManagedConfigPayload(privateKey: crypto.KeyObject) {
  const managedConfig: Record<string, unknown> = {
    revision: 3,
    sha256: 'b'.repeat(64),
    signature_key_id: 'current',
    url: 'https://www.stocksense.work/app-api/desktop/v1/managed-config/3?channel=stable'
  }
  managedConfig.signature = crypto.sign(null, Buffer.from(canonicalJson(managedConfig)), privateKey).toString('base64')

  const payload: Record<string, unknown> = {
    managed_config: managedConfig,
    protocol_version: 1,
    signature_key_id: 'current',
    update: { available: false }
  }
  payload.signature = crypto.sign(null, Buffer.from(canonicalJson(payload)), privateKey).toString('base64')

  return payload
}

function signedSplitPayload(privateKey: crypto.KeyObject, desktopAvailable = true) {
  const payload: Record<string, unknown> = {
    protocol_version: 2,
    release_id: 'stocksense-0.20.0',
    runtime: {
      artifact: {
        sha256: 'c'.repeat(64),
        size_bytes: 4096,
        url: 'https://cdn.stocksense.work/runtime/0.20.0/windows-x64.zip'
      },
      available: true,
      notes: '更新本地分析运行时。',
      required: true,
      revision: 'd'.repeat(40),
      version: '0.20.0'
    },
    signature_key_id: 'current',
    update: desktopAvailable
      ? {
          available: true,
          delivery_mode: 'auto',
          feed_url: 'https://cdn.stocksense.work/desktop/0.20.0/windows-x64/update',
          mandatory: false,
          notes: '更新桌面端。',
          version: '0.20.0'
        }
      : { available: false }
  }

  payload.signature = crypto.sign(null, Buffer.from(canonicalJson(payload)), privateKey).toString('base64')

  return payload
}

test('normalizes only explicitly allowed HTTP release service endpoints', () => {
  assert.equal(
    normalizeDesktopReleaseServiceConfig({ endpoint: 'http://updates.example/check', signingKeys: { k: 'x' } }),
    null
  )
  assert.equal(
    normalizeDesktopReleaseServiceConfig({
      allowInsecureHttp: true,
      endpoint: 'http://updates.example/check',
      signingKeys: { k: 'x' }
    })?.endpoint,
    'http://updates.example/check'
  )
})

test('builds the public check URL with platform, architecture, package flavor and versions', () => {
  const config = normalizeDesktopReleaseServiceConfig({
    backgroundDownloadEnabled: true,
    endpoint: 'https://updates.example/app-api/desktop/v1/check',
    flavor: 'offline',
    signingKeys: { k: 'x' }
  })
  assert.ok(config)
  assert.equal(config.backgroundDownloadEnabled, true)
  const url = new URL(
    buildDesktopReleaseCheckUrl(config, {
      arch: 'x64',
      currentRuntimeRevision: 'e'.repeat(40),
      currentVersion: '0.19.0',
      platform: 'windows'
    })
  )

  assert.equal(url.searchParams.get('platform'), 'windows')
  assert.equal(url.searchParams.get('arch'), 'x64')
  assert.equal(url.searchParams.get('flavor'), 'offline')
  assert.equal(url.searchParams.get('current_version'), '0.19.0')
  assert.equal(url.searchParams.get('current_runtime_revision'), 'e'.repeat(40))
})

test('accepts an authenticated newer manual release', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const result = validateDesktopReleaseCheck(signedPayload(privateKey), {
    currentVersion: '0.19.0',
    signingKeys: { current: rawEd25519PublicKey(publicKey) }
  })

  assert.equal(result.supported, true)
  assert.equal(result.available, true)
  assert.equal(result.release?.version, '0.20.0')
})

test('matches the backend canonical JSON and Ed25519 fixed vector', () => {
  const backendVector = {
    protocol_version: 2,
    release_id: '',
    runtime: { available: false },
    server_time: '2026-08-09T05:00:00Z',
    signature_key_id: 'test-key',
    update: { available: false },
    signature:
      'bQf6y04noat9npkWUayxXeCQ+uKhqsBmyMTXeh2fARuaT7il3jquBudXIHG8h2p+0W64CkSOtMi4dACDPAe+Bw=='
  }

  const result = validateDesktopReleaseCheck(backendVector, {
    currentVersion: '0.19.0',
    signingKeys: { 'test-key': 'skeGk1m9eqmwzsnVq8tU6oI15NA9O5uRX/jtVJ83d6U=' }
  })

  assert.deepEqual(result, { available: false, supported: true })
})

test('accepts an authenticated HTTPS automatic release and rejects an insecure feed', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const signingKeys = { current: rawEd25519PublicKey(publicKey) }
  const accepted = validateDesktopReleaseCheck(signedAutoPayload(privateKey), {
    currentVersion: '0.19.0',
    signingKeys
  })

  assert.equal(accepted.supported, true)
  assert.equal(accepted.release?.deliveryMode, 'auto')
  assert.match(accepted.release?.feedUrl || '', /^https:/)

  const rejected = validateDesktopReleaseCheck(signedAutoPayload(privateKey, 'http://cdn.example/desktop'), {
    currentVersion: '0.19.0',
    signingKeys
  })
  assert.equal(rejected.supported, false)
})

test('rejects a tampered or stale signed release', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const payload = signedPayload(privateKey)
  ;(payload.update as Record<string, unknown>).version = '0.21.0'

  const tampered = validateDesktopReleaseCheck(payload, {
    currentVersion: '0.19.0',
    signingKeys: { current: rawEd25519PublicKey(publicKey) }
  })
  assert.equal(tampered.supported, false)

  const stale = validateDesktopReleaseCheck(signedPayload(privateKey), {
    currentVersion: '0.20.0',
    signingKeys: { current: rawEd25519PublicKey(publicKey) }
  })
  assert.equal(stale.supported, false)
})

test('accepts a separately signed HTTPS managed-config descriptor', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const signingKeys = { current: rawEd25519PublicKey(publicKey) }
  const accepted = validateDesktopReleaseCheck(signedManagedConfigPayload(privateKey), {
    currentVersion: '0.19.0',
    signingKeys
  })

  assert.equal(accepted.supported, true)
  assert.equal(accepted.available, false)
  assert.equal(accepted.managedConfig?.revision, 3)
  assert.equal(
    accepted.managedConfig?.url,
    'https://www.stocksense.work/app-api/desktop/v1/managed-config/3?channel=stable'
  )

  const tampered = signedManagedConfigPayload(privateKey)
  ;((tampered.managed_config as Record<string, unknown>).sha256 as string) = 'c'.repeat(64)
  assert.equal(validateDesktopReleaseCheck(tampered, { currentVersion: '0.19.0', signingKeys }).supported, false)
})

test('accepts one signed release plan containing desktop and runtime updates', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const result = validateDesktopReleaseCheck(signedSplitPayload(privateKey), {
    currentVersion: '0.19.0',
    signingKeys: { current: rawEd25519PublicKey(publicKey) }
  })

  assert.equal(result.supported, true)
  assert.equal(result.available, true)
  assert.equal(result.releaseId, 'stocksense-0.20.0')
  assert.equal(result.release?.version, '0.20.0')
  assert.equal(result.runtime?.version, '0.20.0')
  assert.equal(result.runtime?.revision, 'd'.repeat(40))
  assert.equal(result.runtime?.required, true)
})

test('accepts a runtime-only release plan and rejects a malformed runtime artifact', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const signingKeys = { current: rawEd25519PublicKey(publicKey) }
  const runtimeOnly = validateDesktopReleaseCheck(signedSplitPayload(privateKey, false), {
    currentVersion: '0.20.0',
    signingKeys
  })

  assert.equal(runtimeOnly.supported, true)
  assert.equal(runtimeOnly.available, true)
  assert.equal(runtimeOnly.release, undefined)
  assert.equal(runtimeOnly.runtime?.version, '0.20.0')

  const malformed = signedSplitPayload(privateKey, false)
  ;((malformed.runtime as Record<string, unknown>).artifact as Record<string, unknown>).url =
    'http://cdn.example/runtime.zip'
  delete malformed.signature
  malformed.signature = crypto.sign(null, Buffer.from(canonicalJson(malformed)), privateKey).toString('base64')

  assert.equal(validateDesktopReleaseCheck(malformed, { currentVersion: '0.20.0', signingKeys }).supported, false)
})
