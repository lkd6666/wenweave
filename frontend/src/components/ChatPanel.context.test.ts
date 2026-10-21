import { describe, expect, it } from 'vitest'
import type { AIModelItem, ChatContextStats, ToolExecution } from '../types'
import { contextCompactionNotice, contextInputWindowLabel, contextUsageValues, formatMessageTime, generatedImagePreviews, isRuntimeContextCompacting, mergeFallbackThoughtBlocks, modelImagePreviews, modelUsageDetail, modelUsageLabel, normaliseAssistantTurnBlocks, parseCompactionSummary, supportsDisabledThinkingOption, toolLabel, visibleAssistantTurnBlocks, visibleTemplateReferenceIndexes } from './ChatPanel'
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

  it('retains explicit zero for a current runtime projection', () => {
    const stats = {
      used_tokens: 26_800, compiled_input_tokens: 26_800,
      runtime_context_tokens: 0, runtime_context_source: 'server_request_budget',
    } as ChatContextStats
    expect(contextUsageValues(stats).compiledInputTokens).toBe(0)
  })

  it('retains explicit zero for a prepared projection', () => {
    const stats = { used_tokens: 26_800, compiled_input_tokens: 0 } as ChatContextStats
    expect(contextUsageValues(stats).compiledInputTokens).toBe(0)
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

describe('contextInputWindowLabel', () => {
  it('distinguishes the compression threshold, total window and reserved output', () => {
    const stats = {
      active_context_threshold_tokens: 300_000,
      usable_tokens: 300_000,
      max_tokens: 428_000,
      max_output_tokens: 100_000,
      input_limit_tokens: 328_000,
    } as ChatContextStats

    expect(contextInputWindowLabel(stats)).toBe('达到 300K tokens 时自动压缩；模型总窗口 428K，输出预留 100K，输入上限 328K tokens')
  })

  it('derives the physical input limit for older responses', () => {
    const stats = { active_context_threshold_tokens: 20_000, max_tokens: 32_000, max_output_tokens: 8_000 } as ChatContextStats
    expect(contextInputWindowLabel(stats)).toContain('输入上限 24K tokens')
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
  it.each([
    [0, '0'], [999, '999'], [1000, '1K'], [11141, '11.1K'],
    [999949, '999.9K'], [999950, '1M'], [1000000, '1M'],
    [4832735, '4.83M'], [4843876, '4.84M'],
  ])('abbreviates %i tokens as %s', (totalTokens, expected) => {
    expect(modelUsageLabel({
      model_names: ['测试模型'], input_tokens: totalTokens, output_tokens: 0,
      total_tokens: totalTokens, usage_reported: true,
    })).toContain(`累计 ${expected} tokens`)
  })

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

describe('tool image previews', () => {
  const tool = (overrides: Partial<ToolExecution> = {}): ToolExecution => ({
    id: 'tool-1',
    name: 'read_blocks',
    arguments: {},
    status: 'success',
    html_changed: false,
    ...overrides,
  })

  it('keeps the image gallery data', () => {
    const imageTool = tool({
      name: 'view_article_images',
      model_input: { state: 'available', content: '{"items":[{"index":1}]}', truncated: false },
      activity: {
        kind: 'image_view',
        summary: '已读取图片',
        details: {
          image_content_included: true,
          items: [{ index: 1, label: '文章首图', width: 640, height: 360, preview_url: 'https://cdn.example/hero.png' }],
        },
      },
    })

    expect(modelImagePreviews(imageTool)).toEqual([{
      id: 'model-image-1-https://cdn.example/hero.png',
      url: 'https://cdn.example/hero.png',
      label: '文章首图',
      width: 640,
      height: 360,
    }])
  })

  it('resolves private chat image references to current authorized previews', () => {
    const unsigned = '/api/documents/1/chat-images/photo-1/content'
    const imageTool = tool({
      name: 'view_chat_images_page',
      activity: { kind: 'image_view', summary: '', details: {
        image_content_included: true,
        items: [{ index: 5, kind: 'chat', attachment_id: 'photo-1', label: '@图片5', preview_url: unsigned }],
      } },
    })
    const previews = new Map([['photo-1', `${unsigned}?token=fresh-token`]])

    expect(modelImagePreviews(imageTool, previews)).toMatchObject([{ label: '@图片5', url: `${unsigned}?token=fresh-token` }])
    previews.set('photo-1', `${unsigned}?token=renewed-token`)
    expect(modelImagePreviews(imageTool, previews)).toMatchObject([{ url: `${unsigned}?token=renewed-token` }])
    expect(imageTool.activity?.details?.items).toEqual([
      { index: 5, kind: 'chat', attachment_id: 'photo-1', label: '@图片5', preview_url: unsigned },
    ])
  })

  it('uses uploaded article assets for chat images outside the loaded history', () => {
    const imageTool = tool({
      name: 'view_chat_images_page',
      activity: { kind: 'image_view', summary: '', details: {
        image_content_included: true,
        items: [{ attachment_id: 'photo-1', article_url: '/uploads/photo-1.png', preview_url: '/api/documents/1/chat-images/photo-1/content' }],
      } },
    })
    expect(modelImagePreviews(imageTool)).toMatchObject([{ url: '/uploads/photo-1.png' }])
    expect(modelImagePreviews(imageTool, new Map([['photo-1', '/api/documents/1/chat-images/photo-1/content?token=expiring']]))).toMatchObject([
      { url: '/uploads/photo-1.png' },
    ])
    expect(modelImagePreviews({ ...imageTool, activity: { ...imageTool.activity!, details: {
      ...imageTool.activity!.details, image_content_included: false,
    } } })).toEqual([])
  })

  it('rejects empty or unsafe image sources and keeps safe fallback previews', () => {
    const imageTool = tool({ activity: { kind: 'image_view', summary: '', details: {
      image_content_included: true,
      items: [
        { preview_url: '' },
        { attachment_id: 'photo-1', article_url: 'javascript:alert(1)', preview_url: 'https://cdn.example/photo.png' },
        { preview_url: 'data:text/html,unsafe' },
      ],
    } } })
    expect(modelImagePreviews(imageTool, new Map([['photo-1', 'javascript:alert(2)']]))).toMatchObject([
      { url: 'https://cdn.example/photo.png' },
    ])
  })

  it('previews images returned by import and application tools', () => {
    expect(generatedImagePreviews(tool({
      name: 'import_searched_image',
      activity: { kind: 'image_import', summary: '搜索图片已导入', details: { asset_id: 'asset-1', url: 'https://cdn.example/photo.png', title: '文章照片', width: 1200, height: 800 } },
    }))).toMatchObject([{ url: 'https://cdn.example/photo.png', title: '文章照片', width: 1200, height: 800 }])
    expect(generatedImagePreviews(tool({
      name: 'apply_edited_cover',
      activity: { kind: 'image_application', summary: '封面已更新', details: { url: 'javascript:alert(1)' } },
    }))).toEqual([])
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

describe('image viewing tool labels', () => {
  const imageTool = {
    id: 'image-view', name: 'view_article_images', arguments: {}, status: 'success', html_changed: false,
  } as ToolExecution

  it('distinguishes a dimensions-only request while running and after completion', () => {
    expect(toolLabel({ ...imageTool, status: 'running', arguments: { include_image: false } })).toBe('读取图片尺寸')
    expect(toolLabel({ ...imageTool, activity: { kind: 'image_view', summary: '', details: {
      include_image_requested: false, image_content_included: false, items: [{ width: 3600, height: 1500 }],
    } } })).toBe('读取图片尺寸')
    expect(toolLabel({ ...imageTool, name: 'view_chat_images_page', arguments: { include_image: false } })).toBe('分页读取附图尺寸')
  })

  it('recognizes legacy dimensions-only results without implying that images were provided', () => {
    expect(toolLabel({ ...imageTool, activity: { kind: 'image_view', summary: '', details: {
      vision_supported: true, image_content_included: false, items: [{ width: 3600, height: 1500 }],
    } } })).toBe('读取图片尺寸')
  })

  it('retains the viewing label when pixels are requested or a visual read was budget-blocked', () => {
    expect(toolLabel(imageTool)).toBe('查看文章图片')
    expect(toolLabel({ ...imageTool, name: 'view_chat_images_page', status: 'running' })).toBe('分页查看附图')
    expect(toolLabel({ ...imageTool, name: 'view_chat_images_page', activity: { kind: 'image_view', summary: '', details: {
      image_content_included: true, items: [{ width: 3600, height: 1500 }],
    } } })).toBe('分页查看附图')
    expect(toolLabel({ ...imageTool, activity: { kind: 'image_view', summary: '', details: {
      image_content_included: true, items: [{ width: 3600, height: 1500 }],
    } } })).toBe('查看文章图片')
    expect(toolLabel({ ...imageTool, activity: { kind: 'image_view', summary: '', details: {
      image_content_included: false, budget_limited: true, items: [],
    } } })).toBe('查看文章图片')
  })
})
