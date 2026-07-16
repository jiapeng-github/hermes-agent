'use strict'

/**
 * Produces the StockSense-only MCP defaults resource that is copied into every
 * desktop installer. The API key is release-secret material, never source.
 */

const fs = require('node:fs')
const path = require('node:path')

const APP_ROOT = path.resolve(__dirname, '..')
const TEMPLATE_PATH = path.join(APP_ROOT, 'resources', 'stock-mcp.default.json')
const OUTPUT_PATH = path.join(APP_ROOT, 'build', 'stock-mcp-defaults.json')

function main() {
  const apiKey = (process.env.STOCKSENSE_MX_API_KEY || process.env.EM_API_KEY || '').trim()

  if (!apiKey) {
    throw new Error(
      'Missing STOCKSENSE_MX_API_KEY (or EM_API_KEY). Release builds must inject the 妙想 MCP API key.'
    )
  }

  const defaults = JSON.parse(fs.readFileSync(TEMPLATE_PATH, 'utf8'))
  defaults.default_env = { EM_API_KEY: apiKey }

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true })
  fs.writeFileSync(OUTPUT_PATH, `${JSON.stringify(defaults, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
  console.log('[prepare-stock-mcp-resource] staged bundled 妙想 MCP defaults')
}

main()
