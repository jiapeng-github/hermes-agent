import { afterEach, describe, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'
import type { SessionInfo, SessionMessage } from '@/types/hermes'

import { artifactFromAppActivity, artifactImageSrc, collectArtifactsForSession, mergeArtifacts } from './artifact-utils'

function makeSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    ended_at: null,
    id: 'session-1',
    input_tokens: 0,
    is_active: false,
    last_active: 1000,
    message_count: 1,
    model: null,
    output_tokens: 0,
    preview: null,
    source: null,
    started_at: 1000,
    title: 'Session',
    tool_call_count: 0,
    ...overrides
  }
}

describe('collectArtifactsForSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    $connection.set(null)
  })

  it('indexes plain https links from assistant text', () => {
    const artifacts = collectArtifactsForSession(makeSession(), [
      {
        content: 'Reference: https://example.com/docs/getting-started',
        role: 'assistant',
        timestamp: 2000
      }
    ])

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'https://example.com/docs/getting-started',
      kind: 'link',
      value: 'https://example.com/docs/getting-started'
    })
  })

  it('does not index incidental paths and links from tool payloads', () => {
    const messages: SessionMessage[] = [
      {
        content: JSON.stringify({ path: '/workspace/source.ts', source_url: 'https://example.com/changelog/latest' }),
        role: 'tool',
        tool_name: 'read_file',
        timestamp: 3000
      }
    ]

    const artifacts = collectArtifactsForSession(makeSession({ id: 'session-2' }), messages)

    expect(artifacts).toEqual([])
  })

  it('indexes the visible output of a successful image generation tool', () => {
    const artifacts = collectArtifactsForSession(makeSession(), [
      {
        content: JSON.stringify({ success: true, host_image: '/workspace/output/chart.png' }),
        role: 'tool',
        tool_name: 'image_generate',
        timestamp: 3000
      }
    ])

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({ kind: 'image', value: '/workspace/output/chart.png' })
  })

  it('keeps the newest session relation when the same artifact appears more than once', () => {
    const older = collectArtifactsForSession(makeSession({ id: 'older', profile: 'default', title: 'Older' }), [
      { content: 'Result: /workspace/report.pdf', role: 'assistant', timestamp: 2000 }
    ])
    const newer = collectArtifactsForSession(makeSession({ id: 'newer', profile: 'default', title: 'Newer' }), [
      { content: 'Result: /workspace/report.pdf', role: 'assistant', timestamp: 4000 }
    ])

    expect(mergeArtifacts([...older, ...newer])).toMatchObject([
      { sessionId: 'newer', sessionTitle: 'Newer', value: '/workspace/report.pdf' }
    ])
  })

  it('converts application activity snapshots into launchable artifacts', () => {
    const artifact = artifactFromAppActivity(makeSession({ id: 'app-session', profile: 'research' }), {
      id: 'artifact-1',
      app_id: 'ai.stocksense.watchlist',
      app_version: '1.0.0',
      session_id: 'app-session',
      run_id: 'run-1',
      title: '自选股快照',
      summary: '完成',
      mime_type: 'text/html',
      sha256: 'abc',
      size_bytes: 100,
      created_at: 5000,
      file_path: '/tmp/watchlist.html'
    })

    expect(artifact).toMatchObject({
      appActivityArtifactId: 'artifact-1',
      kind: 'file',
      label: '自选股快照',
      profile: 'research',
      sessionId: 'app-session'
    })
  })

  it('resolves remote image artifact thumbnails through the desktop fs bridge', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path.startsWith('/api/fs/read-data-url?')) {
        return { dataUrl: 'data:image/jpeg;base64,cmVtb3Rl' }
      }

      throw new Error(`unexpected path ${path}`)
    })

    vi.stubGlobal('window', { hermesDesktop: { api } })
    $connection.set({ baseUrl: 'https://gw', mode: 'remote', token: 'secret' } as never)

    const path = '/Users/me/.hermes/skills/work-esab/references/images/manual-step03.jpeg'
    const downloadHref = `https://gw/api/files/download?path=${encodeURIComponent(path)}&token=secret`

    await expect(artifactImageSrc(path, downloadHref)).resolves.toBe('data:image/jpeg;base64,cmVtb3Rl')

    expect(api).toHaveBeenCalledWith({
      path: '/api/fs/read-data-url?path=%2FUsers%2Fme%2F.hermes%2Fskills%2Fwork-esab%2Freferences%2Fimages%2Fmanual-step03.jpeg'
    })
  })
})
