import {
  APP_ORIGINS,
  MAX_HTML_BYTES,
  MAX_IMAGE_BYTES,
  MAX_TOTAL_IMAGE_BYTES,
  SESSION_STORAGE_KEY,
  allowedAppOrigin,
  capturePurpose,
  captureExpiryTimestamp,
  captureCompletionPath,
  captureUrlsMatch,
  extensionErrorMessage,
  isAllowedWechatAssetUrl,
  isCaptureSessionUsable,
  isRecord,
  type CaptureAssetDescriptor,
  type CaptureDraftRead,
  type FinalizedCaptureDraft,
  type StoredCaptureSession,
} from './shared'

interface DownloadedAsset {
  assetId: string
  blob: Blob
  contentType: string
  extension: string
  size: number
}

const EXPIRY_ALARM_PREFIX = 'layoutCaptureExpiry:'
let runningSessionId: string | null = null

async function readStoredSession(): Promise<StoredCaptureSession | null> {
  const result = await chrome.storage.session.get(SESSION_STORAGE_KEY)
  const stored = result[SESSION_STORAGE_KEY] as StoredCaptureSession | undefined
  if (!stored || !isCaptureSessionUsable(stored.session) || !allowedAppOrigin(stored.appOrigin)) {
    if (stored) await clearStoredSession(stored.session.id)
    return null
  }
  stored.session.purpose = capturePurpose(stored.session) || 'layout_reference'
  return stored
}

async function clearStoredSession(sessionId?: string): Promise<void> {
  const result = await chrome.storage.session.get(SESSION_STORAGE_KEY)
  const stored = result[SESSION_STORAGE_KEY] as StoredCaptureSession | undefined
  if (sessionId && stored?.session.id !== sessionId) return
  await chrome.storage.session.remove(SESSION_STORAGE_KEY)
  if (stored?.session.id) await chrome.alarms.clear(`${EXPIRY_ALARM_PREFIX}${stored.session.id}`)
}

async function sendAppEvent(
  stored: StoredCaptureSession,
  eventType: 'status' | 'result' | 'error',
  payload: Record<string, unknown>,
): Promise<void> {
  try {
    await chrome.tabs.sendMessage(stored.appTabId, {
      type: 'layoutCapture:event',
      nonce: stored.nonce,
      sessionId: stored.session.id,
      purpose: stored.session.purpose,
      eventType,
      ...payload,
    })
  } catch {
    // The app tab may have been closed. The capability is still cleared below.
  }
}

async function sendArticleEvent(
  stored: StoredCaptureSession,
  status: 'ready' | 'capturing' | 'downloading' | 'uploading' | 'success' | 'error',
  payload: Record<string, unknown> = {},
): Promise<void> {
  if (stored.articleTabId === undefined) return
  try {
    await chrome.tabs.sendMessage(stored.articleTabId, {
      type: 'layoutCapture:articleEvent',
      sessionId: stored.session.id,
      purpose: stored.session.purpose,
      status,
      ...payload,
    })
  } catch {
    // A loading or closing article tab will restore the panel by querying the background on its next document.
  }
}

async function findArticleTab(targetUrl: string): Promise<chrome.tabs.Tab | null> {
  const tabs = await chrome.tabs.query({ url: 'https://mp.weixin.qq.com/*' })
  return tabs.find((tab) => typeof tab.url === 'string' && captureUrlsMatch(tab.url, targetUrl)) || null
}

async function openArticleTab(targetUrl: string): Promise<chrome.tabs.Tab> {
  const existing = await findArticleTab(targetUrl)
  if (existing?.id !== undefined) {
    await chrome.tabs.update(existing.id, { active: true })
    if (existing.windowId !== undefined) await chrome.windows.update(existing.windowId, { focused: true })
    return existing
  }
  return chrome.tabs.create({ url: targetUrl, active: true })
}

async function ensureWechatCaptureScript(tabId: number): Promise<void> {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['wechat-capture.js'] })
  } catch {
    throw new Error('无法连接微信文章页，请刷新文章页后重新点击“开始采集”')
  }
}

function appOriginFromSender(sender: chrome.runtime.MessageSender): string | null {
  if (sender.tab?.id === undefined || typeof sender.url !== 'string') return null
  return allowedAppOrigin(sender.url)
}

async function registerSession(message: Record<string, unknown>, sender: chrome.runtime.MessageSender): Promise<Record<string, unknown>> {
  const appOrigin = appOriginFromSender(sender)
  if (!appOrigin
    || typeof message.nonce !== 'string'
    || message.nonce.length < 16
    || !isCaptureSessionUsable(message.session)) {
    return { ok: false, message: '浏览器采集会话无效或已过期' }
  }

  const stored: StoredCaptureSession = {
    session: {
      ...message.session,
      purpose: capturePurpose(message.session) || 'layout_reference',
    },
    nonce: message.nonce,
    appTabId: sender.tab!.id!,
    appOrigin,
  }
  await clearStoredSession()
  await chrome.storage.session.set({ [SESSION_STORAGE_KEY]: stored })
  const expiresAt = captureExpiryTimestamp(stored.session.expires_at)
  await chrome.alarms.create(`${EXPIRY_ALARM_PREFIX}${stored.session.id}`, { when: expiresAt })
  await sendAppEvent(stored, 'status', { status: 'opening' })

  try {
    const articleTab = await openArticleTab(stored.session.canonical_url)
    if (articleTab.id === undefined) throw new Error('无法打开微信文章标签页')
    stored.articleTabId = articleTab.id
    await chrome.storage.session.set({ [SESSION_STORAGE_KEY]: stored })
    if (articleTab.status === 'complete') {
      try {
        await ensureWechatCaptureScript(articleTab.id)
        await sendArticleEvent(stored, 'ready', { canonicalUrl: stored.session.canonical_url })
      } catch {
        // A navigation in progress will receive the declared content script after it finishes loading.
      }
    }
    await sendAppEvent(stored, 'status', { status: 'awaiting_verification' })
    return { ok: true }
  } catch (error) {
    const messageText = extensionErrorMessage(error)
    await sendAppEvent(stored, 'error', { message: messageText })
    await clearStoredSession(stored.session.id)
    return { ok: false, message: messageText }
  }
}

function sniffImage(data: Uint8Array): { contentType: string; extension: string } | null {
  const ascii = (start: number, end: number) => String.fromCharCode(...data.slice(start, end))
  if (data.length >= 24
    && data[0] === 0x89
    && ascii(1, 4) === 'PNG'
    && ascii(12, 16) === 'IHDR') return { contentType: 'image/png', extension: 'png' }
  if (data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) {
    return { contentType: 'image/jpeg', extension: 'jpg' }
  }
  if (data.length >= 10 && (ascii(0, 6) === 'GIF87a' || ascii(0, 6) === 'GIF89a')) {
    return { contentType: 'image/gif', extension: 'gif' }
  }
  if (data.length >= 26 && ascii(0, 2) === 'BM') return { contentType: 'image/bmp', extension: 'bmp' }
  if (data.length >= 12 && ascii(0, 4) === 'RIFF' && ascii(8, 12) === 'WEBP') {
    return { contentType: 'image/webp', extension: 'webp' }
  }
  if (data.length >= 16 && ascii(4, 8) === 'ftyp') {
    const brand = ascii(8, 12)
    const compatibleBrands = ascii(16, Math.min(data.length, 64))
    if (brand === 'avif' || brand === 'avis' || compatibleBrands.includes('avif')) {
      return { contentType: 'image/avif', extension: 'avif' }
    }
  }
  return null
}

async function readResponseBytes(response: Response): Promise<Uint8Array> {
  const declaredLength = Number(response.headers.get('content-length') || 0)
  if (declaredLength > MAX_IMAGE_BYTES) throw new Error('图片超过 10 MiB 限制')
  if (!response.body) {
    const data = new Uint8Array(await response.arrayBuffer())
    if (data.byteLength > MAX_IMAGE_BYTES) throw new Error('图片超过 10 MiB 限制')
    return data
  }

  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.byteLength
    if (total > MAX_IMAGE_BYTES) {
      await reader.cancel()
      throw new Error('图片超过 10 MiB 限制')
    }
    chunks.push(value)
  }
  const data = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    data.set(chunk, offset)
    offset += chunk.byteLength
  }
  return data
}

async function downloadAsset(asset: CaptureAssetDescriptor): Promise<DownloadedAsset> {
  if (!isAllowedWechatAssetUrl(asset.url)) throw new Error('图片地址不在微信素材域名范围内')
  const response = await fetch(asset.url, {
    method: 'GET',
    credentials: 'omit',
    cache: 'no-store',
    redirect: 'follow',
    referrerPolicy: 'no-referrer',
  })
  if (!response.ok || !isAllowedWechatAssetUrl(response.url)) throw new Error('图片下载失败')
  const data = await readResponseBytes(response)
  const image = sniffImage(data)
  if (!image) throw new Error('图片格式不受支持')
  return {
    assetId: asset.assetId,
    blob: new Blob([data.slice().buffer as ArrayBuffer], { type: image.contentType }),
    contentType: image.contentType,
    extension: image.extension,
    size: data.byteLength,
  }
}

async function downloadAssets(assets: CaptureAssetDescriptor[]): Promise<Map<string, DownloadedAsset>> {
  const downloads = new Map<string, DownloadedAsset>()
  let cursor = 0
  const workers = Array.from({ length: Math.min(4, assets.length) }, async () => {
    while (cursor < assets.length) {
      const index = cursor++
      const asset = assets[index]
      if (!asset) continue
      try {
        downloads.set(asset.assetId, await downloadAsset(asset))
      } catch {
        // Failed assets are removed from the cloned DOM during finalization.
      }
    }
  })
  await Promise.all(workers)
  return downloads
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload = await response.json() as unknown
    if (isRecord(payload)) {
      const detail = payload.detail
      if (typeof detail === 'string') return detail
      if (isRecord(detail) && typeof detail.message === 'string') return detail.message
    }
  } catch {
    // Use the stable fallback below when the body is not JSON.
  }
  return `浏览器采集上传失败（HTTP ${response.status}）`
}

async function uploadCapture(
  stored: StoredCaptureSession,
  capture: FinalizedCaptureDraft,
  files: DownloadedAsset[],
): Promise<unknown> {
  if (new TextEncoder().encode(capture.sourceHtml).byteLength > MAX_HTML_BYTES) {
    throw new Error('采集正文超过 5 MiB 限制，无法上传')
  }
  const form = new FormData()
  form.append('source_html', capture.sourceHtml)
  form.append('title', capture.title)
  form.append('manifest', JSON.stringify({
    url: stored.session.canonical_url,
    omitted_asset_count: capture.omittedAssetCount,
    cover_asset_id: stored.session.purpose === 'web_article_import' ? capture.coverAssetId : null,
    assets: files.map((file) => ({
      asset_id: file.assetId,
      content_type: file.contentType,
      size: file.size,
    })),
  }))
  for (const file of files) form.append('files', file.blob, `${file.assetId}.${file.extension}`)

  const completionPath = captureCompletionPath(stored.session.purpose, stored.session.id)
  const response = await fetch(
    `${stored.appOrigin}${completionPath}`,
    {
      method: 'POST',
      credentials: 'omit',
      headers: { 'X-Layout-Capture-Token': stored.session.token },
      body: form,
      redirect: 'error',
    },
  )
  if (!response.ok) throw new Error(await responseError(response))
  const preview = await response.json() as unknown
  const validPreview = isRecord(preview)
    && typeof preview.preview_html === 'string'
    && (stored.session.purpose === 'web_article_import'
      ? typeof preview.id === 'string' && Array.isArray(preview.warnings)
      : typeof preview.reference_id === 'string')
  if (!validPreview) {
    throw new Error(stored.session.purpose === 'web_article_import'
      ? '服务器返回的文章导入预览格式无效'
      : '服务器返回的排版预览格式无效')
  }
  return preview
}

async function performCapture(stored: StoredCaptureSession): Promise<void> {
  if (runningSessionId) throw new Error('已有浏览器采集任务正在进行')
  runningSessionId = stored.session.id
  let draftId: string | null = null
  let finalized = false
  try {
    const articleTab = await findArticleTab(stored.session.canonical_url)
    if (articleTab?.id === undefined) throw new Error('未找到关联的微信文章页，请重新打开文章')
    stored.articleTabId = articleTab.id
    await chrome.storage.session.set({ [SESSION_STORAGE_KEY]: stored })
    await ensureWechatCaptureScript(articleTab.id)
    await sendAppEvent(stored, 'status', { status: 'capturing' })
    await sendArticleEvent(stored, 'capturing')

    let draftResponse: unknown
    try {
      draftResponse = await chrome.tabs.sendMessage(articleTab.id, {
        type: 'layoutCapture:createDraft',
        session: {
          id: stored.session.id,
          canonical_url: stored.session.canonical_url,
          expires_at: stored.session.expires_at,
          purpose: stored.session.purpose,
        },
      }) as unknown
    } catch {
      throw new Error('微信文章页未准备好，请刷新文章页后重新发起抓取')
    }
    if (!isRecord(draftResponse) || draftResponse.ok !== true || !isRecord(draftResponse.draft)) {
      throw new Error(isRecord(draftResponse) && typeof draftResponse.message === 'string'
        ? draftResponse.message
        : '无法读取微信文章正文，请确认验证已经完成')
    }
    const draft = draftResponse.draft as unknown as CaptureDraftRead
    if (typeof draft.draftId !== 'string'
      || !Array.isArray(draft.assets)
      || (draft.coverAssetId !== null && typeof draft.coverAssetId !== 'string')) {
      throw new Error('微信文章采集数据格式无效')
    }
    draftId = draft.draftId
    await sendArticleEvent(stored, 'downloading', {
      message: draft.assets.length > 0
        ? `正文结构读取完成，正在处理 ${draft.assets.length} 个图片素材。`
        : '正文结构读取完成，未检测到需要上传的图片素材。',
    })

    const downloaded = await downloadAssets(draft.assets)
    const failedIds = new Set(draft.assets.filter((asset) => !downloaded.has(asset.assetId)).map((asset) => asset.assetId))
    let totalSize = 0
    for (const asset of draft.assets) {
      const file = downloaded.get(asset.assetId)
      if (!file || failedIds.has(asset.assetId)) continue
      if (totalSize + file.size > MAX_TOTAL_IMAGE_BYTES) failedIds.add(asset.assetId)
      else totalSize += file.size
    }

    const finalizeResponse = await chrome.tabs.sendMessage(articleTab.id, {
      type: 'layoutCapture:finalizeDraft',
      draftId,
      failedAssetIds: Array.from(failedIds),
    }) as unknown
    if (!isRecord(finalizeResponse) || finalizeResponse.ok !== true || !isRecord(finalizeResponse.capture)) {
      throw new Error(isRecord(finalizeResponse) && typeof finalizeResponse.message === 'string'
        ? finalizeResponse.message
        : '无法完成微信文章采集')
    }
    finalized = true
    const capture = finalizeResponse.capture as unknown as FinalizedCaptureDraft
    const activeIds = new Set(capture.activeAssetIds)
    const files = draft.assets
      .map((asset) => downloaded.get(asset.assetId))
      .filter((file): file is DownloadedAsset => Boolean(file) && activeIds.has(file!.assetId))

    await sendAppEvent(stored, 'status', { status: 'uploading' })
    await sendArticleEvent(stored, 'uploading', {
      message: files.length > 0
        ? `已保留 ${files.length} 个图片素材，正在上传并生成预览。`
        : stored.session.purpose === 'web_article_import'
          ? '正在上传正文结构并生成文章导入预览。'
          : '正在上传正文结构并生成排版预览。',
    })
    const preview = await uploadCapture(stored, capture, files)
    await sendAppEvent(stored, 'result', { preview })
    await sendArticleEvent(stored, 'success')
    await clearStoredSession(stored.session.id)
  } catch (error) {
    const message = extensionErrorMessage(error)
    await sendAppEvent(stored, 'error', { message })
    await sendArticleEvent(stored, 'error', { message })
    await clearStoredSession(stored.session.id)
  } finally {
    if (draftId && !finalized && stored.articleTabId !== undefined) {
      try {
        await chrome.tabs.sendMessage(stored.articleTabId, { type: 'layoutCapture:discardDraft', draftId })
      } catch {
        // The article tab may have been closed while downloading.
      }
    }
    runningSessionId = null
  }
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  if (!isRecord(message) || typeof message.type !== 'string') return false
  if (message.type === 'layoutCapture:register') {
    void registerSession(message, sender).then(sendResponse)
    return true
  }
  if (message.type === 'layoutCapture:cancel' && typeof message.sessionId === 'string') {
    void clearStoredSession(message.sessionId).then(() => sendResponse({ ok: true }))
    return true
  }
  if (message.type === 'layoutCapture:getState') {
    void readStoredSession().then((stored) => sendResponse({ ok: true, stored, running: Boolean(runningSessionId) }))
    return true
  }
  if (message.type === 'layoutCapture:getArticleTask') {
    void readStoredSession().then((stored) => {
      const tabId = sender.tab?.id
      const senderUrl = sender.url
      const associated = stored && tabId !== undefined && (
        stored.articleTabId === tabId
        || (typeof senderUrl === 'string' && captureUrlsMatch(senderUrl, stored.session.canonical_url))
      )
      if (!stored || !associated) {
        sendResponse({ ok: true, active: false })
        return
      }
      sendResponse({
        ok: true,
        active: true,
        running: runningSessionId === stored.session.id,
        session: {
          id: stored.session.id,
          canonical_url: stored.session.canonical_url,
          expires_at: stored.session.expires_at,
          purpose: stored.session.purpose,
        },
      })
    })
    return true
  }
  if (message.type === 'layoutCapture:begin') {
    void readStoredSession().then((stored) => {
      if (!stored) {
        sendResponse({ ok: false, message: '没有待采集会话，请返回系统重新发起抓取' })
        return
      }
      if (sender.tab?.id !== undefined
        && sender.tab.id !== stored.articleTabId
        && !(typeof sender.url === 'string' && captureUrlsMatch(sender.url, stored.session.canonical_url))) {
        sendResponse({ ok: false, message: '当前微信页面与采集任务不匹配' })
        return
      }
      if (runningSessionId) {
        sendResponse({ ok: false, message: '采集任务已在进行中' })
        return
      }
      sendResponse({ ok: true })
      void performCapture(stored)
    })
    return true
  }
  return false
})

chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm.name.startsWith(EXPIRY_ALARM_PREFIX)) return
  const sessionId = alarm.name.slice(EXPIRY_ALARM_PREFIX.length)
  void readStoredSession().then(async (stored) => {
    if (!stored || stored.session.id !== sessionId) return
    await sendAppEvent(stored, 'error', { message: '浏览器采集会话已过期，请返回系统重新发起抓取' })
    await clearStoredSession(sessionId)
  })
})

async function injectAppBridgeIntoOpenTabs(): Promise<void> {
  const tabs = await chrome.tabs.query({ url: APP_ORIGINS.map((origin) => `${origin}/*`) })
  await Promise.all(tabs.map(async (tab) => {
    if (tab.id === undefined) return
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['app-bridge.js'] })
    } catch {
      // Restricted or closing tabs will be handled by the normal content-script injection on reload.
    }
  }))
}

void injectAppBridgeIntoOpenTabs()
