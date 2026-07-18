'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const { TARGETS, bundleRuntimeEnabled, rebaseCopiedSymlinks } = require('./prepare-offline-runtime.cjs')

test('offline desktop release matrix is limited to the two supported native targets', () => {
  assert.deepEqual(Object.keys(TARGETS).sort(), ['macos-arm64', 'windows-x64'])
  assert.deepEqual(TARGETS['macos-arm64'], {
    arch: 'arm64',
    platform: 'darwin',
    script: 'install.sh',
    uv: 'uv'
  })
  assert.deepEqual(TARGETS['windows-x64'], {
    arch: 'x64',
    platform: 'win32',
    script: 'install.ps1',
    uv: 'uv.exe'
  })
})

test('runtime bundle switch defaults on and accepts explicit offline/network values', () => {
  assert.equal(bundleRuntimeEnabled(undefined), true)
  assert.equal(bundleRuntimeEnabled('1'), true)
  assert.equal(bundleRuntimeEnabled('offline'), true)
  assert.equal(bundleRuntimeEnabled('0'), false)
  assert.equal(bundleRuntimeEnabled('network'), false)
  assert.throws(() => bundleRuntimeEnabled('maybe'), /Invalid STOCKSENSE_BUNDLE_RUNTIME/)
})

test(
  'copied runtime symlinks are rebased away from the release host',
  { skip: process.platform === 'win32' && 'Windows symlink creation requires developer mode' },
  () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-offline-links-'))
    const source = path.join(root, 'source')
    const destination = path.join(root, 'destination')
    try {
      fs.mkdirSync(path.join(source, 'cpython-full', 'bin'), { recursive: true })
      fs.writeFileSync(path.join(source, 'cpython-full', 'bin', 'python'), '')
      fs.symlinkSync(path.join(source, 'cpython-full'), path.join(source, 'cpython-3.11'))
      fs.cpSync(source, destination, { recursive: true, verbatimSymlinks: true })

      rebaseCopiedSymlinks(source, destination)

      assert.equal(fs.readlinkSync(path.join(destination, 'cpython-3.11')), 'cpython-full')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  }
)
