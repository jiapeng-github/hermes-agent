import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CandlestickSeries, ColorType, createChart, HistogramSeries, LineSeries, type Time } from 'lightweight-charts'
import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  addWatchlistStock,
  getCompanyAnalysisSnapshot,
  getWatchlistSnapshot,
  getWatchlistStockDetail,
  refreshWatchlistSnapshot,
  removeWatchlistStock
} from '@/hermes'
import { launchAppInBrowser, WATCHLIST_APP_ID } from '@/lib/app-launch'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CandlestickChart,
  CheckCircle2,
  ChevronDown,
  Clock,
  ExternalLink,
  Info,
  Plus,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Zap
} from '@/lib/icons'
import { cn } from '@/lib/utils'
import type {
  CompanyAnalysisSnapshot,
  IndustryMonitorIndex,
  WatchlistGap,
  WatchlistKlinePoint,
  WatchlistQuote,
  WatchlistRefreshState,
  WatchlistSector,
  WatchlistSnapshot,
  WatchlistStockDetail,
  WatchlistTechnicals
} from '@/types/hermes'

import { COMPANY_ANALYSIS_ROUTE } from '../routes'

const QUERY_KEY = ['finance', 'watchlist'] as const

type DetailTab = 'analysis' | 'market'
type SortKey = 'change' | 'flow' | 'name' | 'price' | 'sector'

interface SortState {
  direction: 'asc' | 'desc'
  key: SortKey
}

export function WatchlistView() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [addInput, setAddInput] = useState('')
  const [addNotice, setAddNotice] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<WatchlistQuote | null>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('market')
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [sort, setSort] = useState<SortState>({ direction: 'desc', key: 'change' })

  const snapshot = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getWatchlistSnapshot,
    refetchInterval: query => {
      const data = query.state.data as WatchlistSnapshot | undefined

      if (data?.refresh?.refreshing) {
        return 1500
      }

      return autoRefresh ? 20_000 : false
    },
    refetchOnWindowFocus: false,
    staleTime: 10_000
  })

  const refresh = useMutation({
    mutationFn: refreshWatchlistSnapshot,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    }
  })

  const launchApp = useMutation({
    mutationFn: () => launchAppInBrowser(WATCHLIST_APP_ID)
  })

  const addStock = useMutation({
    mutationFn: addWatchlistStock,
    onSuccess: response => {
      setAddInput('')
      setAddNotice(response.added === false ? '该股票已在自选股中' : `已添加 ${response.item?.name ?? '股票'}`)
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      window.setTimeout(() => setAddNotice(null), 2500)
    }
  })

  const removeStock = useMutation({
    mutationFn: removeWatchlistStock,
    onSuccess: (_response, code) => {
      if (selectedCode === code) {
        setSelectedCode(null)
      }

      void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    }
  })

  const data = snapshot.data
  const selectedStock = data?.items.find(item => item.code === selectedCode) ?? null
  const isRefreshing = Boolean(data?.refresh?.refreshing || refresh.isPending)
  const sortedItems = useMemo(() => sortWatchlist(data?.items ?? [], sort), [data?.items, sort])

  function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = addInput.trim()

    if (!query) {
      return
    }

    setAddNotice(null)
    addStock.mutate(query)
  }

  function handleSort(key: SortKey) {
    setSort(current => ({
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
      key
    }))
  }

  function openDetail(code: string) {
    setSelectedCode(code)
    setDetailTab('market')
  }

  function openFullAnalysis(stock: WatchlistQuote) {
    setSelectedCode(null)
    navigate(`${COMPANY_ANALYSIS_ROUTE}?query=${encodeURIComponent(stock.code)}`)
  }

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[linear-gradient(180deg,color-mix(in_srgb,var(--ui-chat-surface-background)_94%,white)_0%,var(--ui-chat-surface-background)_22rem)] dark:bg-[linear-gradient(180deg,#061014_0%,var(--ui-chat-surface-background)_24rem)]">
      <WatchlistHeader
        addError={
          addStock.error instanceof Error
            ? addStock.error.message
            : launchApp.error instanceof Error
              ? launchApp.error.message
              : null
        }
        addInput={addInput}
        addNotice={addNotice}
        addPending={addStock.isPending}
        autoRefresh={autoRefresh}
        data={data}
        isLoading={snapshot.isLoading}
        isRefreshing={isRefreshing}
        onAdd={handleAdd}
        onAddInputChange={setAddInput}
        onOpenApp={() => launchApp.mutate()}
        onRefresh={() => refresh.mutate()}
        onToggleAutoRefresh={() => setAutoRefresh(value => !value)}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        {snapshot.isError ? (
          <ErrorPanel message={snapshot.error instanceof Error ? snapshot.error.message : '自选股行情加载失败'} />
        ) : data ? (
          <WatchlistDashboard
            data={data}
            items={sortedItems}
            onDelete={setDeleteTarget}
            onOpenDetail={openDetail}
            onSort={handleSort}
            sort={sort}
          />
        ) : (
          <DashboardSkeleton />
        )}
      </div>

      <StockDetailDialog
        onOpenChange={open => !open && setSelectedCode(null)}
        onOpenFullAnalysis={openFullAnalysis}
        onTabChange={setDetailTab}
        open={Boolean(selectedStock)}
        stock={selectedStock}
        tab={detailTab}
      />

      <ConfirmDialog
        confirmLabel="删除"
        description={deleteTarget ? `将 ${deleteTarget.name}（${deleteTarget.code}）从自选股中移除。` : undefined}
        destructive
        onClose={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (deleteTarget) {
            await removeStock.mutateAsync(deleteTarget.code)
          }
        }}
        open={Boolean(deleteTarget)}
        title="删除自选股"
      />
    </section>
  )
}

function WatchlistHeader({
  addError,
  addInput,
  addNotice,
  addPending,
  autoRefresh,
  data,
  isLoading,
  isRefreshing,
  onAdd,
  onAddInputChange,
  onOpenApp,
  onRefresh,
  onToggleAutoRefresh
}: {
  addError: string | null
  addInput: string
  addNotice: string | null
  addPending: boolean
  autoRefresh: boolean
  data?: WatchlistSnapshot
  isLoading: boolean
  isRefreshing: boolean
  onAdd: (event: FormEvent<HTMLFormElement>) => void
  onAddInputChange: (value: string) => void
  onOpenApp: () => void
  onRefresh: () => void
  onToggleAutoRefresh: () => void
}) {
  const statusLabel = isRefreshing
    ? '行情刷新中'
    : data?.refresh?.cache_state === 'warm'
      ? '已缓存'
      : isLoading
        ? '加载中'
        : '等待行情'

  return (
    <header className="z-20 shrink-0 border-b border-(--ui-stroke-secondary) bg-(--ui-chat-surface-background) px-4 pb-3 pt-[calc(var(--titlebar-height)+0.7rem)] shadow-sm sm:px-5">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span className="grid size-8 shrink-0 place-items-center rounded-[6px] border border-blue-500/25 bg-blue-500/10 text-blue-500 shadow-[0_0_18px_color-mix(in_srgb,rgb(59_130_246)_22%,transparent)]">
              <Star className="size-4" />
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-normal text-foreground">自选股盯盘</h1>
              <p className="truncate text-xs text-(--ui-text-tertiary)">
                实时行情 · 主力资金 · 板块强弱 · K线详情 · 基本面分析
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[0.7rem]">
            <StatusPill tone={data?.ok ? 'good' : isRefreshing ? 'warn' : 'neutral'}>
              {data?.source ?? 'mx-ds-mcp'}
            </StatusPill>
            <StatusPill>{data?.as_of ? `数据日 ${data.as_of}` : '等待交易日'}</StatusPill>
            <StatusPill>{statusLabel}</StatusPill>
            <StatusPill>{`${data?.summary.total ?? 0} 只自选股`}</StatusPill>
          </div>
        </div>

        <div className="min-w-0 xl:w-[38rem]">
          <form className="flex min-w-0 flex-col gap-2 sm:flex-row" onSubmit={onAdd}>
            <label className="relative min-w-0 flex-1">
              <span className="sr-only">输入股票名称或代码</span>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-(--ui-text-tertiary)" />
              <Input
                className="h-8 rounded-[6px] border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) pl-8 text-xs"
                disabled={addPending}
                onChange={event => onAddInputChange(event.target.value)}
                placeholder="输入 A 股名称或代码"
                value={addInput}
              />
            </label>
            <div className="flex shrink-0 items-center gap-2">
              <Button onClick={onOpenApp} size="sm" type="button" variant="outline">
                <ExternalLink className="size-3.5" />
                应用版
              </Button>
              <Button disabled={addPending || !addInput.trim()} size="sm" type="submit" variant="outline">
                {addPending ? <RefreshCw className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
                添加
              </Button>
              <Button
                aria-pressed={autoRefresh}
                className={cn(autoRefresh && 'bg-blue-500/10 text-blue-600 dark:text-blue-300')}
                onClick={onToggleAutoRefresh}
                size="icon-sm"
                title={autoRefresh ? '暂停自动盯盘' : '开启自动盯盘'}
                type="button"
                variant="outline"
              >
                <Clock className="size-3.5" />
              </Button>
              <Button
                disabled={isRefreshing}
                onClick={onRefresh}
                size="icon-sm"
                title="刷新行情"
                type="button"
                variant="outline"
              >
                <RefreshCw className={cn('size-3.5', isRefreshing && 'animate-spin')} />
              </Button>
            </div>
          </form>
          {addError || addNotice ? (
            <p
              className={cn(
                'mt-1.5 text-[0.7rem]',
                addError ? 'text-red-500' : 'text-emerald-600 dark:text-emerald-300'
              )}
            >
              {addError || addNotice}
            </p>
          ) : null}
        </div>
      </div>
    </header>
  )
}

function WatchlistDashboard({
  data,
  items,
  onDelete,
  onOpenDetail,
  onSort,
  sort
}: {
  data: WatchlistSnapshot
  items: WatchlistQuote[]
  onDelete: (stock: WatchlistQuote) => void
  onOpenDetail: (code: string) => void
  onSort: (key: SortKey) => void
  sort: SortState
}) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <IndexStrip indices={data.indices} />
      <SummaryMetrics data={data} />
      <WatchlistTable
        items={items}
        onDelete={onDelete}
        onOpenDetail={onOpenDetail}
        onSort={onSort}
        sort={sort}
        status={sectionStatus(data.refresh, 'quotes', data.gaps)}
      />
      <SectorPerformancePanel sectors={data.sectors} />
      <WatchlistInsight data={data} />
      <MethodologyPanel data={data} />
    </div>
  )
}

function IndexStrip({ indices }: { indices: IndustryMonitorIndex[] }) {
  if (!indices.length) {
    return <ModuleSkeleton label="核心指数刷新中" />
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {indices.map(index => (
        <div
          className="min-h-28 rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm"
          key={index.name}
        >
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="truncate text-xs text-(--ui-text-tertiary)">{index.name}</span>
            <span className="truncate text-[0.65rem] text-(--ui-text-tertiary)">{index.turnover || index.code}</span>
          </div>
          <div className={cn('text-xl font-semibold tabular-nums tracking-normal', toneText(index.change_percent))}>
            {formatNumber(index.value)}
          </div>
          <div className={cn('mt-2 text-xs font-medium tabular-nums', toneText(index.change_percent))}>
            {formatPercent(index.change_percent)}
          </div>
        </div>
      ))}
    </div>
  )
}

function SummaryMetrics({ data }: { data: WatchlistSnapshot }) {
  const summary = data.summary

  const cards = [
    {
      caption: `覆盖 ${data.sectors.length} 个行业`,
      label: '自选股总数',
      tone: 'text-foreground',
      value: `${summary.total} 只`
    },
    {
      caption: `上涨 ${summary.rising} · 下跌 ${summary.falling}`,
      label: '今日上涨家数',
      tone: summary.rising >= summary.falling ? 'text-red-500' : 'text-emerald-500',
      value: `${summary.rising} / ${summary.priced}`
    },
    {
      caption: '当前自选股样本合计',
      label: '主力净流入',
      tone: toneText(summary.main_net_flow_yi),
      value: formatMoney(summary.main_net_flow_yi)
    },
    {
      caption: summary.strongest_sector ? formatPercent(summary.strongest_sector.avg_change_percent) : '等待行情',
      label: '最强板块',
      tone: toneText(summary.strongest_sector?.avg_change_percent),
      value: summary.strongest_sector?.name ?? '暂无'
    }
  ]

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(card => (
        <div
          className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm"
          key={card.label}
        >
          <div className="mb-3 text-xs text-(--ui-text-tertiary)">{card.label}</div>
          <div className={cn('truncate text-2xl font-semibold tracking-normal', card.tone)} title={card.value}>
            {card.value}
          </div>
          <div className="mt-2 truncate text-[0.7rem] text-(--ui-text-tertiary)">{card.caption}</div>
        </div>
      ))}
    </div>
  )
}

function WatchlistTable({
  items,
  onDelete,
  onOpenDetail,
  onSort,
  sort,
  status
}: {
  items: WatchlistQuote[]
  onDelete: (stock: WatchlistQuote) => void
  onOpenDetail: (code: string) => void
  onSort: (key: SortKey) => void
  sort: SortState
  status: ModuleStatus
}) {
  return (
    <PanelShell
      description="自选股实时行情与资金状态"
      icon={<Star className="size-4" />}
      status={status}
      title="自选股"
    >
      {items.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[52rem] border-collapse text-left">
            <thead>
              <tr className="border-b border-(--ui-stroke-secondary) text-[0.7rem] text-(--ui-text-tertiary)">
                <SortableHeader
                  active={sort.key === 'name'}
                  direction={sort.direction}
                  label="名称 / 代码"
                  onClick={() => onSort('name')}
                />
                <SortableHeader
                  active={sort.key === 'price'}
                  direction={sort.direction}
                  label="现价"
                  onClick={() => onSort('price')}
                />
                <SortableHeader
                  active={sort.key === 'change'}
                  direction={sort.direction}
                  label="涨跌幅"
                  onClick={() => onSort('change')}
                />
                <SortableHeader
                  active={sort.key === 'flow'}
                  direction={sort.direction}
                  label="主力净流入"
                  onClick={() => onSort('flow')}
                />
                <th className="px-3 py-2.5 font-medium">近8日趋势</th>
                <SortableHeader
                  active={sort.key === 'sector'}
                  direction={sort.direction}
                  label="板块"
                  onClick={() => onSort('sector')}
                />
                <th className="w-10 px-2 py-2.5">
                  <span className="sr-only">操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map(stock => (
                <tr
                  className="group cursor-pointer border-b border-(--ui-stroke-secondary) transition-colors last:border-b-0 hover:bg-blue-500/5"
                  key={stock.code}
                  onClick={() => onOpenDetail(stock.code)}
                >
                  <td className="px-3 py-3">
                    <div className="font-semibold text-foreground">{stock.name}</div>
                    <div className="mt-0.5 text-[0.68rem] text-(--ui-text-tertiary)">
                      {stock.code}.{stock.exchange}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-sm font-semibold tabular-nums text-foreground">
                    {formatPrice(stock.price)}
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className={cn(
                        'inline-flex min-w-16 justify-center rounded-[4px] px-2 py-1 text-xs font-semibold tabular-nums',
                        changeBadge(stock.change_percent)
                      )}
                    >
                      {formatPercent(stock.change_percent)}
                    </span>
                  </td>
                  <td className={cn('px-3 py-3 text-sm font-semibold tabular-nums', toneText(stock.main_net_flow_yi))}>
                    {formatMoney(stock.main_net_flow_yi)}
                  </td>
                  <td className="h-12 w-28 px-3 py-2">
                    <MiniSparkline change={stock.change_percent} values={stock.sparkline} />
                  </td>
                  <td className="px-3 py-3">
                    <span className="inline-flex max-w-28 truncate rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2 py-1 text-[0.7rem] text-(--ui-text-secondary)">
                      {stock.sector || '其他'}
                    </span>
                  </td>
                  <td className="px-2 py-3">
                    <Button
                      aria-label={`删除 ${stock.name}`}
                      className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                      onClick={event => {
                        event.stopPropagation()
                        onDelete(stock)
                      }}
                      size="icon-xs"
                      title="删除自选股"
                      variant="ghost"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyWatchlist />
      )}
    </PanelShell>
  )
}

function SortableHeader({
  active,
  direction,
  label,
  onClick
}: {
  active: boolean
  direction: 'asc' | 'desc'
  label: string
  onClick: () => void
}) {
  return (
    <th className="px-3 py-2.5 font-medium">
      <button
        className={cn('inline-flex items-center gap-1 hover:text-foreground', active && 'text-blue-500')}
        onClick={onClick}
        type="button"
      >
        {label}
        <ChevronDown className={cn('size-3 transition-transform', active && direction === 'asc' && 'rotate-180')} />
      </button>
    </th>
  )
}

function MiniSparkline({ change, values }: { change: number | null; values: number[] }) {
  if (values.length < 2) {
    return <div className="h-8 w-full rounded-[4px] bg-(--ui-bg-secondary)" />
  }

  const color = change !== null && change < 0 ? 'rgb(16 185 129)' : 'rgb(239 68 68)'
  const data = values.map((value, index) => ({ index, value }))

  return (
    <ResponsiveContainer height="100%" width="100%">
      <LineChart data={data} margin={{ bottom: 2, left: 2, right: 2, top: 2 }}>
        <Line dataKey="value" dot={false} isAnimationActive={false} stroke={color} strokeWidth={2} type="linear" />
      </LineChart>
    </ResponsiveContainer>
  )
}

function SectorPerformancePanel({ sectors }: { sectors: WatchlistSector[] }) {
  const rows = sectors.slice(0, 8).map(sector => ({
    label: `${sector.name}  ${formatPercent(sector.avg_change_percent)}`,
    name: sector.name,
    value: sector.avg_change_percent ?? 0
  }))

  const maxAbs = Math.max(1, ...rows.map(row => Math.abs(row.value)))

  return (
    <PanelShell
      description="按当前自选股等权聚合，右侧为涨、左侧为跌"
      icon={<BarChart3 className="size-4" />}
      status={{ label: rows.length ? '已更新' : '等待中', tone: rows.length ? 'good' : 'neutral' }}
      title="板块今日表现"
    >
      {rows.length ? (
        <div className="min-w-0" style={{ height: Math.max(220, rows.length * 40) }}>
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={rows} layout="vertical" margin={{ bottom: 8, left: 8, right: 16, top: 8 }}>
              <CartesianGrid horizontal={false} stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" />
              <XAxis
                axisLine={false}
                domain={[-maxAbs, maxAbs]}
                tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 10 }}
                tickFormatter={value => `${Number(value).toFixed(1)}%`}
                tickLine={false}
                type="number"
              />
              <YAxis
                axisLine={false}
                dataKey="label"
                tick={{ fill: 'var(--ui-text-secondary)', fontSize: 11 }}
                tickLine={false}
                type="category"
                width={118}
              />
              <ReferenceLine stroke="var(--ui-stroke-primary)" x={0} />
              <Tooltip content={<PercentTooltip />} cursor={{ fill: 'rgba(59, 130, 246, 0.05)' }} />
              <Bar dataKey="value" name="平均涨跌幅" radius={4}>
                {rows.map(row => (
                  <Cell fill={row.value >= 0 ? 'rgb(239 68 68)' : 'rgb(16 185 129)'} key={row.name} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyInline text="暂无板块聚合数据" />
      )}
    </PanelShell>
  )
}

function WatchlistInsight({ data }: { data: WatchlistSnapshot }) {
  const strongest = data.summary.strongest_sector
  const weakest = data.summary.weakest_sector

  return (
    <PanelShell
      description="基于当前自选股行情生成"
      icon={<Zap className="size-4" />}
      status={sectionStatus(data.refresh, 'quotes', data.gaps)}
      title="今日盯盘摘要"
    >
      <p className="text-sm font-medium leading-6 text-foreground">{data.summary.headline}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-[0.7rem]">
        {strongest ? (
          <SignalTag
            label="强势"
            tone="up"
            value={`${strongest.name} ${formatPercent(strongest.avg_change_percent)}`}
          />
        ) : null}
        {weakest ? (
          <SignalTag label="承压" tone="down" value={`${weakest.name} ${formatPercent(weakest.avg_change_percent)}`} />
        ) : null}
        <SignalTag
          label="资金"
          tone={data.summary.main_net_flow_yi >= 0 ? 'up' : 'down'}
          value={formatMoney(data.summary.main_net_flow_yi)}
        />
      </div>
    </PanelShell>
  )
}

function SignalTag({ label, tone, value }: { label: string; tone: 'down' | 'up'; value: string }) {
  return (
    <span className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2.5 py-1">
      <span className="text-(--ui-text-tertiary)">{label}</span>
      <span className={cn('ml-1.5 font-medium', tone === 'up' ? 'text-red-500' : 'text-emerald-500')}>{value}</span>
    </span>
  )
}

function MethodologyPanel({ data }: { data: WatchlistSnapshot }) {
  return (
    <PanelShell
      description={data.methodology?.description ?? ''}
      icon={<Info className="size-4" />}
      status={data.gaps.length ? { label: '数据缺口', tone: 'warn' } : { label: '口径说明', tone: 'neutral' }}
      title={data.methodology?.title ?? '数据口径'}
    >
      {data.gaps.length ? (
        <div className="mb-3 grid gap-2">
          {data.gaps.map(gap => (
            <div
              className="flex gap-2 rounded-[6px] border border-amber-500/20 bg-amber-500/10 p-3 text-xs"
              key={gap.key}
            >
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
              <div>
                <div className="font-semibold text-foreground">{gap.title}</div>
                <div className="mt-1 leading-5 text-(--ui-text-secondary)">{gap.message}</div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <p className="text-[0.68rem] leading-5 text-(--ui-text-tertiary)">
        行情存在延迟，仅用于研究与监控，不构成投资建议。
      </p>
    </PanelShell>
  )
}

function StockDetailDialog({
  onOpenChange,
  onOpenFullAnalysis,
  onTabChange,
  open,
  stock,
  tab
}: {
  onOpenChange: (open: boolean) => void
  onOpenFullAnalysis: (stock: WatchlistQuote) => void
  onTabChange: (tab: DetailTab) => void
  open: boolean
  stock: WatchlistQuote | null
  tab: DetailTab
}) {
  const queryClient = useQueryClient()
  const detailKey = ['finance', 'watchlist', 'detail', stock?.code] as const

  const detail = useQuery({
    enabled: open && Boolean(stock),
    queryKey: detailKey,
    queryFn: () => getWatchlistStockDetail(stock?.code ?? ''),
    staleTime: 5 * 60_000
  })

  const refreshDetail = useMutation({
    mutationFn: () => getWatchlistStockDetail(stock?.code ?? '', true),
    onSuccess: value => queryClient.setQueryData(detailKey, value)
  })

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="flex max-h-[90vh] max-w-[min(72rem,94vw)] flex-col gap-0 overflow-hidden p-0">
        {stock ? (
          <>
            <div className="border-b border-(--ui-stroke-secondary) px-5 pb-3 pt-4">
              <div className="flex flex-wrap items-start justify-between gap-4 pr-8">
                <DialogHeader className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <DialogTitle>{stock.name}</DialogTitle>
                    <span className="rounded-[4px] border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-600 dark:text-blue-300">
                      {stock.code}.{stock.exchange}
                    </span>
                    <span className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2 py-0.5 text-xs text-(--ui-text-secondary)">
                      {stock.sector}
                    </span>
                  </div>
                  <DialogDescription>{detail.data?.summary || '行情详情与公司分析'}</DialogDescription>
                </DialogHeader>
                <div className="text-right">
                  <div className="text-2xl font-semibold tabular-nums text-foreground">
                    {formatPrice(detail.data?.stock.price ?? stock.price)}
                  </div>
                  <div
                    className={cn(
                      'mt-1 text-sm font-semibold tabular-nums',
                      toneText(detail.data?.stock.change_percent ?? stock.change_percent)
                    )}
                  >
                    {formatPercent(detail.data?.stock.change_percent ?? stock.change_percent)}
                  </div>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <Tabs onValueChange={value => onTabChange(value as DetailTab)} value={tab}>
                  <TabsList className="h-8 rounded-[5px] bg-(--ui-bg-secondary) p-0.5">
                    <TabsTrigger className="h-7 rounded-[4px] px-3 text-xs" value="market">
                      <CandlestickChart className="size-3.5" />
                      行情与K线
                    </TabsTrigger>
                    <TabsTrigger className="h-7 rounded-[4px] px-3 text-xs" value="analysis">
                      <BarChart3 className="size-3.5" />
                      详细分析
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
                <div className="flex items-center gap-2">
                  {tab === 'market' ? (
                    <Button
                      disabled={refreshDetail.isPending}
                      onClick={() => refreshDetail.mutate()}
                      size="sm"
                      variant="outline"
                    >
                      <RefreshCw className={cn('size-3.5', refreshDetail.isPending && 'animate-spin')} />
                      刷新K线
                    </Button>
                  ) : null}
                  <Button onClick={() => onOpenFullAnalysis(stock)} size="sm">
                    打开完整分析
                  </Button>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {tab === 'market' ? (
                <MarketDetailContent detail={detail.data} error={detail.error} loading={detail.isLoading} />
              ) : (
                <CompanyAnalysisPreview stock={stock} />
              )}
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function MarketDetailContent({
  detail,
  error,
  loading
}: {
  detail?: WatchlistStockDetail
  error: Error | null
  loading: boolean
}) {
  if (loading) {
    return <ModuleSkeleton label="正在获取 60 日 K 线" />
  }

  if (error || !detail?.ok) {
    return <ErrorInline message={error?.message || detail?.summary || 'K 线数据暂不可用'} />
  }

  const latest = detail.kline[detail.kline.length - 1]

  return (
    <div className="grid gap-4">
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-foreground">日 K 线与成交量</h3>
            <p className="mt-1 text-xs text-(--ui-text-tertiary)">
              前复权 · 最近 {detail.kline.length} 个交易日 · 红涨绿跌
            </p>
          </div>
          <div className="text-[0.7rem] text-(--ui-text-tertiary)">MA5 蓝线 · MA20 金线</div>
        </div>
        <KlineChart points={detail.kline} />
      </section>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <DetailMetric label="开盘" value={formatPrice(latest.open)} />
        <DetailMetric label="最高" value={formatPrice(latest.high)} />
        <DetailMetric label="最低" value={formatPrice(latest.low)} />
        <DetailMetric label="收盘" tone={toneText(latest.change_percent)} value={formatPrice(latest.close)} />
        <DetailMetric label="MA5" value={formatPrice(detail.technicals.ma5)} />
        <DetailMetric label="MA20" value={formatPrice(detail.technicals.ma20)} />
        <DetailMetric label="近20日支撑" value={formatPrice(detail.technicals.support)} />
        <DetailMetric label="近20日压力" value={formatPrice(detail.technicals.resistance)} />
      </div>
      <TechnicalSummary technicals={detail.technicals} />
    </div>
  )
}

function KlineChart({ points }: { points: WatchlistKlinePoint[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current

    if (!container || !points.length) {
      return
    }

    const dark = document.documentElement.classList.contains('dark')

    const chart = createChart(container, {
      autoSize: true,
      crosshair: { mode: 0 },
      grid: {
        horzLines: { color: dark ? 'rgba(148, 163, 184, 0.12)' : 'rgba(148, 163, 184, 0.2)' },
        vertLines: { color: dark ? 'rgba(148, 163, 184, 0.08)' : 'rgba(148, 163, 184, 0.14)' }
      },
      height: 420,
      layout: {
        attributionLogo: false,
        background: { color: 'transparent', type: ColorType.Solid },
        textColor: dark ? '#94a3b8' : '#64748b'
      },
      localization: { locale: 'zh-CN' },
      rightPriceScale: { borderColor: dark ? '#334155' : '#dbe2ea' },
      timeScale: { borderColor: dark ? '#334155' : '#dbe2ea', timeVisible: false }
    })

    const candles = chart.addSeries(CandlestickSeries, {
      borderDownColor: '#10b981',
      borderUpColor: '#ef4444',
      downColor: '#10b981',
      upColor: '#ef4444',
      wickDownColor: '#10b981',
      wickUpColor: '#ef4444'
    })

    candles.setData(
      points.map(point => ({
        close: point.close,
        high: point.high,
        low: point.low,
        open: point.open,
        time: point.date as Time
      }))
    )

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: ''
    })

    volume.priceScale().applyOptions({ scaleMargins: { bottom: 0, top: 0.78 } })
    volume.setData(
      points
        .filter(point => point.volume !== null)
        .map(point => ({
          color: point.close >= point.open ? 'rgba(239, 68, 68, 0.48)' : 'rgba(16, 185, 129, 0.48)',
          time: point.date as Time,
          value: point.volume ?? 0
        }))
    )
    const ma5 = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, priceLineVisible: false })
    ma5.setData(movingAverage(points, 5))
    const ma20 = chart.addSeries(LineSeries, { color: '#d99b18', lineWidth: 2, priceLineVisible: false })
    ma20.setData(movingAverage(points, 20))
    chart.timeScale().fitContent()

    return () => chart.remove()
  }, [points])

  return (
    <div
      className="h-[26.25rem] min-w-0 overflow-hidden rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)"
      ref={containerRef}
    />
  )
}

function movingAverage(points: WatchlistKlinePoint[], windowSize: number) {
  return points.slice(windowSize - 1).map((point, offset) => {
    const index = offset + windowSize - 1
    const window = points.slice(index - windowSize + 1, index + 1)

    return {
      time: point.date as Time,
      value: window.reduce((sum, item) => sum + item.close, 0) / window.length
    }
  })
}

function DetailMetric({ label, tone = 'text-foreground', value }: { label: string; tone?: string; value: string }) {
  return (
    <div className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3">
      <div className="text-[0.68rem] text-(--ui-text-tertiary)">{label}</div>
      <div className={cn('mt-1 text-lg font-semibold tabular-nums', tone)}>{value}</div>
    </div>
  )
}

function TechnicalSummary({ technicals }: { technicals: WatchlistTechnicals }) {
  return (
    <div className="rounded-[6px] border border-blue-500/20 bg-blue-500/8 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
        <Activity className="size-4 text-blue-500" />
        技术面摘要
      </div>
      <div className="grid gap-2 text-xs text-(--ui-text-secondary) sm:grid-cols-3">
        <p>
          趋势：<span className="font-medium text-foreground">{technicals.trend_label}</span>
        </p>
        <p>
          60日涨跌：
          <span className={cn('font-medium', toneText(technicals.period_change_percent))}>
            {formatPercent(technicals.period_change_percent)}
          </span>
        </p>
        <p>
          近20日振幅：
          <span className="font-medium text-foreground">{formatPercent(technicals.amplitude_percent, false)}</span>
        </p>
      </div>
    </div>
  )
}

function CompanyAnalysisPreview({ stock }: { stock: WatchlistQuote }) {
  const analysis = useQuery({
    queryKey: ['finance', 'company-analysis', stock.code],
    queryFn: () => getCompanyAnalysisSnapshot(stock.code),
    refetchInterval: query => {
      const data = query.state.data as CompanyAnalysisSnapshot | undefined

      return data?.refresh?.refreshing ? 2500 : false
    },
    refetchOnWindowFocus: false,
    staleTime: 10_000
  })

  const data = analysis.data

  const hasAnalysis = Boolean(
    data && (data.quote.price !== null || data.research.highlights.length || data.research.risks.length)
  )

  if (analysis.isError) {
    return <ErrorInline message={analysis.error instanceof Error ? analysis.error.message : '公司分析加载失败'} />
  }

  if (!hasAnalysis || !data) {
    return <ModuleSkeleton label={`正在生成 ${stock.name} 的详细分析`} />
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-[11rem_minmax(0,1fr)]">
        <div className="rounded-[7px] border border-blue-500/25 bg-blue-500/8 p-4 text-center">
          <div className="text-xs text-(--ui-text-tertiary)">综合评级</div>
          <div className="mt-3 text-4xl font-semibold text-blue-500">{data.rating.grade}</div>
          <div className="mt-2 text-xs text-(--ui-text-secondary)">
            {data.rating.score !== null ? `${data.rating.score} 分` : '等待评分'}
          </div>
        </div>
        <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
          <h3 className="text-base font-semibold text-foreground">{data.summary.headline}</h3>
          <p className="mt-2 text-sm leading-6 text-(--ui-text-secondary)">{data.rating.summary}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {data.rating.tags.map(tag => (
              <span
                className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-2 py-0.5 text-[0.68rem] text-(--ui-text-tertiary)"
                key={tag}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data.core_metrics.map(metric => (
          <div
            className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3"
            key={metric.label}
          >
            <div className="text-[0.68rem] text-(--ui-text-tertiary)">{metric.label}</div>
            <div className="mt-1 flex items-baseline gap-1">
              <span className="text-xl font-semibold text-foreground">{formatNumber(metric.value)}</span>
              <span className="text-[0.68rem] text-(--ui-text-tertiary)">{metric.unit}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <AnalysisList empty="暂无明确投资亮点" items={data.research.highlights} title="投资亮点" tone="good" />
        <AnalysisList empty="暂无明确风险提示" items={data.research.risks} title="主要风险" tone="warn" />
      </div>
    </div>
  )
}

function AnalysisList({
  empty,
  items,
  title,
  tone
}: {
  empty: string
  items: string[]
  title: string
  tone: 'good' | 'warn'
}) {
  return (
    <section className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
      <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>
      {items.length ? (
        <ul className="grid gap-2">
          {items.slice(0, 5).map(item => (
            <li className="flex gap-2 text-xs leading-5 text-(--ui-text-secondary)" key={item}>
              <span
                className={cn(
                  'mt-1.5 size-1.5 shrink-0 rounded-full',
                  tone === 'good' ? 'bg-emerald-500' : 'bg-amber-500'
                )}
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-(--ui-text-tertiary)">{empty}</p>
      )}
    </section>
  )
}

function PanelShell({
  children,
  description,
  icon,
  status,
  title
}: {
  children: ReactNode
  description: string
  icon: ReactNode
  status: ModuleStatus
  title: string
}) {
  return (
    <section className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-[5px] bg-blue-500/10 text-blue-500">{icon}</span>
            <h2 className="text-sm font-semibold tracking-normal text-foreground">{title}</h2>
          </div>
          <p className="mt-1 text-xs text-(--ui-text-tertiary)">{description}</p>
        </div>
        <ModuleStatusPill status={status} />
      </div>
      {children}
    </section>
  )
}

function PercentTooltip({
  active,
  label,
  payload
}: {
  active?: boolean
  label?: string
  payload?: Array<{ color?: string; name?: string; value?: number | string | null }>
}) {
  if (!active || !payload?.length) {
    return null
  }

  return (
    <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-foreground">{label}</div>
      <div className="text-(--ui-text-secondary)">{formatPercent(Number(payload[0].value))}</div>
    </div>
  )
}

function EmptyWatchlist() {
  return (
    <div className="grid min-h-44 place-items-center rounded-[6px] border border-dashed border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) text-center">
      <div>
        <Star className="mx-auto size-5 text-(--ui-text-tertiary)" />
        <p className="mt-2 text-sm font-medium text-foreground">暂无自选股</p>
      </div>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            className="h-28 animate-pulse rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)"
            key={index}
          />
        ))}
      </div>
      <ModuleSkeleton label="正在加载自选股行情" />
    </div>
  )
}

function ModuleSkeleton({ label }: { label: string }) {
  return (
    <div className="grid min-h-36 place-items-center rounded-[7px] border border-dashed border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) text-xs text-(--ui-text-tertiary)">
      <div className="flex items-center gap-2">
        <RefreshCw className="size-3.5 animate-spin" />
        {label}
      </div>
    </div>
  )
}

function EmptyInline({ text }: { text: string }) {
  return (
    <div className="rounded-[6px] border border-dashed border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4 text-center text-xs text-(--ui-text-tertiary)">
      {text}
    </div>
  )
}

function ErrorInline({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-[7px] border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-500">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-3xl">
      <ErrorInline message={message} />
    </div>
  )
}

function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'good' | 'neutral' | 'warn' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[4px] border px-2 py-0.5',
        tone === 'good'
          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
          : tone === 'warn'
            ? 'border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-300'
            : 'border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) text-(--ui-text-secondary)'
      )}
    >
      {tone === 'good' ? <span className="size-1.5 rounded-full bg-emerald-500" /> : null}
      {children}
    </span>
  )
}

interface ModuleStatus {
  label: string
  tone: 'good' | 'neutral' | 'warn'
}

function ModuleStatusPill({ status }: { status: ModuleStatus }) {
  const Icon = status.tone === 'good' ? CheckCircle2 : status.tone === 'warn' ? AlertTriangle : Info

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[4px] border px-1.5 py-0.5 text-[0.65rem]',
        status.tone === 'good'
          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
          : status.tone === 'warn'
            ? 'border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300'
            : 'border-(--ui-stroke-secondary) text-(--ui-text-tertiary)'
      )}
    >
      <Icon className="size-3" />
      {status.label}
    </span>
  )
}

function sectionStatus(
  refresh: WatchlistRefreshState | undefined,
  section: string,
  gaps: WatchlistGap[]
): ModuleStatus {
  if (refresh?.sections?.[section] === 'refreshing') {
    return { label: '刷新中', tone: 'warn' }
  }

  if (gaps.some(gap => gap.key === section)) {
    return { label: '数据缺口', tone: 'warn' }
  }

  if (refresh?.sections?.[section] === 'success') {
    return { label: '已更新', tone: 'good' }
  }

  if (refresh?.cache_state === 'empty') {
    return { label: '等待中', tone: 'neutral' }
  }

  return { label: '已缓存', tone: 'neutral' }
}

function sortWatchlist(items: WatchlistQuote[], sort: SortState): WatchlistQuote[] {
  const direction = sort.direction === 'asc' ? 1 : -1

  return [...items].sort((left, right) => {
    const leftValue = sortValue(left, sort.key)
    const rightValue = sortValue(right, sort.key)

    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return (leftValue - rightValue) * direction
    }

    return String(leftValue).localeCompare(String(rightValue), 'zh-CN') * direction
  })
}

function sortValue(stock: WatchlistQuote, key: SortKey): number | string {
  if (key === 'name') {
    return stock.name
  }

  if (key === 'sector') {
    return stock.sector
  }

  if (key === 'price') {
    return stock.price ?? -Infinity
  }

  if (key === 'flow') {
    return stock.main_net_flow_yi ?? -Infinity
  }

  return stock.change_percent ?? -Infinity
}

function changeBadge(value: number | null): string {
  if (value === null) {
    return 'bg-(--ui-bg-secondary) text-(--ui-text-tertiary)'
  }

  return value >= 0 ? 'bg-red-500/10 text-red-500' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
}

function toneText(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'text-foreground'
  }

  if (value > 0) {
    return 'text-red-500'
  }

  if (value < 0) {
    return 'text-emerald-500'
  }

  return 'text-foreground'
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
}

function formatPercent(value: number | null | undefined, signed = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  const sign = signed && value > 0 ? '+' : ''

  return `${sign}${value.toFixed(2)}%`
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  const abs = Math.abs(value)

  if (abs >= 10000) {
    return `${sign}${(abs / 10000).toFixed(2)}万亿`
  }

  return `${sign}${abs.toFixed(abs >= 100 ? 0 : 2)}亿`
}
