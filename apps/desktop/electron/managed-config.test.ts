import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import {
  hasPersistedManagedConfig,
  hasSecurePersistedManagedConfig,
  managedConfigPaths,
  normalizeStockSenseManagedConfig,
  persistStockSenseManagedConfig,
  readManagedConfigMetadata
} from './managed-config'

test('accepts only the Hub managed-config whitelist', () => {
  const config = normalizeStockSenseManagedConfig({
    hub: {
      allow_insecure_http: false,
      base_url: 'https://www.stocksense.work/app-api/hub/v1',
      catalog_cache_minutes: 5,
      channel: 'stable',
      enabled: true,
      trusted_keys: { current: Buffer.alloc(32, 7).toString('base64') }
    }
  })

  assert.equal(config?.hub.base_url, 'https://www.stocksense.work/app-api/hub/v1')
  assert.equal(
    normalizeStockSenseManagedConfig({ hub: { enabled: true, base_url: 'https://hub.example', model: 'nope' } }),
    null
  )
  assert.equal(normalizeStockSenseManagedConfig({ hub: { enabled: true, base_url: 'http://hub.example' } }), null)
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
