import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import {
  hasPersistedManagedConfig,
  hasSecurePersistedManagedConfig,
  managedConfigPaths,
  materializeStockSenseRuntimeManagedConfig,
  normalizeStockSenseManagedConfig,
  persistStockSenseManagedConfig,
  readManagedConfigMetadata,
  readStockSenseManagedConfig,
  stockSenseAccountServiceConfig
} from './managed-config'

test('accepts only the StockSense managed-config whitelist', () => {
  const config = normalizeStockSenseManagedConfig({
    account: {
      base_url: 'https://www.stocksense.work/app-api/account/v1',
      enabled: true,
      privacy_version: '2026-08-01',
      request_timeout_seconds: 15,
      required: true
    },
    hub: {
      allow_insecure_http: false,
      base_url: 'https://www.stocksense.work/app-api/hub/v1',
      catalog_cache_minutes: 5,
      channel: 'stable',
      enabled: true,
      trusted_keys: { current: Buffer.alloc(32, 7).toString('base64') }
    },
    inference: { base_url: 'https://www.stocksense.work/app-api/inference/v1' }
  })

  assert.equal(config?.hub.base_url, 'https://www.stocksense.work/app-api/hub/v1')
  assert.deepEqual(stockSenseAccountServiceConfig(config), {
    accountBaseUrl: 'https://www.stocksense.work/app-api/account/v1',
    enabled: true,
    inferenceBaseUrl: 'https://www.stocksense.work/app-api/inference/v1',
    privacyVersion: '2026-08-01',
    required: true,
    timeoutMs: 15_000
  })
  assert.equal(
    normalizeStockSenseManagedConfig({ hub: { enabled: true, base_url: 'https://hub.example', model: 'nope' } }),
    null
  )
  assert.equal(normalizeStockSenseManagedConfig({ hub: { enabled: true, base_url: 'http://hub.example' } }), null)
  assert.equal(
    normalizeStockSenseManagedConfig({
      account: { base_url: 'http://account.example' },
      hub: { enabled: true, base_url: 'https://hub.example' }
    }),
    null
  )
})

test('materializes the StockSense model provider without writing its API key', () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-managed-runtime-'))
  const sourceDir = path.join(rootDir, 'source')
  const targetDir = path.join(rootDir, 'runtime')

  const config = normalizeStockSenseManagedConfig({
    account: { enabled: true, required: true },
    hub: { enabled: true, base_url: 'https://hub.example' },
    inference: { base_url: 'https://inference.example/v1' }
  })

  try {
    assert.ok(config)
    persistStockSenseManagedConfig(sourceDir, config, { revision: 1, sha256: 'b'.repeat(64) })
    assert.equal(materializeStockSenseRuntimeManagedConfig(sourceDir, targetDir), targetDir)

    const materialized = JSON.parse(fs.readFileSync(managedConfigPaths(targetDir).configPath, 'utf8'))

    assert.deepEqual(materialized.providers.stocksense, {
      api: 'https://inference.example/v1',
      discover_models: true,
      key_env: 'STOCKSENSE_MODEL_API_KEY',
      name: 'Finance Mate 积分模型',
      transport: 'openai_chat'
    })
    assert.equal(JSON.stringify(materialized).includes('apiKey'), false)
  } finally {
    fs.rmSync(rootDir, { force: true, recursive: true })
  }
})

test('reads the packaged StockSense account and inference configuration', () => {
  const config = readStockSenseManagedConfig(path.join(import.meta.dirname, '..', 'resources', 'stocksense-managed'))

  assert.equal(config?.account?.required, true)
  assert.equal(config?.account?.base_url, 'https://www.stocksense.work/app-api/account/v1')
  assert.equal(config?.inference?.base_url, 'https://www.stocksense.work/app-api/inference/v1')
})

test('persists a valid managed config atomically in the user-owned directory', () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-managed-config-'))
  const config = normalizeStockSenseManagedConfig({ hub: { enabled: true, base_url: 'https://hub.example' } })

  assert.ok(config)
  const metadata = persistStockSenseManagedConfig(rootDir, config, { revision: 3, sha256: 'a'.repeat(64) })
  const paths = managedConfigPaths(rootDir)

  assert.equal(metadata.revision, 3)
  assert.equal(hasPersistedManagedConfig(rootDir), true)
  assert.equal(hasSecurePersistedManagedConfig(rootDir), true)
  assert.deepEqual(JSON.parse(fs.readFileSync(paths.configPath, 'utf8')), config)
  assert.equal(JSON.parse(fs.readFileSync(paths.metadataPath, 'utf8')).sha256, 'a'.repeat(64))
  assert.equal(readManagedConfigMetadata(rootDir)?.revision, 3)

  fs.rmSync(rootDir, { force: true, recursive: true })
})

test('rejects a persisted HTTP Hub config as a desktop override', () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-managed-config-http-'))
  const { configPath } = managedConfigPaths(rootDir)

  fs.writeFileSync(
    configPath,
    JSON.stringify({
      hub: {
        allow_insecure_http: true,
        base_url: 'http://175.24.139.183/app-api/hub/v1',
        enabled: true
      }
    })
  )

  assert.equal(hasPersistedManagedConfig(rootDir), true)
  assert.equal(hasSecurePersistedManagedConfig(rootDir), false)
})
