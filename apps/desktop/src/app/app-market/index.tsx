import { useEffect, useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import type { AppImportPlan } from '@/global'
import {
  cancelHubAppOperation,
  getHubAppOperation,
  getHubAppPreviewDataUrl,
  type HubAppCategory,
  type HubAppOperation,
  type HubAppSummary,
  listHubAppCategories,
  listHubApps,
  startHubAppInstall
} from '@/hermes'
import { launchAppInBrowser } from '@/lib/app-launch'
import {
  Download,
  ExternalLink,
  Loader2,
  MoreHorizontal,
  Package,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  ZoomIn
} from '@/lib/icons'

export interface AppSummary {
  id: string
  name: string
  description: string
  version: string
  enabled: boolean
  source_editable: boolean
  lineage: 'builtin' | 'imported' | 'user'
  installed_at: string
  updated_at: string
  trust_state: 'builtin' | 'signed' | 'local_untrusted'
  status: 'ready' | 'disabled' | 'incompatible' | 'invalid' | 'busy'
  requested_permissions: AppImportPlan['requested_permissions']
  granted_permissions: AppImportPlan['requested_permissions']
  category?: string | null
}

interface AppList {
  items: AppSummary[]
  next_cursor: null | string
}

interface AppMarketViewProps {
  onCreateApp: () => void
  onEditApp: (app: AppSummary) => void
}

const STATUS_LABEL: Record<AppSummary['status'], string> = {
  ready: '可用',
  disabled: '已停用',
  incompatible: '版本不兼容',
  invalid: '应用异常',
  busy: '运行中'
}

function hubErrorMessage(reason: unknown, fallback: string): string {
  const message = reason instanceof Error ? reason.message : ''

  if (message.includes('HUB_DISABLED')) {
    return '应用中心尚未启用或尚未配置，请联系管理员后重试。'
  }

  if (message.includes('HUB_UNAVAILABLE')) {
    return '暂时无法连接应用中心，请稍后重试。'
  }

  return message || fallback
}

function sourceLabel(app: AppSummary): string {
  if (app.lineage === 'builtin') return '内置'
  if (app.trust_state === 'signed') return '中心安装'
  if (app.lineage === 'user') return '本地创建'
  return '本地导入'
}

function formatInstalledAt(value: string): string {
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(timestamp)
}

function hubStageLabel(state: HubAppOperation['state'] | undefined): string {
  switch (state) {
    case 'queued':
      return '正在排队准备…'
    case 'resolving':
      return '正在解析应用版本…'
    case 'downloading':
      return '正在安全下载应用包…'
    case 'analyzing':
      return '正在分析应用权限…'
    default:
      return '正在准备应用安装…'
  }
}

function categoryLabel(category: string | null | undefined, categories: HubAppCategory[]): string {
  if (!category) return ''
  return categories.find(item => item.id === category)?.name ?? category
}

function selectedCategoryLabel(category: string, categories: HubAppCategory[]): string {
  return category === 'all' ? '全部' : categoryLabel(category, categories)
}

interface HubPreviewSelection {
  dataUrl: string
  name: string
}

interface HubAppPreviewProps {
  app: HubAppSummary
  onOpen: (preview: HubPreviewSelection) => void
}

function HubAppPreview({ app, onOpen }: HubAppPreviewProps) {
  const [dataUrl, setDataUrl] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const previewUrl = app.preview_image_url

  useEffect(() => {
    let cancelled = false

    setDataUrl(null)
    setUnavailable(false)

    if (!previewUrl) {
      return () => {
        cancelled = true
      }
    }

    void getHubAppPreviewDataUrl(app.id, app.version)
      .then(url => {
        if (!cancelled) {
          setDataUrl(url)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUnavailable(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [app.id, app.version, previewUrl])

  return (
    <div className="relative aspect-video overflow-hidden border-b border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary)">
      {dataUrl && !unavailable ? (
        <button
          aria-label={`查看 ${app.name} 预览图`}
          className="group/preview size-full cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
          onClick={() => onOpen({ name: app.name, dataUrl })}
          type="button"
        >
          <img
            alt={`${app.name} 预览图`}
            className="size-full object-cover transition-transform duration-200 group-hover/preview:scale-[1.03]"
            onError={() => setUnavailable(true)}
            src={dataUrl}
          />
          <span className="pointer-events-none absolute inset-0 grid place-items-center bg-black/40 text-xs font-medium text-white opacity-0 transition-opacity group-hover/preview:opacity-100 group-focus-visible/preview:opacity-100">
            <span className="flex items-center gap-1.5 rounded-md bg-black/45 px-2.5 py-1.5 backdrop-blur-sm">
              <ZoomIn className="size-3.5" /> 点击查看全图
            </span>
          </span>
        </button>
      ) : (
        <div className="grid size-full place-items-center text-(--ui-text-tertiary)">
          <div className="grid size-11 place-items-center rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) text-primary">
            <Package className="size-5" />
          </div>
        </div>
      )}
    </div>
  )
}

export function AppMarketView({ onCreateApp, onEditApp }: AppMarketViewProps) {
  const [mode, setMode] = useState<'installed' | 'hub'>('installed')
  const [apps, setApps] = useState<AppSummary[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [importPlan, setImportPlan] = useState<AppImportPlan | null>(null)
  const [importing, setImporting] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<AppSummary | null>(null)
  const [hubApps, setHubApps] = useState<HubAppSummary[]>([])
  const [categories, setCategories] = useState<HubAppCategory[]>([])
  const [selectedCategory, setSelectedCategory] = useState('all')
  const [categoryError, setCategoryError] = useState<string | null>(null)
  const [hubInstalled, setHubInstalled] = useState<
    Record<string, { version: string; state: 'installed' | 'update_available' }>
  >({})
  const [hubLoading, setHubLoading] = useState(false)
  const [hubOperation, setHubOperation] = useState<HubAppOperation | null>(null)
  const [hubRefreshEpoch, setHubRefreshEpoch] = useState(0)
  const [externalInstallNotice, setExternalInstallNotice] = useState<string | null>(null)
  const [hubPreview, setHubPreview] = useState<HubPreviewSelection | null>(null)

  async function loadApps() {
    setLoading(true)
    setError(null)

    try {
      const result = await window.hermesDesktop.api<AppList>({ path: '/api/apps' })
      setApps(result.items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '应用列表加载失败。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadApps()
  }, [])

  useEffect(() => {
    let active = true

    void listHubAppCategories()
      .then(result => {
        if (!active) return
        setCategories(result.items)
        setCategoryError(null)
      })
      .catch(reason => active && setCategoryError(hubErrorMessage(reason, '应用分类加载失败。')))

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (mode !== 'hub') {
      return
    }

    let active = true
    setHubLoading(true)
    setError(null)
    const timer = window.setTimeout(() => {
      void listHubApps({ category: selectedCategory === 'all' ? undefined : selectedCategory, query })
        .then(result => {
          if (!active) return
          setHubApps(result.items)
          setHubInstalled(result.installed)
        })
        .catch(reason => active && setError(hubErrorMessage(reason, '应用中心加载失败。')))
        .finally(() => active && setHubLoading(false))
    }, 250)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [mode, query, selectedCategory, hubRefreshEpoch])

  useEffect(() => {
    if (!hubOperation || !['queued', 'resolving', 'downloading', 'analyzing'].includes(hubOperation.state)) {
      return
    }

    const timer = window.setInterval(() => {
      void getHubAppOperation(hubOperation.operation_id)
        .then(operation => {
          setHubOperation(operation)
          if (operation.state === 'completed' && operation.import_plan) {
            setImportPlan(operation.import_plan)
            setNotice(null)
          }
          if (operation.state === 'failed') {
            setError(operation.error?.message ?? '应用中心安装准备失败。')
          }
        })
        .catch(reason => setError(reason instanceof Error ? reason.message : '无法获取应用安装状态。'))
    }, 800)

    return () => window.clearInterval(timer)
  }, [hubOperation])

  const visibleApps = useMemo(() => {
    const folded = query.trim().toLocaleLowerCase()

    return apps.filter(app => {
      const matchesQuery = !folded || `${app.name} ${app.id} ${app.description}`.toLocaleLowerCase().includes(folded)
      const matchesCategory = selectedCategory === 'all' || app.category === selectedCategory
      return matchesQuery && matchesCategory
    })
  }, [apps, query, selectedCategory])

  const categoryTabs = useMemo(() => {
    return [{ id: 'all', name: '全部' }, ...categories]
  }, [categories])

  async function chooseImport() {
    setError(null)

    try {
      const plan = await window.hermesDesktop.apps.selectAndAnalyzePackage()

      if (plan) {
        setImportPlan(plan)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法分析应用包。')
    }
  }

  async function confirmImport() {
    if (!importPlan || importing) {
      return
    }

    setImporting(true)

    try {
      await window.hermesDesktop.api({
        path: `/api/apps/imports/${encodeURIComponent(importPlan.import_id)}/confirm`,
        method: 'POST',
        body: {
          package_sha256: importPlan.package_sha256,
          conflict_mode: importPlan.conflict.kind === 'none' ? 'install' : 'update',
          copy_app_id: null,
          grants: importPlan.requested_permissions,
          category:
            hubOperation?.import_plan?.import_id === importPlan.import_id ? (hubOperation.category ?? null) : null
        }
      })
      const wasHubInstall = hubOperation?.import_plan?.import_id === importPlan.import_id
      setImportPlan(null)
      setNotice(`已安装 ${importPlan.app.name} ${importPlan.app.version}`)
      if (wasHubInstall) {
        setHubOperation(null)
        setHubRefreshEpoch(value => value + 1)
      }
      await loadApps()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '应用安装失败。')
    } finally {
      setImporting(false)
    }
  }

  async function discardImport() {
    if (importPlan) {
      await window.hermesDesktop
        .api({
          path: `/api/apps/imports/${encodeURIComponent(importPlan.import_id)}`,
          method: 'DELETE'
        })
        .catch(() => undefined)
    }

    setImportPlan(null)
    if (hubOperation?.import_plan?.import_id === importPlan?.import_id) {
      setHubOperation(null)
    }
  }

  async function exportPackage(app: AppSummary) {
    setError(null)

    try {
      const result = await window.hermesDesktop.apps.exportPackage(app.id, {
        includeSource: app.source_editable
      })

      if (!result.canceled) {
        setNotice(`已导出 ${app.name}`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '应用导出失败。')
    }
  }

  async function uninstall(app: AppSummary) {
    await window.hermesDesktop.api({
      path: `/api/apps/${encodeURIComponent(app.id)}?preserve_data=true`,
      method: 'DELETE'
    })
    setNotice(`已卸载 ${app.name}，应用数据已保留`)
    await loadApps()
  }

  async function installFromHub(app: HubAppSummary) {
    setError(null)
    setNotice(null)

    try {
      const operation = await startHubAppInstall(app.id, app.version)
      setHubOperation(operation)
    } catch (reason) {
      setError(hubErrorMessage(reason, '无法开始安装应用。'))
    }
  }

  function showExternalInstallNotice(app: HubAppSummary) {
    setError(null)
    setExternalInstallNotice(app.delivery?.message || '外部安装，请联系运维人员。')
  }

  async function cancelHubInstall() {
    if (!hubOperation) return
    await cancelHubAppOperation(hubOperation.operation_id).catch(() => undefined)
    setNotice('已取消应用安装准备')
    setHubOperation(null)
  }

  const hubBusy = Boolean(
    hubOperation && ['queued', 'resolving', 'downloading', 'analyzing'].includes(hubOperation.state)
  )

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-(--ui-chat-surface-background) [scrollbar-gutter:stable]">
      <header className="sticky top-0 z-20 border-b border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background)/95 px-5 pb-3 pt-[calc(var(--titlebar-height)+0.7rem)] backdrop-blur-md">
        <div className="mx-auto max-w-[75rem]">
          <div className="flex min-h-8 flex-wrap items-center gap-3">
            <div className="mr-auto min-w-0">
              <h1 className="text-base font-semibold text-foreground">应用</h1>
              <p className="mt-0.5 text-xs text-(--ui-text-tertiary)">
                浏览、创建和管理由 Stock Agent 提供服务的 Web 应用
              </p>
            </div>
            {mode === 'installed' && (
              <div className="flex items-center gap-2">
                <Button onClick={() => void chooseImport()} size="sm" variant="outline">
                  <Upload className="size-3.5" />
                  导入
                </Button>
                <Button onClick={onCreateApp} size="sm">
                  <Plus className="size-3.5" />
                  创建应用
                </Button>
              </div>
            )}
          </div>
          <div className="mt-4 flex items-center justify-between gap-3 border-t border-(--ui-stroke-tertiary) pt-3">
            <div className="flex items-center rounded-md border border-(--ui-stroke-tertiary) p-0.5 text-xs">
              <Button
                onClick={() => setMode('installed')}
                size="xs"
                variant={mode === 'installed' ? 'secondary' : 'ghost'}
              >
                已安装
              </Button>
              <Button onClick={() => setMode('hub')} size="xs" variant={mode === 'hub' ? 'secondary' : 'ghost'}>
                应用中心
              </Button>
            </div>
            <div className="relative w-[13rem] sm:w-[20rem]">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-(--ui-text-tertiary)" />
              <Input
                aria-label="搜索应用"
                className="h-8 pl-8"
                onChange={event => setQuery(event.target.value)}
                placeholder="搜索应用"
                value={query}
              />
            </div>
          </div>
          <div className="mt-3 -mx-1 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <div aria-label="应用分类" className="flex min-w-max items-center gap-1" role="tablist">
              {categoryTabs.map(category => (
                <Button
                  aria-selected={selectedCategory === category.id}
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  role="tab"
                  size="xs"
                  variant={selectedCategory === category.id ? 'secondary' : 'ghost'}
                >
                  {category.name}
                </Button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[75rem] px-5 py-4">
        {(error || notice || categoryError) && (
          <div
            className={`mb-4 rounded-md border px-3 py-2 text-xs ${error || categoryError ? 'border-destructive/30 bg-destructive/8 text-destructive' : 'border-emerald-500/25 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300'}`}
            role={error || categoryError ? 'alert' : 'status'}
          >
            {error ?? categoryError ?? notice}
          </div>
        )}

        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-medium text-(--ui-text-secondary)">
            {mode === 'installed'
              ? `${selectedCategoryLabel(selectedCategory, categories)}应用 · ${visibleApps.length}`
              : `${selectedCategoryLabel(selectedCategory, categories)}应用 · ${hubApps.length}`}
          </span>
          <span className="text-[0.6875rem] text-(--ui-text-tertiary)">
            {mode === 'installed' ? '应用不会主动请求行情数据' : '安装前将展示所需权限'}
          </span>
        </div>

        {mode === 'hub' ? (
          hubLoading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map(item => (
                <div
                  className="h-72 animate-pulse rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-card-surface-background)"
                  key={item}
                />
              ))}
            </div>
          ) : hubApps.length ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {hubApps.map(app => {
                const externalInstall = app.delivery?.type === 'external'
                const installed = hubInstalled[app.id]
                const updateAvailable = installed?.state === 'update_available'
                const installing = hubBusy && hubOperation?.hub_app_id === app.id
                const retrying = hubOperation?.state === 'failed' && hubOperation.hub_app_id === app.id
                return (
                  <article
                    className="group flex min-w-0 flex-col overflow-hidden rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-card-surface-background) transition-colors hover:border-primary/30"
                    key={app.id}
                  >
                    <HubAppPreview app={app} onOpen={setHubPreview} />
                    <div className="flex flex-1 flex-col p-3.5">
                      <div className="flex items-start gap-2.5">
                        <div className="grid size-9 shrink-0 place-items-center overflow-hidden rounded-md bg-primary/10 text-primary">
                          {app.icon_url ? (
                            <img
                              alt=""
                              className="size-full object-cover"
                              src={`/api/apps/hub/${encodeURIComponent(app.id)}/icon?version=${encodeURIComponent(app.version)}`}
                            />
                          ) : (
                            <Package className="size-4" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h2 className="line-clamp-1 text-sm font-semibold text-foreground break-words">{app.name}</h2>
                          <p className="mt-0.5 truncate text-[0.6875rem] text-(--ui-text-tertiary)">
                            {app.publisher || 'Finance Mate'}
                          </p>
                        </div>
                      </div>
                      <p className="mt-3 line-clamp-2 text-xs leading-5 text-(--ui-text-secondary)">
                        {app.summary || app.description}
                      </p>
                      <div className="mt-3 flex items-center gap-2">
                        {app.category && <Badge variant="muted">{categoryLabel(app.category, categories)}</Badge>}
                        <span className="text-[0.6875rem] text-(--ui-text-tertiary)">v{app.version}</span>
                        {externalInstall ? (
                          <>
                            <Badge variant="warn">外部安装</Badge>
                            <Button
                              className="ml-auto"
                              onClick={() => showExternalInstallNotice(app)}
                              size="sm"
                              variant="outline"
                            >
                              外部安装
                            </Button>
                          </>
                        ) : installing ? (
                          <Button className="ml-auto" disabled size="sm">
                            <Loader2 className="size-3.5 animate-spin" /> 准备中…
                          </Button>
                        ) : retrying ? (
                          <Button
                            className="ml-auto"
                            onClick={() => void installFromHub(app)}
                            size="sm"
                            variant="outline"
                          >
                            <RefreshCw className="size-3.5" /> 重试
                          </Button>
                        ) : updateAvailable ? (
                          <Button
                            className="ml-auto"
                            disabled={hubBusy}
                            onClick={() => void installFromHub(app)}
                            size="sm"
                          >
                            <RefreshCw className="size-3.5" /> 更新
                          </Button>
                        ) : installed ? (
                          <Badge className="ml-auto" variant="default">
                            已是最新
                          </Badge>
                        ) : (
                          <Button
                            className="ml-auto"
                            disabled={hubBusy}
                            onClick={() => void installFromHub(app)}
                            size="sm"
                          >
                            安装
                          </Button>
                        )}
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="grid min-h-52 place-items-center rounded-md border border-dashed border-(--ui-stroke-secondary) text-center">
              <div>
                <Package className="mx-auto size-6 text-(--ui-text-tertiary)" />
                <p className="mt-2 text-sm font-medium">没有可用的中心应用</p>
                <p className="mt-1 text-xs text-(--ui-text-tertiary)">请检查应用中心服务配置后重试。</p>
              </div>
            </div>
          )
        ) : loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map(item => (
              <div
                className="h-36 animate-pulse rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-card-surface-background)"
                key={item}
              />
            ))}
          </div>
        ) : visibleApps.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visibleApps.map(app => {
              const builtin = app.trust_state === 'builtin'

              return (
                <article
                  className="group flex min-h-36 flex-col rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-card-surface-background) p-3.5 transition-colors hover:border-primary/30"
                  key={app.id}
                >
                  <div className="flex items-start gap-3">
                    <button
                      aria-label={`打开 ${app.name}（应用图标）`}
                      className="grid size-10 shrink-0 place-items-center rounded-md bg-primary/10 text-primary transition-colors hover:bg-primary/15"
                      onClick={() => void launchAppInBrowser(app.id).catch(reason => setError(String(reason)))}
                      type="button"
                    >
                      <Package className="size-5" />
                    </button>
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => void launchAppInBrowser(app.id).catch(reason => setError(String(reason)))}
                      type="button"
                    >
                      <h2 className="line-clamp-2 text-sm font-semibold text-foreground break-words">{app.name}</h2>
                      <p className="mt-0.5 truncate font-mono text-[0.625rem] text-(--ui-text-tertiary)">{app.id}</p>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button aria-label={`管理 ${app.name}`} size="icon-xs" variant="ghost">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => onEditApp(app)}>
                          <Pencil className="size-3.5" /> 修改
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={builtin}
                          onSelect={() => void exportPackage(app)}
                          title={builtin ? '内置应用的运行时金融服务权限不能导出为可移植应用包' : undefined}
                        >
                          <Download className="size-3.5" /> 导出 .happ
                        </DropdownMenuItem>
                        {!builtin && (
                          <DropdownMenuItem className="text-destructive" onSelect={() => setRemoveTarget(app)}>
                            <Trash2 className="size-3.5" /> 卸载
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <p className="mt-2.5 line-clamp-2 text-xs leading-5 text-(--ui-text-secondary)">{app.description}</p>
                  <div className="mt-auto flex flex-wrap items-center gap-2 pt-2.5">
                    {app.category && <Badge variant="muted">{categoryLabel(app.category, categories)}</Badge>}
                    <Badge variant={app.status === 'ready' ? 'default' : 'warn'}>{STATUS_LABEL[app.status]}</Badge>
                    <span className="text-[0.6875rem] text-(--ui-text-tertiary)">v{app.version}</span>
                    <span className="text-[0.6875rem] text-(--ui-text-tertiary)">{sourceLabel(app)}</span>
                    <span className="text-[0.6875rem] text-(--ui-text-tertiary)">
                      安装于 {formatInstalledAt(app.installed_at)}
                    </span>
                    <Button
                      aria-label={`打开 ${app.name}`}
                      className="ml-auto"
                      disabled={app.status !== 'ready'}
                      onClick={() => void launchAppInBrowser(app.id).catch(reason => setError(String(reason)))}
                      size="sm"
                      variant="outline"
                    >
                      <ExternalLink className="size-3.5" /> 打开
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="grid min-h-52 place-items-center rounded-md border border-dashed border-(--ui-stroke-secondary) text-center">
            <div>
              <Package className="mx-auto size-6 text-(--ui-text-tertiary)" />
              <p className="mt-2 text-sm font-medium">没有匹配的应用</p>
              <p className="mt-1 text-xs text-(--ui-text-tertiary)">调整搜索词，或创建一个新应用。</p>
            </div>
          </div>
        )}
      </main>

      <Dialog onOpenChange={open => !open && setHubPreview(null)} open={Boolean(hubPreview)}>
        <DialogContent className="flex h-[min(80vh,52rem)] max-h-[90vh] max-w-[90vw] flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="shrink-0 border-b border-(--ui-stroke-tertiary) px-5 py-4 pr-12">
            <DialogTitle>{hubPreview?.name} · 应用预览</DialogTitle>
            <DialogDescription>滚动查看完整预览图</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 touch-pan-y overflow-auto overscroll-contain bg-(--ui-bg-secondary) p-4">
            {hubPreview && (
              <img
                alt={`${hubPreview.name} 完整预览图`}
                className="mx-auto block h-auto max-w-full rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) shadow-sm"
                src={hubPreview.dataUrl}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog onOpenChange={open => !open && void discardImport()} open={Boolean(importPlan)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>确认导入应用</DialogTitle>
            <DialogDescription>安装前请确认应用身份、来源和所需权限。</DialogDescription>
          </DialogHeader>
          {importPlan && (
            <div className="space-y-3 text-xs">
              <div className="rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) p-3">
                <div className="font-semibold text-foreground">{importPlan.app.name}</div>
                <div className="mt-1 font-mono text-[0.6875rem] text-(--ui-text-tertiary)">
                  {importPlan.app.id} · v{importPlan.app.version}
                </div>
                <p className="mt-2 text-(--ui-text-secondary)">{importPlan.app.description}</p>
              </div>
              <div className="space-y-1 text-(--ui-text-secondary)">
                <p>来源：{importPlan.signature_state === 'valid_trusted' ? '已验证签名' : '本地未签名包'}</p>
                <p>智能体分析：{importPlan.requested_permissions.agent ? '需要授权' : '不需要'}</p>
                <p>MCP：{importPlan.requested_permissions.mcp_servers.join('、') || '不需要'}</p>
                <p>
                  存储：{importPlan.requested_permissions.storage.mode} ·{' '}
                  {importPlan.requested_permissions.storage.quota_mb} MB
                </p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button disabled={importing} onClick={() => void discardImport()} variant="ghost">
              取消
            </Button>
            <Button disabled={importing} onClick={() => void confirmImport()}>
              {importing ? '安装中…' : '确认安装'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog onOpenChange={open => !open && void cancelHubInstall()} open={hubBusy}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>正在准备应用安装</DialogTitle>
            <DialogDescription>正在从应用中心下载并校验应用包，随后会展示权限确认。</DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 text-sm text-(--ui-text-secondary)">
            <Loader2 className="size-4 animate-spin" />
            {hubStageLabel(hubOperation?.state)}
          </div>
          <div aria-label="安装进度" className="h-1.5 overflow-hidden rounded-full bg-(--ui-bg-tertiary)">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-300"
              style={{ width: `${hubOperation?.progress ?? 5}%` }}
            />
          </div>
          <p className="text-right text-[0.6875rem] text-(--ui-text-tertiary)">{hubOperation?.progress ?? 5}%</p>
          <DialogFooter>
            <Button onClick={() => void cancelHubInstall()} variant="ghost">
              取消
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog onOpenChange={open => !open && setExternalInstallNotice(null)} open={Boolean(externalInstallNotice)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>外部安装</DialogTitle>
            <DialogDescription>{externalInstallNotice}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setExternalInstallNotice(null)}>知道了</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        confirmLabel="卸载应用"
        description={removeTarget ? `将移除“${removeTarget.name}”的应用包和版本记录，默认保留应用数据。` : undefined}
        destructive
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => (removeTarget ? uninstall(removeTarget) : undefined)}
        open={Boolean(removeTarget)}
        title="确认卸载"
      />
    </div>
  )
}
