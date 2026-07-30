import { describe, expect, it } from 'vitest'
import { evaluateViewportFit } from './viewportFit'

const WINDOWS_DESKTOP = {
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36',
  platform: 'Win32',
  maxTouchPoints: 0,
}

describe('evaluateViewportFit', () => {
  it('does not prompt when the desktop layout fits the viewport', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      viewportWidth: 1280,
      documentWidth: 1282,
      editorToolbarHeight: 60,
    })).toBeNull()
  })

  it('reports horizontal page overflow on desktop', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      viewportWidth: 1200,
      documentWidth: 1203,
    })).toBe('page-overflow')
  })

  it('reports a wrapped editor toolbar before the generic overflow issue', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      viewportWidth: 1200,
      documentWidth: 1208,
      editorToolbarHeight: 61,
    })).toBe('editor-toolbar-wrapped')
  })

  it('does not prompt on Android devices', () => {
    expect(evaluateViewportFit({
      userAgent: 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/138.0.0.0 Mobile Safari/537.36',
      platform: 'Linux armv81',
      maxTouchPoints: 5,
      viewportWidth: 390,
      documentWidth: 560,
      editorToolbarHeight: 96,
    })).toBeNull()
  })

  it('does not prompt on iPhone devices', () => {
    expect(evaluateViewportFit({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 Version/18.5 Mobile/15E148 Safari/604.1',
      platform: 'iPhone',
      maxTouchPoints: 5,
      viewportWidth: 390,
      documentWidth: 560,
      editorToolbarHeight: 96,
    })).toBeNull()
  })

  it('does not prompt on Windows Phone devices', () => {
    expect(evaluateViewportFit({
      userAgent: 'Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950 XL Dual SIM) AppleWebKit/537.36 Chrome/52.0.2743.116 Mobile Safari/537.36 Edge/15.15063',
      platform: 'Win32',
      maxTouchPoints: 5,
      viewportWidth: 390,
      documentWidth: 560,
      editorToolbarHeight: 96,
    })).toBeNull()
  })

  it('does not prompt on iPadOS devices that identify as Macs', () => {
    expect(evaluateViewportFit({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/18.5 Mobile/15E148 Safari/604.1',
      platform: 'MacIntel',
      maxTouchPoints: 5,
      viewportWidth: 1024,
      documentWidth: 1200,
      editorToolbarHeight: 96,
    })).toBeNull()
  })

  it('still prompts on a Windows touch laptop', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      maxTouchPoints: 10,
      viewportWidth: 991,
      documentWidth: 991,
      editorToolbarHeight: 56,
    })).toBe('desktop-compact-layout')
  })

  it('reports the compact layout on desktop at 991px and below', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      viewportWidth: 991,
      documentWidth: 991,
    })).toBe('desktop-compact-layout')
  })

  it('does not report the compact layout at the 992px desktop boundary', () => {
    expect(evaluateViewportFit({
      ...WINDOWS_DESKTOP,
      viewportWidth: 992,
      documentWidth: 992,
      editorToolbarHeight: 56,
    })).toBeNull()
  })
})
