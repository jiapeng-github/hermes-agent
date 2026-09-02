import type {
  AppActivitySessionResponse,
  HermesAppLaunch,
  HubAppCategoriesResponse,
  HubAppOperation,
  HubAppsResponse
} from '@/types/hermes'

import { hermesApi, profileScoped } from './client'

const HUB_REQUEST_TIMEOUT_MS = 45_000

export function listHubApps({
  category,
  query = ''
}: { category?: string; query?: string } = {}): Promise<HubAppsResponse> {
  const params = new URLSearchParams({ q: query })
  if (category) params.set('category', category)

  return hermesApi<HubAppsResponse>({
    ...profileScoped(),
    path: `/api/apps/hub?${params.toString()}`,
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function listHubAppCategories(): Promise<HubAppCategoriesResponse> {
  return hermesApi<HubAppCategoriesResponse>({
    ...profileScoped(),
    path: '/api/apps/hub/categories',
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

// Packaged Electron renders from file://, so Hub preview images travel through
// the narrow main-process media bridge rather than a renderer-relative URL.
export function getHubAppPreviewDataUrl(appId: string, version: string): Promise<string> {
  return window.hermesDesktop.apps.getHubPreviewDataUrl(appId, version, profileScoped().profile)
}

export function startHubAppInstall(appId: string, version?: string): Promise<HubAppOperation> {
  return hermesApi<HubAppOperation>({
    ...profileScoped(),
    path: `/api/apps/hub/${encodeURIComponent(appId)}/operations`,
    method: 'POST',
    body: version ? { version } : {},
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function getHubAppOperation(operationId: string): Promise<HubAppOperation> {
  return hermesApi<HubAppOperation>({
    ...profileScoped(),
    path: `/api/apps/hub/operations/${encodeURIComponent(operationId)}`,
    timeoutMs: HUB_REQUEST_TIMEOUT_MS
  })
}

export function cancelHubAppOperation(operationId: string): Promise<void> {
  return hermesApi<void>({
    ...profileScoped(),
    path: `/api/apps/hub/operations/${encodeURIComponent(operationId)}`,
    method: 'DELETE'
  })
}

export function launchHermesApp(appId: string, profile?: null | string): Promise<HermesAppLaunch> {
  return hermesApi<HermesAppLaunch>({
    ...(profile ? { profile } : profileScoped()),
    path: `/api/apps/${encodeURIComponent(appId)}/launch`,
    method: 'POST',
    body: {},
    timeoutMs: 15_000
  })
}

export function getAppActivitySession(sessionId: string, profile?: null | string): Promise<AppActivitySessionResponse> {
  return hermesApi<AppActivitySessionResponse>({
    ...(profile ? { profile } : profileScoped()),
    path: `/api/app-activity/sessions/${encodeURIComponent(sessionId)}`,
    timeoutMs: 15_000
  })
}

export function launchAppActivityArtifact(artifactId: string, profile?: null | string): Promise<HermesAppLaunch> {
  return hermesApi<HermesAppLaunch>({
    ...(profile ? { profile } : profileScoped()),
    path: `/api/app-activity/artifacts/${encodeURIComponent(artifactId)}/launch`,
    method: 'POST',
    body: {},
    timeoutMs: 15_000
  })
}
