const REACT_COMPONENT_TRACK = 'Components ⚛'

/**
 * React 19.2 development builds put changed props in User Timing measures.
 * Streaming text then leaves a copy of every growing reply in Chromium's
 * native performance buffer, outside the reported JS heap. Release only React
 * component measures after delivery; browser Performance recordings still
 * receive the original events, and application measures remain available.
 */
export function startReactPerformanceCleanup(): () => void {
  if (typeof PerformanceObserver === 'undefined'
    || !PerformanceObserver.supportedEntryTypes.includes('measure')) return () => undefined

  const clearReactMeasures = (entries: PerformanceEntry[]) => {
    const names = new Set<string>()
    for (const entry of entries) {
      // React prefixes component names with a zero-width space. Checking it
      // first avoids deserializing unrelated performance payloads.
      if (!entry.name.startsWith('\u200b') || names.has(entry.name)) continue
      const detail = (entry as PerformanceMeasure).detail as { devtools?: { track?: string } } | null
      if (detail?.devtools?.track === REACT_COMPONENT_TRACK) names.add(entry.name)
    }
    names.forEach((name) => performance.clearMeasures(name))
  }
  const observer = new PerformanceObserver((list) => clearReactMeasures(list.getEntries()))
  observer.observe({ type: 'measure', buffered: true })
  return () => {
    clearReactMeasures(observer.takeRecords())
    observer.disconnect()
  }
}
