// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const launchHermesApp = vi.fn()

vi.mock('@/hermes', () => ({
  launchHermesApp: (...args: unknown[]) => launchHermesApp(...args)
}))

import { launchAppInBrowser, launchAppWithFallback, WATCHLIST_APP_ID } from './app-launch'

describe('application browser launch', () => {
  const openLaunchUrl = vi.fn()

  beforeEach(() => {
    launchHermesApp.mockReset()
    openLaunchUrl.mockReset()
    window.hermesDesktop = { apps: { openLaunchUrl } } as unknown as Window['hermesDesktop']
  })

  it('opens only the one-time loopback URL returned by the backend', async () => {
    launchHermesApp.mockResolvedValue({
      launch_id: '91dfb287-c638-4cc9-9a12-0cb61dcbab55',
      url: 'http://127.0.0.1:49182/launch/one-time',
      expires_at: '2026-07-13T10:00:30+00:00'
    })
    openLaunchUrl.mockResolvedValue(true)

    await launchAppInBrowser(WATCHLIST_APP_ID)

    expect(launchHermesApp).toHaveBeenCalledWith(WATCHLIST_APP_ID)
    expect(openLaunchUrl).toHaveBeenCalledWith('http://127.0.0.1:49182/launch/one-time')
  })

  it('uses the retained desktop route when AppHost launch fails', async () => {
    const fallback = vi.fn()
    launchHermesApp.mockRejectedValue(new Error('runtime unavailable'))

    launchAppWithFallback(WATCHLIST_APP_ID, fallback)
    await vi.waitFor(() => expect(fallback).toHaveBeenCalledOnce())

    expect(openLaunchUrl).not.toHaveBeenCalled()
  })
})
