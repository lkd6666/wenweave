// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

type RuntimeListener = (
  message: unknown,
  sender: chrome.runtime.MessageSender,
  sendResponse: (response?: unknown) => void,
) => boolean | undefined

afterEach(() => {
  document.body.replaceChildren()
  delete (globalThis as typeof globalThis & { __yibanpaibanWechatCaptureInstalled__?: boolean })
    .__yibanpaibanWechatCaptureInstalled__
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('WeChat capture content script', () => {
  it('opens the task panel on the associated article and reports live progress', async () => {
    document.body.innerHTML = `
      <div id="js_content">公众号正文</div>
      <aside id="yibanpaiban-layout-capture-panel" data-state="success"></aside>
    `
    const listeners: RuntimeListener[] = []
    const sendMessage = vi.fn(async (message: { type?: string }) => {
      if (message.type === 'layoutCapture:getArticleTask') {
        return {
          ok: true,
          active: true,
          running: false,
          session: {
            id: 'capture-1',
            canonical_url: 'https://mp.weixin.qq.com/s/article',
            expires_at: '2026-08-15T08:00:00Z',
          },
        }
      }
      if (message.type === 'layoutCapture:begin') return { ok: true }
      return { ok: false }
    })
    vi.stubGlobal('chrome', {
      runtime: {
        sendMessage,
        onMessage: { addListener: (listener: RuntimeListener) => listeners.push(listener) },
      },
    })

    await import('./wechatCapture')
    await vi.waitFor(() => {
      expect(document.querySelector('#yibanpaiban-layout-capture-panel')).not.toBeNull()
    })

    expect(document.querySelectorAll('#yibanpaiban-layout-capture-panel')).toHaveLength(1)
    const host = document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!
    expect(host.dataset.state).toBe('ready')
    expect(host.shadowRoot!.textContent).toContain('已检测到文章正文')
    host.shadowRoot!.querySelector<HTMLButtonElement>('.start')!.click()
    await vi.waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith({ type: 'layoutCapture:begin' })
    })

    listeners[0]?.({
      type: 'layoutCapture:articleEvent',
      sessionId: 'capture-1',
      status: 'downloading',
    }, {} as chrome.runtime.MessageSender, vi.fn())
    expect(host.dataset.state).toBe('downloading')
    expect(host.shadowRoot!.textContent).toContain('处理图片素材')

    listeners[0]?.({
      type: 'layoutCapture:articleEvent',
      sessionId: 'capture-1',
      status: 'success',
    }, {} as chrome.runtime.MessageSender, vi.fn())
    expect(host.dataset.state).toBe('success')
    expect(host.shadowRoot!.textContent).toContain('预览已经回传')

    listeners[0]?.({
      type: 'layoutCapture:articleEvent',
      sessionId: 'capture-2',
      status: 'ready',
      canonicalUrl: 'https://mp.weixin.qq.com/s/article',
    }, {} as chrome.runtime.MessageSender, vi.fn())
    expect(host.dataset.state).toBe('ready')
    expect(host.shadowRoot!.textContent).toContain('已检测到文章正文')
    expect(host.shadowRoot!.querySelector<HTMLButtonElement>('.start')!.hidden).toBe(false)

    host.shadowRoot!.querySelector<HTMLButtonElement>('.start')!.click()
    await vi.waitFor(() => {
      expect(sendMessage.mock.calls.filter(([message]) => message.type === 'layoutCapture:begin')).toHaveLength(2)
    })
  })
})
