const MAX_HUB_APP_PREVIEW_BYTES = 4 * 1024 * 1024

function containsControlCharacter(value: string): boolean {
  return Array.from(value).some(character => {
    const codePoint = character.codePointAt(0) || 0

    return codePoint < 32 || codePoint === 127
  })
}

function requiredSegment(value: unknown, label: string, maxLength: number): string {
  if (typeof value !== 'string') {
    throw new Error(`${label} is required.`)
  }

  const normalized = value.trim()
  if (!normalized || normalized.length > maxLength || containsControlCharacter(normalized)) {
    throw new Error(`Invalid ${label}.`)
  }

  return normalized
}

/** Build the one Gateway route the renderer may use for Hub preview media. */
export function hubAppPreviewPath(appId: unknown, version: unknown): string {
  const safeAppId = requiredSegment(appId, 'Hub app id', 200)
  const safeVersion = requiredSegment(version, 'Hub app version', 100)
  const params = new URLSearchParams({ version: safeVersion })

  return `/api/apps/hub/${encodeURIComponent(safeAppId)}/preview?${params.toString()}`
}

/** Convert a validated Gateway image response into a renderer-safe data URL. */
export function hubAppPreviewDataUrl(contentType: unknown, bytes: Buffer): string {
  const mimeType = String(contentType || '')
    .split(';', 1)[0]
    .trim()
    .toLowerCase()

  if (!/^image\/(?:avif|gif|jpe?g|png|svg\+xml|webp)$/.test(mimeType)) {
    throw new Error(`Hub preview returned unsupported content type: ${mimeType || 'missing'}.`)
  }

  if (!bytes.length) {
    throw new Error('Hub preview returned an empty image.')
  }

  if (bytes.length > MAX_HUB_APP_PREVIEW_BYTES) {
    throw new Error(`Hub preview exceeds the ${MAX_HUB_APP_PREVIEW_BYTES} byte limit.`)
  }

  return `data:${mimeType};base64,${bytes.toString('base64')}`
}

export { MAX_HUB_APP_PREVIEW_BYTES }
