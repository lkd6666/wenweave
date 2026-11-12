// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatApi, startChatRun } from './chat'
import type { RetryStatus } from '../utils/retry'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

function createRun(notices: RetryStatus[] = [], signal?: AbortSignal) {
  const args: Parameters<typeof startChatRun> = [1, 10, '准备较长文章', 1, 'auto', 'auto', 'stable-start-request']
  args[17] = signal
  args[18] = notice => notices.push(notice)
  return startChatRun(...args)
}

function delayedResponse(ms: number, status = 202) {
  return (_input: unknown, init: RequestInit) => new Promise<Response>((resolve, reject) => {
    const signal = init.signal!
    const abort = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve(new Response(JSON.stringify(status === 202 ? { run_id: 'slow-run' } : { detail: 'busy' }), { status }))
    }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}

describe('slow task creation', () => {
  it('keeps a two-minute creation alive without retries or premature timeout', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn().mockImplementation(delayedResponse(120_000))
    vi.stubGlobal('fetch', fetch)
    const notices: RetryStatus[] = []
    const pending = createRun(notices)
    await vi.advanceTimersByTimeAsync(119_999)
    expect(fetch).toHaveBeenCalledOnce()
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(false)
    expect(notices).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect((await pending).run_id).toBe('slow-run')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('waits three minutes then backs off before recovering an accepted task without another POST', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetch = vi.fn().mockImplementationOnce(delayedResponse(240_000))
      .mockResolvedValueOnce(new Response('{"run_id":"accepted-run"}'))
    vi.stubGlobal('fetch', fetch)
    const notices: RetryStatus[] = []
    const pending = createRun(notices)
    await vi.advanceTimersByTimeAsync(179_999)
    expect(fetch).toHaveBeenCalledOnce()
    expect(notices).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
    expect(notices[0]).toMatchObject({ phase: 'waiting', attempt: 2, delay_seconds: 5 })
    await vi.advanceTimersByTimeAsync(4999)
    expect(fetch).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(1)
    expect((await pending).run_id).toBe('accepted-run')
    expect(fetch.mock.calls[1][0]).toContain('/chat-runs/by-client-request/stable-start-request')
    expect(fetch.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1)
    expect(notices.map(item => item.phase)).toEqual(['waiting', 'attempting', 'recovered'])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('allows three long attempts within the ten-minute retry budget and preserves the request body', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetch = vi.fn()
      .mockImplementationOnce(delayedResponse(170_000, 503))
      .mockResolvedValueOnce(new Response('null'))
      .mockImplementationOnce(delayedResponse(170_000, 503))
      .mockResolvedValueOnce(new Response('null'))
      .mockImplementationOnce(delayedResponse(170_000))
    vi.stubGlobal('fetch', fetch)
    const notices: RetryStatus[] = []
    const pending = createRun(notices)
    await vi.runAllTimersAsync()
    expect((await pending).run_id).toBe('slow-run')
    const posts = fetch.mock.calls.filter(([, init]) => init.method === 'POST')
    expect(posts).toHaveLength(3)
    expect(new Set(posts.map(([, init]) => init.body)).size).toBe(1)
    expect(JSON.parse(posts[0][1].body).client_request_id).toBe('stable-start-request')
    expect(notices.filter(item => item.phase === 'waiting').map(item => item.delay_seconds)).toEqual([5, 10])
    expect(notices.at(-1)?.phase).toBe('recovered')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('waits for server retry advice and never replays creation while the status lookup is unavailable', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn().mockResolvedValueOnce(new Response('{"detail":"busy"}', { status: 503, headers: { 'Retry-After': '45' } }))
      .mockResolvedValueOnce(new Response('{"detail":"status unavailable"}', { status: 503 }))
      .mockResolvedValueOnce(new Response('{"run_id":"accepted-run"}'))
    vi.stubGlobal('fetch', fetch)
    const notices: RetryStatus[] = []
    const pending = createRun(notices)
    await vi.advanceTimersByTimeAsync(44_999)
    expect(fetch).toHaveBeenCalledOnce()
    expect(notices[0].delay_seconds).toBe(45)
    await vi.runAllTimersAsync()
    expect((await pending).run_id).toBe('accepted-run')
    expect(fetch.mock.calls.map(([, init]) => init.method ?? 'GET')).toEqual(['POST', 'GET', 'GET'])
  })

  it.each(['creation', 'backoff', 'confirmation'])('cancels during %s without issuing another creation', async (phase) => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetch = phase === 'creation' ? vi.fn().mockImplementation(delayedResponse(240_000))
      : vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockImplementation(delayedResponse(120_000))
    vi.stubGlobal('fetch', fetch)
    const controller = new AbortController()
    const pending = createRun([], controller.signal)
    const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(phase === 'confirmation' ? 5000 : 1000)
    controller.abort()
    await vi.runAllTimersAsync()
    await rejection
    expect(fetch.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1)
    expect(fetch).toHaveBeenCalledTimes(phase === 'confirmation' ? 2 : 1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('leaves question-answer timeouts at twenty seconds', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn().mockImplementationOnce(delayedResponse(30_000))
      .mockResolvedValueOnce(new Response('{"run_id":"resumed-run"}'))
    vi.stubGlobal('fetch', fetch)
    const notices: RetryStatus[] = []
    const pending = chatApi.answerUserQuestion(1, 'run-1', 'question-1', { action: 'skip' }, 'answer-id', status => notices.push(status))
    await vi.advanceTimersByTimeAsync(20_000)
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
    expect(notices[0]).toMatchObject({ phase: 'waiting', scope: 'question' })
    await vi.runAllTimersAsync()
    expect((await pending).run_id).toBe('resumed-run')
  })
})

it('streams manual compaction phases and consumes the final context once', async () => {
  const frames = [
    { event: 'retry_status', data: { phase: 'waiting', scope: 'compaction', attempt: 2 } },
    { event: 'retry_status', data: { phase: 'attempting', scope: 'compaction', attempt: 2 } },
    { event: 'context_stats', data: { state: 'compacted', used_tokens: 1234 } },
  ].map(frame => `event: ${frame.event}\r\ndata: ${JSON.stringify(frame.data)}\r\n\r\n`).join('')
  const fetch = vi.fn().mockResolvedValue(new Response(frames, { headers: { 'Content-Type': 'text/event-stream' } }))
  vi.stubGlobal('fetch', fetch)
  const events: RetryStatus[] = []
  const result = await chatApi.compactContext(1, 2, 3, false, event => events.push(event))
  expect(result.used_tokens).toBe(1234)
  expect(events.map(event => event.phase)).toEqual(['waiting', 'attempting'])
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toContain('stream=true')
})

it('does not replay manual compaction when its stream fails', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('event: error\ndata: {"status":502,"message":"压缩失败"}\n\n', {
    headers: { 'Content-Type': 'text/event-stream' },
  }))
  vi.stubGlobal('fetch', fetch)
  await expect(chatApi.compactContext(1, 2, 3)).rejects.toMatchObject({ status: 502, detail: '压缩失败' })
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('retries question answers using the same idempotency key', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockResolvedValueOnce(new Response('{"detail":"busy"}', { status: 503 }))
    .mockResolvedValueOnce(new Response('{"run_id":"run-1"}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  const pending = chatApi.answerUserQuestion(1, 'run-1', 'question-1', { action: 'skip' }, 'same-request')
  await vi.runAllTimersAsync()
  expect((await pending).run_id).toBe('run-1')
  expect(fetch.mock.calls.map(call => JSON.parse(call[1].body).client_request_id)).toEqual(['same-request', 'same-request'])
})

it('retries active-run status reads without sending another task', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'))
    .mockResolvedValueOnce(new Response('null', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  const notices: RetryStatus[] = []
  const pending = chatApi.getActiveRun(1, undefined, notice => notices.push(notice))
  await vi.runAllTimersAsync()
  expect(await pending).toBeNull()
  expect(fetch.mock.calls).toHaveLength(2)
  expect(fetch.mock.calls.every(call => String(call[0]).endsWith('/chat-runs/active'))).toBe(true)
  expect(notices.map(notice => notice.phase)).toEqual(['waiting', 'attempting', 'recovered'])
})

it('cancels active-run retry backoff when leaving the editor', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
  vi.stubGlobal('fetch', fetch)
  const controller = new AbortController()
  const pending = chatApi.getActiveRun(1, controller.signal)
  const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(0)
  controller.abort()
  await vi.runAllTimersAsync()
  await rejection
  expect(fetch).toHaveBeenCalledOnce()
})
