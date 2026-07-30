import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { clearChatComposerDraft, readChatComposerDraft, writeChatComposerDraft } from './chatComposerDraft'

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
})
