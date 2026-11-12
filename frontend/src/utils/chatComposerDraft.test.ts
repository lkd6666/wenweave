import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { clearChatComposerDraft, clearChatComposerDraftForRequest, readChatComposerDraft, writeChatComposerDraft } from './chatComposerDraft'

describe('chat composer draft storage', () => {
  const originalWindow = globalThis.window
  const values = new Map<string, string>()

  beforeEach(() => {
    values.clear()
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        sessionStorage: {
          getItem: (key: string) => values.get(key) ?? null,
          setItem: (key: string, value: string) => values.set(key, value),
          removeItem: (key: string) => values.delete(key),
          clear: () => values.clear(),
        },
      },
    })
  })

  afterEach(() => {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: originalWindow })
  })

  it('keeps drafts isolated by document and conversation', () => {
    writeChatComposerDraft(12, 4, { message: '调整标题', reaskFromMessageId: 8, phase: 'retry', clientRequestId: 'request-a' })
    writeChatComposerDraft(12, 5, { message: '调整正文', reaskFromMessageId: null, phase: 'editing' })

    expect(readChatComposerDraft(12, 4)?.message).toBe('调整标题')
    expect(readChatComposerDraft(12, 5)?.message).toBe('调整正文')
    expect(readChatComposerDraft(13, 4)).toBeNull()
  })

  it('rejects malformed saved values and clears a completed draft', () => {
    window.sessionStorage.setItem('yibanpaiban-chat-composer-draft:v1:8:2', '{not-json')
    expect(readChatComposerDraft(8, 2)).toBeNull()

    writeChatComposerDraft(8, 2, { message: '保留这条指令', reaskFromMessageId: null, phase: 'running', runId: 'run-1' })
    clearChatComposerDraft(8, 2)
    expect(readChatComposerDraft(8, 2)).toBeNull()
  })

  it('does not clear a newer draft when an earlier request completes', () => {
    writeChatComposerDraft(8, 2, {
      message: '刚输入的下一条指令',
      reaskFromMessageId: null,
      phase: 'editing',
    })

    expect(clearChatComposerDraftForRequest(8, 2, 'completed-request')).toBe(false)
    expect(readChatComposerDraft(8, 2)?.message).toBe('刚输入的下一条指令')

    writeChatComposerDraft(8, 2, {
      message: '已发送的指令',
      reaskFromMessageId: null,
      phase: 'running',
      clientRequestId: 'completed-request',
    })

    expect(clearChatComposerDraftForRequest(8, 2, 'completed-request')).toBe(true)
    expect(readChatComposerDraft(8, 2)).toBeNull()
  })
  it('persists only attachment metadata even when the caller supplies upload state', () => {
    const file = { id: 'text-1', document_id: 12, session_id: 4, message_id: null,
      filename: 'text.txt', size: 100, characters: 100, lines: 1, sha256: 'abc',
      status: 'ready', pendingText: 'PRIVATE_BODY', content: 'PRIVATE_BODY' }
    writeChatComposerDraft(12, 4, { message: '', reaskFromMessageId: null, phase: 'retry', textAttachments: [file] })
    expect([...values.values()].join('')).not.toContain('PRIVATE_BODY')
    expect(readChatComposerDraft(12, 4)?.textAttachments?.[0]?.id).toBe('text-1')
    expect(readChatComposerDraft(12, 5)).toBeNull()
  })

  it('preserves component IDs and order in retry drafts without storing their source', () => {
    writeChatComposerDraft(12, 4, { message: '@组件1 不要改动', reaskFromMessageId: null, phase: 'retry',
      templateRefs: [{ id: 20, name: '排版尾', html: 'PRIVATE_TEMPLATE_SOURCE' } as { id: number; name: string }] })
    expect(readChatComposerDraft(12, 4)?.templateRefs).toEqual([{ id: 20, name: '排版尾' }])
    expect([...values.values()].join('')).not.toContain('PRIVATE_TEMPLATE_SOURCE')
  })

})
