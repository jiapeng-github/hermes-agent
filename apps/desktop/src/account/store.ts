import { atom, computed } from 'nanostores'

import type { DesktopAccountError, DesktopAccountStatus } from '@/global'

export interface AccountStoreState {
  busy: 'login' | 'logout' | 'refresh' | 'sms' | null
  error: DesktopAccountError | null
  initialized: boolean
  status: DesktopAccountStatus | null
}

const initialState: AccountStoreState = {
  busy: null,
  error: null,
  initialized: false,
  status: null
}

export const $accountState = atom<AccountStoreState>(initialState)
export const $accountAuthenticated = computed(
  $accountState,
  state => state.status?.phase === 'authenticated' && Boolean(state.status.account)
)

let bootstrapPromise: Promise<DesktopAccountStatus> | null = null
let refreshPromise: Promise<DesktopAccountStatus | null> | null = null

function accountBridge() {
  const bridge = window.hermesDesktop?.account

  if (!bridge) {
    throw new Error('StockSense account bridge is unavailable.')
  }

  return bridge
}

export function applyAccountStatus(status: DesktopAccountStatus): void {
  $accountState.set({
    busy: null,
    error: status.error,
    initialized: true,
    status
  })
}

export function bootstrapAccount(): Promise<DesktopAccountStatus> {
  if (bootstrapPromise) {
    return bootstrapPromise
  }

  bootstrapPromise = accountBridge()
    .status()
    .then(status => {
      applyAccountStatus(status)

      return status
    })
    .catch(error => {
      const accountError: DesktopAccountError = {
        code: 'ACCOUNT_BOOT_FAILED',
        message: error instanceof Error ? error.message : String(error),
        retryAfterSeconds: null,
        retryable: true
      }

      $accountState.set({ busy: null, error: accountError, initialized: true, status: null })
      throw error
    })
    .finally(() => {
      bootstrapPromise = null
    })

  return bootstrapPromise
}

export async function sendAccountSms(mobile: string): Promise<number> {
  const current = $accountState.get()
  $accountState.set({ ...current, busy: 'sms', error: null })

  const result = await accountBridge().sendSms(mobile)

  if (!result.ok) {
    $accountState.set({ ...$accountState.get(), busy: null, error: result.error })
    throw result.error
  }

  $accountState.set({ ...$accountState.get(), busy: null, error: null })

  return result.data.cooldownSeconds
}

export async function loginAccount(mobile: string, code: string): Promise<DesktopAccountStatus> {
  const current = $accountState.get()
  $accountState.set({ ...current, busy: 'login', error: null })

  const result = await accountBridge().login({ code, mobile })

  if (!result.ok) {
    $accountState.set({ ...$accountState.get(), busy: null, error: result.error })
    throw result.error
  }

  applyAccountStatus(result.data)

  return result.data
}

export function refreshAccount({ silent = false }: { silent?: boolean } = {}): Promise<DesktopAccountStatus | null> {
  if (refreshPromise) {
    return refreshPromise
  }

  const current = $accountState.get()

  if (current.status?.phase !== 'authenticated') {
    return Promise.resolve(current.status)
  }

  if (!silent) {
    $accountState.set({ ...current, busy: 'refresh', error: null })
  }

  refreshPromise = accountBridge()
    .refresh()
    .then(result => {
      if (!result.ok) {
        $accountState.set({ ...$accountState.get(), busy: null, error: result.error })

        if (['ACCOUNT_DISABLED', 'ACCOUNT_TOKEN_EXPIRED', 'HTTP_401', 'HTTP_403'].includes(result.error.code)) {
          void bootstrapAccount()
        }

        return null
      }

      applyAccountStatus(result.data)

      return result.data
    })
    .catch(error => {
      if (!silent) {
        $accountState.set({
          ...$accountState.get(),
          busy: null,
          error: {
            code: 'ACCOUNT_REFRESH_FAILED',
            message: error instanceof Error ? error.message : String(error),
            retryAfterSeconds: null,
            retryable: true
          }
        })
      }

      return null
    })
    .finally(() => {
      refreshPromise = null
    })

  return refreshPromise
}

export async function logoutAccount(): Promise<void> {
  const current = $accountState.get()
  $accountState.set({ ...current, busy: 'logout', error: null })

  const result = await accountBridge().logout()

  if (!result.ok) {
    $accountState.set({ ...$accountState.get(), busy: null, error: result.error })
    throw result.error
  }

  applyAccountStatus(result.data)
}

export function resetAccountStoreForTest(): void {
  bootstrapPromise = null
  refreshPromise = null
  $accountState.set(initialState)
}
