import { api, apiRequest } from './client'
import type { ChatTextAttachment } from '../types'

export interface TextAttachmentPage extends ChatTextAttachment {
  content: string
  start: number
  end: number
  next_cursor: number | null
  complete: boolean
}

export const chatTextsApi = {
  listDrafts: (documentId: number, sessionId: number, signal?: AbortSignal) => apiRequest<ChatTextAttachment[]>(`/documents/${documentId}/chat-texts?session_id=${sessionId}`, { signal }),
  upload: (documentId: number, sessionId: number, text: string, filename: string, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('session_id', String(sessionId))
    form.append('file', new File([text], filename, { type: 'text/plain;charset=utf-8' }))
    return api.upload<ChatTextAttachment>(`/documents/${documentId}/chat-texts`, form, { signal })
  },
  read: (documentId: number, id: string, start = 0) => api.get<TextAttachmentPage>(`/documents/${documentId}/chat-texts/${encodeURIComponent(id)}?start=${start}`),
  remove: (documentId: number, id: string) => api.delete<void>(`/documents/${documentId}/chat-texts/${encodeURIComponent(id)}`),
}
