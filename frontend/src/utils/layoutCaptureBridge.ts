import { ApiError } from '../api/client'
import type { LayoutCaptureSession, LayoutReferencePreview } from '../types'

export const LAYOUT_CAPTURE_CHANNEL = 'yibanpaiban-layout-capture-v1'

export interface WechatVerificationDetail {
  code: 'wechat_verification_required'
  message: string
  url: string
}

export type LayoutCaptureStatus = 'opening' | 'awaiting_verification' | 'capturing' | 'uploading'
export type CapturePurpose = LayoutCaptureSession['purpose']
export type CaptureExtensionConnection = 'available' | 'missing' | 'upgrade_required'

export type LayoutCaptureBridgeEvent<TResult = LayoutReferencePreview> =
  | { type: 'status'; sessionId: string; status: LayoutCaptureStatus }
  | { type: 'result'; sessionId: string; preview: TResult }
  | { type: 'error'; sessionId: string; message: string }

interface BridgeHost {
  addEventListener(type: 'message', listener: (event: MessageEvent) => void): void
  removeEventListener(type: 'message', listener: (event: MessageEvent) => void): void
  postMessage(message: unknown, targetOrigin: string): void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function newNonce(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

export function getWechatVerificationDetail(error: unknown): WechatVerificationDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !isRecord(error.detail)) return null
  const { code, message, url } = error.detail
  if (code !== 'wechat_verification_required' || typeof message !== 'string' || typeof url !== 'string') return null
  return { code, message, url }
}

function normalizeWechatArticleUrl(rawUrl: string): string | null {
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:'
      || url.hostname.toLowerCase().replace(/\.$/, '') !== 'mp.weixin.qq.com'
      || url.username
      || url.password
      || (url.port && url.port !== '443')
      || !(url.pathname === '/s' || url.pathname.startsWith('/s/'))) return null
    url.hostname = 'mp.weixin.qq.com'
    url.port = ''
    url.hash = ''
    return url.toString()
  } catch {
    return null
  }
}

export function resolveWechatCaptureUrl(responseUrl: string, requestedUrl = ''): string | null {
  const requestedArticle = normalizeWechatArticleUrl(requestedUrl)
  if (requestedArticle) return requestedArticle
  const responseArticle = normalizeWechatArticleUrl(responseUrl)
  if (responseArticle) return responseArticle
  try {
    const verificationUrl = new URL(responseUrl)
    if (verificationUrl.protocol !== 'https:'
      || verificationUrl.hostname.toLowerCase().replace(/\.$/, '') !== 'mp.weixin.qq.com'
      || verificationUrl.pathname !== '/mp/wappoc_appmsgcaptcha') return null
    const targets = verificationUrl.searchParams.getAll('target_url')
    return targets.length === 1 ? normalizeWechatArticleUrl(targets[0] || '') : null
  } catch {
    return null
  }
}

export function isLayoutReferencePreview(value: unknown): value is LayoutReferencePreview {
  if (!isRecord(value) || !isRecord(value.summary) || !Array.isArray(value.assets)) return false
  return typeof value.reference_id === 'string'
    && typeof value.canonical_url === 'string'
    && typeof value.title === 'string'
    && typeof value.preview_html === 'string'
}

export class LayoutCaptureBridge<TResult = LayoutReferencePreview> {
  readonly nonce: string

  private readonly host: BridgeHost
  private readonly origin: string
  private readonly onEvent: (event: LayoutCaptureBridgeEvent<TResult>) => void
  private readonly resultGuard: (value: unknown) => value is TResult
  private activeSessionId: string | null = null
  private activePurpose: CapturePurpose | null = null
  private requiredCapability: CapturePurpose = 'layout_reference'
  private pingTimeout: ReturnType<typeof setTimeout> | null = null
  private pingInterval: ReturnType<typeof setInterval> | null = null
  private pingResolver: ((status: CaptureExtensionConnection) => void) | null = null
  private registrationTimeout: ReturnType<typeof setTimeout> | null = null
  private disposed = false

  constructor(
    onEvent: (event: LayoutCaptureBridgeEvent<TResult>) => void,
    host: BridgeHost = window,
    origin: string = window.location.origin,
    nonce: string = newNonce(),
    resultGuard: (value: unknown) => value is TResult = isLayoutReferencePreview as (value: unknown) => value is TResult,
  ) {
    this.host = host
    this.origin = origin
    this.onEvent = onEvent
    this.resultGuard = resultGuard
    this.nonce = nonce
    this.host.addEventListener('message', this.handleMessage)
  }

  connect(
    requiredCapability: CapturePurpose = 'layout_reference',
    timeoutMs = 1200,
  ): Promise<CaptureExtensionConnection> {
    if (this.disposed) return Promise.resolve('missing')
    this.finishPing('missing')
    this.requiredCapability = requiredCapability
    return new Promise((resolve) => {
      this.pingResolver = resolve
      this.pingTimeout = setTimeout(() => this.finishPing('missing'), timeoutMs)
      this.post('ping')
      this.pingInterval = setInterval(() => this.post('ping'), 250)
    })
  }

  startSession(session: LayoutCaptureSession, timeoutMs = 5000): void {
    if (this.disposed) throw new Error('浏览器采集桥接已关闭')
    this.finishRegistration()
    this.activeSessionId = session.id
    this.activePurpose = session.purpose || 'layout_reference'
    this.post('start', { session })
    this.registrationTimeout = setTimeout(() => {
      if (this.activeSessionId !== session.id) return
      this.activeSessionId = null
      this.activePurpose = null
      this.registrationTimeout = null
      this.onEvent({
        type: 'error',
        sessionId: session.id,
        message: '排版采集助手未确认任务，请刷新页面并重新发起抓取',
      })
    }, timeoutMs)
  }

  cancel(): void {
    if (!this.activeSessionId || this.disposed) return
    this.post('cancel', { sessionId: this.activeSessionId })
    this.activeSessionId = null
    this.activePurpose = null
    this.finishRegistration()
  }

  dispose(): void {
    if (this.disposed) return
    this.cancel()
    this.disposed = true
    this.finishPing('missing')
    this.finishRegistration()
    this.host.removeEventListener('message', this.handleMessage)
  }

  private post(type: 'ping' | 'start' | 'cancel', payload: Record<string, unknown> = {}): void {
    this.host.postMessage({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'app-to-extension',
      nonce: this.nonce,
      type,
      ...payload,
    }, this.origin)
  }

  private finishPing(status: CaptureExtensionConnection): void {
    if (this.pingTimeout !== null) clearTimeout(this.pingTimeout)
    if (this.pingInterval !== null) clearInterval(this.pingInterval)
    this.pingTimeout = null
    this.pingInterval = null
    const resolve = this.pingResolver
    this.pingResolver = null
    resolve?.(status)
  }

  private finishRegistration(): void {
    if (this.registrationTimeout !== null) clearTimeout(this.registrationTimeout)
    this.registrationTimeout = null
  }

  private handleMessage = (event: MessageEvent): void => {
    if (this.disposed || event.source !== this.host || event.origin !== this.origin || !isRecord(event.data)) return
    const message = event.data
    if (message.channel !== LAYOUT_CAPTURE_CHANNEL
      || message.direction !== 'extension-to-app'
      || message.nonce !== this.nonce
      || typeof message.type !== 'string') return

    if (message.type === 'pong') {
      const capabilities = Array.isArray(message.capabilities)
        ? message.capabilities.filter((value): value is CapturePurpose => (
          value === 'layout_reference' || value === 'web_article_import'
        ))
        : ['layout_reference' as const]
      this.finishPing(capabilities.includes(this.requiredCapability) ? 'available' : 'upgrade_required')
      return
    }

    if (typeof message.sessionId !== 'string' || message.sessionId !== this.activeSessionId) return
    const messagePurpose = message.purpose === 'web_article_import' ? 'web_article_import' : 'layout_reference'
    if (messagePurpose !== this.activePurpose) return
    if (message.type === 'status'
      && ['opening', 'awaiting_verification', 'capturing', 'uploading'].includes(String(message.status))) {
      this.finishRegistration()
      this.onEvent({
        type: 'status',
        sessionId: message.sessionId,
        status: message.status as LayoutCaptureStatus,
      })
      return
    }
    if (message.type === 'result' && this.resultGuard(message.preview)) {
      this.finishRegistration()
      this.activeSessionId = null
      this.activePurpose = null
      this.onEvent({ type: 'result', sessionId: message.sessionId, preview: message.preview })
      return
    }
    if (message.type === 'error' && typeof message.message === 'string') {
      this.finishRegistration()
      this.activeSessionId = null
      this.activePurpose = null
      this.onEvent({ type: 'error', sessionId: message.sessionId, message: message.message })
    }
  }
}
