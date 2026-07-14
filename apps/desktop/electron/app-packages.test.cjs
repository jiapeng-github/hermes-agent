const assert = require('node:assert/strict')
const fs = require('node:fs')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  analyzeAppPackage,
  exportAppPackage,
  exportDestination,
  localBackend,
  regularPackageFile
} = require('./app-packages.cjs')

function listen(handler) {
  const server = http.createServer(handler)
  return new Promise(resolve => {
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () => new Promise(done => server.close(done))
      })
    })
  })
}

test('local app package bridge refuses remote and non-loopback backends', () => {
  assert.throws(() => localBackend({ baseUrl: 'https://agent.example.com', token: 'secret' }), /local/)
  assert.throws(() => localBackend({ baseUrl: 'http://localhost:8642', token: 'secret' }), /local/)
  assert.throws(() => localBackend({ baseUrl: 'http://127.0.0.1:8642' }), /session/)
  assert.equal(localBackend({ baseUrl: 'http://127.0.0.1:8642', token: 'secret' }).hostname, '127.0.0.1')
})

test('export destination is stable on macOS, Linux, and Windows path rules', () => {
  assert.equal(exportDestination('/Users/me/My App', path.posix), '/Users/me/My App.happ')
  assert.equal(exportDestination('/home/me/应用.HAPP', path.posix), '/home/me/应用.HAPP')
  assert.equal(exportDestination('C:\\Users\\Me\\My App', path.win32), 'C:\\Users\\Me\\My App.happ')
  assert.equal(exportDestination('C:\\Users\\Me\\应用.happ', path.win32), 'C:\\Users\\Me\\应用.happ')
})

test('analyze streams one selected happ package with local session auth', async t => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'hermes-app-import-'))
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }))
  const packagePath = path.join(root, '测试 package.happ')
  await fs.promises.writeFile(packagePath, Buffer.from('PK\x03\x04fixture'))
  let requestBytes = 0
  const backend = await listen((request, response) => {
    assert.equal(request.method, 'POST')
    assert.equal(request.url, '/api/apps/imports')
    assert.equal(request.headers['x-hermes-session-token'], 'local-token')
    assert.match(String(request.headers['content-type']), /^multipart\/form-data; boundary=/)
    request.on('data', chunk => {
      requestBytes += chunk.length
    })
    request.on('end', () => {
      response.writeHead(201, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ import_id: 'plan-1', app: { id: 'local.test.app' } }))
    })
  })
  t.after(backend.close)

  const plan = await analyzeAppPackage({ baseUrl: backend.baseUrl, token: 'local-token' }, packagePath)

  assert.equal(plan.import_id, 'plan-1')
  assert.ok(requestBytes > (await fs.promises.stat(packagePath)).size)
})

test('export streams to a unicode path and atomically replaces an approved file', async t => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'hermes-app-export-'))
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }))
  const destination = path.join(root, '我的应用')
  await fs.promises.writeFile(`${destination}.happ`, 'old')
  const packageBytes = Buffer.from('PK\x03\x04exported-happ')
  const backend = await listen((request, response) => {
    assert.equal(request.method, 'POST')
    assert.equal(request.url, '/api/apps/local.test.app/export')
    assert.equal(request.headers['x-hermes-session-token'], 'local-token')
    const chunks = []
    request.on('data', chunk => chunks.push(chunk))
    request.on('end', () => {
      assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString('utf8')), { include_source: true })
      response.writeHead(200, {
        'Content-Type': 'application/vnd.hermes.app+zip',
        'Content-Length': String(packageBytes.length)
      })
      response.end(packageBytes)
    })
  })
  t.after(backend.close)

  const result = await exportAppPackage(
    { baseUrl: backend.baseUrl, token: 'local-token' },
    'local.test.app',
    destination,
    { includeSource: true }
  )

  assert.equal(result.path, `${destination}.happ`)
  assert.deepEqual(await fs.promises.readFile(result.path), packageBytes)
  assert.deepEqual((await fs.promises.readdir(root)).sort(), ['我的应用.happ'])
})

test('regular package selection rejects symlinks', async t => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'hermes-app-link-'))
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }))
  const target = path.join(root, 'target.happ')
  const link = path.join(root, 'link.happ')
  await fs.promises.writeFile(target, 'fixture')
  await fs.promises.symlink(target, link)

  await assert.rejects(regularPackageFile(link), /regular file/)
})

test('failed export replacement restores the previous package', async t => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'hermes-app-rollback-'))
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }))
  const destination = path.join(root, 'portable.happ')
  await fs.promises.writeFile(destination, 'previous-package')
  const backend = await listen((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/vnd.hermes.app+zip' })
    response.end('new-package')
  })
  t.after(backend.close)
  const originalRename = fs.promises.rename
  fs.promises.rename = async (source, target) => {
    if (String(source).endsWith('.tmp') && target === destination) {
      throw new Error('simulated final rename failure')
    }
    return originalRename(source, target)
  }
  t.after(() => {
    fs.promises.rename = originalRename
  })

  await assert.rejects(
    exportAppPackage({ baseUrl: backend.baseUrl, token: 'local-token' }, 'local.test.app', destination),
    /simulated final rename failure/
  )

  assert.equal(await fs.promises.readFile(destination, 'utf8'), 'previous-package')
})
