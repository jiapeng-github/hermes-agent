import { createRoot } from 'react-dom/client'

import type { HermesApiRequest } from '@/global'
import { I18nProvider } from '@/i18n'
import { ThemeProvider } from '@/themes/context'

import { AppMarketView } from './index'

const PREVIEW_APPS = [
  {
    id: 'ai.stocksense.watchlist',
    name: '自选股盯盘看板',
    description: '可导出的 A 股自选股盯盘看板，提供行情、板块脉搏、资金主线和个股详情。',
    version: '0.0.1',
    enabled: true,
    source_editable: true,
    lineage: 'user',
    installed_at: '2026-07-25T00:00:00+08:00',
    updated_at: '2026-07-25T00:00:00+08:00',
    trust_state: 'local_untrusted',
    status: 'ready',
    requested_permissions: {
      agent: false,
      mcp_servers: ['mx-ds-mcp'],
      storage: { mode: 'persistent', quota_mb: 5 }
    },
    granted_permissions: {
      agent: false,
      mcp_servers: [],
      storage: { mode: 'none', quota_mb: 0 }
    }
  },
  {
    id: 'local.stockagent.research-assistant',
    name: '研究助手',
    description: '汇总行业线索、公司公告和研报摘要，生成可追溯的研究工作台。',
    version: '0.4.0',
    enabled: true,
    source_editable: true,
    lineage: 'user',
    installed_at: '2026-07-25T00:00:00+08:00',
    updated_at: '2026-07-25T00:00:00+08:00',
    trust_state: 'local_untrusted',
    status: 'ready',
    requested_permissions: {
      agent: true,
      mcp_servers: ['mx-ds-mcp'],
      storage: { mode: 'persistent', quota_mb: 20 }
    },
    granted_permissions: {
      agent: true,
      mcp_servers: ['mx-ds-mcp'],
      storage: { mode: 'persistent', quota_mb: 20 }
    }
  },
  {
    id: 'local.stockagent.earnings-compare',
    name: '财报对比',
    description: '跨公司对比营收、利润、现金流和估值指标。',
    version: '0.2.0',
    enabled: false,
    source_editable: true,
    lineage: 'user',
    installed_at: '2026-07-25T00:00:00+08:00',
    updated_at: '2026-07-25T00:00:00+08:00',
    trust_state: 'local_untrusted',
    status: 'disabled',
    requested_permissions: {
      agent: false,
      mcp_servers: ['mx-ds-mcp'],
      storage: { mode: 'session', quota_mb: 5 }
    },
    granted_permissions: {
      agent: false,
      mcp_servers: [],
      storage: { mode: 'none', quota_mb: 0 }
    }
  }
]

export function mountAppMarketPreview() {
  const dark = new URLSearchParams(window.location.search).get('theme') === 'dark'
  document.documentElement.classList.toggle('dark', dark)
  window.hermesDesktop = {
    api: async (request: HermesApiRequest) => {
      if (request.path === '/api/apps') {
        return { items: PREVIEW_APPS, next_cursor: null }
      }

      return {}
    },
    apps: {
      openLaunchUrl: async () => true,
      selectAndAnalyzePackage: async () => null,
      exportPackage: async () => ({ canceled: true })
    }
  } as unknown as Window['hermesDesktop']

  createRoot(document.getElementById('root')!).render(
    <I18nProvider>
      <ThemeProvider>
        <AppMarketView onCreateApp={() => undefined} onEditApp={() => undefined} />
      </ThemeProvider>
    </I18nProvider>
  )
}
