import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { AppThemeContext } from './appTheme'
import type { AppThemeContextValue, ResolvedTheme, ThemePreference } from './appTheme'

const THEME_PREFERENCE_KEY = 'yibanpaiban-theme-preference'
const TOUCH_INTERACTION_QUERY = '(max-width: 991px), (pointer: coarse)'

function hasTouchInteraction(): boolean {
  return window.matchMedia(TOUCH_INTERACTION_QUERY).matches
}

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getStoredPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_PREFERENCE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Storage can be unavailable in a restricted browser context.
  }
  return 'system'
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(getStoredPreference)
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme)
  const [touchInteraction, setTouchInteraction] = useState(hasTouchInteraction)

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => setSystemTheme(media.matches ? 'dark' : 'light')
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    const media = window.matchMedia(TOUCH_INTERACTION_QUERY)
    const handleChange = () => setTouchInteraction(media.matches)
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [])

  const resolvedTheme = preference === 'system' ? systemTheme : preference

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme
    document.documentElement.style.colorScheme = resolvedTheme
  }, [resolvedTheme])

  const setPreference = useCallback((nextPreference: ThemePreference) => {
    setPreferenceState(nextPreference)
    try {
      window.localStorage.setItem(THEME_PREFERENCE_KEY, nextPreference)
    } catch {
      // Keep the active preference for this session when persistence is unavailable.
    }
  }, [])

  const value = useMemo<AppThemeContextValue>(
    () => ({ preference, resolvedTheme, setPreference }),
    [preference, resolvedTheme, setPreference],
  )

  return (
    <AppThemeContext.Provider value={value}>
      <ConfigProvider
        locale={zhCN}
        virtual={!touchInteraction}
        theme={{
          algorithm: resolvedTheme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: '#1677ff',
            borderRadius: 6,
            ...(resolvedTheme === 'dark'
              ? {
                  colorBgBase: '#141414',
                  colorBgLayout: '#141414',
                  colorBgContainer: '#1c1c1c',
                  colorBgElevated: '#242424',
                  colorBgSpotlight: '#2a2a2a',
                  colorFillSecondary: '#222222',
                  colorBorder: '#383838',
                  colorBorderSecondary: '#2c2c2c',
                  colorText: '#f1f1f1',
                  colorTextSecondary: '#b8b8b8',
                  colorTextTertiary: '#8a8a8a',
                  boxShadowSecondary: '0 6px 16px rgba(0, 0, 0, 0.42)',
                }
              : {}),
          },
        }}
      >
        {children}
      </ConfigProvider>
    </AppThemeContext.Provider>
  )
}
