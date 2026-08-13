import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { ThinkingModel } from './thinkingPreference'
import { readThinkingPreference, resolveThinkingPreference, saveThinkingPreference } from './thinkingPreference'

const model = {
  id: 7,
  supports_disabled_thinking: true,
  thinking_config: { efforts: { low: {}, high: {} } },
} as ThinkingModel

describe('thinking preference storage', () => {
  const originalWindow = globalThis.window
  const values = new Map<string, string>()

  beforeEach(() => {
    values.clear()
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          getItem: (key: string) => values.get(key) ?? null,
          setItem: (key: string, value: string) => values.set(key, value),
        },
      },
    })
  })

  afterEach(() => {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: originalWindow })
  })

  it('persists a preference separately for each user and model', () => {
    saveThinkingPreference(3, model.id, { mode: 'enabled', effort: 'high' })

    expect(readThinkingPreference(3, model.id)).toEqual({ mode: 'enabled', effort: 'high' })
    expect(readThinkingPreference(4, model.id)).toBeNull()
    expect(readThinkingPreference(3, 8)).toBeNull()
  })

  it('falls back when a saved preference is no longer supported', () => {
    saveThinkingPreference(3, model.id, { mode: 'disabled', effort: 'low' })

    expect(resolveThinkingPreference(3, { ...model, supports_disabled_thinking: false })).toEqual({ mode: 'enabled', effort: 'auto' })
    expect(resolveThinkingPreference(3, model, true)).toEqual({ mode: 'enabled', effort: 'auto' })
  })
})
