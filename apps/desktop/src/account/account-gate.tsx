import { useStore } from '@nanostores/react'
import { IconCheck, IconLoader2, IconLock, IconMessage, IconRefresh } from '@tabler/icons-react'
import { type FormEvent, type ReactNode, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

import stockSenseLogo from './stocksense-logo.png'
import {
  $accountState,
  applyAccountStatus,
  bootstrapAccount,
  loginAccount,
  refreshAccount,
  sendAccountSms
} from './store'

const MOBILE_RE = /^1[3-9]\d{9}$/
const CODE_RE = /^\d{6}$/
const ACCOUNT_REFRESH_INTERVAL_MS = 60_000

export function AccountGate({ children }: { children: ReactNode }) {
  const state = useStore($accountState)

  useEffect(() => {
    void bootstrapAccount().catch(() => undefined)

    return window.hermesDesktop.account.onChanged(applyAccountStatus)
  }, [])

  useEffect(() => {
    if (state.status?.phase !== 'authenticated') {
      return
    }

    const refreshIfVisible = () => {
      if (document.visibilityState === 'visible') {
        void refreshAccount({ silent: true })
      }
    }

    const interval = window.setInterval(refreshIfVisible, ACCOUNT_REFRESH_INTERVAL_MS)

    refreshIfVisible()
    window.addEventListener('focus', refreshIfVisible)
    document.addEventListener('visibilitychange', refreshIfVisible)

    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', refreshIfVisible)
      document.removeEventListener('visibilitychange', refreshIfVisible)
    }
  }, [state.status?.phase, state.status?.profile])

  if (!state.initialized) {
    return <AccountBootView />
  }

  if (state.status?.gateEnabled === false || state.status?.phase === 'authenticated') {
    return children
  }

  return <AccountLoginView />
}

function AccountBootView() {
  const { t } = useI18n()

  return (
    <div className="relative grid h-dvh min-h-[32rem] place-items-center overflow-hidden bg-background text-foreground">
      <div className="absolute inset-x-0 top-0 h-(--titlebar-height) [-webkit-app-region:drag]" />
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <IconLoader2 className="size-4 animate-spin text-primary" />
        <span>{t.account.initializing}</span>
      </div>
    </div>
  )
}

function AccountLoginView() {
  const { t } = useI18n()
  const state = useStore($accountState)
  const copy = t.account
  const [mobile, setMobile] = useState('')
  const [code, setCode] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    if (cooldown <= 0) {
      return
    }

    const timer = window.setInterval(() => setCooldown(value => Math.max(0, value - 1)), 1000)

    return () => window.clearInterval(timer)
  }, [cooldown])

  const busy = state.busy
  const error = localError || state.error?.message || state.status?.error?.message || null
  const secureStorageAvailable = state.status?.secureStorageAvailable !== false
  const phoneValid = MOBILE_RE.test(mobile)
  const codeValid = CODE_RE.test(code)
  const canSend = phoneValid && cooldown === 0 && busy === null && secureStorageAvailable
  const canLogin = phoneValid && codeValid && accepted && busy === null && secureStorageAvailable

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setLocalError(null)

    if (!phoneValid) {
      setLocalError(copy.invalidMobile)

      return
    }

    if (!codeValid) {
      setLocalError(copy.invalidCode)

      return
    }

    if (!accepted) {
      setLocalError(copy.agreementRequired)

      return
    }

    try {
      await loginAccount(mobile, code)
    } catch {
      // The account store owns the normalized service error.
    }
  }

  const sendCode = async () => {
    setLocalError(null)

    if (!phoneValid) {
      setLocalError(copy.invalidMobile)

      return
    }

    try {
      setCooldown(await sendAccountSms(mobile))
    } catch {
      // The account store owns the normalized service error.
    }
  }

  return (
    <main className="relative h-dvh min-h-[38rem] overflow-auto bg-white text-[#182033] [color-scheme:light]">
      <div className="fixed inset-x-0 top-0 z-30 h-(--titlebar-height) [-webkit-app-region:drag]" />

      <div className="grid min-h-full grid-cols-1 lg:grid-cols-[minmax(20rem,44%)_minmax(30rem,56%)]">
        <section className="flex min-h-[17rem] items-center justify-center border-b border-[#e5eaf2] bg-[#f5f7fb] px-8 pb-8 pt-[calc(var(--titlebar-height)+2rem)] lg:min-h-full lg:border-b-0 lg:border-r lg:px-12 lg:py-[calc(var(--titlebar-height)+3rem)]">
          <div className="flex max-w-md flex-col items-center text-center">
            <img
              alt={`${copy.brand} Logo`}
              className="h-auto w-40 object-contain md:w-56 xl:w-64"
              draggable={false}
              src={stockSenseLogo}
            />
            <div className="mt-5 text-[2rem] font-semibold leading-tight text-[#111a2d] md:mt-7 md:text-[2.25rem]">
              {copy.brand.toUpperCase()}
            </div>
            <p className="mt-3 text-sm leading-6 text-[#7b8495] md:text-base">{copy.subtitle}</p>
          </div>
        </section>

        <section className="flex min-h-[32rem] min-w-0 flex-col bg-white px-6 pb-8 pt-10 sm:px-10 md:px-14 md:pb-10 lg:min-h-full lg:pt-[calc(var(--titlebar-height)+2rem)] xl:px-20">
          <div className="mx-auto flex w-full max-w-[30rem] flex-1 items-center py-8 md:py-12">
            <form className="w-full" onSubmit={submit}>
              <header className="mb-9">
                <h1 className="text-[2rem] font-semibold leading-tight text-[#111827]">{copy.loginTitle}</h1>
                <p className="mt-3 text-sm leading-6 text-[#7b8495]">{copy.loginSubtitle}</p>
              </header>

              <div className="space-y-5">
                <label className="block space-y-2">
                  <span className="text-xs font-medium text-[#3f4756]">{copy.mobileLabel}</span>
                  <div className="flex h-12 overflow-hidden rounded-[6px] border border-[#cfd6e2] bg-white transition-colors focus-within:border-[#0b57f0] focus-within:ring-2 focus-within:ring-[#0b57f0]/15">
                    <span className="grid w-16 shrink-0 place-items-center border-r border-[#e2e6ed] bg-white text-sm text-[#606a7b]">
                      +86
                    </span>
                    <Input
                      aria-label={copy.mobileLabel}
                      autoComplete="tel"
                      className="h-full flex-1 rounded-none border-0 px-4 text-sm text-[#182033] shadow-none placeholder:text-[#a0a8b6] focus-visible:ring-0"
                      disabled={busy !== null}
                      inputMode="numeric"
                      maxLength={11}
                      onChange={event => setMobile(event.target.value.replace(/\D/g, '').slice(0, 11))}
                      placeholder={copy.mobilePlaceholder}
                      style={{ background: '#fff', boxShadow: 'none' }}
                      value={mobile}
                    />
                  </div>
                </label>

                <label className="block space-y-2">
                  <span className="text-xs font-medium text-[#3f4756]">{copy.codeLabel}</span>
                  <div className="flex h-12 overflow-hidden rounded-[6px] border border-[#cfd6e2] bg-white transition-colors focus-within:border-[#0b57f0] focus-within:ring-2 focus-within:ring-[#0b57f0]/15">
                    <Input
                      aria-label={copy.codeLabel}
                      autoComplete="one-time-code"
                      className="h-full min-w-0 flex-1 rounded-none border-0 px-4 font-mono text-sm text-[#182033] shadow-none placeholder:text-[#a0a8b6] focus-visible:ring-0"
                      disabled={busy !== null}
                      inputMode="numeric"
                      maxLength={6}
                      onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                      placeholder={copy.codePlaceholder}
                      style={{ background: '#fff', boxShadow: 'none' }}
                      value={code}
                    />
                    <Button
                      className="h-full min-w-28 rounded-none border-l border-[#dbe1ea] bg-white px-4 text-[#0b57f0] hover:bg-[#f4f7ff] hover:text-[#084bd4]"
                      disabled={!canSend}
                      onClick={() => void sendCode()}
                      type="button"
                      variant="ghost"
                    >
                      {busy === 'sms' ? (
                        <>
                          <IconLoader2 className="animate-spin" />
                          {copy.sendingCode}
                        </>
                      ) : cooldown > 0 ? (
                        copy.resendIn(cooldown)
                      ) : (
                        <>
                          <IconMessage />
                          {copy.sendCode}
                        </>
                      )}
                    </Button>
                  </div>
                </label>

                <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-5 text-[#6f7888]">
                  <span
                    className={cn(
                      'mt-0.5 grid size-4 shrink-0 place-items-center rounded-[3px] border transition-colors',
                      accepted ? 'border-[#0b57f0] bg-[#0b57f0] text-white' : 'border-[#b8c0cd] bg-white'
                    )}
                  >
                    {accepted && <IconCheck className="size-3" stroke={2.5} />}
                  </span>
                  <input
                    checked={accepted}
                    className="sr-only"
                    disabled={busy !== null}
                    onChange={event => setAccepted(event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    {copy.agreementPrefix}{' '}
                    <button
                      className="text-[#0b57f0] underline decoration-[#0b57f0]/25 underline-offset-2 hover:decoration-[#0b57f0]"
                      onClick={event => {
                        event.preventDefault()
                        void window.hermesDesktop.openExternal('https://www.stocksense.work/terms')
                      }}
                      type="button"
                    >
                      {copy.terms}
                    </button>{' '}
                    {copy.agreementAnd}{' '}
                    <button
                      className="text-[#0b57f0] underline decoration-[#0b57f0]/25 underline-offset-2 hover:decoration-[#0b57f0]"
                      onClick={event => {
                        event.preventDefault()
                        void window.hermesDesktop.openExternal('https://www.stocksense.work/privacy')
                      }}
                      type="button"
                    >
                      {copy.privacy}
                    </button>
                  </span>
                </label>
              </div>

              {!secureStorageAvailable && (
                <div className="mt-5 border-l-2 border-[#df3651] pl-3 text-xs leading-5 text-[#c92543]">
                  {copy.secureStorageUnavailable}
                </div>
              )}

              {error && (
                <div className="mt-5 border-l-2 border-[#df3651] pl-3 text-xs leading-5 text-[#c92543]">{error}</div>
              )}

              <Button
                className="mt-8 h-12 w-full rounded-[6px] bg-[#0b57f0] text-sm text-white hover:bg-[#084bd4] disabled:bg-[#8caef8] disabled:text-white"
                disabled={!canLogin}
                size="lg"
                type="submit"
              >
                {busy === 'login' ? (
                  <>
                    <IconLoader2 className="animate-spin" />
                    {copy.signingIn}
                  </>
                ) : (
                  copy.signIn
                )}
              </Button>

              {state.error?.retryable && (
                <Button
                  className="mx-auto mt-3 flex text-[#667085] hover:text-[#182033]"
                  onClick={() => void bootstrapAccount().catch(() => undefined)}
                  type="button"
                  variant="text"
                >
                  <IconRefresh />
                  {copy.retry}
                </Button>
              )}
            </form>
          </div>

          <div className="mx-auto flex w-full max-w-[30rem] items-center gap-2 pb-1 text-xs text-[#8a93a2]">
            <IconLock className="size-3.5" />
            <span>{copy.secureStorageProtected}</span>
          </div>
        </section>
      </div>
    </main>
  )
}
