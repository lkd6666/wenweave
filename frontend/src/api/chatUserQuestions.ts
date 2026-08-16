import { ApiError, authenticatedFetch } from './client'
import type { PendingChatUserQuestion } from '../types'

const PENDING_QUESTION_EVENTS_URL = '/api/chat-user-questions/events'

export function parsePendingQuestionsSseChunk(buffer: string): {
  snapshots: PendingChatUserQuestion[][]
  rest: string
} {
  const snapshots: PendingChatUserQuestion[][] = []
  const parts = buffer.split(/\r?\n\r?\n/)
  const rest = parts.pop() ?? ''

  parts.forEach((part) => {
    let eventName = 'message'
    const dataLines: string[] = []
    part.split(/\r?\n/).forEach((line) => {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    })
    if (eventName !== 'pending_questions' || dataLines.length === 0) return
    try {
      const payload = JSON.parse(dataLines.join('\n')) as unknown
      if (Array.isArray(payload)) snapshots.push(payload as PendingChatUserQuestion[])
    } catch {
      // A reconnect delivers a complete snapshot, so a malformed event can be skipped safely.
    }
  })

  return { snapshots, rest }
}

export async function* streamPendingChatUserQuestions(
  signal?: AbortSignal,
): AsyncGenerator<PendingChatUserQuestion[]> {
  const response = await authenticatedFetch(PENDING_QUESTION_EVENTS_URL, {
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const payload = await response.json() as { detail?: unknown }
      detail = payload.detail ?? payload
    } catch {
      // Preserve the HTTP status text when the server did not return JSON.
    }
    throw new ApiError(response.status, detail)
  }
  if (!response.body) throw new ApiError(response.status, '待确认提醒连接未建立')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parsePendingQuestionsSseChunk(buffer)
      buffer = parsed.rest
      for (const snapshot of parsed.snapshots) yield snapshot
    }
    if (buffer.trim()) {
      const parsed = parsePendingQuestionsSseChunk(`${buffer}\n\n`)
      for (const snapshot of parsed.snapshots) yield snapshot
    }
  } finally {
    reader.releaseLock()
  }
}
