import { useCallback, useEffect, useRef, useState } from 'react'
import { chatTextsApi } from '../api/chatTexts'
import { ApiError } from '../api/client'
import type { ChatTextAttachment, ChatTextAttachmentDraft } from '../types'
import { MAX_TEXT_ATTACHMENT_BYTES, MAX_TEXT_ATTACHMENTS, pastedTextName } from '../utils/textAttachments'
import { useOperationScope } from './useOperationScope'

export function useChatTextAttachments(documentId: number | undefined, sessionId: number | null) {
  const key = `${documentId}:${sessionId}`
  const ownsScope = useOperationScope(key)
  const [state, setState] = useState<{ key: string; items: ChatTextAttachmentDraft[]; error: string }>({ key, items: [], error: '' })
  const items = state.key === key ? state.items : []
  const itemsRef = useRef(items)
  itemsRef.current = items
  const detached = useRef(new Set<string>())
  const update = useCallback((change: (current: ChatTextAttachmentDraft[]) => ChatTextAttachmentDraft[]) => {
    if (!ownsScope()) return
    itemsRef.current = change(itemsRef.current)
    const next = itemsRef.current
    setState(current => ({ key, items: next, error: current.key === key ? current.error : '' }))
  }, [key, ownsScope])
  const controllers = useRef(new Set<AbortController>())
  const reload = useCallback(async () => {
    if (!documentId || !sessionId || !ownsScope()) return
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const rows = await chatTextsApi.listDrafts(documentId, sessionId, controller.signal)
      if (!ownsScope()) return
      update(current => [...current, ...rows.filter(row => !detached.current.has(row.id) && !current.some(item => item.id === row.id))])
      setState(current => ({ ...current, error: '' }))
    } catch {
      if (ownsScope() && !controller.signal.aborted) setState(current => ({ key, items: current.key === key ? current.items : [], error: '未能恢复未发送文本附件，可重试加载。' }))
    } finally { controllers.current.delete(controller) }
  }, [documentId, sessionId, key, ownsScope, update])

  useEffect(() => {
    detached.current = new Set()
    setState({ key, items: [], error: '' })
    itemsRef.current = []
    void reload()
    const activeControllers = controllers.current
    return () => { activeControllers.forEach(controller => controller.abort()); activeControllers.clear() }
  }, [key, reload])

  const upload = useCallback(async (item: ChatTextAttachmentDraft) => {
    if (!documentId || !sessionId || !item.pendingText || !ownsScope()) return
    const controller = new AbortController()
    controllers.current.add(controller)
    update(current => current.map(row => row.id === item.id ? { ...row, status: 'uploading', error: undefined } : row))
    try {
      const ready = await chatTextsApi.upload(documentId, sessionId, item.pendingText, item.filename, controller.signal)
      if (!ownsScope()) return
      update(current => current.map(row => row.id === item.id ? { ...ready, status: 'ready' } : row))
    } catch (error) {
      if (!ownsScope()) return
      update(current => current.map(row => row.id === item.id ? { ...row, status: 'error', error: error instanceof Error ? error.message : '上传失败，可重试' } : row))
    } finally { controllers.current.delete(controller) }
  }, [documentId, sessionId, ownsScope, update])

  const paste = useCallback((text: string) => {
    if (!documentId || !sessionId || !ownsScope()) return false
    const item: ChatTextAttachmentDraft = { id: `pending-${crypto.randomUUID()}`, document_id: documentId, session_id: sessionId,
      message_id: null, filename: pastedTextName(), size: new TextEncoder().encode(text).length,
      characters: text.length, lines: text.split('\n').length, sha256: '', status: 'uploading', pendingText: text }
    if (item.size > MAX_TEXT_ATTACHMENT_BYTES) throw new Error('单份文本附件不能超过 2MB，原文已保留在剪贴板中')
    if (itemsRef.current.length >= MAX_TEXT_ATTACHMENTS) throw new Error('每条消息最多 8 份文本附件，请先发送或移除已有附件')
    update(current => [...current, item])
    void upload(item)
    return true
  }, [documentId, sessionId, ownsScope, update, upload])

  const detach = useCallback((sent: ChatTextAttachment[]) => {
    if (!ownsScope()) return
    sent.forEach(item => detached.current.add(item.id))
    update(current => current.filter(item => !sent.some(row => row.id === item.id)))
  }, [ownsScope, update])
  const restore = useCallback((sent: ChatTextAttachment[]) => {
    if (!ownsScope()) return
    const matching = sent.filter(row => row.document_id === documentId && row.session_id === sessionId)
    matching.forEach(item => detached.current.delete(item.id))
    update(current => [...current, ...matching.filter(row => !current.some(item => item.id === row.id))])
  }, [documentId, sessionId, ownsScope, update])
  const remove = useCallback(async (item: ChatTextAttachmentDraft) => {
    if (!ownsScope() || item.status === 'uploading') return
    if (!item.pendingText && item.message_id === null) {
      try { await chatTextsApi.remove(item.document_id, item.id) }
      catch (error) {
        // An accepted POST may have bound a restored reference while the UI
        // still holds draft metadata. Detach it without deleting history.
        if (!(error instanceof ApiError) || error.status !== 409) throw error
      }
    }
    if (ownsScope()) detach([item])
  }, [ownsScope, detach])
  return { items, paste, detach, restore, remove, retry: upload, reload, loadError: state.key === key ? state.error : '' }
}
