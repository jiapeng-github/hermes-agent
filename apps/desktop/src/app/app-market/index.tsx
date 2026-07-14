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
import { launchAppInBrowser } from '@/lib/app-launch'
import { Download, ExternalLink, MoreHorizontal, Package, Pencil, Plus, Search, Trash2, Upload } from '@/lib/icons'

export interface AppSummary {
  id: string
  name: string
  description: string
  version: string
  enabled: boolean
  source_editable: boolean
  trust_state: 'builtin' | 'signed' | 'local_untrusted'
  status: 'ready' | 'disabled' | 'incompatible' | 'invalid' | 'busy'
  requested_permissions: AppImportPlan['requested_permissions']
  granted_permissions: AppImportPlan['requested_permissions']
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

export function AppMarketView({ onCreateApp, onEditApp }: AppMarketViewProps) {
  const [apps, setApps] = useState<AppSummary[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [importPlan, setImportPlan] = useState<AppImportPlan | null>(null)
  const [importing, setImporting] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<AppSummary | null>(null)

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

  const visibleApps = useMemo(() => {
    const folded = query.trim().toLocaleLowerCase()

    if (!folded) {
      return apps
    }

    return apps.filter(app => `${app.name} ${app.id} ${app.description}`.toLocaleLowerCase().includes(folded))
  }, [apps, query])

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
          grants: importPlan.requested_permissions
        }
      })
      setImportPlan(null)
      setNotice(`已安装 ${importPlan.app.name} ${importPlan.app.version}`)
      await loadApps()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '应用安装失败。')
    } finally {
      setImporting(false)
    }
  }

  async function discardImport() {
    if (importPlan) {
      await window.hermesDesktop.api({
        path: `/api/apps/imports/${encodeURIComponent(importPlan.import_id)}`,
        method: 'DELETE'
      }).catch(() => undefined)
    }

    setImportPlan(null)
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

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-(--ui-chat-surface-background) [scrollbar-gutter:stable]">
      <header className="sticky top-0 z-20 border-b border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background)/95 px-5 pb-3 pt-[calc(var(--titlebar-height)+0.7rem)] backdrop-blur-md">
        <div className="mx-auto flex max-w-[75rem] flex-wrap items-center gap-3">
          <div className="mr-auto min-w-0">
            <h1 className="text-base font-semibold text-foreground">应用市场</h1>
            <p className="mt-0.5 text-xs text-(--ui-text-tertiary)">浏览、创建和管理由 Stock Agent 提供服务的 Web 应用</p>
          </div>
          <div className="relative min-w-[12rem] flex-1 sm:max-w-[20rem]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-(--ui-text-tertiary)" />
            <Input
              aria-label="搜索应用"
              className="h-8 pl-8"
              onChange={event => setQuery(event.target.value)}
              placeholder="搜索应用"
              value={query}
            />
          </div>
          <Button onClick={() => void chooseImport()} size="sm" variant="outline">
            <Upload className="size-3.5" />
            导入
          </Button>
          <Button onClick={onCreateApp} size="sm">
            <Plus className="size-3.5" />
            创建应用
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-[75rem] px-5 py-4">
        {(error || notice) && (
          <div
            className={`mb-4 rounded-md border px-3 py-2 text-xs ${error ? 'border-destructive/30 bg-destructive/8 text-destructive' : 'border-emerald-500/25 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300'}`}
            role={error ? 'alert' : 'status'}
          >
            {error ?? notice}
          </div>
        )}

        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-medium text-(--ui-text-secondary)">全部应用 · {visibleApps.length}</span>
          <span className="text-[0.6875rem] text-(--ui-text-tertiary)">应用市场不会主动请求行情数据</span>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map(item => (
              <div className="h-36 animate-pulse rounded-md border border-(--ui-stroke-tertiary) bg-white dark:bg-(--ui-bg-elevated)" key={item} />
            ))}
          </div>
        ) : visibleApps.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visibleApps.map(app => {
              const builtin = app.trust_state === 'builtin'

              return (
                <article
                  className="group flex min-h-36 flex-col rounded-md border border-(--ui-stroke-tertiary) bg-white p-3.5 shadow-sm transition-colors hover:border-primary/30 dark:bg-(--ui-bg-elevated)"
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
                  <div className="mt-auto flex items-center gap-2 pt-2.5">
                    <Badge variant={app.status === 'ready' ? 'default' : 'warn'}>{STATUS_LABEL[app.status]}</Badge>
                    <span className="text-[0.6875rem] text-(--ui-text-tertiary)">v{app.version}</span>
                    {builtin && <span className="text-[0.6875rem] text-(--ui-text-tertiary)">内置</span>}
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
                <div className="mt-1 font-mono text-[0.6875rem] text-(--ui-text-tertiary)">{importPlan.app.id} · v{importPlan.app.version}</div>
                <p className="mt-2 text-(--ui-text-secondary)">{importPlan.app.description}</p>
              </div>
              <div className="space-y-1 text-(--ui-text-secondary)">
                <p>来源：{importPlan.signature_state === 'valid_trusted' ? '已验证签名' : '本地未签名包'}</p>
                <p>智能体分析：{importPlan.requested_permissions.agent ? '需要授权' : '不需要'}</p>
                <p>MCP：{importPlan.requested_permissions.mcp_servers.join('、') || '不需要'}</p>
                <p>存储：{importPlan.requested_permissions.storage.mode} · {importPlan.requested_permissions.storage.quota_mb} MB</p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button disabled={importing} onClick={() => void discardImport()} variant="ghost">取消</Button>
            <Button disabled={importing} onClick={() => void confirmImport()}>{importing ? '安装中…' : '确认安装'}</Button>
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
