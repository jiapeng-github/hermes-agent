#!/usr/bin/env node

import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'

function argument(name) {
  const index = process.argv.indexOf(`--${name}`)

  return index >= 0 ? process.argv[index + 1] : null
}

function requiredArgument(name) {
  const value = argument(name)

  if (!value) {
    throw new Error(`Missing required --${name} argument.`)
  }

  return value
}

function walk(directory) {
  const files = []

  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const resolved = path.join(directory, entry.name)

    if (entry.isDirectory()) {
      files.push(...walk(resolved))
    } else if (entry.isFile()) {
      files.push(resolved)
    }
  }

  return files
}

function fileByBasename(files, name) {
  const matches = files.filter(file => path.basename(file) === name)

  if (matches.length !== 1) {
    throw new Error(`Expected exactly one ${name} in build artifacts, found ${matches.length}.`)
  }

  return matches[0]
}

function fileByBasenameUnder(files, name, directory) {
  const matches = files.filter(file => path.basename(file) === name && file.split(path.sep).includes(directory))

  if (matches.length !== 1) {
    throw new Error(`Expected exactly one ${directory}/${name} in build artifacts, found ${matches.length}.`)
  }

  return matches[0]
}

function fileHash(file, algorithm) {
  return crypto.createHash(algorithm).update(fs.readFileSync(file)).digest(algorithm === 'sha512' ? 'base64' : 'hex')
}

function copyAsset(assets, stagingDir, { arch, flavor, platform, role, source, target }) {
  const destination = path.join(stagingDir, target)
  fs.copyFileSync(source, destination)

  const sizeBytes = fs.statSync(destination).size
  const sha256 = fileHash(destination, 'sha256')
  const asset = { arch, flavor, platform, relative_path: target, role, sha256, size_bytes: sizeBytes }

  if (role === 'updater') {
    asset.sha512 = fileHash(destination, 'sha512')
  }

  assets.push(asset)
}

function main() {
  const input = path.resolve(requiredArgument('input'))
  const output = path.resolve(requiredArgument('output'))
  const version = requiredArgument('version')
  const channel = requiredArgument('channel')
  const installerFlavor = 'offline'
  const updaterFlavor = 'update'
  const files = walk(input)
  const stagingDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stocksense-release-bundle-'))
  const assets = []

  try {
    const windowsInstallerBase = `StockSense-${version}-win-x64-${installerFlavor}`
    const windowsUpdaterBase = `StockSense-${version}-win-x64-${updaterFlavor}`
    const windowsInstaller = fileByBasenameUnder(files, `${windowsInstallerBase}.exe`, 'offline')
    const windowsUpdater = fileByBasenameUnder(files, `${windowsUpdaterBase}.exe`, 'update')
    const windowsBlockmap = fileByBasenameUnder(files, `${windowsUpdaterBase}.exe.blockmap`, 'update')
    const windowsFeed = fileByBasenameUnder(files, 'latest.yml', 'update')
    const windowsRuntime = fileByBasename(files, `StockSense-Runtime-${version}-win-x64.zip`)
    copyAsset(assets, stagingDir, {
      arch: 'x64',
      flavor: installerFlavor,
      platform: 'windows',
      role: 'installer',
      source: windowsInstaller,
      target: `${windowsInstallerBase}.exe`
    })
    copyAsset(assets, stagingDir, {
      arch: 'x64',
      flavor: updaterFlavor,
      platform: 'windows',
      role: 'updater',
      source: windowsUpdater,
      target: `${windowsUpdaterBase}.exe`
    })
    copyAsset(assets, stagingDir, {
      arch: 'x64',
      flavor: updaterFlavor,
      platform: 'windows',
      role: 'feed',
      source: windowsFeed,
      target: 'latest.yml'
    })
    copyAsset(assets, stagingDir, {
      arch: 'x64',
      flavor: updaterFlavor,
      platform: 'windows',
      role: 'blockmap',
      source: windowsBlockmap,
      target: `${windowsUpdaterBase}.exe.blockmap`
    })
    copyAsset(assets, stagingDir, {
      arch: 'x64',
      flavor: 'runtime',
      platform: 'windows',
      role: 'runtime',
      source: windowsRuntime,
      target: `StockSense-Runtime-${version}-win-x64.zip`
    })

    const macInstallerBase = `StockSense-${version}-mac-arm64-${installerFlavor}`
    const macUpdaterBase = `StockSense-${version}-mac-arm64-${updaterFlavor}`
    const macInstaller = fileByBasenameUnder(files, `${macInstallerBase}.dmg`, 'offline')
    const macUpdater = fileByBasenameUnder(files, `${macUpdaterBase}.zip`, 'update')
    const macBlockmap = fileByBasenameUnder(files, `${macUpdaterBase}.zip.blockmap`, 'update')
    const macFeed = fileByBasenameUnder(files, 'latest-mac.yml', 'update')
    const macRuntime = fileByBasename(files, `StockSense-Runtime-${version}-mac-arm64.zip`)
    copyAsset(assets, stagingDir, {
      arch: 'arm64',
      flavor: installerFlavor,
      platform: 'macos',
      role: 'installer',
      source: macInstaller,
      target: `${macInstallerBase}.dmg`
    })
    copyAsset(assets, stagingDir, {
      arch: 'arm64',
      flavor: updaterFlavor,
      platform: 'macos',
      role: 'updater',
      source: macUpdater,
      target: `${macUpdaterBase}.zip`
    })
    copyAsset(assets, stagingDir, {
      arch: 'arm64',
      flavor: updaterFlavor,
      platform: 'macos',
      role: 'feed',
      source: macFeed,
      target: 'latest-mac.yml'
    })
    copyAsset(assets, stagingDir, {
      arch: 'arm64',
      flavor: updaterFlavor,
      platform: 'macos',
      role: 'blockmap',
      source: macBlockmap,
      target: `${macUpdaterBase}.zip.blockmap`
    })
    copyAsset(assets, stagingDir, {
      arch: 'arm64',
      flavor: 'runtime',
      platform: 'macos',
      role: 'runtime',
      source: macRuntime,
      target: `StockSense-Runtime-${version}-mac-arm64.zip`
    })

    const revision = String(process.env.GITHUB_SHA || '').trim() || execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
    const manifest = {
      assets,
      channel,
      install_order: ['runtime', 'desktop'],
      product: 'stocksense',
      release_id: `stocksense-${version}`,
      runtime: { revision, version },
      schema_version: 2,
      version
    }
    const checksums = assets.map(asset => `${asset.sha256}  ${asset.relative_path}`).join('\n') + '\n'

    fs.writeFileSync(path.join(stagingDir, 'release-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
    fs.writeFileSync(path.join(stagingDir, 'SHA256SUMS.txt'), checksums)
    fs.mkdirSync(path.dirname(output), { recursive: true })
    fs.rmSync(output, { force: true })
    execFileSync('zip', ['-q', '-X', output, ...[...assets.map(asset => asset.relative_path), 'release-manifest.json', 'SHA256SUMS.txt']], {
      cwd: stagingDir,
      stdio: 'inherit'
    })
    process.stdout.write(`Created release bundle: ${output}\n`)
  } finally {
    fs.rmSync(stagingDir, { force: true, recursive: true })
  }
}

main()
