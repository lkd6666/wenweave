import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { brandingApi } from '../api/branding'
import { AppBrandingContext, DEFAULT_APP_BRANDING, brandingAssetUrl } from './appBranding'
import type { AppBranding } from '../types'

export function AppBrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<AppBranding>(DEFAULT_APP_BRANDING)

  const refreshBranding = useCallback(async () => {
    try {
      setBranding(await brandingApi.get())
    } catch {
      setBranding(DEFAULT_APP_BRANDING)
    }
  }, [])

  useEffect(() => {
    void refreshBranding()
  }, [refreshBranding])

  useEffect(() => {
    document.title = branding.system_name
    let favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (!favicon) {
      favicon = document.createElement('link')
      favicon.rel = 'icon'
      document.head.append(favicon)
    }
    const faviconUrl = brandingAssetUrl(branding.favicon_url, branding.updated_at)
    favicon.href = faviconUrl ?? '/favicon.svg'
    favicon.type = faviconUrl ? branding.favicon_content_type : 'image/svg+xml'
  }, [branding])

  const value = useMemo(() => ({ branding, refreshBranding }), [branding, refreshBranding])

  return <AppBrandingContext.Provider value={value}>{children}</AppBrandingContext.Provider>
}
