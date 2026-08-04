'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const test = require('node:test')

const { createRuntimeUpdate } = require('./create-runtime-update.cjs')

test('Runtime update package reuses managed Python and carries verified source plus cache', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-runtime-pack-test-'))
  const offlineRoot = path.join(root, 'offline')
  const outputRoot = path.join(root, 'output')
  const extractedRoot = path.join(root, 'extracted')

  try {
    fs.mkdirSync(path.join(offlineRoot, 'bin'), { recursive: true })
    fs.mkdirSync(path.join(offlineRoot, 'python'), { recursive: true })
    fs.mkdirSync(path.join(offlineRoot, 'uv-cache'), { recursive: true })
    fs.writeFileSync(path.join(offlineRoot, 'manifest.json'), JSON.stringify({ bundled: true, target: 'macos-arm64' }))
    fs.writeFileSync(path.join(offlineRoot, 'bin', 'uv'), 'uv')
    fs.writeFileSync(path.join(offlineRoot, 'install.sh'), '#!/bin/sh\n')
    fs.writeFileSync(path.join(offlineRoot, 'hermes-agent-source.zip'), 'source')
    fs.writeFileSync(path.join(offlineRoot, 'python', 'python3'), 'python')
    fs.writeFileSync(path.join(offlineRoot, 'uv-cache', 'wheel.whl'), 'wheel')

    const { manifest, output } = createRuntimeUpdate('macos-arm64', { offlineRoot, outputRoot })
    fs.mkdirSync(extractedRoot)
    execFileSync('tar', ['-xf', output, '-C', extractedRoot])

    assert.equal(manifest.python_bundled, false)
    assert.equal(fs.existsSync(path.join(extractedRoot, 'python')), false)
    assert.equal(fs.readFileSync(path.join(extractedRoot, 'hermes-agent-source.zip'), 'utf8'), 'source')
    assert.equal(fs.readFileSync(path.join(extractedRoot, 'uv-cache', 'wheel.whl'), 'utf8'), 'wheel')

    const extractedManifest = JSON.parse(fs.readFileSync(path.join(extractedRoot, 'manifest.json'), 'utf8'))
    assert.equal(extractedManifest.product, 'stocksense-runtime')
    assert.ok(extractedManifest.files['hermes-agent-source.zip'])
    assert.ok(extractedManifest.files['uv-cache/wheel.whl'])
  } finally {
    fs.rmSync(root, { force: true, recursive: true })
  }
})
