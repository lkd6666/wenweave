import { createContext, useContext } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export interface AppThemeContextValue {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

export const AppThemeContext = createContext<AppThemeContextValue | null>(null)

export function useAppTheme(): AppThemeContextValue {
  const context = useContext(AppThemeContext)
  if (!context) throw new Error('useAppTheme must be used within AppThemeProvider')
  return context
}
