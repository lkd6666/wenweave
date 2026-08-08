import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSseChunk, recordChatUserQuestionActivity, startChatRun } from './chat'

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
