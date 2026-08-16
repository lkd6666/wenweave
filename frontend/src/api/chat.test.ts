import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSseChunk, recordChatUserQuestionActivity, reaskSourceUnavailableFromError, startChatRun } from './chat'
import { ApiError } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('recordChatUserQuestionActivity', () => {
  it('posts an interaction heartbeat to the pending question', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ timeout_at: '2026-07-29T00:02:00Z' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const result = await recordChatUserQuestionActivity(12, 'run/with space', 'question/with space')

    expect(result.timeout_at).toBe('2026-07-29T00:02:00Z')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/documents/12/chat-runs/run%2Fwith%20space/questions/question%2Fwith%20space/activity',
      expect.objectContaining({ method: 'POST', body: '{}' }),
    )
  })
})

describe('startChatRun', () => {
  it('keeps persisted session templates when the composer has no manual component mention', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ run_id: 'run-1' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('window', { setTimeout, clearTimeout })

    await startChatRun(12, 3, '调整标题层级', 4, 'enabled', 'auto', 'client-request-1')

    const [, request] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(request.body))).not.toHaveProperty('template_ids')
  })
})

describe('re-ask errors', () => {
  it('recognizes an unavailable history anchor without treating document conflicts as retryable', () => {
    const unavailable = new ApiError(409, {
      code: 'reask_source_unavailable',
      message: '未找到当前对话中可重新提问的消息',
    })

    expect(reaskSourceUnavailableFromError(unavailable)).toEqual({
      code: 'reask_source_unavailable',
      message: '未找到当前对话中可重新提问的消息',
    })
    expect(reaskSourceUnavailableFromError(new ApiError(409, {
      code: 'reask_document_conflict',
      message: '文档已变化',
      current_checksum: 'a'.repeat(64),
    }))).toBeNull()
  })
})

describe('chat SSE event timing', () => {
  it('extracts replay age without exposing transport metadata to event handlers', () => {
    const parsed = parseSseChunk(
      'id: 12\r\nevent: reasoning_delta\r\ndata: {"text":"继续分析","_event_age_ms":125430}\r\n\r\n',
    )

    expect(parsed.rest).toBe('')
    expect(parsed.events).toEqual([
      {
        sequence: 12,
        eventAgeMs: 125430,
        event: 'reasoning_delta',
        data: { text: '继续分析' },
      },
    ])
  })
})
