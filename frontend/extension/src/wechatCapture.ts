import { createCaptureDraft, discardCaptureDraft, finalizeCaptureDraft } from './extractor'
import { readOriginalArticleDocument } from './articleSource'
import {
  capturePurpose,
  captureUrlsMatch,
  extensionErrorMessage,
  isCaptureTargetSessionUsable,
  isRecord,
  type CapturePurpose,
} from './shared'
import { WechatCapturePanel, type WechatPanelState } from './wechatPanel'

interface WechatCaptureGlobal {
  __yibanpaibanWechatCaptureInstalled__?: boolean
}

function installWechatCapture(): void {
  const captureGlobal = globalThis as typeof globalThis & WechatCaptureGlobal
  if (captureGlobal.__yibanpaibanWechatCaptureInstalled__) return
  captureGlobal.__yibanpaibanWechatCaptureInstalled__ = true
  document.querySelector('#yibanpaiban-layout-capture-panel')?.remove()
  const panel = new WechatCapturePanel(document)
  let activeSessionId: string | null = null
  let activePurpose: CapturePurpose | null = null

  function targetLabel(rawUrl: string): string {
    try {
      const url = new URL(rawUrl)
      return `${url.hostname}${url.pathname}`
    } catch {
      return 'mp.weixin.qq.com'
    }
  }

  function hasArticleContent(): boolean {
    const content = document.querySelector<HTMLElement>('#js_content')
    return Boolean(content?.textContent?.trim())
  }

  async function beginCapture(): Promise<void> {
    if (!activeSessionId) return
    panel.show('capturing', { purpose: activePurpose || 'layout_reference' })
    try {
      const response = await chrome.runtime.sendMessage({ type: 'layoutCapture:begin' }) as unknown
      if (!isRecord(response) || response.ok !== true) {
        throw new Error(isRecord(response) && typeof response.message === 'string'
          ? response.message
          : '无法启动采集')
      }
    } catch (error) {
      panel.show('error', {
        message: extensionErrorMessage(error),
        purpose: activePurpose || 'layout_reference',
      })
    }
  }

  function showReadyPanel(canonicalUrl: string): void {
    panel.show('ready', {
      message: hasArticleContent()
        ? '已检测到文章正文，可以开始抓取。'
        : '请先完成微信验证，确认页面显示正文后再开始抓取。',
      target: targetLabel(canonicalUrl),
      onStart: () => { void beginCapture() },
      purpose: activePurpose || 'layout_reference',
    })
  }

  async function syncPanel(): Promise<void> {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'layoutCapture:getArticleTask' }) as unknown
      if (!isRecord(response) || response.ok !== true || response.active !== true || !isRecord(response.session)) return
      if (typeof response.session.id !== 'string' || typeof response.session.canonical_url !== 'string') return
      activeSessionId = response.session.id
      activePurpose = capturePurpose(response.session) || 'layout_reference'
      if (response.running === true) panel.show('capturing', { purpose: activePurpose })
      else showReadyPanel(response.session.canonical_url)
    } catch {
      // The extension may have been reloaded while this page stayed open.
    }
  }

  chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
    if (!isRecord(message) || typeof message.type !== 'string') return false
    try {
      if (message.type === 'layoutCapture:articleEvent'
        && typeof message.sessionId === 'string'
        && typeof message.status === 'string'
        && ['ready', 'capturing', 'downloading', 'uploading', 'success', 'error'].includes(message.status)) {
        const status = message.status as WechatPanelState
        if (status === 'ready' && typeof message.canonicalUrl === 'string') {
          activeSessionId = message.sessionId
          activePurpose = capturePurpose(message) || 'layout_reference'
          showReadyPanel(message.canonicalUrl)
          return false
        }
        if (message.sessionId !== activeSessionId || capturePurpose(message) !== activePurpose) return false
        panel.show(status, {
          message: typeof message.message === 'string' ? message.message : undefined,
          purpose: activePurpose || 'layout_reference',
        })
        if (status === 'success' || status === 'error') {
          activeSessionId = null
          activePurpose = null
        }
        return false
      }
      if (message.type === 'layoutCapture:createDraft') {
        if (!isCaptureTargetSessionUsable(message.session)
          || !captureUrlsMatch(location.href, message.session.canonical_url)) {
          throw new Error('当前微信文章与采集会话不匹配，或会话已过期')
        }
        const purpose = capturePurpose(message.session) || 'layout_reference'
        void readOriginalArticleDocument(document, location.href).then((original) => {
          sendResponse({ ok: true, draft: createCaptureDraft(original, location.href, purpose, document) })
        }).catch((error: unknown) => sendResponse({ ok: false, message: extensionErrorMessage(error) }))
        return true
      }
      if (message.type === 'layoutCapture:finalizeDraft'
        && typeof message.draftId === 'string'
        && Array.isArray(message.failedAssetIds)) {
        sendResponse({
          ok: true,
          capture: finalizeCaptureDraft(
            message.draftId,
            message.failedAssetIds.filter((value): value is string => typeof value === 'string'),
          ),
        })
        return false
      }
      if (message.type === 'layoutCapture:discardDraft' && typeof message.draftId === 'string') {
        discardCaptureDraft(message.draftId)
        sendResponse({ ok: true })
        return false
      }
    } catch (error) {
      sendResponse({ ok: false, message: extensionErrorMessage(error) })
    }
    return false
  })

  void syncPanel()
}

installWechatCapture()
