import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DesktopAccountStatus } from '@/global'
import { I18nProvider } from '@/i18n'

import { AccountGate } from './account-gate'
import { resetAccountStoreForTest } from './store'

function accountStatus(phase: DesktopAccountStatus['phase']): DesktopAccountStatus {
  const authenticated = phase === 'authenticated'

  return {
    account: authenticated
      ? {
          mobileMasked: '138****8000',
          pointsBalance: 1200,
          pointsUpdatedAt: '2026-08-05T08:00:00Z',
          recentPointsSpent: null,
          status: 'ACTIVE',
          userId: 'user-a'
        }
      : null,
    deviceName: 'Desktop Test',
    error: null,
    gateEnabled: true,
    modelCatalog: [],
    modelCredential: null,
    phase,
    profile: authenticated ? 'default' : null,
    secureStorageAvailable: true
  }
}

function installBridge(initial: DesktopAccountStatus) {
  const authenticated = accountStatus('authenticated')

  const bridge = {
    login: vi.fn().mockResolvedValue({ data: authenticated, ok: true }),
    logout: vi.fn().mockResolvedValue({ data: accountStatus('unauthenticated'), ok: true }),
    onChanged: vi.fn().mockReturnValue(() => undefined),
    refresh: vi.fn().mockResolvedValue({ data: authenticated, ok: true }),
    sendSms: vi.fn().mockResolvedValue({ data: { cooldownSeconds: 60 }, ok: true }),
    status: vi.fn().mockResolvedValue(initial)
  }

  Object.defineProperty(window, 'hermesDesktop', {
    configurable: true,
    value: {
      account: bridge,
      openExternal: vi.fn().mockResolvedValue(undefined)
    },
    writable: true
  })

  return bridge
}

function renderGate() {
  return render(
    <I18nProvider configClient={null} initialLocale="zh">
      <AccountGate>
        <div>股票工作区</div>
      </AccountGate>
    </I18nProvider>
  )
}

describe('Finance Mate account gate', () => {
  beforeEach(() => {
    resetAccountStoreForTest()
  })

  afterEach(() => {
    cleanup()
    resetAccountStoreForTest()
    Reflect.deleteProperty(window, 'hermesDesktop')
    vi.restoreAllMocks()
  })

  it('keeps the workspace unmounted until the user signs in', async () => {
    installBridge(accountStatus('unauthenticated'))
    renderGate()

    expect(await screen.findByText('登录 / 注册')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '登录 Finance Mate' })).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Finance Mate Logo' })).toBeTruthy()
    expect(screen.getByLabelText('手机号码').parentElement?.className).toContain('bg-white')
    expect(screen.getByLabelText('短信验证码').parentElement?.className).toContain('bg-white')
    expect(screen.queryByText('股票工作区')).toBeNull()
  })

  it('mounts the workspace immediately for a valid account session', async () => {
    installBridge(accountStatus('authenticated'))
    renderGate()

    expect(await screen.findByText('股票工作区')).toBeTruthy()
    expect(screen.queryByText('登录 / 注册')).toBeNull()
  })

  it('mounts the workspace only after SMS login succeeds', async () => {
    const bridge = installBridge(accountStatus('unauthenticated'))
    renderGate()

    fireEvent.change(await screen.findByLabelText('手机号码'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByLabelText('短信验证码'), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '登录 / 注册' }))

    expect(await screen.findByText('股票工作区')).toBeTruthy()
    expect(bridge.login).toHaveBeenCalledWith({ code: '123456', mobile: '13800138000' })
  })
})
