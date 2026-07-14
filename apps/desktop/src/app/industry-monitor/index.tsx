import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { getIndustryMonitorSnapshot, refreshIndustryMonitorSnapshot } from '@/hermes'
import { Activity, AlertTriangle, BarChart3, CheckCircle2, Clock, Globe, Info, RefreshCw, Zap } from '@/lib/icons'
import { cn } from '@/lib/utils'
import type {
  IndustryMonitorBreadth,
  IndustryMonitorGap,
  IndustryMonitorGroup,
  IndustryMonitorIndex,
  IndustryMonitorNorthbound,
  IndustryMonitorRefreshState,
  IndustryMonitorResearchView,
  IndustryMonitorSnapshot
} from '@/types/hermes'

const QUERY_KEY = ['finance', 'industry-monitor'] as const

type HeatmapMode = 'industry' | 'topic'

export function IndustryMonitorView() {
  const queryClient = useQueryClient()
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [heatmapMode, setHeatmapMode] = useState<HeatmapMode>('topic')

  const snapshot = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getIndustryMonitorSnapshot,
    refetchInterval: query => {
      const data = query.state.data as IndustryMonitorSnapshot | undefined

      if (data?.refresh?.refreshing) {
        return 1500
      }

      return autoRefresh ? 60_000 : false
    },
    refetchOnWindowFocus: false,
    staleTime: 10_000
  })

  const refresh = useMutation({
    mutationFn: refreshIndustryMonitorSnapshot,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    }
  })

  const data = snapshot.data
  const isRefreshing = Boolean(data?.refresh?.refreshing || refresh.isPending)

  const hasSnapshot = Boolean(
    data &&
    (data.indices.length > 0 ||
      data.market_breadth ||
      data.industry_heatmap.length > 0 ||
      data.topic_heatmap.length > 0 ||
      data.fund_flow.length > 0 ||
      data.northbound)
  )

  useEffect(() => {
    if (!autoRefresh) {
      return
    }

    const timer = window.setInterval(() => {
      const current = queryClient.getQueryData<IndustryMonitorSnapshot>(QUERY_KEY)

      if (!current?.refresh?.refreshing) {
        refresh.mutate()
      }
    }, 5 * 60_000)

    return () => window.clearInterval(timer)
  }, [autoRefresh, queryClient, refresh])

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[linear-gradient(180deg,color-mix(in_srgb,var(--ui-chat-surface-background)_94%,white)_0%,var(--ui-chat-surface-background)_22rem)] dark:bg-[linear-gradient(180deg,#061014_0%,var(--ui-chat-surface-background)_24rem)]">
      <MarketHeader
        autoRefresh={autoRefresh}
        data={data}
        isLoading={snapshot.isLoading}
        isRefreshing={isRefreshing}
        onRefresh={() => refresh.mutate()}
        onToggleAutoRefresh={() => setAutoRefresh(value => !value)}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        {snapshot.isError ? (
          <ErrorPanel message={snapshot.error instanceof Error ? snapshot.error.message : '行业监控数据加载失败'} />
        ) : hasSnapshot && data ? (
          <IndustryMonitorDashboard
            data={data}
            heatmapMode={heatmapMode}
            isRefreshing={isRefreshing}
            onHeatmapModeChange={setHeatmapMode}
          />
        ) : (
          <DashboardSkeleton isRefreshing={isRefreshing || snapshot.isLoading} />
        )}
      </div>
    </section>
  )
}

function MarketHeader({
  autoRefresh,
  data,
  isLoading,
  isRefreshing,
  onRefresh,
  onToggleAutoRefresh
}: {
  autoRefresh: boolean
  data?: IndustryMonitorSnapshot
  isLoading: boolean
  isRefreshing: boolean
  onRefresh: () => void
  onToggleAutoRefresh: () => void
}) {
  const statusLabel = isRefreshing
    ? '分区刷新中'
    : data?.refresh?.cache_state === 'warm'
      ? '已缓存'
      : isLoading
        ? '加载中'
        : '等待行情'

  return (
    <header className="z-20 shrink-0 border-b border-(--ui-stroke-secondary) bg-(--ui-chat-surface-background) px-4 pb-3 pt-[calc(var(--titlebar-height)+0.7rem)] shadow-sm sm:px-5">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span className="grid size-8 shrink-0 place-items-center rounded-[6px] border border-blue-500/25 bg-blue-500/10 text-blue-500 shadow-[0_0_18px_color-mix(in_srgb,rgb(59_130_246)_22%,transparent)]">
              <BarChart3 className="size-4" />
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-normal text-foreground">A股行业轮动监控</h1>
              <p className="truncate text-xs text-(--ui-text-tertiary)">
                市场广度 · 动态热点 · 主力资金 · 北向成交 · 研报催化
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[0.7rem]">
            <StatusPill tone={data?.ok ? 'good' : isRefreshing ? 'warn' : 'neutral'}>
              {data?.source ?? 'mx-ds-mcp'}
            </StatusPill>
            <StatusPill>{data?.as_of ? `数据日 ${data.as_of}` : '等待交易日'}</StatusPill>
            <StatusPill>{statusLabel}</StatusPill>
            {data?.cached_at ? <StatusPill>{`缓存 ${formatClock(data.cached_at)}`}</StatusPill> : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button
            aria-pressed={autoRefresh}
            className={cn(autoRefresh && 'bg-blue-500/10 text-blue-600 dark:text-blue-300')}
            onClick={onToggleAutoRefresh}
            size="sm"
            variant="outline"
          >
            <Clock className="size-3.5" />
            自动刷新
          </Button>
          <Button className="gap-1.5" disabled={isRefreshing} onClick={onRefresh} size="sm" variant="outline">
            <RefreshCw className={cn('size-3.5', isRefreshing && 'animate-spin')} />
            刷新
          </Button>
        </div>
      </div>
    </header>
  )
}

function IndustryMonitorDashboard({
  data,
  heatmapMode,
  isRefreshing,
  onHeatmapModeChange
}: {
  data: IndustryMonitorSnapshot
  heatmapMode: HeatmapMode
  isRefreshing: boolean
  onHeatmapModeChange: (mode: HeatmapMode) => void
}) {
  const activeHeatmap = heatmapMode === 'topic' ? data.topic_heatmap : data.industry_heatmap

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <MarketHero data={data} isRefreshing={isRefreshing} />
      <IndexMetricGrid
        indices={data.indices}
        marketSampleSize={data.market_sample_size}
        marketTurnover={data.market_turnover_yi}
      />
      <RotationPanel
        items={activeHeatmap}
        mode={heatmapMode}
        onModeChange={onHeatmapModeChange}
        status={sectionStatus(data.refresh, 'heatmap', data.gaps)}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.04fr)_minmax(22rem,0.96fr)]">
        <FlowStrengthPanel
          inflow={data.fund_flow}
          pressure={data.pressure}
          sampleSize={data.market_sample_size}
          status={sectionStatus(data.refresh, 'fund-flow', data.gaps)}
        />
        <NorthboundPanel northbound={data.northbound} status={sectionStatus(data.refresh, 'northbound', data.gaps)} />
      </div>
      <ResearchPanel
        isRefreshing={isRefreshing}
        items={data.research}
        status={sectionStatus(data.refresh, 'research', data.gaps)}
      />
      <MethodologyPanel data={data} />
    </div>
  )
}

function MarketHero({ data, isRefreshing }: { data: IndustryMonitorSnapshot; isRefreshing: boolean }) {
  const signals = [
    data.topic_heatmap[0] ? { label: '热点题材', value: data.topic_heatmap[0].name } : null,
    data.fund_flow[0] ? { label: '资金偏好', value: data.fund_flow[0].name } : null,
    data.pressure[0] ? { label: '承压方向', value: data.pressure[0].name } : null
  ].filter((item): item is { label: string; value: string } => Boolean(item))

  return (
    <PanelShell
      description="由市场广度、动态题材和资金强弱共同生成"
      icon={<Zap className="size-4" />}
      status={sectionStatus(data.refresh, 'breadth', data.gaps)}
      title="今日市场主线"
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-7 tracking-normal text-foreground">{data.summary.headline}</p>
          {data.summary.details.length ? (
            <div className="mt-3 grid gap-1 text-xs leading-5 text-(--ui-text-secondary)">
              {data.summary.details.map(detail => (
                <p key={detail}>{detail}</p>
              ))}
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            {signals.map(signal => (
              <span
                className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2.5 py-1 text-[0.7rem]"
                key={signal.label}
              >
                <span className="text-(--ui-text-tertiary)">{signal.label}</span>
                <span className="ml-1.5 font-medium text-foreground">{signal.value}</span>
              </span>
            ))}
          </div>
          {isRefreshing ? (
            <div className="mt-4 flex items-center gap-1.5 text-[0.7rem] text-amber-600 dark:text-amber-300">
              <RefreshCw className="size-3 animate-spin" />
              核心行情已可用，研报与剩余分区仍在后台刷新
            </div>
          ) : null}
        </div>
        <BreadthSummary breadth={data.market_breadth} marketTurnover={data.market_turnover_yi} />
      </div>
    </PanelShell>
  )
}

function BreadthSummary({
  breadth,
  marketTurnover
}: {
  breadth: IndustryMonitorBreadth | null
  marketTurnover: number | null
}) {
  if (!breadth) {
    return <EmptyInline text="等待市场广度数据" />
  }

  const flatRatio = breadth.total ? (breadth.flat / breadth.total) * 100 : 0
  const downRatio = Math.max(0, 100 - breadth.advance_ratio - flatRatio)

  return (
    <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs text-(--ui-text-tertiary)">市场广度</span>
        <span className="rounded-[4px] bg-blue-500/10 px-1.5 py-0.5 text-[0.65rem] font-medium text-blue-600 dark:text-blue-300">
          {breadth.sentiment_label}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-semibold tracking-normal text-foreground">
          {breadth.advance_ratio.toFixed(1)}%
        </span>
        <span className="text-xs text-(--ui-text-tertiary)">上涨占比</span>
      </div>
      <div
        className="mt-3 flex h-2 overflow-hidden rounded-[3px] bg-(--ui-bg-tertiary)"
        title={`上涨 ${breadth.advancers} / 下跌 ${breadth.decliners}`}
      >
        <div className="bg-red-500" style={{ width: `${breadth.advance_ratio}%` }} />
        <div className="bg-(--ui-stroke-secondary)" style={{ width: `${flatRatio}%` }} />
        <div className="bg-emerald-500" style={{ width: `${downRatio}%` }} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <BreadthValue label="上涨" tone="text-red-500" value={breadth.advancers} />
        <BreadthValue label="下跌" tone="text-emerald-500" value={breadth.decliners} />
        <BreadthValue label="涨停" tone="text-red-500" value={breadth.limit_up} />
        <BreadthValue label="跌停" tone="text-emerald-500" value={breadth.limit_down} />
      </div>
      <div className="mt-3 border-t border-(--ui-stroke-secondary) pt-2 text-[0.68rem] text-(--ui-text-tertiary)">
        全A成交额 <span className="font-medium text-foreground">{formatMoney(marketTurnover)}</span>
      </div>
    </div>
  )
}

function BreadthValue({ label, tone, value }: { label: string; tone: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-(--ui-text-tertiary)">{label}</span>
      <span className={cn('font-semibold tabular-nums', tone)}>{value.toLocaleString('zh-CN')}</span>
    </div>
  )
}

function IndexMetricGrid({
  indices,
  marketSampleSize,
  marketTurnover
}: {
  indices: IndustryMonitorIndex[]
  marketSampleSize: number
  marketTurnover: number | null
}) {
  const cards = [
    ...indices.map(index => ({
      caption: index.turnover || index.code || '核心指数',
      change: index.change_percent,
      label: index.name,
      value: formatIndexValue(index.value)
    })),
    {
      caption: marketSampleSize ? `动态样本 ${marketSampleSize} 只` : '全市场口径',
      change: null,
      label: '全A成交额',
      value: formatMoney(marketTurnover)
    }
  ]

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {cards.map(card => (
        <div
          className="min-h-28 rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm"
          key={card.label}
        >
          <div className="mb-3 truncate text-xs text-(--ui-text-tertiary)">{card.label}</div>
          <div className={cn('truncate text-xl font-semibold tabular-nums tracking-normal', toneText(card.change))}>
            {card.value}
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 text-[0.68rem]">
            <span className="truncate text-(--ui-text-tertiary)">{card.caption}</span>
            {card.change !== null ? (
              <span className={cn('shrink-0 font-medium tabular-nums', toneText(card.change))}>
                {formatPercent(card.change)}
              </span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}

function RotationPanel({
  items,
  mode,
  onModeChange,
  status
}: {
  items: IndustryMonitorGroup[]
  mode: HeatmapMode
  onModeChange: (mode: HeatmapMode) => void
  status: ModuleStatus
}) {
  return (
    <PanelShell
      actions={
        <SegmentedControl
          onChange={onModeChange}
          options={[
            { label: '热点题材', value: 'topic' },
            { label: '一级行业', value: 'industry' }
          ]}
          value={mode}
        />
      }
      description={
        mode === 'topic' ? '热门板块与高信号概念的动态聚合' : '按动态样本中的申万一级行业聚合，不使用固定行业篮子'
      }
      icon={<BarChart3 className="size-4" />}
      status={status}
      title="热点与行业轮动"
    >
      {items.length === 0 ? (
        <ModuleSkeleton label="等待热点聚合数据" />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.slice(0, 16).map(item => (
            <HeatTile item={item} key={`${item.name}-${item.side}-${item.sample_count}`} />
          ))}
        </div>
      )}
    </PanelShell>
  )
}

function HeatTile({ item }: { item: IndustryMonitorGroup }) {
  const tone = item.side === 'cold' ? 'cold' : item.side === 'fund' ? 'fund' : 'hot'

  const tileClass =
    tone === 'cold'
      ? 'border-emerald-500/25 bg-emerald-500/8'
      : tone === 'fund'
        ? 'border-blue-500/25 bg-blue-500/8'
        : 'border-red-500/25 bg-red-500/8'

  const badgeClass =
    tone === 'cold'
      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
      : tone === 'fund'
        ? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
        : 'bg-red-500/10 text-red-500'

  return (
    <article className={cn('min-h-36 rounded-[6px] border p-3', tileClass)}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-foreground">{item.name}</h3>
          <p className="mt-0.5 text-[0.68rem] text-(--ui-text-tertiary)">信号样本 {item.sample_count}</p>
        </div>
        <span className={cn('shrink-0 rounded-[4px] px-1.5 py-0.5 text-[0.65rem] font-medium', badgeClass)}>
          {sideLabel(item.side)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 border-y border-(--ui-stroke-secondary) py-2.5">
        <TileMetric
          label="均涨跌"
          tone={toneText(item.avg_change_percent)}
          value={formatPercent(item.avg_change_percent)}
        />
        <TileMetric
          label="主力净额"
          tone={toneText(item.main_net_inflow_yi)}
          value={formatMoney(item.main_net_inflow_yi)}
        />
        <TileMetric label="成交额" tone="text-foreground" value={formatMoney(item.turnover_yi)} />
      </div>
      <p className="mt-2.5 line-clamp-1 text-[0.68rem] text-(--ui-text-tertiary)" title={item.leaders.join('、')}>
        {item.leaders.length ? `代表个股：${item.leaders.join('、')}` : '代表个股暂缺'}
      </p>
    </article>
  )
}

function TileMetric({ label, tone, value }: { label: string; tone: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className={cn('truncate text-sm font-semibold tabular-nums', tone)} title={value}>
        {value}
      </div>
      <div className="mt-1 truncate text-[0.62rem] text-(--ui-text-tertiary)">{label}</div>
    </div>
  )
}

function FlowStrengthPanel({
  inflow,
  pressure,
  sampleSize,
  status
}: {
  inflow: IndustryMonitorGroup[]
  pressure: IndustryMonitorGroup[]
  sampleSize: number
  status: ModuleStatus
}) {
  const rows = useMemo(() => {
    const seen = new Set<string>()

    return [
      ...inflow.slice(0, 7).map(item => ({ ...item, lane: 'in' as const })),
      ...pressure.slice(0, 7).map(item => ({ ...item, lane: 'out' as const }))
    ]
      .filter(item => {
        if (seen.has(item.name)) {
          return false
        }

        seen.add(item.name)

        return true
      })
      .map(item => ({
        label: `${item.name}  ${formatSignedCompact(item.main_net_inflow_yi)}`,
        name: item.name,
        value: item.main_net_inflow_yi
      }))
  }, [inflow, pressure])

  const maxAbs = Math.max(1, ...rows.map(item => Math.abs(item.value)))

  return (
    <PanelShell
      description={`动态信号样本聚合${sampleSize ? `，覆盖 ${sampleSize} 只股票` : ''}；数值为样本净额，不代表板块全量资金`}
      icon={<Activity className="size-4" />}
      status={status}
      title="题材资金强弱"
    >
      {rows.length === 0 ? (
        <ModuleSkeleton label="等待资金强弱数据" />
      ) : (
        <div className="h-[24rem] min-w-0">
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={rows} layout="vertical" margin={{ bottom: 8, left: 8, right: 12, top: 8 }}>
              <CartesianGrid horizontal={false} stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" />
              <XAxis
                axisLine={false}
                domain={[-maxAbs, maxAbs]}
                tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 10 }}
                tickFormatter={value => formatAxisMoney(Number(value))}
                tickLine={false}
                type="number"
              />
              <YAxis
                axisLine={false}
                dataKey="label"
                tick={{ fill: 'var(--ui-text-secondary)', fontSize: 10 }}
                tickLine={false}
                type="category"
                width={118}
              />
              <ReferenceLine stroke="var(--ui-stroke-primary)" x={0} />
              <Tooltip content={<MoneyTooltip />} cursor={{ fill: 'rgba(59, 130, 246, 0.05)' }} />
              <Bar dataKey="value" name="样本主力净额" radius={4}>
                {rows.map(row => (
                  <Cell fill={row.value >= 0 ? 'rgb(239 68 68)' : 'rgb(16 185 129)'} key={row.name} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </PanelShell>
  )
}

function NorthboundPanel({
  northbound,
  status
}: {
  northbound: IndustryMonitorNorthbound | null
  status: ModuleStatus
}) {
  if (!northbound) {
    return (
      <PanelShell
        description="等待北向成交额、沪股通成交额与深股通成交额"
        icon={<Globe className="size-4" />}
        status={status}
        title="北向成交活跃度"
      >
        <ModuleSkeleton label="暂无北向成交活跃度数据" />
      </PanelShell>
    )
  }

  const { current, series } = northbound

  const averageTotal =
    northbound.average_total_yi || series.reduce((sum, point) => sum + point.total_yi, 0) / Math.max(series.length, 1)

  return (
    <PanelShell
      description={`近20日沪深通道成交结构，均额 ${formatMoney(averageTotal)}`}
      icon={<Globe className="size-4" />}
      status={status}
      title="北向成交活跃度"
    >
      <div className="grid grid-cols-3 overflow-hidden rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) divide-x divide-(--ui-stroke-secondary)">
        <NorthboundMetric label="北向总额" value={formatMoney(current.total_yi)} />
        <NorthboundMetric label="沪股通" value={formatMoney(current.sh_yi)} />
        <NorthboundMetric label="深股通" value={formatMoney(current.sz_yi)} />
      </div>
      <div className="mt-3 h-[17.5rem] min-w-0">
        <ResponsiveContainer height="100%" width="100%">
          <BarChart data={series} margin={{ bottom: 8, left: 0, right: 4, top: 14 }}>
            <CartesianGrid stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" vertical={false} />
            <XAxis
              axisLine={false}
              dataKey="date"
              interval="preserveStartEnd"
              minTickGap={28}
              tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 10 }}
              tickFormatter={formatShortDate}
              tickLine={false}
            />
            <YAxis
              axisLine={false}
              tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 10 }}
              tickFormatter={value => formatAxisMoney(Number(value))}
              tickLine={false}
              width={40}
            />
            <Tooltip content={<MoneyTooltip />} cursor={{ fill: 'rgba(59, 130, 246, 0.05)' }} />
            <Legend
              align="center"
              iconType="circle"
              verticalAlign="bottom"
              wrapperStyle={{ color: 'var(--ui-text-tertiary)', fontSize: 11, paddingTop: 8 }}
            />
            <ReferenceLine stroke="var(--ui-text-tertiary)" strokeDasharray="3 5" y={averageTotal} />
            <Bar dataKey="sh_yi" fill="rgb(59 130 246)" name="沪股通" radius={[3, 3, 0, 0]} stackId="northbound" />
            <Bar dataKey="sz_yi" fill="rgb(34 197 203)" name="深股通" radius={[3, 3, 0, 0]} stackId="northbound" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 grid gap-2 text-xs text-(--ui-text-secondary) sm:grid-cols-2">
        <p>
          深市占比 <span className="font-semibold text-foreground">{current.sz_share_percent.toFixed(1)}%</span>，
          {current.bias_label}
        </p>
        <p>
          成交活跃度 <span className="font-semibold text-foreground">{current.activity_label}</span>，均值比{' '}
          {current.activity_ratio.toFixed(2)}
        </p>
      </div>
      <p className="mt-2 text-[0.68rem] leading-4 text-(--ui-text-tertiary)">{northbound.note}</p>
    </PanelShell>
  )
}

function NorthboundMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="truncate text-[0.65rem] text-(--ui-text-tertiary)">{label}</div>
      <div className="mt-1 truncate text-base font-semibold tabular-nums text-foreground" title={value}>
        {value}
      </div>
    </div>
  )
}

function ResearchPanel({
  isRefreshing,
  items,
  status
}: {
  isRefreshing: boolean
  items: IndustryMonitorResearchView[]
  status: ModuleStatus
}) {
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState<IndustryMonitorResearchView | null>(null)
  const visible = expanded ? items : items.slice(0, 4)

  return (
    <>
      <PanelShell
        actions={
          items.length > 4 ? (
            <Button onClick={() => setExpanded(value => !value)} size="xs" variant="ghost">
              {expanded ? '收起' : `展开 ${items.length - 4} 条`}
            </Button>
          ) : null
        }
        description="围绕当前热点题材检索新闻催化、研报观点与风险提示"
        icon={<Info className="size-4" />}
        status={status}
        title="轮动研判"
      >
        {visible.length === 0 ? (
          <ModuleSkeleton label={isRefreshing ? '研报视角刷新中' : '暂无研报观点数据'} />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {visible.map(item => (
              <article
                className="flex min-h-40 flex-col rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3"
                key={`${item.title}-${item.published_at}`}
              >
                <div className="mb-1 flex flex-wrap items-center gap-2 text-[0.68rem] text-(--ui-text-tertiary)">
                  <span>{item.source || '未知来源'}</span>
                  <span>{item.published_at}</span>
                </div>
                <h3 className="line-clamp-2 text-sm font-semibold leading-5 text-foreground">{item.title}</h3>
                <p className="mt-2 line-clamp-3 text-xs leading-5 text-(--ui-text-secondary)">{item.summary}</p>
                <Button className="mt-auto self-start" onClick={() => setSelected(item)} size="inline" variant="text">
                  查看完整摘要
                </Button>
              </article>
            ))}
          </div>
        )}
      </PanelShell>
      <ResearchDialog article={selected} onOpenChange={open => !open && setSelected(null)} />
    </>
  )
}

function ResearchDialog({
  article,
  onOpenChange
}: {
  article: IndustryMonitorResearchView | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={Boolean(article)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{article?.title ?? '研报摘要'}</DialogTitle>
          <DialogDescription>
            {[article?.source, article?.published_at].filter(Boolean).join(' · ') || '妙想 MCP 研报检索'}
          </DialogDescription>
        </DialogHeader>
        <div className="whitespace-pre-wrap text-sm leading-6 text-(--ui-text-secondary)">
          {article?.summary || '暂无摘要内容。'}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function MethodologyPanel({ data }: { data: IndustryMonitorSnapshot }) {
  const visibleGaps = data.gaps.filter(gap => gap.severity !== 'info')

  return (
    <PanelShell
      description={data.methodology?.description ?? ''}
      icon={<Info className="size-4" />}
      status={visibleGaps.length > 0 ? { label: '数据缺口', tone: 'warn' } : { label: '口径说明', tone: 'neutral' }}
      title={data.methodology?.title ?? '数据口径'}
    >
      {visibleGaps.length > 0 ? (
        <div className="mb-3 grid gap-2">
          {visibleGaps.map(gap => (
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
        板块资金为动态股票样本聚合值，用于比较轮动强弱，不等同于全板块资金净流入。本页面不构成投资建议。
      </p>
    </PanelShell>
  )
}

function PanelShell({
  actions,
  children,
  className,
  description,
  icon,
  status,
  title
}: {
  actions?: ReactNode
  children: ReactNode
  className?: string
  description: string
  icon: ReactNode
  status: ModuleStatus
  title: string
}) {
  return (
    <section
      className={cn(
        'rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm',
        className
      )}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-[5px] bg-blue-500/10 text-blue-500">{icon}</span>
            <h2 className="text-sm font-semibold tracking-normal text-foreground">{title}</h2>
          </div>
          {description ? <p className="mt-1 text-xs text-(--ui-text-tertiary)">{description}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          <ModuleStatusPill status={status} />
        </div>
      </div>
      {children}
    </section>
  )
}

function SegmentedControl({
  onChange,
  options,
  value
}: {
  onChange: (value: HeatmapMode) => void
  options: { label: string; value: HeatmapMode }[]
  value: HeatmapMode
}) {
  return (
    <div className="flex rounded-[5px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-0.5">
      {options.map(option => (
        <button
          aria-pressed={value === option.value}
          className={cn(
            'rounded-[4px] px-2 py-0.5 text-[0.68rem] font-medium transition-colors',
            value === option.value
              ? 'bg-(--ui-bg-elevated) text-foreground shadow-sm'
              : 'text-(--ui-text-tertiary) hover:text-foreground'
          )}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function MoneyTooltip({
  active,
  label,
  payload
}: {
  active?: boolean
  label?: string
  payload?: Array<{ color?: string; dataKey?: string | number; name?: string; value?: number | string | null }>
}) {
  if (!active || !payload?.length) {
    return null
  }

  return (
    <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-foreground">{label}</div>
      <div className="grid gap-1">
        {payload.map(item => (
          <div className="flex min-w-32 items-center justify-between gap-4" key={`${item.dataKey}-${item.name}`}>
            <span className="inline-flex items-center gap-1.5 text-(--ui-text-tertiary)">
              <span className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
              {item.name}
            </span>
            <span className="font-medium text-foreground">{formatMoney(Number(item.value))}</span>
          </div>
        ))}
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

function DashboardSkeleton({ isRefreshing }: { isRefreshing: boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-6 shadow-sm">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground">
          <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin')} />
          正在生成行业轮动快照
        </div>
        <p className="text-xs leading-5 text-(--ui-text-tertiary)">
          指数、市场广度与动态样本会先返回，研报视角随后异步补齐。
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {['市场主线', '核心指数', '热点轮动', '资金强弱'].map(label => (
          <div
            className="h-28 animate-pulse rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4"
            key={label}
          >
            <div className="mb-4 h-3 w-20 rounded bg-(--ui-bg-tertiary)" />
            <div className="h-7 w-28 rounded bg-(--ui-bg-tertiary)" />
          </div>
        ))}
      </div>
    </div>
  )
}

function ModuleSkeleton({ label }: { label: string }) {
  return (
    <div className="grid min-h-32 place-items-center rounded-[6px] border border-dashed border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) text-xs text-(--ui-text-tertiary)">
      <div className="flex items-center gap-2">
        <RefreshCw className="size-3.5 animate-spin" />
        {label}
      </div>
    </div>
  )
}

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-3xl rounded-[7px] border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-500">
      <div className="mb-1 flex items-center gap-2 font-semibold">
        <AlertTriangle className="size-4" />
        行业监控加载失败
      </div>
      <p>{message}</p>
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
  refresh: IndustryMonitorRefreshState | undefined,
  section: string,
  gaps: IndustryMonitorGap[]
): ModuleStatus {
  if (refresh?.sections?.[section] === 'refreshing') {
    return { label: '刷新中', tone: 'warn' }
  }

  if (gaps.some(gap => gap.key === section || (section === 'heatmap' && ['gainers', 'losers'].includes(gap.key)))) {
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

function sideLabel(side: string): string {
  if (side === 'fund') {
    return '资金'
  }

  if (side === 'cold') {
    return '承压'
  }

  return '热点'
}

function formatIndexValue(value: number | null): string {
  return value === null ? '暂无' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '暂无'
  }

  const sign = value > 0 ? '+' : ''

  return `${sign}${value.toFixed(2)}%`
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  const sign = value > 0 ? '' : value < 0 ? '-' : ''
  const abs = Math.abs(value)

  if (abs >= 10000) {
    return `${sign}${(abs / 10000).toFixed(2)}万亿`
  }

  return `${sign}${abs.toFixed(abs >= 100 ? 0 : 1)}亿`
}

function formatSignedCompact(value: number): string {
  const sign = value > 0 ? '+' : ''

  return `${sign}${Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1)}亿`
}

function formatAxisMoney(value: number): string {
  const abs = Math.abs(value)

  if (abs >= 10000) {
    return `${(value / 10000).toFixed(1)}万亿`
  }

  if (abs >= 1000) {
    return `${(value / 1000).toFixed(1)}千亿`
  }

  return `${value.toFixed(0)}亿`
}

function formatShortDate(value: string): string {
  const match = value.match(/\d{4}-(\d{2})-(\d{2})/)

  return match ? `${match[1]}-${match[2]}` : value
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

function formatClock(value: string): string {
  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
