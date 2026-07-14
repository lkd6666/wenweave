import { useAuthStore } from '../store/authStore'
import { ApiError } from './client'
import type { AgentRunStatus, ChangeSummary, ChatContextStats, ChatMessageItem, ReadRange, SelectedElementContext, ToolActivity, ToolExecution } from '../types'
import { sanitizeSelectedElements } from '../utils/selectedElements'

const API_BASE = '/api'
const STREAM_CONNECT_TIMEOUT_MS = 20_000
const STREAM_INACTIVITY_TIMEOUT_MS = 35_000

export type ChatStreamEvent =
  | { event: 'text_delta'; data: { text: string } }
  | { event: 'reasoning_delta'; data: { text: string } }
  | { event: 'tool_call'; data: { id?: string; name: string; arguments: ToolExecution['arguments']; preparing?: boolean } }
  | {
      event: 'tool_result'
      data: { name: string; result: string; html?: string; read_range?: ReadRange; change_summary?: ChangeSummary; activity?: ToolActivity }
    }
  | { event: 'agent_status'; data: { thinking: { requested: ThinkingMode; applied: boolean; detail: string } } }
  | { event: 'heartbeat'; data: { status?: AgentRunStatus; idle_seconds?: number; detail?: string } }
  | { event: 'context_stats'; data: ChatContextStats }
  | { event: 'final'; data: { content: string; html: string; html_changed: boolean; compliance: unknown } }
  | { event: 'error'; data: { message: string } }

export interface AgentRunInfo {
  run_id: string
  status: AgentRunStatus
  user_message_id: number
  assistant_message_id: number | null
  error_message: string
}

export type SequencedChatStreamEvent = ChatStreamEvent & { sequence: number }

export type ThinkingMode = 'auto' | 'enabled' | 'disabled'
export type ThinkingEffort = 'auto' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

class StreamInactivityError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'StreamInactivityError'
  }
}

function parseSseChunk(buffer: string): { events: SequencedChatStreamEvent[]; rest: string } {
  const events: SequencedChatStreamEvent[] = []
  // EventSourceResponse 使用标准 CRLF（\r\n\r\n）分隔 SSE 事件。此前只按 \n\n
  // 切分，导致增量事件被留在 buffer 中直到响应结束才被一次性渲染。
  const parts = buffer.split(/\r?\n\r?\n/)
  const rest = parts.pop() ?? ''

  for (const part of parts) {
    if (!part.trim()) continue
    let eventName = 'message'
    let eventId = 0
    const dataLines: string[] = []
    for (const line of part.split(/\r?\n/)) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('id:')) {
        eventId = Number(line.slice(3).trim()) || 0
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    const dataStr = dataLines.join('\n')
    if (!dataStr) continue
    try {
      events.push({
        sequence: eventId,
        event: eventName as ChatStreamEvent['event'],
        data: JSON.parse(dataStr),
      } as SequencedChatStreamEvent)
    } catch {
      // 忽略无法解析的片段
    }
  }
  return { events, rest }
}

export async function startChatRun(
  documentId: number,
  message: string,
  modelId: number,
  thinkingMode: ThinkingMode,
  thinkingEffort: ThinkingEffort,
  clientRequestId: string,
  selectedElements?: SelectedElementContext[],
  layoutReferenceId?: string,
): Promise<AgentRunInfo> {
  const token = useAuthStore.getState().token
  let lastError: unknown
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const res = await fetch(`${API_BASE}/documents/${documentId}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message,
          model_id: modelId,
          client_request_id: clientRequestId,
          thinking_mode: thinkingMode,
          thinking_effort: thinkingEffort,
          selected_elements: sanitizeSelectedElements(selectedElements ?? []),
          ...(layoutReferenceId ? { layout_reference_id: layoutReferenceId } : {}),
        }),
      })
      if (res.status === 401) useAuthStore.getState().logout()
      if (!res.ok) {
        let detail: unknown = res.statusText
        try {
          const data = await res.json()
          detail = data.detail ?? data
        } catch {
          // Ignore a malformed error payload.
        }
        throw new ApiError(res.status, detail)
      }
      return await res.json() as AgentRunInfo
    } catch (err) {
      lastError = err
      if (err instanceof ApiError || attempt === 2) throw err
      await delay(300 * (attempt + 1))
    }
  }
  throw lastError instanceof Error ? lastError : new Error('无法创建 Agent 运行')
}

export async function* streamChatRunEvents(
  documentId: number,
  runId: string,
  after: number,
  signal?: AbortSignal,
): AsyncGenerator<SequencedChatStreamEvent> {
  const token = useAuthStore.getState().token
  const res = await fetchWithTimeout(
    `${API_BASE}/documents/${documentId}/chat-runs/${runId}/events?after=${after}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal },
    STREAM_CONNECT_TIMEOUT_MS,
    '建立实时输出连接超时',
  )
  if (res.status === 401) useAuthStore.getState().logout()
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Ignore a malformed error payload.
    }
    throw new ApiError(res.status, detail)
  }

  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持流式响应')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await readWithInactivityTimeout(reader, signal)
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseChunk(buffer)
      buffer = parsed.rest
      for (const evt of parsed.events) {
        yield evt
      }
    }

    if (buffer.trim()) {
      const parsed = parseSseChunk(buffer + '\n\n')
      for (const evt of parsed.events) {
        yield evt
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function cancelChatRun(documentId: number, runId: string): Promise<AgentRunInfo> {
  const token = useAuthStore.getState().token
  const res = await fetch(`${API_BASE}/documents/${documentId}/chat-runs/${runId}/cancel`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Ignore a malformed error payload.
    }
    throw new ApiError(res.status, detail)
  }
  return await res.json() as AgentRunInfo
}

export const chatApi = {
  listMessages: (documentId: number) => apiGet<ChatMessageItem[]>(`/documents/${documentId}/messages`),
  getActiveRun: (documentId: number) => apiGet<AgentRunInfo | null>(`/documents/${documentId}/chat-runs/active`),
  getRun: (documentId: number, runId: string) => apiGet<AgentRunInfo>(`/documents/${documentId}/chat-runs/${runId}`),
  getContext: (documentId: number, modelId: number) => apiGet<ChatContextStats>(`/documents/${documentId}/chat-context?model_id=${encodeURIComponent(modelId)}`),
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<Response> {
  const controller = new AbortController()
  const onAbort = () => controller.abort(init.signal?.reason)
  if (init.signal?.aborted) onAbort()
  else init.signal?.addEventListener('abort', onAbort, { once: true })
  const timer = window.setTimeout(
    () => controller.abort(new StreamInactivityError(timeoutMessage)),
    timeoutMs,
  )
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (controller.signal.reason instanceof StreamInactivityError) throw controller.signal.reason
    throw error
  } finally {
    window.clearTimeout(timer)
    init.signal?.removeEventListener('abort', onAbort)
  }
}

async function readWithInactivityTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  signal?: AbortSignal,
) {
  return await new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
    let settled = false
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      callback()
    }
    const onAbort = () => finish(() => reject(signal?.reason ?? new DOMException('请求已取消', 'AbortError')))
    const timer = window.setTimeout(() => {
      void reader.cancel()
      finish(() => reject(new StreamInactivityError('实时输出超过 35 秒没有任何数据，正在重新连接')))
    }, STREAM_INACTIVITY_TIMEOUT_MS)

    if (signal?.aborted) {
      onAbort()
      return
    }
    signal?.addEventListener('abort', onAbort, { once: true })
    reader.read().then(
      (result) => finish(() => resolve(result)),
      (error) => finish(() => reject(error)),
    )
  })
}

async function apiGet<T>(path: string): Promise<T> {
  const token = useAuthStore.getState().token
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}
