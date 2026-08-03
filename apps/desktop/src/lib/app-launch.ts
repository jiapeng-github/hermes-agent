import { launchHermesApp } from '@/hermes'

export const WATCHLIST_APP_ID = 'ai.stocksense.watchlist'

export async function launchAppInBrowser(appId: string, profile?: string | null): Promise<void> {
  const launch = profile ? await launchHermesApp(appId, profile) : await launchHermesApp(appId)
  await window.hermesDesktop.apps.openLaunchUrl(launch.url)
}

export function launchAppWithFallback(appId: string, fallback: () => void): void {
  void launchAppInBrowser(appId).catch(fallback)
}
