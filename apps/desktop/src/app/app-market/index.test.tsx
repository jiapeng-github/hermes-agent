// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const launchHermesApp = vi.fn()
const listHubAppCategories = vi.fn()
const listHubApps = vi.fn()
const startHubAppInstall = vi.fn()
const getHubAppOperation = vi.fn()
const cancelHubAppOperation = vi.fn()
const getHubAppPreviewDataUrl = vi.fn()

vi.mock('@/hermes', () => ({
  launchHermesApp: (...args: unknown[]) => launchHermesApp(...args),
  listHubAppCategories: (...args: unknown[]) => listHubAppCategories(...args),
  listHubApps: (...args: unknown[]) => listHubApps(...args),
  startHubAppInstall: (...args: unknown[]) => startHubAppInstall(...args),
  getHubAppOperation: (...args: unknown[]) => getHubAppOperation(...args),
  cancelHubAppOperation: (...args: unknown[]) => cancelHubAppOperation(...args),
  getHubAppPreviewDataUrl: (...args: unknown[]) => getHubAppPreviewDataUrl(...args)
}))

import { AppMarketView } from './index'

const builtinApp = {
  id: 'ai.stocksense.watchlist',
  name: '自选股盯盘看板',
  description: 'Profile 隔离的 A 股自选股盯盘应用',
  version: '1.0.0',
  enabled: true,
  source_editable: false,
  lineage: 'builtin',
  installed_at: '2026-07-24T12:00:00+08:00',
  updated_at: '2026-07-24T12:00:00+08:00',
  trust_state: 'builtin',
  status: 'ready',
  requested_permissions: {
    agent: true,
    mcp_servers: ['mx-ds-mcp'],
    storage: { mode: 'persistent', quota_mb: 10 }
  },
  granted_permissions: {
    agent: true,
    mcp_servers: ['mx-ds-mcp'],
    storage: { mode: 'persistent', quota_mb: 10 }
  }
}

const installedApps = [builtinApp]

describe('AppMarketView', () => {
  const api = vi.fn()
  const openLaunchUrl = vi.fn()
  const selectAndAnalyzePackage = vi.fn()
  const exportPackage = vi.fn()

  beforeEach(() => {
    api.mockReset()
    openLaunchUrl.mockReset()
    selectAndAnalyzePackage.mockReset()
    exportPackage.mockReset()
    launchHermesApp.mockReset()
    listHubAppCategories.mockReset()
    listHubApps.mockReset()
    startHubAppInstall.mockReset()
    getHubAppOperation.mockReset()
    cancelHubAppOperation.mockReset()
    getHubAppPreviewDataUrl.mockReset()
    api.mockResolvedValue({ items: installedApps, next_cursor: null })
    listHubAppCategories.mockResolvedValue({
      items: [{ id: 'finance', name: '金融' }],
      cache_state: 'fresh'
    })
    listHubApps.mockResolvedValue({ items: [], installed: {}, cache_state: 'fresh' })
    getHubAppPreviewDataUrl.mockResolvedValue('data:image/webp;base64,cHJldmlldw==')
    window.hermesDesktop = {
      api,
      apps: { exportPackage, openLaunchUrl, selectAndAnalyzePackage }
    } as unknown as Window['hermesDesktop']
  })

  afterEach(cleanup)

  it('lists installed apps, launches one, and starts the builder template', async () => {
    const onCreateApp = vi.fn()
    const onEditApp = vi.fn()
    launchHermesApp.mockResolvedValue({
      launch_id: 'launch-1',
      url: 'http://127.0.0.1:49182/launch/code',
      expires_at: '2026-07-13T10:00:30+00:00'
    })
    openLaunchUrl.mockResolvedValue(true)
    render(<AppMarketView onCreateApp={onCreateApp} onEditApp={onEditApp} />)

    expect(await screen.findByText('自选股盯盘看板')).toBeTruthy()
    const appCardClassName = screen.getByText('自选股盯盘看板').closest('article')?.className

    expect(appCardClassName).toContain('bg-(--ui-card-surface-background)')
    fireEvent.click(screen.getByRole('button', { name: '创建应用' }))
    fireEvent.click(screen.getByRole('button', { name: '打开 自选股盯盘看板' }))

    expect(onCreateApp).toHaveBeenCalledOnce()
    await waitFor(() => expect(openLaunchUrl).toHaveBeenCalledWith('http://127.0.0.1:49182/launch/code'))

    const manageButton = screen.getByRole('button', { name: '管理 自选股盯盘看板' })
    fireEvent.pointerDown(manageButton, { button: 0, ctrlKey: false })
    const exportItem = await screen.findByText('导出 .happ')
    expect(exportItem.getAttribute('data-disabled')).not.toBeNull()
    fireEvent.click(await screen.findByRole('menuitem', { name: '修改' }))
    expect(onEditApp).toHaveBeenCalledWith(expect.objectContaining({ id: 'ai.stocksense.watchlist' }))
  })

  it('shows the immutable import plan before confirming installation', async () => {
    selectAndAnalyzePackage.mockResolvedValue({
      import_id: '0da4f333-05ba-4b32-aa5e-e60a3ecf1268',
      expires_at: '2026-07-13T10:15:00+00:00',
      app: {
        id: 'local.stockagent.research',
        name: '研究助手',
        version: '1.0.0',
        description: '研究应用'
      },
      source_included: true,
      signature_state: 'unsigned',
      requested_permissions: {
        agent: true,
        mcp_servers: ['mx-ds-mcp'],
        storage: { mode: 'persistent', quota_mb: 10 }
      },
      conflict: { kind: 'none', existing_version: null, incoming_version: '1.0.0' },
      warnings: [],
      package_sha256: 'a'.repeat(64)
    })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    fireEvent.click(screen.getByRole('button', { name: '导入' }))
    expect(await screen.findByText('确认导入应用')).toBeTruthy()
    expect(screen.getByText('研究助手')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认安装' }))

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        expect.objectContaining({
          path: '/api/apps/imports/0da4f333-05ba-4b32-aa5e-e60a3ecf1268/confirm',
          method: 'POST'
        })
      )
    )
  })

  it('marks a newer hub package as an update and starts the existing secure install flow', async () => {
    listHubApps.mockResolvedValue({
      items: [
        {
          id: 'ai.stocksense.watchlist',
          name: '自选股盯盘看板',
          summary: 'A 股自选股盯盘应用',
          version: '1.1.0',
          category: 'finance',
          preview_image_url: 'https://www.stocksense.work/previews/watchlist.webp'
        }
      ],
      installed: {
        'ai.stocksense.watchlist': { version: '1.0.0', state: 'update_available' }
      },
      cache_state: 'fresh'
    })
    startHubAppInstall.mockResolvedValue({
      operation_id: 'hub-operation-1',
      hub_app_id: 'ai.stocksense.watchlist',
      version: '1.1.0',
      state: 'queued',
      progress: 5,
      created_at: '2026-07-24T12:00:00+08:00',
      updated_at: '2026-07-24T12:00:00+08:00'
    })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    fireEvent.click(screen.getByRole('button', { name: '应用中心' }))

    expect(await screen.findByRole('button', { name: '更新' })).toBeTruthy()
    expect((await screen.findByRole('img', { name: '自选股盯盘看板 预览图' })).getAttribute('src')).toBe(
      'data:image/webp;base64,cHJldmlldw=='
    )
    expect(getHubAppPreviewDataUrl).toHaveBeenCalledWith('ai.stocksense.watchlist', '1.1.0')
    fireEvent.click(screen.getByRole('button', { name: '更新' }))

    await waitFor(() => expect(startHubAppInstall).toHaveBeenCalledWith('ai.stocksense.watchlist', '1.1.0'))
    expect(await screen.findByText('正在准备应用安装')).toBeTruthy()
    expect(screen.getByLabelText('安装进度')).toBeTruthy()
  })

  it('opens a scrollable full-size preview when a hub preview image is clicked', async () => {
    listHubApps.mockResolvedValue({
      items: [
        {
          id: 'ai.stocksense.watchlist',
          name: '自选股盯盘看板',
          summary: 'A 股自选股盯盘应用',
          version: '1.1.0',
          category: 'finance',
          preview_image_url: 'https://www.stocksense.work/previews/watchlist.webp'
        }
      ],
      installed: {},
      cache_state: 'fresh'
    })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    fireEvent.click(screen.getByRole('button', { name: '应用中心' }))
    fireEvent.click(await screen.findByRole('button', { name: '查看 自选股盯盘看板 预览图' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('自选股盯盘看板 · 应用预览')).toBeTruthy()
    expect(within(dialog).getByText('滚动查看完整预览图')).toBeTruthy()
    expect(within(dialog).getByRole('img', { name: '自选股盯盘看板 完整预览图' }).getAttribute('src')).toBe(
      'data:image/webp;base64,cHJldmlldw=='
    )
  })

  it('loads hub categories and passes the selected category code to the hub list', async () => {
    listHubApps.mockResolvedValue({ items: [], installed: {}, cache_state: 'fresh' })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    expect(await screen.findByRole('tab', { name: '金融' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '应用中心' }))
    fireEvent.click(screen.getByRole('tab', { name: '金融' }))

    await waitFor(() => expect(listHubApps).toHaveBeenLastCalledWith({ category: 'finance', query: '' }))
  })

  it('filters installed apps with their persisted category without rendering a preview image', async () => {
    api.mockResolvedValue({
      items: [
        { ...builtinApp, category: 'finance' },
        {
          ...builtinApp,
          id: 'local.stockagent.research',
          name: '研究助手',
          category: 'research'
        }
      ],
      next_cursor: null
    })
    listHubAppCategories.mockResolvedValue({
      items: [
        { id: 'finance', name: '金融' },
        { id: 'research', name: '研究' }
      ],
      cache_state: 'fresh'
    })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    fireEvent.click(await screen.findByRole('tab', { name: '金融' }))

    expect(screen.getByText('自选股盯盘看板')).toBeTruthy()
    expect(screen.queryByText('研究助手')).toBeNull()
    expect(screen.queryByRole('img', { name: /预览图/ })).toBeNull()
  })

  it('shows external-install guidance without starting a package operation', async () => {
    listHubApps.mockResolvedValue({
      items: [
        {
          id: 'ai.stocksense.external-terminal',
          name: '机构终端',
          summary: '由运维统一部署的外部系统',
          version: '1.0.0',
          category: '工具',
          delivery: { type: 'external', message: '外部安装，请联系运维人员。' }
        }
      ],
      installed: {},
      cache_state: 'fresh'
    })
    render(<AppMarketView onCreateApp={vi.fn()} onEditApp={vi.fn()} />)

    await screen.findByText('自选股盯盘看板')
    fireEvent.click(screen.getByRole('button', { name: '应用中心' }))
    fireEvent.click(await screen.findByRole('button', { name: '外部安装' }))

    expect(await screen.findByText('外部安装，请联系运维人员。')).toBeTruthy()
    expect(startHubAppInstall).not.toHaveBeenCalled()
  })
})
