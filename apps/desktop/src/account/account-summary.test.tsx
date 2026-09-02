// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DesktopAccountStatus } from '@/global'
import { I18nProvider } from '@/i18n'

import { AccountSummary } from './account-summary'
import { applyAccountStatus, resetAccountStoreForTest } from './store'

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  )
})

const authenticatedStatus: DesktopAccountStatus = {
  account: {
    mobileMasked: '138****8000',
    pointsBalance: 1200,
    pointsUpdatedAt: '2026-08-05T08:00:00Z',
    recentPointsSpent: null,
    status: 'ACTIVE',
    userId: 'user-a'
  },
  deviceName: 'Desktop Test',
  error: null,
  gateEnabled: true,
  modelCatalog: [],
  modelCredential: null,
  phase: 'authenticated',
  profile: 'default',
  secureStorageAvailable: true
}

describe('AccountSummary', () => {
  beforeEach(() => {
    resetAccountStoreForTest()
    applyAccountStatus(authenticatedStatus)
  })

  afterEach(() => {
    cleanup()
    resetAccountStoreForTest()
  })

  it('uses the shared content-card material for account details', async () => {
    const { baseElement } = render(
      <I18nProvider configClient={null} initialLocale="zh">
        <AccountSummary />
      </I18nProvider>
    )

    fireEvent.click(screen.getByRole('button', { name: /138\*{4}8000/ }))

    await waitFor(() => {
      const content = baseElement.querySelector<HTMLElement>('[data-slot="popover-content"]')

      expect(content?.style.getPropertyValue('--popover-surface')).toBe('var(--ui-card-surface-background)')
    })
  })
})
