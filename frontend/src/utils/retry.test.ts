// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { abortableDelay, isRetryable, retryAfterMs, retryDelayMs, retryRequest } from './retry'
import type { RetryStatus } from './retry'
import { retryNotice } from './retryNotice'

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('bounded idempotent retries', () => {
  it('classifies permanent responses and respects provider advice', () => {
    for (const status of [400, 401, 403, 404, 409, 422]) expect(isRetryable(new ApiError(status, 'bad'))).toBe(false)
    expect(isRetryable(new ApiError(429, 'insufficient_quota'))).toBe(false)
    expect(isRetryable(new ApiError(503, 'busy', { 'x-should-retry': 'false' }))).toBe(false)
    expect(isRetryable(new TypeError('Failed to fetch'))).toBe(true)
    expect(retryAfterMs(new ApiError(429, 'busy', { 'retry-after-ms': '1250' }))).toBe(1250)
    expect(retryAfterMs(new ApiError(429, 'busy', { 'retry-after': 'Wed, 04 Nov 2026 00:00:07 GMT' }), Date.UTC(2026, 10, 4))).toBe(7000)
    expect(retryDelayMs(new ApiError(429, 'busy', { 'Retry-After': '61' }), 1, 100, 60_000)).toBeNull()
    vi.spyOn(Math, 'random').mockReturnValue(1)
    expect(retryDelayMs(new ApiError(503, 'busy'), 30, 500, 5000)).toBe(5000)
  })

  it('publishes waiting, attempting and recovered with a stable operation identity', async () => {
    vi.useFakeTimers()
    const events: RetryStatus[] = []
    const request = vi.fn().mockRejectedValueOnce(new ApiError(429, 'busy', { 'Retry-After': '2' })).mockResolvedValue('done')
    const pending = retryRequest(request, { scope: 'start', onRetry: event => events.push(event) })
    await vi.advanceTimersByTimeAsync(0)
    expect(events[0]).toMatchObject({ phase: 'waiting', attempt: 2, delay_seconds: 2 })
    await vi.advanceTimersByTimeAsync(1999)
    expect(request).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(await pending).toBe('done')
    expect(events.map(event => event.phase)).toEqual(['waiting', 'attempting', 'recovered'])
    expect(new Set(events.map(event => event.operation_id)).size).toBe(1)
  })

  it('aborts a pending backoff without making another request or leaking timers', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const request = vi.fn().mockRejectedValue(new ApiError(503, 'busy'))
    const pending = retryRequest(request, { scope: 'start', signal: controller.signal })
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await rejected
    await vi.runAllTimersAsync()
    expect(request).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('stops at the attempts or elapsed budget and does not retry permanent failures', async () => {
    vi.useFakeTimers()
    const request = vi.fn().mockRejectedValue(new ApiError(503, 'busy'))
    const exhausted: RetryStatus[] = []
    const pending = retryRequest(request, { scope: 'cancel', onRetry: event => exhausted.push(event) })
    const rejected = expect(pending).rejects.toMatchObject({ status: 503 })
    await vi.runAllTimersAsync()
    await rejected
    expect(request).toHaveBeenCalledTimes(3)
    expect(exhausted.at(-1)?.phase).toBe('exhausted')
    request.mockClear()
    await expect(retryRequest(request, { scope: 'start', maxElapsedMs: 1 })).rejects.toMatchObject({ status: 503 })
    expect(request).toHaveBeenCalledTimes(1)
    request.mockReset().mockRejectedValue(new ApiError(403, 'denied'))
    await expect(retryRequest(request, { scope: 'start' })).rejects.toMatchObject({ status: 403 })
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('does not replay successful requests when the recovery observer fails', async () => {
    vi.useFakeTimers()
    const request = vi.fn().mockRejectedValueOnce(new ApiError(503, 'busy')).mockResolvedValue('done')
    const pending = retryRequest(request, { scope: 'start', onRetry: event => {
      if (event.phase === 'recovered') throw new TypeError('observer failed')
    } })
    const rejected = expect(pending).rejects.toThrow('observer failed')
    await vi.runAllTimersAsync()
    await rejected
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('does not restart replayed countdowns', () => {
    const notice = retryNotice({ scope: 'compaction', phase: 'waiting', operation_id: 'test', attempt: 2,
      max_attempts: 3, delay_seconds: 3, reason: 'upstream_429', detail: '服务限流' }, 5000)
    expect(notice.title).toBe('上下文压缩：等待重试')
    expect(Date.now() - notice.retryStartedAtMs!).toBeGreaterThanOrEqual(5000)
  })

  it('rejects delays with an already aborted signal', async () => {
    const controller = new AbortController()
    controller.abort()
    await expect(abortableDelay(10_000, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })
})
