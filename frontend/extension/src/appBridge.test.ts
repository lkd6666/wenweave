// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

const CHANNEL = 'yibanpaiban-layout-capture-v1'

function dispatchAppMessage(type: string, payload: Record<string, unknown> = {}): void {
  window.dispatchEvent(new MessageEvent('message', {
    data: {
      channel: CHANNEL,
      direction: 'app-to-extension',
      nonce: 'nonce-1',
      type,
      ...payload,
    },
    origin: window.location.origin,
    source: window,
  }))
}

afterEach(() => {
  delete (globalThis as typeof globalThis & { __yibanpaibanLayoutCaptureBridgeInstalled__?: boolean })
    .__yibanpaibanLayoutCaptureBridgeInstalled__
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('application bridge content script', () => {
  it('advertises article-import capability in its handshake', async () => {
    vi.stubGlobal('chrome', {
      runtime: {
        id: 'extension-id',
        sendMessage: vi.fn(),
        onMessage: { addListener: vi.fn() },
      },
    })
    vi.stubGlobal('__LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__', [window.location.origin])
    const postMessage = vi.spyOn(window, 'postMessage')

    await import('./appBridge')
    dispatchAppMessage('ping')

    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'pong',
      protocolVersion: 2,
      capabilities: ['layout_reference', 'web_article_import'],
    }), window.location.origin)
  })

  it('does not answer ping and detaches itself after its extension context is invalidated', async () => {
    const runtime = {
      id: undefined as string | undefined,
      sendMessage: vi.fn(),
      onMessage: { addListener: vi.fn() },
    }
    vi.stubGlobal('chrome', { runtime })
    vi.stubGlobal('__LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__', [window.location.origin])
    const postMessage = vi.spyOn(window, 'postMessage')

    await import('./appBridge')
    dispatchAppMessage('ping')
    expect(postMessage).not.toHaveBeenCalled()

    runtime.id = 'restored-extension-context'
    dispatchAppMessage('ping')
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('contains synchronous runtime errors while starting a capture', async () => {
    const sendMessage = vi.fn(() => {
      throw new Error('Extension context invalidated.')
    })
    vi.stubGlobal('chrome', {
      runtime: {
        id: 'extension-id',
        sendMessage,
        onMessage: { addListener: vi.fn() },
      },
    })
    vi.stubGlobal('__LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__', [window.location.origin])
    const postMessage = vi.spyOn(window, 'postMessage')

    await import('./appBridge')
    expect(() => dispatchAppMessage('start', {
      session: {
        id: 'capture-1',
        token: 'capture-token-at-least-20-characters',
        canonical_url: 'https://mp.weixin.qq.com/s/article',
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        purpose: 'layout_reference',
      },
    })).not.toThrow()

    await vi.waitFor(() => {
      expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
        type: 'error',
        sessionId: 'capture-1',
      }), window.location.origin)
    })
  })
})
