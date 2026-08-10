import { describe, expect, it } from 'vitest'

import { hubAppPreviewDataUrl, hubAppPreviewPath, MAX_HUB_APP_PREVIEW_BYTES } from './hub-app-preview'

describe('Hub app preview bridge helpers', () => {
  it('builds a constrained, encoded Gateway preview route', () => {
    expect(hubAppPreviewPath('ai.stocksense.panorama', '1.0.0+build 1')).toBe(
      '/api/apps/hub/ai.stocksense.panorama/preview?version=1.0.0%2Bbuild+1'
    )
  })

  it('rejects malformed media route inputs', () => {
    expect(() => hubAppPreviewPath('', '1.0.0')).toThrow('Invalid Hub app id.')
    expect(() => hubAppPreviewPath('ai.stocksense.panorama', 'bad\nversion')).toThrow('Invalid Hub app version.')
  })

  it('returns a data URL only for bounded image responses', () => {
    expect(hubAppPreviewDataUrl('image/webp; charset=utf-8', Buffer.from([1, 2, 3]))).toBe('data:image/webp;base64,AQID')
    expect(() => hubAppPreviewDataUrl('text/html', Buffer.from('<html>'))).toThrow('unsupported content type')
    expect(() => hubAppPreviewDataUrl('image/png', Buffer.alloc(MAX_HUB_APP_PREVIEW_BYTES + 1))).toThrow('exceeds')
  })
})
