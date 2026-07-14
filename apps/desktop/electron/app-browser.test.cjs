const assert = require('node:assert/strict')
const test = require('node:test')

const { normalizeAppLaunchUrl, openAppLaunchUrl } = require('./app-browser.cjs')

test('application browser launch accepts only one-time IPv4 loopback URLs', () => {
  assert.equal(
    normalizeAppLaunchUrl('http://127.0.0.1:49182/launch/one-time'),
    'http://127.0.0.1:49182/launch/one-time'
  )
  for (const url of [
    'https://127.0.0.1:49182/launch/code',
    'http://localhost:49182/launch/code',
    'http://127.0.0.1:49182/api/health',
    'http://user@127.0.0.1:49182/launch/code',
    'https://evil.example/launch/code'
  ]) {
    assert.throws(() => normalizeAppLaunchUrl(url), /AppHost|Invalid/)
  }
})

for (const platform of ['darwin', 'win32', 'linux']) {
  test(`application browser launch delegates to the OS shell on ${platform}`, async () => {
    const opened = []
    const result = await openAppLaunchUrl('http://127.0.0.1:49182/launch/code', async url => opened.push(url))

    assert.equal(result, true)
    assert.deepEqual(opened, ['http://127.0.0.1:49182/launch/code'])
  })
}
