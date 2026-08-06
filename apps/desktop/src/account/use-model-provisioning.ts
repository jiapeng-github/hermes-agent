import type { ConnectionState } from '@hermes/shared'
import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import type { DesktopAccountModelCatalogItem } from '@/global'
import { getGlobalModelInfo, setModelAssignment } from '@/hermes'
import { queryClient } from '@/lib/query-client'
import { setCurrentModel, setCurrentModelSource, setCurrentProvider } from '@/store/session'

import { $accountState } from './store'

export function useStockSenseModelProvisioning(gatewayState: ConnectionState) {
  const accountState = useStore($accountState)
  const attemptedForProfile = useRef<string | null>(null)
  const status = accountState.status

  useEffect(() => {
    const profile = status?.profile

    if (gatewayState !== 'open' || status?.phase !== 'authenticated' || !profile) {
      return
    }

    if (attemptedForProfile.current === profile) {
      return
    }

    const defaultModel =
      status.modelCredential?.defaultModel ||
      status.modelCatalog.find((model: DesktopAccountModelCatalogItem) => model.default && model.enabled)?.id ||
      ''

    if (!status.modelCredential?.available || !defaultModel) {
      return
    }

    attemptedForProfile.current = profile
    let cancelled = false

    void getGlobalModelInfo()
      .then(async current => {
        // Existing explicit model choices always win. StockSense is only the
        // default for a profile that has never selected a provider/model.
        if (current.provider || current.model || cancelled) {
          return
        }

        const provider = 'custom:stocksense'
        await setModelAssignment({ model: defaultModel, provider, scope: 'main' })

        if (cancelled) {
          return
        }

        setCurrentProvider(provider)
        setCurrentModel(defaultModel)
        setCurrentModelSource('default')
        await queryClient.invalidateQueries({ queryKey: ['model-options'] })
      })
      .catch(() => {
        // A transient backend/model-catalog failure should not block the app.
        // The user can still choose the provider from the model picker.
        if (!cancelled) {
          attemptedForProfile.current = null
        }
      })

    return () => {
      cancelled = true
    }
  }, [gatewayState, status])
}
