import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import type { ValidatedRuntimeRelease } from './desktop-release'
import { currentRuntimeRevision, runtimeTarget, validateRuntimeBundle } from './runtime-release'

const RELEASE: ValidatedRuntimeRelease = {
  artifactUrl: 'https://cdn.example/runtime.zip',
  notes: '',
  required: true,
  revision: 'a'.repeat(40),
  sha256: 'b'.repeat(64),
  sizeBytes: 1024,
  version: '0.20.0'
}

test('maps only the supported native runtime targets', () => {
  assert.equal(runtimeTarget('win32', 'x64'), 'windows-x64')
  assert.equal(runtimeTarget('darwin', 'arm64'), 'macos-arm64')
  assert.equal(runtimeTarget('darwin', 'x64'), null)
})

test('prefers the explicit runtime revision and falls back to the bootstrap pin', () => {
  assert.equal(
    currentRuntimeRevision({ runtimeRevision: 'C'.repeat(40), pinnedCommit: 'd'.repeat(40) }),
    'c'.repeat(40)
  )
  assert.equal(currentRuntimeRevision({ pinnedCommit: 'd'.repeat(40) }), 'd'.repeat(40))
  assert.equal(currentRuntimeRevision({ pinnedCommit: 'not-a-revision' }), null)
})

test('validates an extracted runtime bundle against the signed release plan', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-runtime-bundle-'))

  try {
    fs.mkdirSync(path.join(root, 'uv-cache'))
    fs.writeFileSync(path.join(root, 'hermes-agent-source.zip'), 'source')
    fs.writeFileSync(path.join(root, 'install.ps1'), 'script')
    fs.writeFileSync(path.join(root, 'uv-cache', 'wheel.whl'), 'wheel')
    const digest = (relative: string) =>
      crypto
        .createHash('sha256')
        .update(fs.readFileSync(path.join(root, relative)))
        .digest('hex')
    fs.writeFileSync(
      path.join(root, 'manifest.json'),
      JSON.stringify({
        cache_bundled: true,
        files: {
          'hermes-agent-source.zip': digest('hermes-agent-source.zip'),
          'install.ps1': digest('install.ps1'),
          'uv-cache/wheel.whl': digest('uv-cache/wheel.whl')
        },
        product: 'stocksense-runtime',
        python: '3.11',
        python_bundled: false,
        revision: RELEASE.revision,
        schema_version: 1,
        source_bundled: true,
        target: 'windows-x64',
        version: RELEASE.version
      })
    )

    assert.equal(validateRuntimeBundle(root, RELEASE, 'windows-x64').version, RELEASE.version)
    assert.throws(() => validateRuntimeBundle(root, { ...RELEASE, revision: 'e'.repeat(40) }, 'windows-x64'))
  } finally {
    fs.rmSync(root, { force: true, recursive: true })
  }
})
