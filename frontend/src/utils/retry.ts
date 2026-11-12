import { ApiError } from '../api/client'

export interface RetryStatus {
  operation_id: string
  scope: 'start' | 'stream' | 'model' | 'compaction' | 'tool_read' | 'cancel' | 'question'
  phase: 'waiting' | 'attempting' | 'recovered' | 'exhausted'
  attempt: number
  max_attempts: number
  delay_seconds: number
  retry_at?: string
  reason: string
  detail: string
  tool?: string
}

export interface RetryOptions {
  scope: RetryStatus['scope']
  signal?: AbortSignal
  onRetry?: (status: RetryStatus) => void
  maxAttempts?: number
  maxElapsedMs?: number
  baseMs?: number
  maxDelayMs?: number
}

export function isRetryable(error: unknown): boolean {
  if (error instanceof Error && error.name === 'AbortError') return false
  if (error instanceof ApiError) {
    if (/insufficient_quota|insufficient[_ ](?:balance|credit)|billing_hard_limit|credit balance.*low|quota.*(?:exhausted|depleted)|(?:daily|monthly).*quota.*exceed|余额不足|欠费|额度已用尽|context_length_exceeded/i.test(error.message)) return false
    if (error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) return false
    if (error.headers.get('x-should-retry') === 'false') return false
    return error.status === 0 || [408, 429].includes(error.status) || error.status >= 500
  }
  return error instanceof TypeError || (error instanceof Error && /StreamInactivityError|network|fetch|connection|连接|输出连接已结束|timeout/i.test(`${error.name} ${error.message}`))
}

export function retryAfterMs(error: unknown, now = Date.now()): number | null {
  if (!(error instanceof ApiError)) return null
  for (const key of ['retry-after-ms', 'x-ms-retry-after-ms', 'retry-after']) {
    const raw = error.headers.get(key)
    if (raw === null || raw.trim() === '') continue
    const n = Number(raw)
    const value = Number.isFinite(n) ? n * (key.endsWith('-ms') ? 1 : 1000) : Date.parse(raw) - now
    if (Number.isFinite(value) && value >= 0) return value
  }
  return null
}

export function retryDelayMs(error: unknown, failedAttempt: number, baseMs = 500, capMs = 30_000): number | null {
  const advice = retryAfterMs(error)
  if (advice !== null && advice > capMs) return null // Never retry before the server's deadline.
  const local = Math.min(capMs, baseMs * 2 ** Math.min(30, Math.max(0, failedAttempt - 1)))
  return Math.min(capMs, Math.ceil(Math.max(local * (.5 + Math.random() * .5), advice ?? 0)))
}

export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(new DOMException('请求已取消', 'AbortError')) }
    const cleanup = () => { window.clearTimeout(timer); signal?.removeEventListener('abort', abort) }
    const timer = window.setTimeout(() => { cleanup(); resolve() }, ms)
    if (signal?.aborted) abort()
    else signal?.addEventListener('abort', abort, { once: true })
  })
}

/** Only invoke at an explicitly idempotent request boundary. */
export async function retryRequest<T>(operation: () => Promise<T>, options: RetryOptions): Promise<T> {
  const { signal, onRetry, scope, maxAttempts = 3, maxElapsedMs = 90_000, baseMs = 500, maxDelayMs = 30_000 } = options
  const started = performance.now()
  const operationId = `${scope}-${Date.now()}-${Math.random().toString(36).slice(2)}`
  const emit = (phase: RetryStatus['phase'], attempt: number, delay = 0) => onRetry?.({
    operation_id: operationId, scope, phase, attempt, max_attempts: maxAttempts,
    delay_seconds: delay / 1000, retry_at: new Date(Date.now() + delay).toISOString(),
    reason: 'transport', detail: phase === 'exhausted' ? '本操作已停止自动重试，请检查网络或服务状态。'
      : scope === 'start' ? '任务创建可能需要较长时间；重试时先按原请求编号查询，已创建则直接恢复。' : '正在恢复请求。',
  })
  for (let attempt = 1; ; attempt += 1) {
    signal?.throwIfAborted()
    if (attempt > 1) emit('attempting', attempt)
    let result: T
    try {
      result = await operation()
    } catch (error) {
      if (signal?.aborted) throw error
      const delay = retryDelayMs(error, attempt, baseMs, maxDelayMs)
      if (!isRetryable(error) || attempt >= maxAttempts || delay === null || performance.now() - started + delay >= maxElapsedMs) {
        if (attempt > 1 || isRetryable(error)) emit('exhausted', attempt)
        throw error
      }
      emit('waiting', attempt + 1, delay)
      await abortableDelay(delay, signal)
      if (performance.now() - started >= maxElapsedMs) { emit('exhausted', attempt); throw error }
      continue
    }
    if (attempt > 1) emit('recovered', attempt)
    return result
  }
}
