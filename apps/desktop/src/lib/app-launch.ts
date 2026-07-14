import { launchHermesApp } from '@/hermes'

export const WATCHLIST_APP_ID = 'ai.hermes.watchlist'

export async function launchAppInBrowser(appId: string): Promise<void> {
  const launch = await launchHermesApp(appId)
  await window.hermesDesktop.apps.openLaunchUrl(launch.url)
}

export function launchAppWithFallback(appId: string, fallback: () => void): void {
  void launchAppInBrowser(appId).catch(fallback)
}
