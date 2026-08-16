export const APP_ORIGINS = typeof __LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__ !== 'undefined'
  && Array.isArray(__LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__)
  ? __LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__
  : ['http://localhost:5173', 'http://127.0.0.1:5173']
export const LAYOUT_CAPTURE_CHANNEL = 'yibanpaiban-layout-capture-v1'
export const SESSION_STORAGE_KEY = 'layoutCaptureSession'
export const MAX_CAPTURE_ASSETS = 50
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
export const MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
export const MAX_HTML_BYTES = 5 * 1024 * 1024

export type CapturePurpose = 'layout_reference' | 'web_article_import'

export interface CaptureSession {
  id: string
  token: string
  canonical_url: string
  expires_at: string
  purpose: CapturePurpose
}

export type CaptureTargetSession = Omit<CaptureSession, 'token'>

export interface StoredCaptureSession {
  session: CaptureSession
  nonce: string
  appTabId: number
  appOrigin: string
  articleTabId?: number
}

export interface CaptureAssetDescriptor {
  assetId: string
  url: string
}

export interface CaptureDraftRead {
  draftId: string
  title: string
  assets: CaptureAssetDescriptor[]
  omittedAssetCount: number
  coverAssetId: string | null
}

export interface FinalizedCaptureDraft {
  sourceHtml: string
  title: string
  activeAssetIds: string[]
  omittedAssetCount: number
  coverAssetId: string | null
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function capturePurpose(value: unknown): CapturePurpose | null {
  if (!isRecord(value) || value.purpose === undefined) return 'layout_reference'
  return value.purpose === 'layout_reference' || value.purpose === 'web_article_import' ? value.purpose : null
}

export function captureCompletionPath(purpose: CapturePurpose, sessionId: string): string {
  const encodedId = encodeURIComponent(sessionId)
  return purpose === 'web_article_import'
    ? `/api/documents/link-imports/capture-sessions/${encodedId}/complete`
    : `/api/layout-references/capture-sessions/${encodedId}/complete`
}

export function allowedAppOrigin(rawUrl: string): string | null {
  try {
    const origin = new URL(rawUrl).origin
    return APP_ORIGINS.includes(origin) ? origin : null
  } catch {
    return null
  }
}

export function normalizeCaptureUrl(rawUrl: string): string | null {
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null
    url.hostname = url.hostname.toLowerCase().replace(/\.$/, '')
    url.port = ''
    url.hash = ''
    return url.toString()
  } catch {
    return null
  }
}

export function isWechatArticleUrl(rawUrl: string): boolean {
  const normalized = normalizeCaptureUrl(rawUrl)
  return normalized !== null && new URL(normalized).hostname === 'mp.weixin.qq.com'
}

export function captureUrlsMatch(left: string, right: string): boolean {
  const normalizedLeft = normalizeCaptureUrl(left)
  return normalizedLeft !== null && normalizedLeft === normalizeCaptureUrl(right)
}

export function captureExpiryTimestamp(value: string): number {
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value)
  return Date.parse(hasTimezone ? value : `${value}Z`)
}

export function isCaptureSessionUsable(value: unknown, now = Date.now()): value is CaptureSession {
  if (!isRecord(value)
    || typeof value.id !== 'string'
    || typeof value.token !== 'string'
    || typeof value.canonical_url !== 'string'
    || typeof value.expires_at !== 'string'
    || capturePurpose(value) === null) return false
  const expiresAt = captureExpiryTimestamp(value.expires_at)
  return value.id.length > 0
    && value.token.length >= 20
    && isWechatArticleUrl(value.canonical_url)
    && Number.isFinite(expiresAt)
    && expiresAt > now
}

export function isCaptureTargetSessionUsable(value: unknown, now = Date.now()): value is CaptureTargetSession {
  if (!isRecord(value)
    || typeof value.id !== 'string'
    || typeof value.canonical_url !== 'string'
    || typeof value.expires_at !== 'string'
    || capturePurpose(value) === null) return false
  const expiresAt = captureExpiryTimestamp(value.expires_at)
  return value.id.length > 0
    && isWechatArticleUrl(value.canonical_url)
    && Number.isFinite(expiresAt)
    && expiresAt > now
}

export function isAllowedWechatAssetUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:') return false
    const hostname = url.hostname.toLowerCase().replace(/\.$/, '')
    return hostname === 'mp.weixin.qq.com'
      || hostname === 'res.wx.qq.com'
      || hostname === 'mmbiz.qpic.cn'
      || hostname === 'mmecoa.qpic.cn'
      || hostname === 'wx.qlogo.cn'
      || hostname.endsWith('.qpic.cn')
      || hostname.endsWith('.qlogo.cn')
  } catch {
    return false
  }
}

export function extensionErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : '浏览器采集失败，请重新发起抓取'
}
