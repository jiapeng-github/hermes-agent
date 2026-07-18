'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')

const { resolveNativeTarget } = require('./stage-native-deps.cjs')

test('native dependency target defaults to the build host', () => {
  assert.deepEqual(resolveNativeTarget({}, { platform: 'darwin', arch: 'arm64' }), {
    platform: 'darwin',
    arch: 'arm64'
  })
})

test('StockSense target overrides select Windows x64 during macOS cross-builds', () => {
  assert.deepEqual(
    resolveNativeTarget(
      { STOCKSENSE_TARGET_PLATFORM: 'win32', STOCKSENSE_TARGET_ARCH: 'x64' },
      { platform: 'darwin', arch: 'arm64' }
    ),
    { platform: 'win32', arch: 'x64' }
  )
})

test('legacy npm target overrides remain supported', () => {
  assert.deepEqual(
    resolveNativeTarget({ npm_config_platform: 'win32', npm_config_arch: 'x64' }, { platform: 'darwin', arch: 'arm64' }),
    { platform: 'win32', arch: 'x64' }
  )
})
