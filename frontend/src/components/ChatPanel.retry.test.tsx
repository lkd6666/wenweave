// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentRunNotice } from './ChatPanel'

afterEach(() => { vi.useRealTimers() })

it('transitions an expired wait into progress confirmation and shows total request counts', async () => {
  vi.useFakeTimers()
  const container = document.createElement('div')
  const root = createRoot(container)
  const notice = { kind: 'retrying' as const, title: '模型请求：等待重试', detail: '服务限流',
    phase: 'waiting' as const, attempt: 2, maxAttempts: 3, retryDelaySeconds: 2, retryStartedAtMs: Date.now() }
  try {
    await act(async () => { root.render(<AgentRunNotice notice={notice} />) })
    expect(container.textContent).toContain('第 2/3 次请求')
    expect(container.textContent).toContain('2 秒后重试')
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(container.textContent).toContain('等待时间已到，正在确认请求进度')
    expect(container.textContent).not.toContain('0 秒后重试')
    await act(async () => { root.render(<AgentRunNotice notice={{ ...notice, phase: 'attempting', retryDelaySeconds: undefined }} />) })
    expect(container.textContent).toContain('正在请求，等待响应')
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})
