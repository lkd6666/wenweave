import type { ThinkingEffort, ThinkingMode } from '../api/chat'
import type { AIModelItem } from '../types'

const STORAGE_PREFIX = 'yibanpaiban-thinking-preference:v1'
const THINKING_MODES: readonly ThinkingMode[] = ['auto', 'enabled', 'disabled']
const THINKING_EFFORTS: readonly ThinkingEffort[] = ['auto', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']

export interface ThinkingPreference {
  mode: ThinkingMode
  effort: ThinkingEffort
}

export type ThinkingModel = Pick<AIModelItem, 'id' | 'supports_disabled_thinking' | 'thinking_config'>

function storageKey(userId: number | null | undefined, modelId: number): string | null {
  return userId && userId > 0 && modelId > 0 ? `${STORAGE_PREFIX}:${userId}:${modelId}` : null
}

function isThinkingPreference(value: unknown): value is ThinkingPreference {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ThinkingPreference>
  return THINKING_MODES.includes(item.mode as ThinkingMode)
    && THINKING_EFFORTS.includes(item.effort as ThinkingEffort)
}

function configuredEfforts(model: ThinkingModel | null | undefined): string[] {
  const efforts = model?.thinking_config?.efforts
  return efforts && typeof efforts === 'object' && !Array.isArray(efforts) ? Object.keys(efforts) : []
}

export function readThinkingPreference(
  userId: number | null | undefined,
  modelId: number,
): ThinkingPreference | null {
  const key = storageKey(userId, modelId)
  if (!key) return null
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isThinkingPreference(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function saveThinkingPreference(
  userId: number | null | undefined,
  modelId: number,
  preference: ThinkingPreference,
): void {
  const key = storageKey(userId, modelId)
  if (!key) return
  try {
    window.localStorage.setItem(key, JSON.stringify(preference))
  } catch {
    // The current page continues to use the selected preference.
  }
}

export function resolveThinkingPreference(
  userId: number | null | undefined,
  model: ThinkingModel | null | undefined,
  temporarilyUnsupported = false,
): ThinkingPreference {
  const fallback: ThinkingPreference = { mode: 'enabled', effort: 'auto' }
  if (!model) return fallback
  const stored = readThinkingPreference(userId, model.id)
  if (!stored) return fallback
  const efforts = configuredEfforts(model)
  if (stored.effort !== 'auto' && !efforts.includes(stored.effort)) return fallback
  if (stored.mode === 'disabled' && (model.supports_disabled_thinking === false || temporarilyUnsupported)) {
    return fallback
  }
  return stored
}
