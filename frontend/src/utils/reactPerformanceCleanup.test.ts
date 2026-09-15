import { PerformanceObserver } from 'node:perf_hooks'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { startReactPerformanceCleanup } from './reactPerformanceCleanup'

const reactMeasure = '\u200bStreamingReasoning'
const appMeasure = 'app-stream-latency'
let stop: (() => void) | undefined
afterEach(() => {
  stop?.()
  stop = undefined
  performance.clearMeasures(reactMeasure)
  performance.clearMeasures(appMeasure)
  vi.unstubAllGlobals()
})

describe('React development performance buffer', () => {
  it('releases React prop snapshots while preserving application timings', async () => {
    vi.stubGlobal('PerformanceObserver', PerformanceObserver)
    const detail = { devtools: { track: 'Components ⚛', properties: [['content', '长段思考'.repeat(10_000)]] } }
    stop = startReactPerformanceCleanup()
    performance.measure(appMeasure, { start: 0, detail: { requestId: 'local-test' } })
    for (let delta = 0; delta < 20; delta += 1) {
      performance.measure(reactMeasure, { start: 0, detail })
    }
    await vi.waitFor(() => expect(performance.getEntriesByName(reactMeasure)).toHaveLength(0))
    expect(performance.getEntriesByName(appMeasure)).toHaveLength(1)
    // Disposal flushes pending records and stops future observation for HMR.
    performance.measure(reactMeasure, { start: 0, detail })
    stop()
    expect(performance.getEntriesByName(reactMeasure)).toHaveLength(0)
    performance.measure(reactMeasure, { start: 0, detail })
    await new Promise<void>((resolve) => setImmediate(resolve))
    expect(performance.getEntriesByName(reactMeasure)).toHaveLength(1)
  })

  it('does not clear application records with similar names or unsupported environments', async () => {
    vi.stubGlobal('PerformanceObserver', PerformanceObserver)
    stop = startReactPerformanceCleanup()
    performance.measure(reactMeasure, { start: 0, detail: { devtools: { track: 'App' } } })
    await new Promise<void>((resolve) => setImmediate(resolve))
    expect(performance.getEntriesByName(reactMeasure)).toHaveLength(1)
    stop()
    vi.stubGlobal('PerformanceObserver', undefined)
    expect(() => startReactPerformanceCleanup()()).not.toThrow()
  })
})
