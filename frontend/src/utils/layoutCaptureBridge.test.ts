import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { LayoutCaptureSession, LayoutReferencePreview } from '../types'
import {
  LAYOUT_CAPTURE_CHANNEL,
  LayoutCaptureBridge,
  getWechatVerificationDetail,
  resolveWechatCaptureUrl,
} from './layoutCaptureBridge'

class FakeBridgeHost {
  listener: ((event: MessageEvent) => void) | null = null
  messages: unknown[] = []

  addEventListener(_type: 'message', listener: (event: MessageEvent) => void) {
    this.listener = listener
  }

  removeEventListener(_type: 'message', listener: (event: MessageEvent) => void) {
    if (this.listener === listener) this.listener = null
  }

  postMessage(message: unknown) {
    this.messages.push(message)
  }

  dispatch(data: unknown, origin = 'https://app.example.com') {
    this.listener?.({ data, origin, source: this } as unknown as MessageEvent)
  }
}

const session: LayoutCaptureSession = {
  id: 'capture-1',
  token: 'short-lived-capture-token',
  canonical_url: 'https://mp.weixin.qq.com/s/article',
  expires_at: '2026-08-15T12:00:00Z',
  purpose: 'layout_reference',
}

const preview: LayoutReferencePreview = {
  reference_id: 'reference-1',
  canonical_url: session.canonical_url,
  title: '文章标题',
  site_name: 'mp.weixin.qq.com',
  preview_html: '<p>正文</p>',
  assets: [],
  summary: { block_count: 1, image_slots: 0, image_assets: 0, extracted_from: '浏览器采集的公众号正文' },
  requires_asset_reuse_confirmation: false,
  warning: null,
}

afterEach(() => {
  vi.useRealTimers()
})

describe('layout capture fallback bridge', () => {
  it('recognizes only the structured WeChat verification response', () => {
    const detail = { code: 'wechat_verification_required', message: '需要验证', url: session.canonical_url }
    expect(getWechatVerificationDetail(new ApiError(409, detail))).toEqual(detail)
    expect(getWechatVerificationDetail(new ApiError(422, detail))).toBeNull()
    expect(getWechatVerificationDetail(new ApiError(409, '需要验证'))).toBeNull()
  })

  it('keeps the submitted article URL instead of a WeChat captcha redirect', () => {
    const articleUrl = 'https://mp.weixin.qq.com/s/article?scene=1'
    const captchaUrl = 'https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=secret&target_url='
      + encodeURIComponent(articleUrl)

    expect(resolveWechatCaptureUrl(captchaUrl, articleUrl)).toBe(articleUrl)
    expect(resolveWechatCaptureUrl(captchaUrl)).toBe(articleUrl)
    expect(resolveWechatCaptureUrl(
      'https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?target_url=https%3A%2F%2Fexample.com%2Fs%2Farticle',
    )).toBeNull()
  })

  it('reports the extension as unavailable after the handshake timeout', async () => {
    vi.useFakeTimers()
    const host = new FakeBridgeHost()
    const bridge = new LayoutCaptureBridge(() => undefined, host, 'https://app.example.com', 'nonce-1')
    const available = bridge.connect('layout_reference', 500)

    await vi.advanceTimersByTimeAsync(500)

    await expect(available).resolves.toBe('missing')
    expect(host.messages).toContainEqual(expect.objectContaining({ type: 'ping', nonce: 'nonce-1' }))
    bridge.dispose()
  })

  it('detects a bridge that is injected after the first ping', async () => {
    vi.useFakeTimers()
    const host = new FakeBridgeHost()
    const bridge = new LayoutCaptureBridge(() => undefined, host, 'https://app.example.com', 'nonce-1')
    const available = bridge.connect('layout_reference', 1000)

    await vi.advanceTimersByTimeAsync(300)
    expect(host.messages.filter((message) => (message as { type?: string }).type === 'ping').length).toBeGreaterThan(1)
    host.dispatch({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce: 'nonce-1',
      type: 'pong',
    })

    await expect(available).resolves.toBe('available')
    bridge.dispose()
  })

  it('requires an explicit capability for article imports while preserving legacy layout support', async () => {
    const host = new FakeBridgeHost()
    const bridge = new LayoutCaptureBridge(() => undefined, host, 'https://app.example.com', 'nonce-1')
    const connection = bridge.connect('web_article_import', 1000)
    host.dispatch({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce: 'nonce-1',
      type: 'pong',
    })

    await expect(connection).resolves.toBe('upgrade_required')
    bridge.dispose()
  })

  it('ignores mismatched nonces and accepts a valid completion result', () => {
    const host = new FakeBridgeHost()
    const events: unknown[] = []
    const bridge = new LayoutCaptureBridge((event) => events.push(event), host, 'https://app.example.com', 'nonce-1')
    bridge.startSession(session)

    host.dispatch({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce: 'nonce-other',
      type: 'result',
      sessionId: session.id,
      purpose: 'layout_reference',
      preview,
    })
    expect(events).toEqual([])

    host.dispatch({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce: 'nonce-1',
      type: 'result',
      sessionId: session.id,
      purpose: 'layout_reference',
      preview,
    })
    expect(events).toEqual([{ type: 'result', sessionId: session.id, preview }])
    bridge.dispose()
  })

  it('reports an error when the extension does not register a capture session', async () => {
    vi.useFakeTimers()
    const host = new FakeBridgeHost()
    const events: unknown[] = []
    const bridge = new LayoutCaptureBridge((event) => events.push(event), host, 'https://app.example.com', 'nonce-1')

    bridge.startSession(session, 500)
    await vi.advanceTimersByTimeAsync(500)

    expect(events).toEqual([{
      type: 'error',
      sessionId: session.id,
      message: '排版采集助手未确认任务，请刷新页面并重新发起抓取',
    }])
    bridge.dispose()
  })

  it('cancels the registration timeout after the extension acknowledges the session', async () => {
    vi.useFakeTimers()
    const host = new FakeBridgeHost()
    const events: unknown[] = []
    const bridge = new LayoutCaptureBridge((event) => events.push(event), host, 'https://app.example.com', 'nonce-1')

    bridge.startSession(session, 500)
    host.dispatch({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce: 'nonce-1',
      type: 'status',
      sessionId: session.id,
      status: 'opening',
      purpose: 'layout_reference',
    })
    await vi.advanceTimersByTimeAsync(500)

    expect(events).toEqual([{ type: 'status', sessionId: session.id, status: 'opening' }])
    bridge.dispose()
  })
})
