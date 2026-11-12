// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatTextAttachments } from './useChatTextAttachments'
import { chatTextsApi } from '../api/chatTexts'
import { ApiError } from '../api/client'
import type { ChatTextAttachment } from '../types'

const attachment: ChatTextAttachment = { id: 'text-1', document_id: 1, session_id: 10, message_id: null,
  filename: '资料.txt', size: 12000, characters: 4000, lines: 1, sha256: 'abc' }
let current: ReturnType<typeof useChatTextAttachments>
let root: Root
let container: HTMLDivElement
function Harness({ id }: { id: number }) { current = useChatTextAttachments(id, id * 10); return null }
async function render(id = 1) { await act(async () => root.render(<Harness id={id} />)) }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.spyOn(chatTextsApi, 'listDrafts').mockResolvedValue([])
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('retains failed upload text for retry then drops the body after success', async () => {
  const upload = vi.spyOn(chatTextsApi, 'upload').mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(attachment)
  await render()
  await act(async () => { current.paste('正文'.repeat(4000)) })
  expect(current.items[0]?.status).toBe('error')
  expect(current.items[0]?.pendingText).toBeTruthy()
  await act(async () => { await current.retry(current.items[0]!) })
  expect(upload).toHaveBeenCalledTimes(2)
  expect(current.items[0]?.status).toBe('ready')
  expect(current.items[0]?.pendingText).toBeUndefined()
})

it('ignores an old upload and callbacks after navigating away and returning', async () => {
  let resolve!: (value: ChatTextAttachment) => void
  vi.spyOn(chatTextsApi, 'upload').mockReturnValue(new Promise(done => { resolve = done }))
  await render()
  const old = current
  await act(async () => { current.paste('正文'.repeat(4000)) })
  await render(2)
  await render(1)
  await act(async () => { resolve(attachment); old.restore([attachment]); old.paste('old text') })
  expect(current.items).toEqual([])
})

it('keeps detached queue attachments out of reload and allows explicit restore', async () => {
  vi.mocked(chatTextsApi.listDrafts).mockResolvedValue([attachment])
  await render()
  await act(async () => current.detach([attachment]))
  await act(async () => { await current.reload() })
  expect(current.items).toEqual([])
  await act(async () => current.restore([attachment, { ...attachment, id: 'foreign', session_id: 99 }]))
  expect(current.items.map(item => item.id)).toEqual(['text-1'])
})

it('exposes restore failure and recovers without discarding local drafts', async () => {
  vi.mocked(chatTextsApi.listDrafts).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([attachment])
  await render()
  expect(current.loadError).toContain('重试加载')
  await act(async () => { await current.reload() })
  expect(current.loadError).toBe('')
  expect(current.items).toHaveLength(1)
})

it('allows removing a retry reference already bound by an accepted POST', async () => {
  vi.mocked(chatTextsApi.listDrafts).mockResolvedValue([attachment])
  vi.spyOn(chatTextsApi, 'remove').mockRejectedValue(new ApiError(409, '已发送文本附件不能单独删除'))
  await render()
  await act(async () => { await current.remove(current.items[0]!) })
  expect(current.items).toEqual([])
})
