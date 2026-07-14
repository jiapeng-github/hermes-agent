const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { pipeline } = require('node:stream/promises')
const crypto = require('node:crypto')

const MAX_PACKAGE_BYTES = 52_428_800
const MAX_JSON_BYTES = 2 * 1024 * 1024
const REQUEST_TIMEOUT_MS = 60_000
const APP_ID_RE = /^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){2,}$/

function localBackend(connection) {
  const parsed = new URL(String(connection?.baseUrl || ''))
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port) {
    throw new Error('Applications are available only through the local Stock Agent backend.')
  }
  if (!connection?.token) throw new Error('The local Stock Agent session is unavailable.')
  return parsed
}

async function regularPackageFile(filePath) {
  const resolved = path.resolve(String(filePath || ''))
  if (path.extname(resolved).toLowerCase() !== '.happ') {
    throw new Error('Select a .happ application package.')
  }
  const stat = await fs.promises.lstat(resolved)
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('The selected package must be a regular file.')
  if (stat.size > MAX_PACKAGE_BYTES) throw new Error('The selected package exceeds the 50 MiB limit.')
  return { resolved, size: stat.size }
}

function collectResponse(response, limit = MAX_JSON_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    response.on('error', reject)
    response.on('data', chunk => {
      size += chunk.length
      if (size > limit) {
        response.destroy(new Error('The Stock Agent response exceeded its safety limit.'))
        return
      }
      chunks.push(chunk)
    })
    response.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
  })
}

function requestOptions(connection, url, method, headers = {}) {
  return {
    method,
    hostname: url.hostname,
    port: url.port,
    path: `${url.pathname}${url.search}`,
    headers: {
      'X-Hermes-Session-Token': connection.token,
      ...headers
    }
  }
}

async function analyzeAppPackage(connection, filePath) {
  const backend = localBackend(connection)
  const selected = await regularPackageFile(filePath)
  const boundary = `----HermesApp${crypto.randomBytes(18).toString('hex')}`
  const filename = path.basename(selected.resolved).replace(/["\r\n]/g, '_')
  const prefix = Buffer.from(
    `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="package"; filename="${filename}"\r\n` +
      'Content-Type: application/vnd.hermes.app+zip\r\n\r\n'
  )
  const suffix = Buffer.from(`\r\n--${boundary}--\r\n`)
  const url = new URL('/api/apps/imports', backend)

  return new Promise((resolve, reject) => {
    const request = http.request(
      requestOptions(connection, url, 'POST', {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': String(prefix.length + selected.size + suffix.length)
      }),
      async response => {
        try {
          const text = await collectResponse(response)
          if ((response.statusCode || 500) >= 400) {
            throw new Error(`${response.statusCode}: ${text || response.statusMessage}`)
          }
          resolve(JSON.parse(text))
        } catch (error) {
          reject(error)
        }
      }
    )
    request.on('error', reject)
    request.setTimeout(REQUEST_TIMEOUT_MS, () => request.destroy(new Error('Application import timed out.')))
    request.write(prefix)
    const input = fs.createReadStream(selected.resolved)
    input.on('error', error => request.destroy(error))
    input.on('end', () => request.end(suffix))
    input.pipe(request, { end: false })
  })
}

function exportDestination(filePath, pathApi = path) {
  const resolved = pathApi.resolve(String(filePath || ''))
  return pathApi.extname(resolved).toLowerCase() === '.happ' ? resolved : `${resolved}.happ`
}

async function exportAppPackage(connection, appId, filePath, options = {}) {
  if (!APP_ID_RE.test(String(appId || ''))) throw new Error('Invalid application id.')
  const backend = localBackend(connection)
  const destination = exportDestination(filePath)
  const existing = await fs.promises.lstat(destination).catch(error => {
    if (error.code === 'ENOENT') return null
    throw error
  })
  if (existing && (!existing.isFile() || existing.isSymbolicLink())) {
    throw new Error('The export destination must be a regular file path.')
  }

  const body = Buffer.from(JSON.stringify({ include_source: Boolean(options.includeSource) }))
  const url = new URL(`/api/apps/${encodeURIComponent(appId)}/export`, backend)
  const temporary = path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.${crypto.randomBytes(8).toString('hex')}.tmp`
  )
  const backup = existing
    ? path.join(path.dirname(destination), `.${path.basename(destination)}.${crypto.randomBytes(8).toString('hex')}.bak`)
    : null

  try {
    await new Promise((resolve, reject) => {
      const request = http.request(
        requestOptions(connection, url, 'POST', {
          'Content-Type': 'application/json',
          'Content-Length': String(body.length)
        }),
        async response => {
          try {
            if ((response.statusCode || 500) >= 400) {
              const text = await collectResponse(response)
              throw new Error(`${response.statusCode}: ${text || response.statusMessage}`)
            }
            const declared = Number(response.headers['content-length'] || 0)
            if (declared > MAX_PACKAGE_BYTES) throw new Error('The exported package exceeds the 50 MiB limit.')
            let received = 0
            response.on('data', chunk => {
              received += chunk.length
              if (received > MAX_PACKAGE_BYTES) {
                response.destroy(new Error('The exported package exceeds the 50 MiB limit.'))
              }
            })
            await pipeline(response, fs.createWriteStream(temporary, { flags: 'wx', mode: 0o600 }))
            resolve()
          } catch (error) {
            reject(error)
          }
        }
      )
      request.on('error', reject)
      request.setTimeout(REQUEST_TIMEOUT_MS, () => request.destroy(new Error('Application export timed out.')))
      request.end(body)
    })
    if (backup) await fs.promises.rename(destination, backup)
    try {
      await fs.promises.rename(temporary, destination)
    } catch (error) {
      if (backup) await fs.promises.rename(backup, destination).catch(() => {})
      throw error
    }
    if (backup) await fs.promises.unlink(backup)
    return { canceled: false, path: destination }
  } catch (error) {
    await fs.promises.unlink(temporary).catch(() => {})
    if (backup && !existing?.isSymbolicLink()) {
      const destinationExists = await fs.promises.lstat(destination).then(() => true).catch(() => false)
      if (!destinationExists) await fs.promises.rename(backup, destination).catch(() => {})
    }
    throw error
  }
}

module.exports = {
  MAX_PACKAGE_BYTES,
  analyzeAppPackage,
  exportAppPackage,
  exportDestination,
  localBackend,
  regularPackageFile
}
