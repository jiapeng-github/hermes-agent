// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getAppActivitySession = vi.fn()
const launchAppActivityArtifact = vi.fn()
const launchAppInBrowser = vi.fn()

vi.mock('@/hermes', () => ({
  getAppActivitySession: (...args: unknown[]) => getAppActivitySession(...args),
  launchAppActivityArtifact: (...args: unknown[]) => launchAppActivityArtifact(...args)
}))

vi.mock('@/lib/app-launch', () => ({
  launchAppInBrowser: (...args: unknown[]) => launchAppInBrowser(...args)
}))

import { AppActivityView } from './app-activity-view'

describe('AppActivityView', () => {
  const openLaunchUrl = vi.fn()

  beforeEach(() => {
    getAppActivitySession.mockReset()
    launchAppActivityArtifact.mockReset()
    launchAppInBrowser.mockReset()
    openLaunchUrl.mockReset()
    window.hermesDesktop = {
      apps: { openLaunchUrl }
    } as unknown as Window['hermesDesktop']
    getAppActivitySession.mockResolvedValue({
      session: {
        app_id: 'ai.stocksense.watchlist',
        session_id: 'session-1',
        app_name: '自选股盯盘看板',
        created_at: 1_785_000_000,
        updated_at: 1_785_000_100
      },
      artifacts: [
        {
          id: 'artifact-1',
          app_id: 'ai.stocksense.watchlist',
          app_version: '1.0.0',
          session_id: 'session-1',
          run_id: 'run-1',
          title: '贵州茅台行情快照',
          summary: '最新价与资金面数据已刷新。',
          mime_type: 'text/html',
          sha256: 'a'.repeat(64),
          size_bytes: 2048,
          created_at: 1_785_000_100,
          file_path: '/tmp/artifact/index.html'
        }
      ],
      runs: []
    })
    launchAppActivityArtifact.mockResolvedValue({
      launch_id: 'launch-1',
      url: 'http://127.0.0.1:49182/launch/code?next=%2F__hermes%2Fartifacts%2Fartifact-1',
      expires_at: '2026-08-02T12:00:30+08:00'
    })
    openLaunchUrl.mockResolvedValue(true)
    launchAppInBrowser.mockResolvedValue(undefined)
  })

  afterEach(cleanup)

  it('renders the read-only timeline and opens an artifact through AppHost', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <AppActivityView profile="research" sessionId="session-1" />
        </QueryClientProvider>
      </MemoryRouter>
    )

    expect(await screen.findByText('自选股盯盘看板')).toBeTruthy()
    expect(screen.getByText('贵州茅台行情快照')).toBeTruthy()
    expect(screen.getByText('贵州茅台行情快照').closest('article')?.className).toContain(
      'bg-(--ui-card-surface-background)'
    )
    expect(screen.queryByRole('textbox')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '打开产物' }))

    await waitFor(() => expect(launchAppActivityArtifact).toHaveBeenCalledWith('artifact-1', 'research'))
    expect(openLaunchUrl).toHaveBeenCalledWith(
      'http://127.0.0.1:49182/launch/code?next=%2F__hermes%2Fartifacts%2Fartifact-1'
    )

    fireEvent.click(screen.getByRole('button', { name: '继续分析' }))

    await waitFor(() => expect(launchAppInBrowser).toHaveBeenCalledWith('ai.stocksense.watchlist', 'research'))
  })
})
