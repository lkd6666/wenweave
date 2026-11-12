import { ApiError, apiUpload as uploadForm, authenticatedFetch } from './client'
import type { UploadOptions } from './client'
import { retryRequest } from '../utils/retry'
import type { RetryStatus } from '../utils/retry'
import type { AgentRunStatus, AssistantTurnBlock, ChangeSummary, ChatContextCompactResult, ChatContextStats, ChatHistoryArchive, ChatImageAttachment, ChatMessageItem, ChatSessionItem, ChatUserQuestion, ContextCompaction, LayoutReferenceImitationStrength, ReadRange, ReasoningTrace, SelectedElementContext, ToolActivity, ToolExecution } from '../types'

export const MAX_CHAT_IMAGES_PER_MESSAGE = 100
import { sanitizeSelectedElements } from '../utils/selectedElements'

const API_BASE = '/api'
const STREAM_CONNECT_TIMEOUT_MS = 20_000
// Creating a run includes resource preparation and context preflight. Give
// that work its own deadline instead of the short status/SSE connect timeout.
const START_RUN_TIMEOUT_MS = 3 * 60_000
const QUESTION_ANSWER_TIMEOUT_MS = 20_000
// The backend emits a transport heartbeat every 10 seconds. Keep this as a
// long silent-connection guard, not a limit on model/tool generation time.
const STREAM_INACTIVITY_TIMEOUT_MS = 5 * 60_000
const CANCEL_REQUEST_TIMEOUT_MS = 10_000

export type ChatStreamEvent =
  | { event: 'retry_status'; data: RetryStatus }
  | { event: 'text_delta'; data: { text: string; _transient?: boolean } }
  | { event: 'reasoning_delta'; data: { text: string; _transient?: boolean } }
  | { event: 'tool_call'; data: { id?: string; replaces_id?: string; name: string; arguments: ToolExecution['arguments']; preparing?: boolean; argument_tokens?: number } }
  | { event: 'user_question'; data: ChatUserQuestion }
  | {
      event: 'tool_result'
      data: { id?: string; name: string; result: string; html?: string; read_range?: ReadRange; change_summary?: ChangeSummary; activity?: ToolActivity; model_input?: ToolExecution['model_input'] }
    }
  | { event: 'agent_status'; data: { thinking: { requested: ThinkingMode; applied: boolean; detail: string } } }
  | {
      event: 'thinking_capability_fallback'
      data: { model_id: number; message: string; reason: string; fallback_mode: 'auto' }
    }
  | { event: 'heartbeat'; data: { status?: AgentRunStatus; idle_seconds?: number; detail?: string; phase?: string; turn?: number } }
  | {
      event: 'model_turn_retry'
      data: {
        turn?: number
        attempt: number
        max_attempts: number
        remaining_attempts: number
        delay_seconds: number
        retry_after_seconds?: number
        reason: string
        detail: string
      }
    }
  | { event: 'context_stats'; data: ChatContextStats }
  | { event: 'context_compaction'; data: ContextCompaction & { id?: string } }
  | {
      event: 'final'
      data: {
        content: string
        html: string
        html_changed: boolean
        compliance: unknown
        partial?: boolean
        partial_save_state?: 'none' | 'preserved' | 'conflict' | 'unavailable'
        run_status?: AgentRunStatus
        error_message?: string
      }
    }
  | { event: 'error'; data: { message: string } }

export interface AgentRunTimeline {
  tool_calls: ToolExecution[]
  reasoning: ReasoningTrace
  turn_blocks: AssistantTurnBlock[]
}

export interface AgentRunInfo {
  run_id: string
  session_id: number
  status: AgentRunStatus
  user_message_id: number
  assistant_message_id: number | null
  error_message: string
  event_sequence: number
  timeline?: AgentRunTimeline | null
  reask_activation?: { archive_id: number; source_message_id: number; current_html: string } | null
  user_question?: ChatUserQuestion | null
}

export type UserQuestionAnswer =
  | { action: 'select'; optionIds: string[] }
  | { action: 'custom'; customRequirement: string }
  | { action: 'skip' }

export interface ReaskDocumentConflict {
  code: 'reask_document_conflict'
  message: string
  current_checksum: string
}

export interface ReaskSourceUnavailable {
  code: 'reask_source_unavailable'
  message: string
}

export interface ReaskConflictResolution {
  resolution: 'discard_current_changes'
  currentChecksum: string
}

export function reaskDocumentConflictFromError(error: unknown): ReaskDocumentConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail || typeof error.detail !== 'object') return null
  const detail = error.detail as Partial<ReaskDocumentConflict>
  if (
    detail.code !== 'reask_document_conflict'
    || typeof detail.message !== 'string'
    || typeof detail.current_checksum !== 'string'
  ) return null
  return { code: detail.code, message: detail.message, current_checksum: detail.current_checksum }
}

export function reaskSourceUnavailableFromError(error: unknown): ReaskSourceUnavailable | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail || typeof error.detail !== 'object') return null
  const detail = error.detail as Partial<ReaskSourceUnavailable>
  if (detail.code !== 'reask_source_unavailable' || typeof detail.message !== 'string') return null
  return { code: detail.code, message: detail.message }
}

export type SequencedChatStreamEvent = ChatStreamEvent & { sequence: number; eventAgeMs: number }

export type ThinkingMode = 'auto' | 'enabled' | 'disabled'
export type ThinkingEffort = 'auto' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

class StreamInactivityError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'StreamInactivityError'
  }
}

export function parseSseChunk(buffer: string): { events: SequencedChatStreamEvent[]; rest: string } {
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
      const rawData = JSON.parse(dataStr) as unknown
      if (!rawData || typeof rawData !== 'object' || Array.isArray(rawData)) continue
      const parsedData = { ...rawData } as Record<string, unknown>
      const rawEventAgeMs = parsedData._event_age_ms
      delete parsedData._event_age_ms
      events.push({
        sequence: eventId,
        eventAgeMs: typeof rawEventAgeMs === 'number' && Number.isFinite(rawEventAgeMs)
          ? Math.max(0, rawEventAgeMs)
          : 0,
        event: eventName as ChatStreamEvent['event'],
        data: parsedData,
      } as SequencedChatStreamEvent)
    } catch {
      // 忽略无法解析的片段
    }
  }
  return { events, rest }
}

export async function startChatRun(
  documentId: number,
  sessionId: number,
  message: string,
  modelId: number,
  thinkingMode: ThinkingMode,
  thinkingEffort: ThinkingEffort,
  clientRequestId: string,
  selectedElements?: SelectedElementContext[],
  layoutReferenceId?: string,
  gzhThemeProposalId?: string,
  layoutReferenceAssetsConfirmed?: boolean,
  imageAttachmentIds: string[] = [],
  layoutReferenceSelectedAssetIds: string[] = [],
  layoutReferenceImitationStrength: LayoutReferenceImitationStrength = 'structure',
  templateIds?: number[],
  reaskFromMessageId?: number,
  reaskConflictResolution?: ReaskConflictResolution,
  signal?: AbortSignal,
  onRetry?: (status: RetryStatus) => void,
  textAttachmentIds: string[] = [],
): Promise<AgentRunInfo> {
  let confirmBeforeRetry = false
  return retryRequest(async () => {
      if (confirmBeforeRetry) {
        // A lost response can hide a successful creation. Read its durable
        // result before replaying the POST, using the same idempotency key.
        const existing = await chatApi.getRunByClientRequest(documentId, clientRequestId, signal)
        if (existing) return existing
      }
      signal?.throwIfAborted()
      confirmBeforeRetry = true
      const res = await fetchWithTimeout(
        `${API_BASE}/documents/${documentId}/chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message,
            model_id: modelId,
            session_id: sessionId,
            client_request_id: clientRequestId,
            thinking_mode: thinkingMode,
            thinking_effort: thinkingEffort,
            selected_elements: sanitizeSelectedElements(selectedElements ?? []),
            ...(templateIds !== undefined ? { template_ids: templateIds.slice(0, 6) } : {}),
            image_attachment_ids: imageAttachmentIds,
            text_attachment_ids: textAttachmentIds,
            ...(layoutReferenceId ? { layout_reference_id: layoutReferenceId } : {}),
            ...(layoutReferenceId ? { layout_reference_assets_confirmed: Boolean(layoutReferenceAssetsConfirmed) } : {}),
            ...(layoutReferenceId ? { layout_reference_selected_asset_ids: layoutReferenceSelectedAssetIds } : {}),
            ...(layoutReferenceId ? { layout_reference_imitation_strength: layoutReferenceImitationStrength } : {}),
            ...(gzhThemeProposalId ? { gzh_theme_proposal_id: gzhThemeProposalId } : {}),
            ...(reaskFromMessageId ? { reask_from_message_id: reaskFromMessageId } : {}),
            ...(reaskConflictResolution ? {
              reask_conflict_resolution: reaskConflictResolution.resolution,
              reask_conflict_checksum: reaskConflictResolution.currentChecksum,
            } : {}),
          }),
          signal,
        },
        START_RUN_TIMEOUT_MS,
        '创建 Agent 运行超时，正在确认请求状态',
      )
      if (!res.ok) {
        let detail: unknown = res.statusText
        try {
          const data = await res.json()
          detail = data.detail ?? data
        } catch {
          // Ignore a malformed error payload.
        }
        throw new ApiError(res.status, detail, res.headers)
      }
      return await res.json() as AgentRunInfo
  }, {
    scope: 'start', signal, onRetry, maxAttempts: 3, maxElapsedMs: 10 * 60_000,
    baseMs: 10_000, maxDelayMs: 60_000,
  })
}

export async function* streamChatRunEvents(
  documentId: number,
  runId: string,
  after: number,
  signal?: AbortSignal,
): AsyncGenerator<SequencedChatStreamEvent> {
  const res = await fetchWithTimeout(
    `${API_BASE}/documents/${documentId}/chat-runs/${runId}/events?after=${after}`,
    { signal },
    STREAM_CONNECT_TIMEOUT_MS,
    '建立实时输出连接超时',
  )
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Ignore a malformed error payload.
    }
    throw new ApiError(res.status, detail, res.headers)
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
    // A question/final event can end consumption while the SSE response is
    // still open. Releasing the lock alone keeps the network body buffering;
    // explicitly cancel it on early exit and on local abort.
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

export async function cancelChatRun(documentId: number, runId: string,
  onRetry?: (status: RetryStatus) => void): Promise<AgentRunInfo> {
  return retryRequest(async () => {
  const res = await fetchWithTimeout(
    `${API_BASE}/documents/${documentId}/chat-runs/${runId}/cancel`,
    {
      method: 'POST',
    },
    CANCEL_REQUEST_TIMEOUT_MS,
    '停止请求超时，请重试',
  )
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Ignore a malformed error payload.
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return await res.json() as AgentRunInfo
  }, { scope: 'cancel', onRetry, maxElapsedMs: 35_000, maxDelayMs: 5000 })
}

export async function answerChatUserQuestion(
  documentId: number,
  runId: string,
  questionId: string,
  answer: UserQuestionAnswer,
  clientRequestId: string,
  onRetry?: (status: RetryStatus) => void,
): Promise<AgentRunInfo> {
  const body = answer.action === 'select'
    ? { action: answer.action, option_ids: answer.optionIds, client_request_id: clientRequestId }
    : answer.action === 'custom'
      ? { action: answer.action, custom_requirement: answer.customRequirement, client_request_id: clientRequestId }
      : { action: answer.action, client_request_id: clientRequestId }
  return retryRequest(() => apiPost<AgentRunInfo>(
    `/documents/${documentId}/chat-runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionId)}/answer`,
    body,
    undefined,
    QUESTION_ANSWER_TIMEOUT_MS,
  ), { scope: 'question', onRetry, maxElapsedMs: 90_000 })
}

export async function recordChatUserQuestionActivity(
  documentId: number,
  runId: string,
  questionId: string,
): Promise<{ timeout_at: string | null }> {
  return apiPost<{ timeout_at: string | null }>(
    `/documents/${documentId}/chat-runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionId)}/activity`,
    {},
  )
}

export const chatApi = {
  listSessions: (documentId: number, includeArchived = true) => apiGet<ChatSessionItem[]>(`/documents/${documentId}/chat-sessions?include_archived=${includeArchived}`),
  createSession: (documentId: number, title = '新对话') => apiPost<ChatSessionItem>(`/documents/${documentId}/chat-sessions`, { title }),
  updateImageSettings: (documentId: number, sessionId: number, payload: { image_model_id: number | null }) => apiPatch<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}/image-settings`, payload),
  renameSession: (documentId: number, sessionId: number, title: string) => apiPatch<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}`, { title }),
  archiveSession: (documentId: number, sessionId: number) => apiPost<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}/archive`, {}),
  restoreSession: (documentId: number, sessionId: number) => apiPost<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}/restore`, {}),
  truncateSession: (documentId: number, sessionId: number) => apiPost<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}/truncate`, {}),
  restoreSessionContext: (documentId: number, sessionId: number) => apiPost<ChatSessionItem>(`/documents/${documentId}/chat-sessions/${sessionId}/restore-context`, {}),
  clearLayoutReference: (documentId: number, sessionId: number) => apiDelete<void>(`/documents/${documentId}/chat-sessions/${sessionId}/layout-reference`),
  replaceTemplateAttachments: (documentId: number, sessionId: number, templateIds: number[]) => apiPut<ChatSessionItem>(
    `/documents/${documentId}/chat-sessions/${sessionId}/template-attachments`,
    { template_ids: templateIds.slice(0, 6) },
  ),
  removeTemplateAttachment: (documentId: number, sessionId: number, templateId: number) => apiDelete<ChatSessionItem>(
    `/documents/${documentId}/chat-sessions/${sessionId}/template-attachments/${encodeURIComponent(templateId)}`,
  ),
  clearThemeContext: (documentId: number, sessionId: number) => apiDelete<ChatSessionItem>(
    `/documents/${documentId}/chat-sessions/${sessionId}/theme-context`,
  ),
  listMessages: (documentId: number, sessionId: number, includeHidden = false) => apiGet<ChatMessageItem[]>(
    `/documents/${documentId}/messages?session_id=${encodeURIComponent(sessionId)}&include_hidden=${includeHidden}`,
  ),
  listRecentMessages: (documentId: number, sessionId: number, limit: number, beforeId?: number) => apiGet<ChatMessageItem[]>(
    `/documents/${documentId}/messages?session_id=${encodeURIComponent(sessionId)}&limit=${encodeURIComponent(limit)}${beforeId === undefined ? '' : `&before_id=${encodeURIComponent(beforeId)}`}`,
  ),
  listHistoryArchives: (documentId: number, sessionId: number) => apiGet<ChatHistoryArchive[]>(
    `/documents/${documentId}/chat-sessions/${sessionId}/history-archives`,
  ),
  listHistoryArchiveMessages: (documentId: number, sessionId: number, archiveId: number) => apiGet<ChatMessageItem[]>(
    `/documents/${documentId}/chat-sessions/${sessionId}/history-archives/${archiveId}/messages`,
  ),
  getActiveRun: (documentId: number, signal?: AbortSignal, onRetry?: (status: RetryStatus) => void) => retryRequest(
    () => apiGet<AgentRunInfo | null>(`/documents/${documentId}/chat-runs/active`, signal),
    { scope: 'stream', signal, onRetry },
  ),
  getRunByClientRequest: (documentId: number, clientRequestId: string, signal?: AbortSignal) => apiGet<AgentRunInfo | null>(
    `/documents/${documentId}/chat-runs/by-client-request/${encodeURIComponent(clientRequestId)}`,
    signal,
  ),
  getRun: (documentId: number, runId: string, signal?: AbortSignal) => retryRequest(
    () => apiGet<AgentRunInfo>(`/documents/${documentId}/chat-runs/${runId}`, signal),
    { scope: 'stream', signal },
  ),
  answerUserQuestion: answerChatUserQuestion,
  recordUserQuestionActivity: recordChatUserQuestionActivity,
  getContext: (documentId: number, modelId: number, sessionId: number) => apiGet<ChatContextStats>(`/documents/${documentId}/chat-context?model_id=${encodeURIComponent(modelId)}&session_id=${encodeURIComponent(sessionId)}`),
  previewContext: (documentId: number, modelId: number, sessionId: number, message: string, selectedElements: SelectedElementContext[], imageAttachmentIds: string[] = [], templateIds: number[] = [], signal?: AbortSignal, textAttachmentIds: string[] = []) => apiPost<ChatContextStats>(
    `/documents/${documentId}/chat-context/preview`,
    {
      model_id: modelId,
      session_id: sessionId,
      message,
      selected_elements: sanitizeSelectedElements(selectedElements),
      image_attachment_ids: imageAttachmentIds,
      text_attachment_ids: textAttachmentIds,
      template_ids: templateIds.slice(0, 6),
    },
    signal,
  ),
  compactContext: compactChatContext,
  uploadImage: (documentId: number, file: File, options?: UploadOptions) => apiUpload<ChatImageAttachment>(`/documents/${documentId}/chat-images`, file, options),
  duplicateImage: (documentId: number, attachmentId: string) => apiPost<ChatImageAttachment>(
    `/documents/${documentId}/chat-images/${encodeURIComponent(attachmentId)}/duplicate`,
    {},
  ),
  deleteImage: (documentId: number, attachmentId: string) => apiDelete<void>(`/documents/${documentId}/chat-images/${encodeURIComponent(attachmentId)}`),
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
  const timer = globalThis.setTimeout(
    () => controller.abort(new StreamInactivityError(timeoutMessage)),
    timeoutMs,
  )
  try {
    return await authenticatedFetch(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (controller.signal.reason instanceof StreamInactivityError) throw controller.signal.reason
    throw error
  } finally {
    globalThis.clearTimeout(timer)
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
      globalThis.clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      callback()
    }
    const onAbort = () => finish(() => reject(signal?.reason ?? new DOMException('请求已取消', 'AbortError')))
    const timer = globalThis.setTimeout(() => {
      void reader.cancel().catch(() => undefined)
      finish(() => reject(new StreamInactivityError('实时连接长时间没有数据，正在重新连接')))
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

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetchWithTimeout(`${API_BASE}${path}`, { signal }, STREAM_CONNECT_TIMEOUT_MS, '读取任务状态超时')
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return (await res.json()) as T
}

async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal, timeoutMs?: number): Promise<T> {
  const init: RequestInit = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    signal,
  }
  const res = timeoutMs
    ? await fetchWithTimeout(`${API_BASE}${path}`, init, timeoutMs, '提交确认结果超时，正在确认请求状态')
    : await authenticatedFetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return (await res.json()) as T
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await authenticatedFetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return (await res.json()) as T
}

async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await authenticatedFetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return (await res.json()) as T
}

async function apiUpload<T>(path: string, file: File, options?: UploadOptions): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  return uploadForm<T>(path, body, options)
}

async function apiDelete<T>(path: string): Promise<T> {
  const res = await authenticatedFetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204 || !res.headers.get('content-type')?.includes('application/json')) {
    return undefined as T
  }
  return await res.json() as T
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown = res.statusText
  try {
    const data = await res.json()
    detail = data.detail ?? data
  } catch {
    // Use the transport status when the server did not return JSON.
  }
  return new ApiError(res.status, detail, res.headers)
}


async function compactChatContext(documentId: number, modelId: number, sessionId: number, rebuild = false,
  onRetry?: (status: RetryStatus) => void, signal?: AbortSignal): Promise<ChatContextCompactResult> {
  // The backend owns compaction retries. Replaying this POST after a lost
  // response could create another snapshot, so only reconnect normal runs.
  const res = await fetchWithTimeout(`${API_BASE}/documents/${documentId}/chat-context/compact?stream=true`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId, session_id: sessionId, rebuild }), signal,
  }, STREAM_CONNECT_TIMEOUT_MS, '建立压缩进度连接超时')
  if (!res.ok) throw await toApiError(res)
  if (!res.headers.get('content-type')?.includes('text/event-stream')) return await res.json()
  const reader = res.body?.getReader()
  if (!reader) throw new Error('浏览器不支持流式响应')
  let buffer = ''
  const decoder = new TextDecoder()
  try {
    while (true) {
      const { done, value } = await readWithInactivityTimeout(reader, signal)
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const parsed = parseSseChunk(buffer + (done ? '\n\n' : ''))
      buffer = parsed.rest
      for (const event of parsed.events) {
        if (event.event === 'retry_status') onRetry?.(event.data)
        if (event.event === 'error') throw new ApiError(('status' in event.data ? Number(event.data.status) : 502), event.data.message)
        if (event.event === 'context_stats') return event.data as ChatContextCompactResult
      }
      if (done) throw new Error('压缩进度连接中断，请刷新上下文状态后再试')
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
