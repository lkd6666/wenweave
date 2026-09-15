import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AppThemeProvider } from './theme/AppThemeProvider.tsx'
import { AppBrandingProvider } from './brand/AppBrandingProvider.tsx'
import { startReactPerformanceCleanup } from './utils/reactPerformanceCleanup'

if (import.meta.env.DEV) {
  const stopPerformanceCleanup = startReactPerformanceCleanup()
  import.meta.hot?.dispose(stopPerformanceCleanup)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppThemeProvider>
      <AppBrandingProvider>
        <App />
      </AppBrandingProvider>
    </AppThemeProvider>
  </StrictMode>,
)
