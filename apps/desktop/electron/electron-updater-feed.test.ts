import assert from 'node:assert/strict'
import http from 'node:http'

import { CancellationToken } from 'builder-util-runtime'
import { NodeHttpExecutor } from 'builder-util/out/nodeHttpExecutor'
import type { AppUpdater } from 'electron-updater'
import { GenericProvider } from 'electron-updater/out/providers/GenericProvider'
import type { ProviderRuntimeOptions } from 'electron-updater/out/providers/Provider'
import { test } from 'vitest'

function listen(server: http.Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      server.off('error', reject)
      const address = server.address()

      if (!address || typeof address === 'string') {
        reject(new Error('Test update server did not expose a TCP port.'))

        return
      }

      resolve(address.port)
    })
  })
}

function close(server: http.Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close(error => (error ? reject(error) : resolve()))
  })
}

test('directory feed preserves its query for YAML, updater and blockmap requests', async () => {
  const requests: string[] = []
  const updateFileName = 'StockSense-0.20.0-mac-arm64-update.zip'
  const sha512 = Buffer.alloc(64, 7).toString('base64')

  const channelYaml = [
    'version: 0.20.0',
    'files:',
    `  - url: ${updateFileName}`,
    `    sha512: ${sha512}`,
    '    size: 14',
    `path: ${updateFileName}`,
    `sha512: ${sha512}`,
    'releaseDate: 2026-08-09T05:00:00.000Z'
  ].join('\n')

  const server = http.createServer((request, response) => {
    requests.push(request.url || '')

    if (request.url?.startsWith('/desktop/stable/macos-arm64/update/latest-mac.yml?')) {
      response.setHeader('content-type', 'application/yaml')
      response.end(channelYaml)

      return
    }

    response.setHeader('content-type', 'application/octet-stream')
    response.end('update-payload')
  })

  const port = await listen(server)

  try {
    const tokenQuery = 'token=signed-download-token&channel=stable'
    const feedUrl = `http://127.0.0.1:${port}/desktop/stable/macos-arm64/update/?${tokenQuery}`
    const executor = new NodeHttpExecutor()

    const provider = new GenericProvider(
      { provider: 'generic', url: feedUrl },
      { channel: null, isAddNoCacheQuery: false } as unknown as AppUpdater,
      {
        executor,
        isUseMultipleRangeRequest: false,
        platform: 'darwin'
      } as unknown as ProviderRuntimeOptions
    )

    const updateInfo = await provider.getLatestVersion()
    const updateFile = provider.resolveFiles(updateInfo)[0]
    const blockmapFiles = await provider.getBlockMapFiles(updateFile.url, '0.19.0', updateInfo.version)
    const newBlockmap = blockmapFiles[1]

    await executor.downloadToBuffer(updateFile.url, { cancellationToken: new CancellationToken() })
    await executor.downloadToBuffer(newBlockmap, { cancellationToken: new CancellationToken() })

    assert.deepEqual(requests, [
      `/desktop/stable/macos-arm64/update/latest-mac.yml?${tokenQuery}`,
      `/desktop/stable/macos-arm64/update/${updateFileName}?${tokenQuery}`,
      `/desktop/stable/macos-arm64/update/${updateFileName}.blockmap?${tokenQuery}`
    ])
  } finally {
    await close(server)
  }
})
