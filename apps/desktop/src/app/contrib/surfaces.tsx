/**
 * Wiring surfaces — each pane is its own memoized component. Every surface
 * reads the reactive state it renders from at the leaf (its own atom
 * subscriptions) and reaches the controller's callbacks through the stable
 * `actions` bag, so a state change scoped to one surface (or a bare
 * wiring-controller tick) never re-renders another. This is what keeps the
 * layout tree's zones independently rendered — the whole point of the shell.
 */

import { useStore } from '@nanostores/react'
import { type ComponentProps, lazy, memo, type ReactNode, Suspense, useMemo } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router'

import { ContribBoundary, ContribRender } from '@/contrib/react/boundary'
import { useContributions } from '@/contrib/react/use-contributions'
import { $activeConnectionId } from '@/store/connections'
import { $gateway } from '@/store/gateway'
import { $activeGatewayProfile } from '@/store/profile'
import { $freshDraftReady, $gatewayState } from '@/store/session'

import { ChatView } from '../chat'
import { ChatSidebar } from '../chat/sidebar'
import { TerminalPaneChrome } from '../right-sidebar/terminal/chrome'
import { contributedRoutes, NEW_CHAT_ROUTE, ROUTES_AREA, sessionRoute, SETTINGS_ROUTE } from '../routes'
import { useStatusSnapshot } from '../shell/hooks/use-status-snapshot'
import { useStatusbarItems } from '../shell/hooks/use-statusbar-items'
import { ModelMenuPanel } from '../shell/model-menu-panel'
import { StatusbarControls } from '../shell/statusbar-controls'

import { latestChatActions, latestSidebarActions } from './latest-actions'
import { setStatusbarItemGroup, useStatusbarContributions } from './panes'
import type { SidebarActions, WiringActions } from './types'

// Same lazy-view split as DesktopController — pages load on demand. The
// full-page views the workspace route table mounts live here; overlay views
// (agents/settings/…) are the controller's and stay in wiring.tsx.
const ArtifactsView = lazy(async () => ({ default: (await import('../artifacts')).ArtifactsView }))
const AppMarketView = lazy(async () => ({ default: (await import('../app-market')).AppMarketView }))
const CronView = lazy(async () => ({ default: (await import('../cron')).CronView }))
const SkillsView = lazy(async () => ({ default: (await import('../skills')).SkillsView }))

export function LegacySessionRedirect() {
  const { sessionId } = useParams()

  return <Navigate replace to={sessionId ? sessionRoute(sessionId) : NEW_CHAT_ROUTE} />
}

export const SidebarSurface = memo(function SidebarSurface({
  actions,
  currentView
}: {
  actions: SidebarActions
  currentView: ComponentProps<typeof ChatSidebar>['currentView']
}) {
  const latestActions = useMemo(() => latestSidebarActions(actions), [actions])

  return <ChatSidebar currentView={currentView} {...latestActions} />
})

export const TerminalSurface = memo(function TerminalSurface() {
  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-(--ui-terminal-surface-background)">
      <TerminalPaneChrome />
    </div>
  )
})

/** Owns the statusbar's own data hooks (status snapshot poll, contributed
 *  items) so its 15s refresh — and any statusbar-only churn — re-renders the
 *  bar alone, never the chat/sidebar/terminal. */
export const StatusbarSurface = memo(function StatusbarSurface({
  actions,
  agentsOpen,
  chatOpen,
  commandCenterOpen
}: {
  actions: WiringActions
  agentsOpen: boolean
  chatOpen: boolean
  commandCenterOpen: boolean
}) {
  const activeConnectionId = useStore($activeConnectionId)
  const activeGatewayProfile = useStore($activeGatewayProfile)
  const gatewayState = useStore($gatewayState)
  const freshDraftReady = useStore($freshDraftReady)
  const gatewayScope = `${activeConnectionId ?? ''}\0${activeGatewayProfile}`
  const { inferenceStatus, statusSnapshot } = useStatusSnapshot(gatewayState, actions.requestGateway, gatewayScope)
  const extraLeftItems = useStatusbarContributions('left')
  const extraRightItems = useStatusbarContributions('right')

  const { leftStatusbarItems, statusbarItems } = useStatusbarItems({
    agentsOpen,
    chatOpen,
    commandCenterOpen,
    extraLeftItems,
    extraRightItems,
    freshDraftReady,
    gatewayState,
    inferenceStatus,
    openAgents: actions.openAgents,
    openCommandCenterSection: actions.openCommandCenterSection,
    requestGateway: actions.requestGateway,
    statusSnapshot,
    toggleCommandCenter: actions.toggleCommandCenter
  })

  return <StatusbarControls items={statusbarItems} leftItems={leftStatusbarItems} />
})

/** The workspace pane: the real route table (chat + full-page views + plugin
 *  routes). Subscribes to the gateway instance/state and ROUTES_AREA itself;
 *  the voice cap arrives as a prop. ChatView subscribes to its own session
 *  atoms, so streaming never round-trips through the controller. */
export const ChatRoutesSurface = memo(function ChatRoutesSurface({
  actions,
  maxVoiceRecordingSeconds
}: {
  actions: WiringActions
  maxVoiceRecordingSeconds?: number
}) {
  const activeConnectionId = useStore($activeConnectionId)
  const activeGatewayProfile = useStore($activeGatewayProfile)
  const gateway = useStore($gateway)
  const gatewayState = useStore($gatewayState)
  useContributions(ROUTES_AREA)
  const routeContributions = contributedRoutes()

  const modelMenuContent = useMemo(
    () =>
      gatewayState === 'open' ? (
        <ModelMenuPanel
          gateway={gateway || undefined}
          onSelectModel={actions.selectModel}
          ownerConnectionId={activeConnectionId || undefined}
          profile={activeGatewayProfile}
          requestGateway={actions.requestGateway}
        />
      ) : null,
    [actions, activeConnectionId, activeGatewayProfile, gateway, gatewayState]
  )

  const chatActions = useMemo(() => latestChatActions(actions), [actions])

  const chatView = (
    <ChatView
      gateway={gateway}
      maxVoiceRecordingSeconds={maxVoiceRecordingSeconds}
      modelMenuContent={modelMenuContent}
      modelOptionsOwnerConnectionId={activeConnectionId || undefined}
      modelOptionsProfile={activeGatewayProfile}
      requestModelOptionsForOwner={actions.requestGateway}
      {...chatActions}
    />
  )

  // FULL-PAGE views (not chat): a page is not a tab-able surface, so the zone's
  // tab strip stands down while one is showing. That is `paneChrome.headerVeto`
  // on the contribution, not a DOM marker — the `data-zone-no-header` attribute
  // that used to ride this wrapper gated a body double-click toggle that no
  // longer exists, and nothing has read it since.
  const page = (view: ReactNode) => (
    <div className="contents">
      <Suspense fallback={null}>{view}</Suspense>
    </div>
  )

  return (
    <Routes>
      <Route element={chatView} index />
      <Route element={chatView} path=":sessionId" />
      <Route element={page(<SkillsView setStatusbarItemGroup={setStatusbarItemGroup} />)} path="skills" />
      <Route
        element={page(
          <AppMarketView
            onCreateApp={() =>
              actions.openAppBuilder(
                '/app-builder\n\n我要创建一个 Web 应用。请使用应用创建流程与我协作，并先根据以下模板补齐需求：\n应用名称：\n目标用户：\n核心页面：\n所需数据与服务：\n主要交互：\n验收标准：'
              )
            }
            onEditApp={app => {
              const needsDerivedApp = app.trust_state === 'builtin' || !app.source_editable
              const task = needsDerivedApp
                ? `我要以应用「${app.name}」（${app.id}）为蓝本创建一份可编辑的派生应用。请不要修改原应用；先梳理可复用的页面与数据需求，再使用新的用户应用 ID 创建工作区。\n\n希望调整的功能：`
                : `我要修改应用「${app.name}」（${app.id}）。请先检查当前版本和可编辑源代码，再按应用修改流程创建 checkout 工作区。\n\n本次修改目标：`

              actions.openAppBuilder(`/app-builder\n\n${task}`)
            }}
          />
        )}
        path="apps"
      />
      <Route element={<Navigate replace to={`${SETTINGS_ROUTE}?tab=messaging`} />} path="messaging" />
      <Route element={page(<ArtifactsView setStatusbarItemGroup={setStatusbarItemGroup} />)} path="artifacts" />
      <Route
        element={page(
          <CronView
            onClose={() => actions.onNewSessionInWorkspace(null)}
            onOpenSession={actions.onResumeSession}
            presentation="page"
            setStatusbarItemGroup={setStatusbarItemGroup}
          />
        )}
        path="cron"
      />
      <Route element={null} path="agents" />
      <Route element={null} path="command-center" />
      <Route element={null} path="profiles" />
      <Route element={null} path="settings" />
      <Route element={null} path="starmap" />
      <Route element={null} path="webhooks" />
      {/* Registry-contributed pages (core features + plugins) render in the
          workspace pane like any built-in view — behind the same blast wall
          as every other contribution mount. */}
      {routeContributions.map(route => (
        <Route
          element={page(
            <ContribBoundary id={route.key}>
              <ContribRender render={route.render} />
            </ContribBoundary>
          )}
          key={route.key}
          path={route.path.slice(1)}
        />
      ))}
      <Route element={<Navigate replace to={NEW_CHAT_ROUTE} />} path="new" />
      <Route element={<LegacySessionRedirect />} path="sessions/:sessionId" />
      <Route element={<Navigate replace to={NEW_CHAT_ROUTE} />} path="*" />
    </Routes>
  )
})
