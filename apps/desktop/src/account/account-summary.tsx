import { useStore } from '@nanostores/react'
import { IconCoins, IconDeviceDesktop, IconLogout, IconRefresh, IconUserCircle } from '@tabler/icons-react'
import type { CSSProperties } from 'react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useI18n } from '@/i18n'

import { $accountState, logoutAccount, refreshAccount } from './store'

function formatUpdatedAt(value: string | null, locale: string): string {
  if (!value) {
    return '—'
  }

  const timestamp = Date.parse(value)

  if (!Number.isFinite(timestamp)) {
    return value
  }

  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : locale, {
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric'
  }).format(timestamp)
}

export function AccountSummary() {
  const { locale, t } = useI18n()
  const state = useStore($accountState)
  const account = state.status?.account

  if (!account) {
    return null
  }

  const copy = t.account
  const refreshing = state.busy === 'refresh'
  const loggingOut = state.busy === 'logout'

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label={`${copy.accountLabel} ${account.mobileMasked}`}
          className="flex h-10 w-full min-w-0 items-center gap-2 rounded-[4px] px-2 text-left text-xs text-(--ui-text-secondary) transition-colors [-webkit-app-region:no-drag] hover:bg-(--ui-control-hover-background) hover:text-foreground"
          type="button"
        >
          <span className="grid size-6 shrink-0 place-items-center rounded-[4px] bg-primary/10 text-primary">
            <IconUserCircle className="size-4" stroke={1.8} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium text-foreground">{account.mobileMasked}</span>
            <span className="block truncate text-[0.65rem] text-(--ui-text-tertiary)">
              {account.pointsBalance.toLocaleString()} {copy.pointUnit}
            </span>
          </span>
          <IconCoins className="size-3.5 shrink-0 text-primary" stroke={1.8} />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        className="w-72 p-0"
        side="right"
        sideOffset={8}
        style={{ '--popover-surface': 'var(--ui-card-surface-background)' } as CSSProperties}
      >
        <div className="border-b border-(--ui-stroke-tertiary) px-3 py-3">
          <div className="text-xs font-medium text-foreground">{account.mobileMasked}</div>
          <div className="mt-1 flex items-baseline gap-1 text-primary">
            <span className="text-xl font-semibold tabular-nums">{account.pointsBalance.toLocaleString()}</span>
            <span className="text-[0.65rem] font-medium">{copy.pointUnit}</span>
          </div>
        </div>

        <dl className="grid gap-2 px-3 py-3 text-xs">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">{copy.pointsUpdated}</dt>
            <dd className="truncate text-right text-foreground">{formatUpdatedAt(account.pointsUpdatedAt, locale)}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="flex items-center gap-1.5 text-muted-foreground">
              <IconDeviceDesktop className="size-3.5" />
              {copy.currentDevice}
            </dt>
            <dd className="max-w-36 truncate text-right text-foreground">{state.status?.deviceName || '—'}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">{copy.recentUsage}</dt>
            <dd className="text-right text-foreground">
              {account.recentPointsSpent == null
                ? copy.noRecentUsage
                : `${account.recentPointsSpent.toLocaleString()} ${copy.pointUnit}`}
            </dd>
          </div>
        </dl>

        {state.error && (
          <div className="border-t border-destructive/20 px-3 py-2 text-[0.6875rem] text-destructive">
            {state.error.message}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-(--ui-stroke-tertiary) px-2 py-2">
          <Button disabled={refreshing || loggingOut} onClick={() => void refreshAccount()} size="xs" variant="ghost">
            <IconRefresh className={refreshing ? 'animate-spin' : undefined} />
            {refreshing ? copy.refreshing : copy.refreshPoints}
          </Button>
          <Button
            disabled={refreshing || loggingOut}
            onClick={() => void logoutAccount().catch(() => undefined)}
            size="xs"
            variant="ghost"
          >
            <IconLogout />
            {loggingOut ? copy.signingOut : copy.signOut}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
