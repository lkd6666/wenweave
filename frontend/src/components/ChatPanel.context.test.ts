import { describe, expect, it } from 'vitest'
import type { AIModelItem, ChatContextStats } from '../types'
import { contextCompactionNotice, contextUsageValues, formatMessageTime, isRuntimeContextCompacting, mergeFallbackThoughtBlocks, modelUsageDetail, modelUsageLabel, normaliseAssistantTurnBlocks, parseCompactionSummary, supportsDisabledThinkingOption, visibleAssistantTurnBlocks, visibleTemplateReferenceIndexes } from './ChatPanel'
import { questionDeadlineMs } from './UserQuestionPanel'

describe('contextUsageValues', () => {
  it('keeps the raw ledger separate from the next compiled model input', () => {
    const stats = {
      used_tokens: 26_800,
      compiled_input_tokens: 26_800,
      ledger_tokens: 185_000,
      runtime_context_tokens: 0,
      conversation_tokens: 185_000,
    } as ChatContextStats

    expect(contextUsageValues(stats)).toEqual({
      compiledInputTokens: 26_800,
      ledgerTokens: 185_000,
      runtimeContextTokens: 0,
    })
  })

  it('uses the server-recomputed next input after a completed tool', () => {
    const stats = {
      used_tokens: 26_800,
      compiled_input_tokens: 26_800,
      ledger_tokens: 185_000,
      runtime_context_tokens: 31_200,
      runtime_context_source: 'server_recomputed_after_tool',
    } as ChatContextStats

    expect(contextUsageValues(stats)).toEqual({
      compiledInputTokens: 31_200,
      ledgerTokens: 185_000,
      runtimeContextTokens: 31_200,
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

describe('contextCompactionNotice', () => {
  it('distinguishes a completed compression from a no-op check', () => {
    expect(contextCompactionNotice('压缩上下文成功，节省 10,207 tokens，压缩率 17%（60,469 → 50,262 tokens）。')).toEqual({
      kind: 'success',
      title: '上下文已压缩',
      detail: '节省 10,207 tokens，压缩率 17%（60,469 → 50,262 tokens）。',
    })

    expect(contextCompactionNotice('上下文检查完成，本次无需压缩（当前 50,262 tokens）。')).toEqual({
      kind: 'info',
      title: '无需压缩',
      detail: '本次无需压缩（当前 50,262 tokens）。',
    })
  })
})

describe('parseCompactionSummary', () => {
  it('formats the runtime work-summary schema into labelled sections', () => {
    const summary = parseCompactionSummary(JSON.stringify({
      objective: '为高净值客户制作西藏高端定制自驾游排版',
      constraints: '拒绝小清新风格，保留三种定价。',
      decisions: '背景使用 CSS 实现，不使用 SVG。',
      completed: '完成首屏与路线表格。',
      active_work: '检查营地段落与图片分布。',
      blockers: '无',
      next_steps: '继续优化服务权益卡片。',
      source_refs: 'event:2103026918',
    }))

    expect(summary?.objective).toBe('为高净值客户制作西藏高端定制自驾游排版')
    expect(summary?.sections).toEqual(expect.arrayContaining([
        { key: 'active_work', label: '正在处理', values: ['检查营地段落与图片分布。'] },
        { key: 'next_steps', label: '下一步', values: ['继续优化服务权益卡片。'] },
        { key: 'constraints', label: '约束条件', values: ['拒绝小清新风格，保留三种定价。'] },
    ]))
  })

  it('supports the durable-memory schema and fenced JSON', () => {
    const summary = parseCompactionSummary('```json\n{"objective":"继续完成排版","active_work":["压缩早期历史"],"pending_tasks":["继续处理最近回合"],"narrative":"模型生成的会话工作摘要"}\n```')

    expect(summary).toEqual({
      objective: '继续完成排版',
      narrative: '模型生成的会话工作摘要',
      sections: [
        { key: 'active_work', label: '正在处理', values: ['压缩早期历史'] },
        { key: 'pending_tasks', label: '待处理', values: ['继续处理最近回合'] },
      ],
    })
  })

  it('leaves legacy or malformed summaries for the plain-text fallback', () => {
    expect(parseCompactionSummary('较早对话和工具结果已整理为工作记忆。')).toBeNull()
    expect(parseCompactionSummary('{"objective":')).toBeNull()
  })
})

describe('assistant timeline visibility', () => {
  it('keeps persisted context-compaction blocks in the execution timeline', () => {
    const blocks = visibleAssistantTurnBlocks([{
      id: 'context-compaction-1',
      type: 'context_compaction',
      state: 'done',
      content: '',
      tool: null,
      context_compaction: {
        summary: '已整理早期工具循环。',
        original_tokens: 190_000,
        used_tokens: 48_000,
        summarized_cycles: 3,
        digested_cycles: 3,
        dropped_cycles: 0,
        summary_tokens: 600,
        durable_snapshot: true,
      },
    }])

    expect(blocks).toHaveLength(1)
    expect(blocks[0].context_compaction?.durable_snapshot).toBe(true)
  })

  it('keeps task-plan tool calls in the visible execution timeline', () => {
    const blocks = visibleAssistantTurnBlocks([{
      id: 'task-plan',
      type: 'tool',
      state: 'done',
      content: '',
      tool: {
        id: 'task-plan',
        name: 'update_task_plan',
        arguments: {},
        status: 'success',
        preparing: false,
        result: '任务清单已更新',
        html_changed: false,
        activity: { kind: 'plan', summary: '任务清单 1/2 已完成' },
        read_range: null,
        change_summary: null,
      },
    }])

    expect(blocks).toHaveLength(1)
    expect(blocks[0].tool?.name).toBe('update_task_plan')
  })

  it('adds saved reasoning when older structured blocks omitted it', () => {
    const blocks = mergeFallbackThoughtBlocks([{
      id: 'tool-1',
      type: 'tool',
      state: 'done',
      content: '',
      tool: null,
    }], { status: 'complete', content: '先读取文档，再调整层级。', detail: '' })

    expect(blocks[0]).toMatchObject({ type: 'thought', state: 'done', content: '先读取文档，再调整层级。' })
  })

  it('does not replace the legacy tool fallback when adding saved reasoning', () => {
    const legacyTools = [{
      id: 'tool-1',
      type: 'tool' as const,
      state: 'done' as const,
      content: '',
      tool: null,
    }]
    const blocks = mergeFallbackThoughtBlocks(legacyTools, {
      status: 'complete', content: '先读取文档，再调整层级。', detail: '',
    })

    expect(blocks).toHaveLength(2)
    expect(blocks[1]).toBe(legacyTools[0])
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
