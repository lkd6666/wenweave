const NOTIFICATION_PERMISSION_ATTEMPTED_KEY = 'yibanpaiban-chat-question-notification-permission-v1'

export function requestChatQuestionNotificationPermissionOnce(): void {
  if (typeof window === 'undefined' || typeof window.Notification === 'undefined') return
  if (window.Notification.permission !== 'default') return
  try {
    if (window.localStorage.getItem(NOTIFICATION_PERMISSION_ATTEMPTED_KEY) === '1') return
    window.localStorage.setItem(NOTIFICATION_PERMISSION_ATTEMPTED_KEY, '1')
  } catch {
    // The browser permission state still prevents repeated prompts after a decision.
  }
  try {
    void window.Notification.requestPermission().catch(() => undefined)
  } catch {
    // Unsupported or policy-blocked permission requests degrade to in-app prompts.
  }
}

export function editorDocumentIdFromPath(pathname: string): number | null {
  const match = /^\/editor\/(\d+)(?:\/|$)/.exec(pathname)
  if (!match) return null
  const documentId = Number(match[1])
  return Number.isSafeInteger(documentId) && documentId > 0 ? documentId : null
}

export function shouldShowGlobalQuestionModal(
  pathname: string,
  visibilityState: DocumentVisibilityState,
  documentId: number,
): boolean {
  return visibilityState === 'visible' && editorDocumentIdFromPath(pathname) !== documentId
}
