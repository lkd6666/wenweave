// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import {
  DARK_MODE_PREVIEW_HEIGHT_MESSAGE,
  DARK_MODE_PREVIEW_SANDBOX,
  buildDarkModePreviewDocument,
  isDarkModePreviewHeightMessage,
} from './darkModePreview'

describe('dark mode preview document', () => {
  it('uses the WeChat converter with the editor-safe dark mode settings', () => {
    const document = buildDarkModePreviewDocument({
      html: '<p style="color:#000">正文</p>',
      token: 'trusted-token',
    })

    expect(document).toContain("mode: 'dark'")
    expect(document).toContain("defaultDarkTextColor: '#989898'")
    expect(document).toContain("defaultDarkBgColor: '#191919'")
    expect(document).toContain("attribute: ['data-no-dark']")
    expect(document).toContain('needJudgeFirstPage: false')
    expect(document).toContain('background: #191919')
  })

  it('keeps links usable while limiting scripts to the trusted nonce', () => {
    const document = buildDarkModePreviewDocument({
      html: '<a href="https://example.com">链接</a><script>throw new Error("untrusted")</script>',
      token: 'trusted-token',
    })
    const parsed = new DOMParser().parseFromString(document, 'text/html')

    expect(parsed.querySelector('a')?.target).toBe('_blank')
    expect(parsed.querySelector('a')?.rel).toContain('noopener')
    const csp = parsed.querySelector<HTMLMetaElement>('meta[http-equiv="Content-Security-Policy"]')?.content
    expect(csp).toContain("default-src 'none'")
    expect(csp).toContain("base-uri 'none'")
    expect(csp).toContain("script-src 'nonce-trusted-token'")
    expect(csp).toContain("object-src 'none'")
    expect(csp).toContain("frame-src 'none'")
    expect(csp).not.toContain("script-src 'unsafe-inline'")
    expect(parsed.querySelectorAll('script[nonce="trusted-token"]')).toHaveLength(2)
    // Keep nonce text in the emitted srcDoc. In real browsers it is hidden
    // after DOMParser serializes the document, so the final document must not
    // go through an additional parse-and-serialize cycle.
    expect(document).toContain('<script nonce="trusted-token">')
  })

  it('uses an opaque, read-only sandbox for the dark-mode frame', () => {
    expect(DARK_MODE_PREVIEW_SANDBOX).toContain('allow-scripts')
    expect(DARK_MODE_PREVIEW_SANDBOX).toContain('allow-popups')
    expect(DARK_MODE_PREVIEW_SANDBOX).not.toContain('allow-same-origin')
    expect(DARK_MODE_PREVIEW_SANDBOX).not.toContain('allow-forms')
  })

  it('accepts only valid height messages', () => {
    expect(isDarkModePreviewHeightMessage({
      type: DARK_MODE_PREVIEW_HEIGHT_MESSAGE,
      token: 'trusted-token',
      height: 480,
    })).toBe(true)
    expect(isDarkModePreviewHeightMessage({
      type: DARK_MODE_PREVIEW_HEIGHT_MESSAGE,
      token: 'trusted-token',
      height: Number.NaN,
    })).toBe(false)
    expect(isDarkModePreviewHeightMessage({ type: 'other', token: 'trusted-token', height: 480 })).toBe(false)
  })
})
