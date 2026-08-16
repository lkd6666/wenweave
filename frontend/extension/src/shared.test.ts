import { describe, expect, it } from 'vitest'
import {
  captureCompletionPath,
  allowedAppOrigin,
  captureExpiryTimestamp,
  captureUrlsMatch,
  isCaptureSessionUsable,
  isCaptureTargetSessionUsable,
} from './shared'

describe('extension capture session restrictions', () => {
  it('accepts both loopback names used by the development application', () => {
    expect(allowedAppOrigin('http://localhost:5173/editor/1')).toBe('http://localhost:5173')
    expect(allowedAppOrigin('http://127.0.0.1:5173/editor/1')).toBe('http://127.0.0.1:5173')
    expect(allowedAppOrigin('http://localhost:4173/editor/1')).toBeNull()
    expect(allowedAppOrigin('https://example.com/editor/1')).toBeNull()
  })

  it('accepts only a live session for the exact associated WeChat article URL', () => {
    const now = Date.parse('2026-08-15T04:00:00Z')
    const session = {
      id: 'capture-id',
      token: 'capture-token-with-enough-entropy',
      canonical_url: 'https://mp.weixin.qq.com/s/article?a=1',
      expires_at: '2026-08-15T04:10:00Z',
    }

    expect(isCaptureSessionUsable(session, now)).toBe(true)
    expect(isCaptureTargetSessionUsable({
      id: session.id,
      canonical_url: session.canonical_url,
      expires_at: session.expires_at,
    }, now)).toBe(true)
    expect(captureUrlsMatch('https://mp.weixin.qq.com/s/article?a=1#wechat_redirect', session.canonical_url)).toBe(true)
    expect(captureUrlsMatch('https://mp.weixin.qq.com/s/other?a=1', session.canonical_url)).toBe(false)
    expect(isCaptureSessionUsable({ ...session, expires_at: '2026-08-15T03:59:59Z' }, now)).toBe(false)
    expect(isCaptureSessionUsable({ ...session, canonical_url: 'https://example.com/article' }, now)).toBe(false)
  })

  it('treats a timezone-less server expiry as UTC for MySQL compatibility', () => {
    const now = Date.parse('2026-08-15T04:00:00Z')
    const session = {
      id: 'capture-id',
      token: 'capture-token-with-enough-entropy',
      canonical_url: 'https://mp.weixin.qq.com/s/article',
      expires_at: '2026-08-15T04:10:00',
    }

    expect(captureExpiryTimestamp(session.expires_at)).toBe(Date.parse('2026-08-15T04:10:00Z'))
    expect(isCaptureSessionUsable(session, now)).toBe(true)
  })

  it('routes only known capture purposes to fixed application endpoints', () => {
    expect(captureCompletionPath('layout_reference', 'capture/1')).toBe(
      '/api/layout-references/capture-sessions/capture%2F1/complete',
    )
    expect(captureCompletionPath('web_article_import', 'capture/1')).toBe(
      '/api/documents/link-imports/capture-sessions/capture%2F1/complete',
    )
  })
})
