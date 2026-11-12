import type { ChatTextAttachment } from '../types'
import type { TemplateReference } from './templateReferences'

export type ChatComposerDraftPhase = 'editing' | 'starting' | 'running' | 'retry'

export interface ChatComposerDraft {
  message: string
  reaskFromMessageId: number | null
  phase: ChatComposerDraftPhase
  clientRequestId?: string
  runId?: string
  textAttachments?: ChatTextAttachment[]
  templateRefs?: TemplateReference[]
}

const STORAGE_PREFIX = 'yibanpaiban-chat-composer-draft:v1'

function storageKey(documentId: number, sessionId: number): string {
  return `${STORAGE_PREFIX}:${documentId}:${sessionId}`
}

function safeAttachments(value: unknown): ChatTextAttachment[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ChatTextAttachment => Boolean(item && typeof item.id === 'string'
    && Number.isSafeInteger(item.document_id) && Number.isSafeInteger(item.session_id)
    && (item.message_id === null || Number.isSafeInteger(item.message_id)) && typeof item.filename === 'string'
    && Number.isFinite(item.size) && Number.isFinite(item.characters) && Number.isFinite(item.lines)
    && typeof item.sha256 === 'string' && item.status !== 'uploading' && item.status !== 'error'))
    .slice(0, 8).map(({ id, document_id, session_id, message_id, filename, size, characters, lines, sha256 }) =>
      ({ id, document_id, session_id, message_id, filename, size, characters, lines, sha256 }))
}

function safeTemplateReferences(value: unknown): TemplateReference[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is TemplateReference => Boolean(item
    && Number.isSafeInteger(item.id) && item.id > 0 && typeof item.name === 'string'))
    .slice(0, 6).map(({ id, name }) => ({ id, name }))
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
    return isDraft(parsed) ? { ...parsed, templateRefs: safeTemplateReferences(parsed.templateRefs), textAttachments: safeAttachments(parsed.textAttachments).filter(item => item.document_id === documentId && item.session_id === sessionId) } : null
  } catch {
    return null
  }
}

export function writeChatComposerDraft(documentId: number, sessionId: number, draft: ChatComposerDraft): void {
  try {
    window.sessionStorage.setItem(storageKey(documentId, sessionId), JSON.stringify({ ...draft, templateRefs: safeTemplateReferences(draft.templateRefs), textAttachments: safeAttachments(draft.textAttachments) }))
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

/** Removes only the draft that belongs to the completed request. */
export function clearChatComposerDraftForRequest(documentId: number, sessionId: number, clientRequestId: string): boolean {
  const draft = readChatComposerDraft(documentId, sessionId)
  if (!clientRequestId || draft?.clientRequestId !== clientRequestId) return false
  clearChatComposerDraft(documentId, sessionId)
  return true
}
