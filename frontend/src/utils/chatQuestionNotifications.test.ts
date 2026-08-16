import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  editorDocumentIdFromPath,
  requestChatQuestionNotificationPermissionOnce,
  shouldShowGlobalQuestionModal,
} from './chatQuestionNotifications'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('requestChatQuestionNotificationPermissionOnce', () => {
  it('requests permission only once from repeated task submissions', () => {
    const requestPermission = vi.fn().mockResolvedValue('granted')
    const storage = new Map<string, string>()
    vi.stubGlobal('window', {
      Notification: { permission: 'default', requestPermission },
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      },
    })

    requestChatQuestionNotificationPermissionOnce()
    requestChatQuestionNotificationPermissionOnce()

    expect(requestPermission).toHaveBeenCalledTimes(1)
  })

  it('does not request again after the browser has already decided', () => {
    const requestPermission = vi.fn().mockResolvedValue('denied')
    vi.stubGlobal('window', {
      Notification: { permission: 'denied', requestPermission },
      localStorage: { getItem: vi.fn(), setItem: vi.fn() },
    })

    requestChatQuestionNotificationPermissionOnce()

    expect(requestPermission).not.toHaveBeenCalled()
  })
})

describe('global question presentation routing', () => {
  it('keeps the matching editor on its inline card and uses a modal elsewhere', () => {
    expect(editorDocumentIdFromPath('/editor/42')).toBe(42)
    expect(shouldShowGlobalQuestionModal('/editor/42', 'visible', 42)).toBe(false)
    expect(shouldShowGlobalQuestionModal('/editor/7', 'visible', 42)).toBe(true)
    expect(shouldShowGlobalQuestionModal('/workbench', 'visible', 42)).toBe(true)
  })

  it('suppresses the modal while the page is hidden so the system notification can take over', () => {
    expect(shouldShowGlobalQuestionModal('/workbench', 'hidden', 42)).toBe(false)
  })
})
