export type ChatComposerDraftPhase = 'editing' | 'starting' | 'running' | 'retry'

export interface ChatComposerDraft {
  message: string
  reaskFromMessageId: number | null
  phase: ChatComposerDraftPhase
  clientRequestId?: string
  runId?: string
}

const STORAGE_PREFIX = 'yibanpaiban-chat-composer-draft:v1'

function storageKey(documentId: number, sessionId: number): string {
  return `${STORAGE_PREFIX}:${documentId}:${sessionId}`
}

function isDraft(value: unknown): value is ChatComposerDraft {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ChatComposerDraft>
  return typeof item.message === 'string'
    && (item.reaskFromMessageId === null || (typeof item.reaskFromMessageId === 'number' && Number.isSafeInteger(item.reaskFromMessageId) && item.reaskFromMessageId > 0))
    && ['editing', 'starting', 'running', 'retry'].includes(String(item.phase))
    && (item.clientRequestId === undefined || typeof item.clientRequestId === 'string')
    && (item.runId === undefined || typeof item.runId === 'string')
}

export function readChatComposerDraft(documentId: number, sessionId: number): ChatComposerDraft | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(documentId, sessionId))
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isDraft(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function writeChatComposerDraft(documentId: number, sessionId: number, draft: ChatComposerDraft): void {
  try {
    window.sessionStorage.setItem(storageKey(documentId, sessionId), JSON.stringify(draft))
  } catch {
    // The in-memory composer stays usable when browser storage is unavailable.
  }
}

export function clearChatComposerDraft(documentId: number, sessionId: number): void {
  try {
    window.sessionStorage.removeItem(storageKey(documentId, sessionId))
  } catch {
    // Storage cleanup must never prevent a completed conversation from rendering.
  }
}
