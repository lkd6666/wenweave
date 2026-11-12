import type { ChatRunNotice } from '../components/ChatPanel'
import type { RetryStatus } from './retry'

const labels: Record<RetryStatus['scope'], string> = {
  start: '创建任务', stream: '恢复实时输出', model: '模型请求',
  compaction: '上下文压缩', tool_read: '工具读取', cancel: '停止任务',
  question: '提交确认结果',
}

export function retryNotice(status: RetryStatus, eventAgeMs = 0): ChatRunNotice {
  const label = labels[status.scope] ?? '请求'
  const titles = { waiting: `${label}：等待重试`, attempting: `${label}：正在重试`,
    recovered: `${label}已恢复`, exhausted: `${label}：自动重试已停止` }
  return {
    kind: status.phase === 'recovered' ? 'success' : status.phase === 'exhausted' ? 'error' : 'retrying',
    title: titles[status.phase], detail: status.phase === 'recovered' ? '请求已成功，继续执行。' : status.detail,
    operationId: status.operation_id, phase: status.phase,
    attempt: status.attempt, maxAttempts: status.max_attempts,
    retryDelaySeconds: status.phase === 'waiting' ? status.delay_seconds : undefined,
    // Event age is computed against the stream's server clock. This also
    // handles replayed waits without restarting the original countdown.
    retryStartedAtMs: Date.now() - Math.max(0, eventAgeMs),
  }
}
