import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { getCompanyAnalysisSnapshot, refreshCompanyAnalysisSnapshot } from '@/hermes'
import { Activity, AlertTriangle, BarChart3, CheckCircle2, Clock, Info, RefreshCw, Search, Zap } from '@/lib/icons'
import { cn } from '@/lib/utils'
import type {
  CompanyAnalysisArticle,
  CompanyAnalysisCapital,
  CompanyAnalysisFinancialTrend,
  CompanyAnalysisGap,
  CompanyAnalysisMetric,
  CompanyAnalysisOperatingMetric,
  CompanyAnalysisPeer,
  CompanyAnalysisProfitability,
  CompanyAnalysisQuote,
  CompanyAnalysisRefreshState,
  CompanyAnalysisResearch,
  CompanyAnalysisSeriesPoint,
  CompanyAnalysisSnapshot,
  CompanyAnalysisValuation
} from '@/types/hermes'

const DEFAULT_QUERY = '宁德时代'
const QUERY_ROOT = ['finance', 'company-analysis'] as const

export function CompanyAnalysisView() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const routeQuery = searchParams.get('query')?.trim() || DEFAULT_QUERY
  const [inputValue, setInputValue] = useState(routeQuery)
  const [submittedQuery, setSubmittedQuery] = useState(routeQuery)

  const queryKey = useMemo(() => [...QUERY_ROOT, submittedQuery] as const, [submittedQuery])

  const snapshot = useQuery({
    queryKey,
    queryFn: () => getCompanyAnalysisSnapshot(submittedQuery),
    refetchInterval: query => {
      const data = query.state.data as CompanyAnalysisSnapshot | undefined

      return data?.refresh?.refreshing ? 2500 : false
    },
    refetchOnWindowFocus: false,
    staleTime: 10_000
  })

  const refresh = useMutation({
    mutationFn: () => refreshCompanyAnalysisSnapshot(submittedQuery),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey })
    }
  })

  const data = snapshot.data
  const isRefreshing = Boolean(data?.refresh?.refreshing || refresh.isPending)

  const hasSnapshot = Boolean(
    data &&
    (data.quote.price !== null ||
      data.core_metrics.length > 0 ||
      data.financial_trend.revenue_yi.length > 0 ||
      data.peers.length > 0 ||
      data.research.articles.length > 0)
  )

  useEffect(() => {
    if (routeQuery === submittedQuery) {
      return
    }

    setInputValue(routeQuery)
    setSubmittedQuery(routeQuery)
  }, [routeQuery, submittedQuery])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextQuery = inputValue.trim() || DEFAULT_QUERY
    setInputValue(nextQuery)
    setSubmittedQuery(nextQuery)
    setSearchParams(nextQuery === DEFAULT_QUERY ? {} : { query: nextQuery }, { replace: true })
  }

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-[linear-gradient(180deg,color-mix(in_srgb,var(--ui-chat-surface-background)_94%,white)_0%,var(--ui-chat-surface-background)_22rem)] dark:bg-[linear-gradient(180deg,#061014_0%,var(--ui-chat-surface-background)_24rem)]">
      <CompanyHeader
        data={data}
        inputValue={inputValue}
        isLoading={snapshot.isLoading}
        isRefreshing={isRefreshing}
        onInputChange={setInputValue}
        onRefresh={() => refresh.mutate()}
        onSubmit={handleSubmit}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        {snapshot.isError ? (
          <ErrorPanel message={snapshot.error instanceof Error ? snapshot.error.message : '公司分析数据加载失败'} />
        ) : hasSnapshot && data ? (
          <CompanyDashboard data={data} isRefreshing={isRefreshing} />
        ) : (
          <DashboardSkeleton isRefreshing={isRefreshing || snapshot.isLoading} query={submittedQuery} />
        )}
      </div>
    </section>
  )
}

function CompanyHeader({
  data,
  inputValue,
  isLoading,
  isRefreshing,
  onInputChange,
  onRefresh,
  onSubmit
}: {
  data?: CompanyAnalysisSnapshot
  inputValue: string
  isLoading: boolean
  isRefreshing: boolean
  onInputChange: (value: string) => void
  onRefresh: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  const statusLabel = isRefreshing
    ? '刷新中'
    : data?.refresh?.cache_state === 'warm'
      ? '已缓存'
      : isLoading
        ? '加载中'
        : '等待搜索'

  return (
    <header className="z-20 shrink-0 border-b border-(--ui-stroke-secondary) bg-(--ui-chat-surface-background) px-4 pb-3 pt-[calc(var(--titlebar-height)+0.7rem)] shadow-sm sm:px-5">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span className="grid size-8 shrink-0 place-items-center rounded-[6px] border border-blue-500/25 bg-blue-500/10 text-blue-500 shadow-[0_0_18px_color-mix(in_srgb,rgb(59_130_246)_22%,transparent)]">
              <BarChart3 className="size-4" />
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-normal text-foreground">
                上市公司基本面分析报告
              </h1>
              <p className="truncate text-xs text-(--ui-text-tertiary)">
                公司画像 · 财务趋势 · 估值位置 · 同行比较 · 研报摘要
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[0.7rem]">
            <StatusPill tone={data?.ok ? 'good' : isRefreshing ? 'warn' : 'neutral'}>
              {data?.source ?? 'mx-ds-mcp'}
            </StatusPill>
            <StatusPill>{data?.as_of ? `数据日 ${data.as_of}` : '等待公司数据'}</StatusPill>
            <StatusPill>{statusLabel}</StatusPill>
            {data?.cached_at ? <StatusPill>{`缓存 ${formatClock(data.cached_at)}`}</StatusPill> : null}
          </div>
        </div>

        <form className="flex min-w-0 flex-col gap-2 sm:flex-row xl:w-[31rem]" onSubmit={onSubmit}>
          <label className="relative min-w-0 flex-1">
            <span className="sr-only">搜索公司名称或股票代码</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-(--ui-text-tertiary)" />
            <Input
              className="h-8 rounded-[6px] border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) pl-8 text-xs"
              onChange={event => onInputChange(event.target.value)}
              placeholder="输入公司名称或股票代码，例如 宁德时代 / 300750"
              value={inputValue}
            />
          </label>
          <div className="flex shrink-0 items-center gap-2">
            <Button className="gap-1.5" disabled={isRefreshing} size="sm" type="submit" variant="outline">
              <Search className="size-3.5" />
              搜索
            </Button>
            <Button
              className="gap-1.5"
              disabled={isRefreshing}
              onClick={onRefresh}
              size="sm"
              type="button"
              variant="outline"
            >
              <RefreshCw className={cn('size-3.5', isRefreshing && 'animate-spin')} />
              刷新
            </Button>
          </div>
        </form>
      </div>
    </header>
  )
}

function CompanyDashboard({ data, isRefreshing }: { data: CompanyAnalysisSnapshot; isRefreshing: boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <CompanyHero data={data} isRefreshing={isRefreshing} />
      <MetricGrid metrics={data.core_metrics} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(22rem,0.9fr)]">
        <FinancialTrendPanel trend={data.financial_trend} />
        <ProfitabilityPanel operatingMetrics={data.operating_metrics} profitability={data.profitability} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <ValuationPanel quote={data.quote} valuation={data.valuation} />
        <CapitalPanel capital={data.capital} cashFlow={data.cash_flow} />
      </div>
      <PeersPanel peers={data.peers} />
      <ResearchPanel research={data.research} />
      <RatingPanel data={data} />
      <MethodologyPanel data={data} />
    </div>
  )
}

function CompanyHero({ data, isRefreshing }: { data: CompanyAnalysisSnapshot; isRefreshing: boolean }) {
  const quote = data.quote
  const name = data.resolved.name || quote.name || data.query

  const code = data.resolved.code
    ? `${data.resolved.code}${data.resolved.exchange ? `.${data.resolved.exchange}` : ''}`
    : '未匹配代码'

  return (
    <PanelShell
      description={data.summary.headline}
      icon={<Activity className="size-4" />}
      status={sectionStatus(data.refresh, 'profile', data.gaps)}
      title="公司核心画像"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-semibold tracking-normal text-foreground">{name}</h2>
            <span className="rounded-[4px] border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-600 dark:text-blue-300">
              {code}
            </span>
            {quote.industry ? (
              <span className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2 py-0.5 text-xs text-(--ui-text-secondary)">
                {quote.industry}
              </span>
            ) : null}
          </div>
          <p className="mb-3 max-w-3xl text-sm leading-6 text-(--ui-text-secondary)">
            {quote.business || '等待妙想 MCP 返回主营业务与行业画像。'}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(quote.concepts || []).slice(0, 6).map(concept => (
              <span
                className="rounded-[4px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-2 py-0.5 text-[0.7rem] text-(--ui-text-tertiary)"
                key={concept}
              >
                {concept}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm">
          <div className="mb-1 text-xs text-(--ui-text-tertiary)">最新价</div>
          <div className="flex items-end justify-between gap-3">
            <div className="text-3xl font-semibold tracking-normal text-foreground">{formatPrice(quote.price)}</div>
            <div className={cn('text-right text-sm font-medium', toneText(quote.change_percent))}>
              <div>{formatPercent(quote.change_percent)}</div>
              <div className="text-xs">{formatSignedNumber(quote.change_amount)}</div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <QuoteMini label="总市值" value={formatMoney(quote.market_cap_yi)} />
            <QuoteMini label="PE(TTM)" value={formatRatio(quote.pe_ttm)} />
            <QuoteMini label="PB" value={formatRatio(quote.pb)} />
            <QuoteMini label="成交额" value={formatMoney(quote.turnover_yi)} />
          </div>
          {isRefreshing ? (
            <div className="mt-3 flex items-center gap-1.5 text-[0.7rem] text-amber-600 dark:text-amber-300">
              <RefreshCw className="size-3 animate-spin" />
              正在后台刷新
            </div>
          ) : null}
        </div>
      </div>
    </PanelShell>
  )
}

function QuoteMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[5px] bg-(--ui-bg-secondary) px-2.5 py-2">
      <div className="mb-1 text-[0.65rem] text-(--ui-text-tertiary)">{label}</div>
      <div className="truncate text-sm font-semibold text-foreground">{value}</div>
    </div>
  )
}

function MetricGrid({ metrics }: { metrics: CompanyAnalysisMetric[] }) {
  const items = metrics.length > 0 ? metrics : []

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map(metric => (
        <div
          className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 shadow-sm"
          key={metric.label}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs text-(--ui-text-tertiary)">{metric.label}</span>
            <span
              className={cn(
                'rounded-[4px] px-1.5 py-0.5 text-[0.65rem]',
                metric.tone === 'good'
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300'
                  : metric.tone === 'bad'
                    ? 'bg-red-500/10 text-red-500'
                    : 'bg-(--ui-bg-secondary) text-(--ui-text-tertiary)'
              )}
            >
              {metric.caption}
            </span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-semibold tracking-normal text-foreground">{formatNumber(metric.value)}</span>
            <span className="text-xs text-(--ui-text-tertiary)">{metric.unit}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function FinancialTrendPanel({ trend }: { trend: CompanyAnalysisFinancialTrend }) {
  const rows = mergeSeries(trend.revenue_yi, trend.net_profit_yi)

  return (
    <PanelShell
      description="最近报告期收入与利润的同轴展示"
      icon={<BarChart3 className="size-4" />}
      status={{ label: rows.length ? '已缓存' : '等待中', tone: rows.length ? 'good' : 'neutral' }}
      title="财务趋势"
    >
      {rows.length ? <RevenueProfitChart rows={rows} /> : <EmptyInline text="暂无收入/利润序列" />}
    </PanelShell>
  )
}

function RevenueProfitChart({ rows }: { rows: MergedSeriesRow[] }) {
  const chartData = rows.map(row => ({
    period: row.period,
    revenue_yi: row.primary,
    net_profit_yi: row.secondary
  }))

  return (
    <div className="h-[19rem] min-w-0">
      <ResponsiveContainer height="100%" width="100%">
        <ComposedChart data={chartData} margin={{ bottom: 8, left: 2, right: 4, top: 8 }}>
          <CartesianGrid stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="period"
            tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
            tickFormatter={value => `${formatCompact(Number(value))}`}
            tickLine={false}
            width={42}
            yAxisId="revenue"
          />
          <YAxis
            axisLine={false}
            orientation="right"
            tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
            tickFormatter={value => `${formatCompact(Number(value))}`}
            tickLine={false}
            width={42}
            yAxisId="profit"
          />
          <Tooltip
            content={<ChartTooltip units={{ net_profit_yi: '亿元', revenue_yi: '亿元' }} />}
            cursor={{ fill: 'rgba(37, 99, 235, 0.06)' }}
          />
          <Legend
            align="center"
            iconType="circle"
            verticalAlign="bottom"
            wrapperStyle={{ color: 'var(--ui-text-tertiary)', fontSize: 12, paddingTop: 10 }}
          />
          <Bar dataKey="revenue_yi" fill="rgb(59 130 246)" name="营业收入" radius={[5, 5, 0, 0]} yAxisId="revenue" />
          <Line
            activeDot={{ r: 5 }}
            dataKey="net_profit_yi"
            dot={{ r: 3 }}
            name="净利润"
            stroke="rgb(239 68 68)"
            strokeWidth={3}
            type="monotone"
            yAxisId="profit"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function ProfitabilityPanel({
  profitability,
  operatingMetrics
}: {
  profitability: CompanyAnalysisProfitability
  operatingMetrics: CompanyAnalysisOperatingMetric[]
}) {
  const rows = mergeSeries(profitability.gross_margin_percent, profitability.roe_percent)

  return (
    <PanelShell
      description="毛利率与净资产收益率走势"
      icon={<Activity className="size-4" />}
      status={{ label: rows.length ? '已缓存' : '等待中', tone: rows.length ? 'good' : 'neutral' }}
      title="盈利能力"
    >
      {rows.length ? <LineCompareChart rows={rows} /> : <EmptyInline text="暂无盈利能力序列" />}
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {operatingMetrics.slice(0, 4).map(metric => (
          <div
            className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 py-2"
            key={metric.label}
          >
            <div className="text-[0.68rem] text-(--ui-text-tertiary)">{metric.label}</div>
            <div className="mt-1 text-sm font-semibold text-foreground">
              {formatNumber(metric.value)}
              {metric.value === null ? '' : metric.unit}
            </div>
          </div>
        ))}
      </div>
    </PanelShell>
  )
}

function LineCompareChart({ rows }: { rows: MergedSeriesRow[] }) {
  const chartData = rows.map(row => ({
    gross_margin_percent: row.primary,
    period: row.period,
    roe_percent: row.secondary
  }))

  return (
    <div className="h-52 min-w-0">
      <ResponsiveContainer height="100%" width="100%">
        <LineChart data={chartData} margin={{ bottom: 8, left: 0, right: 10, top: 8 }}>
          <CartesianGrid stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="period"
            tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
            tickFormatter={value => `${Number(value).toFixed(0)}%`}
            tickLine={false}
            width={40}
          />
          <Tooltip content={<ChartTooltip units={{ gross_margin_percent: '%', roe_percent: '%' }} />} />
          <Legend
            align="center"
            iconType="circle"
            verticalAlign="bottom"
            wrapperStyle={{ color: 'var(--ui-text-tertiary)', fontSize: 12, paddingTop: 10 }}
          />
          <Line
            activeDot={{ r: 5 }}
            dataKey="gross_margin_percent"
            dot={{ r: 3 }}
            name="毛利率"
            stroke="rgb(37 99 235)"
            strokeWidth={3}
            type="monotone"
          />
          <Line
            activeDot={{ r: 5 }}
            dataKey="roe_percent"
            dot={{ r: 3 }}
            name="ROE"
            stroke="rgb(16 185 129)"
            strokeWidth={3}
            type="monotone"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function ValuationPanel({ quote, valuation }: { quote: CompanyAnalysisQuote; valuation: CompanyAnalysisValuation }) {
  const range = valuation.price_range

  return (
    <PanelShell
      description="价格区间与同行估值相对位置"
      icon={<Zap className="size-4" />}
      status={{ label: valuation.signal, tone: valuation.signal === '高于同行中位' ? 'warn' : 'good' }}
      title="估值与价格"
    >
      <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
        <div className="mb-2 flex items-center justify-between text-xs text-(--ui-text-tertiary)">
          <span>{range.label}</span>
          <span>{range.percentile !== null ? `位置 ${range.percentile}%` : '等待价格序列'}</span>
        </div>
        <div className="relative h-3 rounded-full bg-(--ui-bg-tertiary)">
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-[linear-gradient(90deg,rgb(16_185_129),rgb(245_158_11),rgb(239_68_68))]"
            style={{ width: `${range.percentile ?? 0}%` }}
          />
          <div
            className="absolute top-1/2 size-4 -translate-y-1/2 rounded-full border-2 border-white bg-red-500 shadow"
            style={{ left: `calc(${range.percentile ?? 0}% - 0.5rem)` }}
          />
        </div>
        <div className="mt-2 flex justify-between text-[0.7rem] text-(--ui-text-tertiary)">
          <span>{formatPrice(range.low)}</span>
          <span className="font-semibold text-foreground">{formatPrice(range.current ?? quote.price)}</span>
          <span>{formatPrice(range.high)}</span>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <QuoteMini label="PE(TTM)" value={formatRatio(valuation.pe_ttm)} />
        <QuoteMini label="同行PE中位" value={formatRatio(valuation.peer_median_pe)} />
        <QuoteMini label="PB" value={formatRatio(valuation.pb)} />
      </div>
    </PanelShell>
  )
}

function CapitalPanel({
  capital,
  cashFlow
}: {
  capital: CompanyAnalysisCapital
  cashFlow: { operating_cash_flow_yi: CompanyAnalysisSeriesPoint[] }
}) {
  const values = cashFlow.operating_cash_flow_yi
  const chartData = values.map(point => ({ cash_flow_yi: point.value, period: point.period }))

  return (
    <PanelShell
      description="交易活跃度与经营现金流"
      icon={<Clock className="size-4" />}
      status={{ label: capital.activity_label, tone: capital.activity_label === '活跃' ? 'good' : 'neutral' }}
      title="资金与现金流"
    >
      <div className="grid gap-2 sm:grid-cols-3">
        <QuoteMini label="成交额" value={formatMoney(capital.turnover_yi)} />
        <QuoteMini
          label="换手率"
          value={capital.turnover_rate_percent === null ? '暂无' : `${capital.turnover_rate_percent.toFixed(2)}%`}
        />
        <QuoteMini label="量比" value={formatRatio(capital.volume_ratio)} />
      </div>
      <div className="mt-4 h-44 rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-2 py-3">
        {values.length ? (
          <ResponsiveContainer height="100%" width="100%">
            <BarChart data={chartData} margin={{ bottom: 0, left: 0, right: 8, top: 8 }}>
              <CartesianGrid stroke="var(--ui-stroke-secondary)" strokeDasharray="4 6" vertical={false} />
              <XAxis
                axisLine={false}
                dataKey="period"
                tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
                tickLine={false}
              />
              <YAxis
                axisLine={false}
                tick={{ fill: 'var(--ui-text-tertiary)', fontSize: 11 }}
                tickFormatter={value => formatCompact(Number(value))}
                tickLine={false}
                width={40}
              />
              <Tooltip
                content={<ChartTooltip units={{ cash_flow_yi: '亿元' }} />}
                cursor={{ fill: 'rgba(16, 185, 129, 0.06)' }}
              />
              <Bar dataKey="cash_flow_yi" name="经营现金流" radius={[5, 5, 0, 0]}>
                {chartData.map(point => (
                  <Cell fill={point.cash_flow_yi >= 0 ? 'rgb(16 185 129)' : 'rgb(239 68 68)'} key={point.period} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyInline text="暂无经营现金流序列" />
        )}
      </div>
    </PanelShell>
  )
}

function PeersPanel({ peers }: { peers: CompanyAnalysisPeer[] }) {
  const maxMarketCap = Math.max(...peers.map(peer => peer.market_cap_yi ?? 0), 1)

  return (
    <PanelShell
      description="基于妙想 MCP 同行业/相近主营业务筛选"
      icon={<BarChart3 className="size-4" />}
      status={{ label: peers.length ? '已缓存' : '等待中', tone: peers.length ? 'good' : 'neutral' }}
      title="同行对比"
    >
      {peers.length ? (
        <div className="overflow-hidden rounded-[7px] border border-(--ui-stroke-secondary)">
          <div className="grid grid-cols-[minmax(9rem,1.3fr)_1fr_0.8fr_0.8fr_0.8fr] bg-(--ui-bg-secondary) px-3 py-2 text-[0.68rem] font-medium text-(--ui-text-tertiary)">
            <span>公司</span>
            <span>市值</span>
            <span>毛利率</span>
            <span>ROE</span>
            <span>PE(TTM)</span>
          </div>
          {peers.map(peer => (
            <div
              className={cn(
                'grid grid-cols-[minmax(9rem,1.3fr)_1fr_0.8fr_0.8fr_0.8fr] items-center gap-2 border-t border-(--ui-stroke-secondary) px-3 py-2 text-xs',
                peer.is_target && 'bg-blue-500/10'
              )}
              key={peer.code}
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-foreground">{peer.name}</div>
                <div className="text-[0.65rem] text-(--ui-text-tertiary)">{peer.code}</div>
              </div>
              <div className="min-w-0">
                <div className="mb-1 text-foreground">{formatMoney(peer.market_cap_yi)}</div>
                <div className="h-1.5 rounded-full bg-(--ui-bg-tertiary)">
                  <div
                    className="h-full rounded-full bg-blue-500"
                    style={{ width: `${((peer.market_cap_yi ?? 0) / maxMarketCap) * 100}%` }}
                  />
                </div>
              </div>
              <span>{formatPercentPlain(peer.gross_margin_percent)}</span>
              <span>{formatPercentPlain(peer.roe_percent)}</span>
              <span>{formatRatio(peer.pe_ttm)}</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyInline text="暂无同行比较数据" />
      )}
    </PanelShell>
  )
}

function ResearchPanel({ research }: { research: CompanyAnalysisResearch }) {
  const [selectedArticle, setSelectedArticle] = useState<CompanyAnalysisArticle | null>(null)

  return (
    <>
      <div className="grid gap-4 xl:grid-cols-2">
        <PanelShell
          description="从最近研报摘要中抽取"
          icon={<CheckCircle2 className="size-4" />}
          status={{
            label: research.highlights.length ? '已缓存' : '等待中',
            tone: research.highlights.length ? 'good' : 'neutral'
          }}
          title="投资亮点"
        >
          <PointList emptyText="暂无可抽取的亮点" items={research.highlights} tone="good" />
        </PanelShell>
        <PanelShell
          description="优先抽取研报风险提示原文"
          icon={<AlertTriangle className="size-4" />}
          status={{
            label: research.risks.length ? `${research.risks.length}条` : '等待中',
            tone: research.risks.length ? 'warn' : 'neutral'
          }}
          title="主要风险"
        >
          <PointList emptyText="暂无可抽取的风险提示" items={research.risks} tone="warn" />
        </PanelShell>
        <PanelShell
          className="xl:col-span-2"
          description="默认精简展示，点击查看完整摘要"
          icon={<Info className="size-4" />}
          status={{
            label: research.articles.length ? `${research.articles.length}条` : '等待中',
            tone: research.articles.length ? 'good' : 'neutral'
          }}
          title="研报摘要"
        >
          <div className="grid gap-2">
            {research.articles.length ? (
              research.articles.slice(0, 5).map((article, index) => (
                <article
                  className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3"
                  key={`${article.title}-${article.published_at}-${index}`}
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-[0.68rem] text-(--ui-text-tertiary)">
                    <span>{article.source || '未知来源'}</span>
                    <span>{article.published_at || '未知时间'}</span>
                  </div>
                  <h3 className="text-sm font-semibold text-foreground">{article.title}</h3>
                  <p className="mt-1 line-clamp-3 text-xs leading-5 text-(--ui-text-secondary)">{article.summary}</p>
                  <Button
                    className="mt-2 h-7 px-2 text-xs"
                    onClick={() => setSelectedArticle(article)}
                    size="sm"
                    variant="outline"
                  >
                    查看完整摘要
                  </Button>
                </article>
              ))
            ) : (
              <EmptyInline text="暂无研报摘要" />
            )}
          </div>
        </PanelShell>
      </div>
      <ArticleDialog article={selectedArticle} onOpenChange={open => !open && setSelectedArticle(null)} />
    </>
  )
}

function ArticleDialog({
  article,
  onOpenChange
}: {
  article: CompanyAnalysisArticle | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={Boolean(article)}>
      <DialogContent className="max-w-3xl gap-0 overflow-hidden p-0">
        {article ? (
          <div className="flex max-h-[78vh] min-h-0 flex-col">
            <DialogHeader className="border-b border-(--ui-stroke-secondary) px-5 py-4">
              <DialogTitle icon={Info}>{article.title || '研报摘要'}</DialogTitle>
              <DialogDescription>
                {[article.source || '未知来源', article.published_at || '未知时间'].filter(Boolean).join(' · ')}
              </DialogDescription>
            </DialogHeader>
            <div className="min-h-0 overflow-y-auto px-5 py-4">
              <p className="whitespace-pre-wrap text-sm leading-7 text-(--ui-text-secondary)">
                {article.summary || '暂无摘要内容。'}
              </p>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function RatingPanel({ data }: { data: CompanyAnalysisSnapshot }) {
  return (
    <PanelShell
      description="基于结构化指标与研报摘要的聚合判断"
      icon={<Zap className="size-4" />}
      status={{ label: data.rating.grade, tone: data.rating.score && data.rating.score >= 76 ? 'good' : 'neutral' }}
      title="综合评价"
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-start">
        <div className="grid size-20 shrink-0 place-items-center rounded-[7px] bg-blue-600 text-white shadow-sm">
          <div className="text-center">
            <div className="text-2xl font-semibold">{data.rating.grade}</div>
            <div className="text-[0.65rem] opacity-80">综合评分</div>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-6 text-(--ui-text-secondary)">{data.rating.summary || data.summary.headline}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {data.rating.tags.map(tag => (
              <span
                className="rounded-[4px] bg-blue-500/10 px-2 py-0.5 text-[0.7rem] text-blue-600 dark:text-blue-300"
                key={tag}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
    </PanelShell>
  )
}

function MethodologyPanel({ data }: { data: CompanyAnalysisSnapshot }) {
  return (
    <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 text-xs leading-5 text-(--ui-text-tertiary)">
      <div className="mb-2 flex flex-wrap items-center gap-2 font-medium text-foreground">
        <Info className="size-3.5 text-blue-500" />
        <span>{data.methodology?.title ?? '数据说明'}</span>
      </div>
      <p>{data.methodology?.description}</p>
      {data.gaps.length ? (
        <div className="mt-3 grid gap-2">
          {data.gaps.map(gap => (
            <div
              className={cn(
                'rounded-[5px] border px-3 py-2',
                gap.severity === 'error'
                  ? 'border-red-500/25 bg-red-500/10 text-red-500'
                  : gap.severity === 'warning'
                    ? 'border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-300'
                    : 'border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)'
              )}
              key={gap.key}
            >
              <span className="font-medium">{gap.title}</span>：{gap.message}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function PanelShell({
  children,
  className,
  description,
  icon,
  status,
  title
}: {
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
          <p className="mt-1 text-xs text-(--ui-text-tertiary)">{description}</p>
        </div>
        <ModuleStatusPill status={status} />
      </div>
      {children}
    </section>
  )
}

function PointList({ emptyText, items, tone }: { emptyText: string; items: string[]; tone: 'good' | 'warn' }) {
  if (!items.length) {
    return <EmptyInline text={emptyText} />
  }

  return (
    <ul className="grid gap-2">
      {items.slice(0, 5).map(item => (
        <li
          className="flex gap-2 rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 py-2 text-xs leading-5 text-(--ui-text-secondary)"
          key={item}
        >
          <span
            className={cn('mt-1 size-1.5 shrink-0 rounded-full', tone === 'good' ? 'bg-emerald-500' : 'bg-amber-500')}
          />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

function DashboardSkeleton({ isRefreshing, query }: { isRefreshing: boolean; query: string }) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-6 shadow-sm">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground">
          <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin')} />
          正在生成 {query} 的公司分析
        </div>
        <p className="text-xs leading-5 text-(--ui-text-tertiary)">
          页面会先返回加载态，后端连接妙想 MCP 完成后自动更新。
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {['行情画像', '核心指标', '财务趋势', '研报摘要'].map(label => (
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

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-3xl rounded-[7px] border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-500">
      <div className="mb-1 flex items-center gap-2 font-semibold">
        <AlertTriangle className="size-4" />
        公司分析加载失败
      </div>
      <p>{message}</p>
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

function ChartTooltip({
  active,
  label,
  payload,
  units
}: {
  active?: boolean
  label?: string
  payload?: Array<{ color?: string; name?: string; value?: number | string | null; dataKey?: string | number }>
  units: Record<string, string>
}) {
  if (!active || !payload?.length) {
    return null
  }

  return (
    <div className="rounded-[7px] border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-foreground">{label}</div>
      <div className="grid gap-1">
        {payload.map(item => {
          const key = String(item.dataKey ?? '')
          const unit = units[key] ?? ''

          return (
            <div className="flex min-w-32 items-center justify-between gap-4" key={`${key}-${item.name}`}>
              <span className="inline-flex items-center gap-1.5 text-(--ui-text-tertiary)">
                <span className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
                {item.name}
              </span>
              <span className="font-medium text-foreground">{formatTooltipValue(item.value, unit)}</span>
            </div>
          )
        })}
      </div>
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

interface ModuleStatus {
  label: string
  tone: 'good' | 'neutral' | 'warn'
}

interface MergedSeriesRow {
  period: string
  primary: number | null
  secondary: number | null
}

function sectionStatus(
  refresh: CompanyAnalysisRefreshState | undefined,
  section: string,
  gaps: CompanyAnalysisGap[]
): ModuleStatus {
  if (refresh?.sections?.[section] === 'refreshing') {
    return { label: '刷新中', tone: 'warn' }
  }

  if (gaps.some(gap => gap.key === section)) {
    return { label: '数据缺口', tone: 'warn' }
  }

  if (refresh?.cache_state === 'empty') {
    return { label: '等待中', tone: 'neutral' }
  }

  if (refresh?.completed_at) {
    return { label: '刚刚更新', tone: 'good' }
  }

  return { label: '已缓存', tone: 'neutral' }
}

function mergeSeries(
  primary: CompanyAnalysisSeriesPoint[],
  secondary: CompanyAnalysisSeriesPoint[]
): MergedSeriesRow[] {
  const labels = [...primary.map(point => point.period), ...secondary.map(point => point.period)].filter(
    (label, index, arr) => label && arr.indexOf(label) === index
  )

  return labels.map(period => ({
    period,
    primary: primary.find(point => point.period === period)?.value ?? null,
    secondary: secondary.find(point => point.period === period)?.value ?? null
  }))
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

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return value.toLocaleString('zh-CN', { maximumFractionDigits: value >= 100 ? 0 : 1 })
}

function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return ''
  }

  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(value >= 100 ? 0 : 1)
}

function formatTooltipValue(value: number | string | null | undefined, unit: string): string {
  if (value === null || value === undefined || value === '') {
    return '暂无'
  }

  const numeric = typeof value === 'number' ? value : Number(value)

  if (Number.isNaN(numeric)) {
    return `${value}${unit}`
  }

  if (unit === '%') {
    return `${numeric.toFixed(2)}%`
  }

  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: Math.abs(numeric) >= 100 ? 1 : 2 })}${unit}`
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '暂无'
  }

  const sign = value > 0 ? '+' : ''

  return `${sign}${value.toFixed(2)}%`
}

function formatPercentPlain(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '暂无'
  }

  return `${value.toFixed(1)}%`
}

function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return `${value.toFixed(value >= 100 ? 0 : 1)}x`
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return `¥${value.toFixed(2)}`
}

function formatSignedNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '暂无'
  }

  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
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
