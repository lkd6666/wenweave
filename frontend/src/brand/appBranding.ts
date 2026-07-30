import { createContext, useContext } from 'react'
import type { AppBranding } from '../types'

export interface AppBrandingContextValue {
  branding: AppBranding
  refreshBranding: () => Promise<void>
}

export const DEFAULT_APP_BRANDING: AppBranding = {
  system_name: '微信公众号 AI 排版系统',
  logo_url: null,
  logo_content_type: '',
  favicon_url: null,
  favicon_content_type: '',
  updated_at: null,
}

export const AppBrandingContext = createContext<AppBrandingContextValue | null>(null)

export function brandingAssetUrl(url: string | null, updatedAt: string | null): string | null {
  if (!url) return null
  return `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(updatedAt ?? 'default')}`
}

export function useAppBranding(): AppBrandingContextValue {
  const context = useContext(AppBrandingContext)
  if (!context) throw new Error('useAppBranding must be used within AppBrandingProvider')
  return context
}
