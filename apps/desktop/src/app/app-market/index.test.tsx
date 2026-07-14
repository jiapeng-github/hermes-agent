// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const launchHermesApp = vi.fn()

vi.mock('@/hermes', () => ({
  launchHermesApp: (...args: unknown[]) => launchHermesApp(...args)
}))

import { AppMarketView } from './index'

const builtinApp = {
  id: 'ai.hermes.watchlist',
  name: '自选股盯盘看板',
  description: 'Profile 隔离的 A 股自选股盯盘应用',
  version: '1.0.1',
  enabled: true,
  source_editable: false,
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

const builtinFinanceApps = [
  {
    ...builtinApp,
    id: 'ai.hermes.industry-monitor',
    name: '行业轮动于资金流向监控',
    description: 'A 股市场广度、热点题材、行业轮动、资金流与北向成交监控'
  },
  {
    ...builtinApp,
    id: 'ai.hermes.company-analysis',
    name: '上市公司基本面分析',
    description: '按公司名称或股票代码生成公司画像、财务趋势与研报分析'
  },
  builtinApp
]

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
    api.mockResolvedValue({ items: builtinFinanceApps, next_cursor: null })
    window.hermesDesktop = {
      api,
      apps: { exportPackage, openLaunchUrl, selectAndAnalyzePackage }
    } as unknown as Window['hermesDesktop']
  })

  afterEach(cleanup)

  it('lists all built-in finance apps, launches one, and starts the builder template', async () => {
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
    expect(screen.getByText('行业轮动于资金流向监控')).toBeTruthy()
    expect(screen.getByText('上市公司基本面分析')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '创建应用' }))
    fireEvent.click(screen.getByRole('button', { name: '打开 行业轮动于资金流向监控' }))

    expect(onCreateApp).toHaveBeenCalledOnce()
    await waitFor(() => expect(openLaunchUrl).toHaveBeenCalledWith('http://127.0.0.1:49182/launch/code'))

    const manageButton = screen.getByRole('button', { name: '管理 行业轮动于资金流向监控' })
    fireEvent.pointerDown(manageButton, { button: 0, ctrlKey: false })
    const exportItem = await screen.findByText('导出 .happ')
    expect(exportItem.getAttribute('data-disabled')).not.toBeNull()
    fireEvent.click(await screen.findByRole('menuitem', { name: '修改' }))
    expect(onEditApp).toHaveBeenCalledWith(expect.objectContaining({ id: 'ai.hermes.industry-monitor' }))
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
})
