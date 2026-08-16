import {
  LAYOUT_CAPTURE_CHANNEL,
  allowedAppOrigin,
  capturePurpose,
  isCaptureSessionUsable,
  isRecord,
  type CaptureSession,
  type CapturePurpose,
} from './shared'

interface LayoutCaptureBridgeGlobal {
  __yibanpaibanLayoutCaptureBridgeInstalled__?: boolean
}

function extensionContextAlive(): boolean {
  try {
    return typeof chrome.runtime?.id === 'string' && chrome.runtime.id.length > 0
  } catch {
    return false
  }
}

function sendRuntimeMessage(message: Record<string, unknown>): Promise<unknown> {
  try {
    return Promise.resolve(chrome.runtime.sendMessage(message))
  } catch (error) {
    return Promise.reject(error)
  }
}

function installBridge(): void {
  const appOrigin = allowedAppOrigin(window.location.href)
  const bridgeGlobal = globalThis as typeof globalThis & LayoutCaptureBridgeGlobal
  if (!appOrigin || bridgeGlobal.__yibanpaibanLayoutCaptureBridgeInstalled__) return
  bridgeGlobal.__yibanpaibanLayoutCaptureBridgeInstalled__ = true

  let activeNonce: string | null = null
  let activeSessionId: string | null = null
  let activePurpose: CapturePurpose | null = null

  function postToApp(nonce: string, type: string, payload: Record<string, unknown> = {}): void {
    window.postMessage({
      channel: LAYOUT_CAPTURE_CHANNEL,
      direction: 'extension-to-app',
      nonce,
      type,
      ...payload,
    }, appOrigin!)
  }

  function handleWindowMessage(event: MessageEvent): void {
    if (event.source !== window || event.origin !== appOrigin || !isRecord(event.data)) return
    const message = event.data
    if (message.channel !== LAYOUT_CAPTURE_CHANNEL
      || message.direction !== 'app-to-extension'
      || typeof message.nonce !== 'string'
      || typeof message.type !== 'string') return

    if (!extensionContextAlive()) {
      window.removeEventListener('message', handleWindowMessage)
      return
    }

    if (message.type === 'ping') {
      postToApp(message.nonce, 'pong', {
        protocolVersion: 2,
        capabilities: ['layout_reference', 'web_article_import'],
      })
      return
    }

    if (message.type === 'start') {
      if (!isCaptureSessionUsable(message.session)) {
        const sessionId = isRecord(message.session) && typeof message.session.id === 'string'
          ? message.session.id
          : ''
        postToApp(message.nonce, 'error', {
          sessionId,
          message: '浏览器采集会话无效或已过期，请返回系统重新发起抓取',
        })
        return
      }
      const session = message.session as CaptureSession
      const nonce = message.nonce
      activeNonce = nonce
      activeSessionId = session.id
      activePurpose = capturePurpose(session) || 'layout_reference'
      void sendRuntimeMessage({
        type: 'layoutCapture:register',
        nonce: activeNonce,
        session,
      }).then((response: unknown) => {
        if (!isRecord(response) || response.ok !== true) {
          postToApp(nonce, 'error', {
            sessionId: session.id,
            message: isRecord(response) && typeof response.message === 'string' ? response.message : '排版采集助手未能创建会话',
          })
        }
      }).catch(() => {
        postToApp(nonce, 'error', { sessionId: session.id, message: '排版采集助手连接已中断，请刷新页面重试' })
      })
      return
    }

    if (message.type === 'cancel' && message.nonce === activeNonce && message.sessionId === activeSessionId) {
      void sendRuntimeMessage({ type: 'layoutCapture:cancel', sessionId: activeSessionId }).catch(() => {
        // The extension may have been reloaded while the editor page stayed open.
      })
      activeNonce = null
      activeSessionId = null
      activePurpose = null
    }
  }

  window.addEventListener('message', handleWindowMessage)

  chrome.runtime.onMessage.addListener((message: unknown) => {
    if (!isRecord(message)
      || message.type !== 'layoutCapture:event'
      || typeof activeNonce !== 'string'
      || typeof activeSessionId !== 'string'
      || activePurpose === null
      || message.nonce !== activeNonce
      || message.sessionId !== activeSessionId
      || capturePurpose(message) !== activePurpose
      || typeof message.eventType !== 'string') return
    postToApp(activeNonce, message.eventType, {
      sessionId: activeSessionId,
      status: message.status,
      message: message.message,
      preview: message.preview,
      purpose: activePurpose,
    })
    if (message.eventType === 'result' || message.eventType === 'error') {
      activeNonce = null
      activeSessionId = null
      activePurpose = null
    }
  })
}

installBridge()
