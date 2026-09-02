'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  ANTIVIRUS_BAIT_BASENAMES,
  TARGETS,
  createRuntimeEnv,
  removeAntivirusBaitFiles,
  removeCachedWindowsMinorPythonLink,
  rebaseCopiedSymlinks
} = require('./prepare-offline-runtime.cjs')

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

test('offline runtime keeps project uv configuration enabled for locked sync', () => {
  const runtimeEnv = createRuntimeEnv({
    prepUvCache: '/tmp/uv-cache',
    prepPython: '/tmp/python',
    tempRoot: '/tmp/runtime',
    baseEnv: { UV_NO_CONFIG: '1', UV_HTTP_TIMEOUT: '45' }
  })

  assert.equal(Object.hasOwn(runtimeEnv, 'UV_NO_CONFIG'), false)
  assert.equal(runtimeEnv.UV_HTTP_TIMEOUT, '45')
  assert.equal(runtimeEnv.UV_PROJECT_ENVIRONMENT, path.join('/tmp/runtime', 'venv'))
})

test('antivirus-bait launcher stubs are removed anywhere in the bundle', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-av-bait-'))
  try {
    const pyRoot = path.join(root, 'python', 'cpython-3.11-windows-x86_64-none', 'Lib', 'site-packages')
    const distlib = path.join(pyRoot, 'pip', '_vendor', 'distlib')
    const setuptools = path.join(pyRoot, 'setuptools')
    // uv's unpacked wheel cache ALSO carries the setuptools stubs -- one
    // quarantined copy here invalidated the whole bundle in the field.
    const uvCache = path.join(root, 'uv-cache', 'archive-v0', '4QIFsgvxLvAWMghR', 'setuptools')
    for (const dir of [distlib, setuptools, uvCache]) {
      fs.mkdirSync(dir, { recursive: true })
    }
    for (const name of ['t64-arm.exe', 'w64-arm.exe']) {
      fs.writeFileSync(path.join(distlib, name), 'stub')
    }
    for (const name of ['cli-arm64.exe', 'gui-arm64.exe']) {
      fs.writeFileSync(path.join(setuptools, name), 'stub')
    }
    fs.writeFileSync(path.join(uvCache, 'cli-arm64.exe'), 'stub')
    // Keep-files: near-miss basenames must be untouched.
    fs.writeFileSync(path.join(distlib, 't64.exe'), 'keep me')
    fs.writeFileSync(path.join(uvCache, 'cli-arm64.exe.bak'), 'keep me')

    const removed = removeAntivirusBaitFiles(root)

    assert.equal(removed.length, 5)
    for (const name of ['t64-arm.exe', 'w64-arm.exe']) {
      assert.equal(fs.existsSync(path.join(distlib, name)), false)
    }
    for (const name of ['cli-arm64.exe', 'gui-arm64.exe']) {
      assert.equal(fs.existsSync(path.join(setuptools, name)), false)
    }
    assert.equal(fs.existsSync(path.join(uvCache, 'cli-arm64.exe')), false)
    assert.equal(fs.existsSync(path.join(distlib, 't64.exe')), true)
    assert.equal(fs.existsSync(path.join(uvCache, 'cli-arm64.exe.bak')), true)
    assert.deepEqual(
      [...ANTIVIRUS_BAIT_BASENAMES].sort(),
      ['cli-arm64.exe', 'gui-arm64.exe', 't64-arm.exe', 'w64-arm.exe']
    )
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('cached Windows Python minor link is removed before uv recreates it', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-windows-python-link-'))
  const minorLink = path.join(root, 'cpython-3.11-windows-x86_64-none')
  const patchInstall = path.join(root, 'cpython-3.11.14-windows-x86_64-none')
  try {
    fs.mkdirSync(patchInstall)
    if (process.platform === 'win32') {
      fs.mkdirSync(minorLink)
    } else {
      fs.symlinkSync(patchInstall, minorLink, 'junction')
    }

    assert.equal(removeCachedWindowsMinorPythonLink(root), true)
    assert.equal(fs.existsSync(minorLink), false)
    assert.equal(fs.existsSync(patchInstall), true)
    assert.equal(removeCachedWindowsMinorPythonLink(root), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
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
