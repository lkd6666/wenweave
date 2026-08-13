import { describe, expect, it } from 'vitest'
import type { AIModelItem, ChatContextStats } from '../types'
import { contextUsageValues, formatMessageTime, isRuntimeContextCompacting, modelUsageDetail, modelUsageLabel, normaliseAssistantTurnBlocks, supportsDisabledThinkingOption, visibleTemplateReferenceIndexes } from './ChatPanel'
import { questionDeadlineMs } from './UserQuestionPanel'

describe('contextUsageValues', () => {
  it('keeps the raw ledger separate from the next compiled model input', () => {
    const stats = {
      used_tokens: 26_800,
      compiled_input_tokens: 26_800,
      ledger_tokens: 185_000,
      runtime_projected_tokens: 0,
      conversation_tokens: 185_000,
    } as ChatContextStats

    expect(contextUsageValues(stats)).toEqual({
      compiledInputTokens: 26_800,
      ledgerTokens: 185_000,
      runtimeProjectionTokens: 0,
    })
  })

  it('shows the in-conversation compaction container only during runtime compaction', () => {
    const stats = {
      runtime_context_state: 'run_compacting',
    } as ChatContextStats

    expect(isRuntimeContextCompacting(stats, true)).toBe(true)
    expect(isRuntimeContextCompacting(stats, false)).toBe(false)
    expect(isRuntimeContextCompacting({ ...stats, runtime_context_state: 'in_run_compacted' }, true)).toBe(false)
    expect(isRuntimeContextCompacting({ state: 'preparing', requires_compaction: true } as ChatContextStats, true)).toBe(true)
  })
})

describe('formatMessageTime', () => {
  const now = new Date(2026, 6, 29, 12, 0)
  const messageTime = (day: number) => new Date(2026, 6, day, 9, 10).toISOString()

  it('uses relative labels for recent calendar days and a date for older messages', () => {
    expect(formatMessageTime(messageTime(29), now)).toBe('09:10')
    expect(formatMessageTime(messageTime(28), now)).toBe('昨天 09:10')
    expect(formatMessageTime(messageTime(26), now)).toBe('3天前 09:10')
    expect(formatMessageTime(messageTime(21), now)).toBe('2026-07-21 09:10')
  })

  it('returns an empty label for an invalid timestamp', () => {
    expect(formatMessageTime('invalid', now)).toBe('')
  })
})

describe('model usage display', () => {
  it('renders legacy records without cache or call-count fields', () => {
    const legacyUsage = {
      model_names: ['测试模型'],
      input_tokens: 120,
      output_tokens: 20,
      total_tokens: 140,
      usage_reported: true,
    }

    expect(modelUsageLabel(legacyUsage)).toBe('测试模型 · 本轮 0 次累计 140 tokens · 缓存命中 0%')
    expect(modelUsageDetail(legacyUsage)).toBe('测试模型：本轮累计 0 次模型调用；输入 120 tokens；缓存命中 0 tokens（0%）；输出 20 tokens；合计 140 tokens')
  })

  it('derives cache-hit rate when a legacy record omits it', () => {
    const usageWithoutRate = {
      model_names: ['测试模型'],
      input_tokens: 120,
      output_tokens: 20,
      total_tokens: 140,
      cache_read_tokens: 90,
      usage_reported: true,
    }

    expect(modelUsageLabel(usageWithoutRate)).toContain('缓存命中 75%')
  })
})

describe('normaliseAssistantTurnBlocks', () => {
  it('keeps legacy tool timeline blocks renderable when content is missing', () => {
    const blocks = [{
      id: 'block-legacy-tool',
      type: 'tool',
      state: 'done',
      tool: null,
    }] as unknown as Parameters<typeof normaliseAssistantTurnBlocks>[0]

    expect(normaliseAssistantTurnBlocks(blocks)).toEqual([{
      id: 'block-legacy-tool',
      type: 'tool',
      state: 'done',
      content: '',
      tool: null,
    }])
  })
})

describe('questionDeadlineMs', () => {
  it('treats legacy offset-free question deadlines as UTC', () => {
    expect(questionDeadlineMs('2026-07-29T16:00:00')).toBe(Date.parse('2026-07-29T16:00:00Z'))
    expect(questionDeadlineMs('2026-07-29T16:00:00+00:00')).toBe(Date.parse('2026-07-29T16:00:00Z'))
  })
})

describe('supportsDisabledThinkingOption', () => {
  const officialDeepSeek = {
    id: 9,
    model_name: 'deepseek-chat',
    supports_disabled_thinking: true,
    thinking_config: { disabled: { thinking: { type: 'disabled' } } },
  } as unknown as AIModelItem

  it('keeps official DeepSeek selectable and hides only runtime or persisted unsupported models', () => {
    expect(supportsDisabledThinkingOption(officialDeepSeek, new Set())).toBe(true)
    expect(supportsDisabledThinkingOption(officialDeepSeek, new Set([officialDeepSeek.id]))).toBe(false)
    expect(supportsDisabledThinkingOption({ ...officialDeepSeek, supports_disabled_thinking: false }, new Set())).toBe(false)
  })
})

describe('visibleTemplateReferenceIndexes', () => {
  it('does not turn session resources into attachments when the message has no explicit component reference', () => {
    expect([...visibleTemplateReferenceIndexes('请继续调整正文间距。', 2)]).toEqual([])
  })

  it('keeps only valid component references written in the message', () => {
    expect([...visibleTemplateReferenceIndexes('使用 @组件2，再参考 @组件1 和 @组件3。', 2)]).toEqual([1, 0])
  })
})
