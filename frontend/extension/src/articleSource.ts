import { MAX_HTML_BYTES, captureUrlsMatch, isRecord } from './shared'

const MAX_SOURCE_BYTES = 10 * 1024 * 1024

/** Decode a string literal as data; never execute the page's JavaScript. */
function decodeStringLiteral(value: string): string {
  const escapes: Record<string, string> = { n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', v: '\v', '0': '\0' }
  return value.replace(/\\(?:x([0-9a-f]{2})|u([0-9a-f]{4})|\r?\n|([\s\S]))/gi, (_match, hex: string, unicode: string, escaped: string) => {
    if (hex || unicode) return String.fromCharCode(Number.parseInt(hex || unicode, 16))
    return escaped === undefined ? '' : escapes[escaped] ?? escaped
  })
}

function embeddedArticleHtml(doc: Document): string | null {
  for (const script of Array.from(doc.scripts)) {
    const match = script.textContent?.match(/\bcontent_noencode\s*:\s*(['"])((?:\\[\s\S]|(?!\1)[^\\])*)\1/)
    if (!match) continue
    const html = decodeStringLiteral(match[2]!)
    if (html.trim() && new TextEncoder().encode(html).byteLength <= MAX_HTML_BYTES) return html
  }
  return null
}

export function originalArticleDocument(doc: Document): Document {
  const original = new DOMParser().parseFromString(doc.documentElement.outerHTML, 'text/html')
  const root = original.querySelector<HTMLElement>('#js_content')
  const html = embeddedArticleHtml(doc)
  if (root && html) root.innerHTML = html
  // Runtime dark-mode attributes/classes are not part of the author's HTML.
  for (const element of Array.from(original.querySelectorAll<HTMLElement>('*'))) {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name.startsWith('data-darkmode-original-color-')) element.style?.setProperty('color', attribute.value)
      if (attribute.name.startsWith('data-darkmode-original-bgcolor-')) element.style?.setProperty('background-color', attribute.value)
      if (attribute.name.startsWith('data-darkmode-') || attribute.name === 'data_color_scheme_dark') element.removeAttribute(attribute.name)
    }
    for (const name of Array.from(element.classList)) {
      if (/^js_darkmode__\d+$/.test(name)) element.classList.remove(name)
    }
  }
  return original
}

async function loadOriginalArticleDocument(doc: Document, currentUrl: string): Promise<Document> {
  // WeChat often retains the editor's original HTML in its initial data. This
  // avoids another request and also restores DOM changed by image/dark scripts.
  if (embeddedArticleHtml(doc)) return originalArticleDocument(doc)
  try {
    const response = await fetch(currentUrl, {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(8000),
    })
    if (!response.ok || !captureUrlsMatch(response.url, currentUrl)) throw new Error('Article source unavailable')
    if (Number(response.headers.get('content-length')) > MAX_SOURCE_BYTES) throw new Error('Article source too large')
    const reader = response.body?.getReader()
    if (!reader) throw new Error('Article source unavailable')
    const chunks: Uint8Array[] = []
    let bytes = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        bytes += value.byteLength
        if (bytes > MAX_SOURCE_BYTES) throw new Error('Article source too large')
        chunks.push(value)
      }
    } finally {
      await reader.cancel()
    }
    const data = new Uint8Array(bytes)
    let offset = 0
    for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.byteLength }
    const original = new DOMParser().parseFromString(new TextDecoder().decode(data), 'text/html')
    const root = original.querySelector('#js_content')
    if (root && (root.textContent?.trim() || root.querySelector('img, svg'))) return originalArticleDocument(original)
  } catch {
    // A verification response, failed request, or oversized source still has a
    // usable article DOM in the verified tab. Keep its declarations as fallback.
  }
  return originalArticleDocument(doc)
}

export async function readOriginalArticleDocument(doc: Document, currentUrl: string): Promise<Document> {
  const original = await loadOriginalArticleDocument(doc, currentUrl)
  const links = Array.from(original.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"]')).slice(0, 64)
  let cursor = 0
  let totalBytes = 0
  await Promise.all(Array.from({ length: Math.min(4, links.length) }, async () => {
    while (cursor < links.length) {
      const link = links[cursor++]!
      try {
        const url = new URL(link.getAttribute('href') || '', currentUrl)
        if (url.protocol !== 'https:' || !['mp.weixin.qq.com', 'res.wx.qq.com'].includes(url.hostname)) continue
        const response: unknown = await chrome.runtime.sendMessage({ type: 'layoutCapture:readStylesheet', url: url.href })
        if (!isRecord(response) || response.ok !== true || typeof response.css !== 'string') continue
        totalBytes += new TextEncoder().encode(response.css).byteLength
        if (totalBytes > 4 * 1024 * 1024) continue
        const style = original.createElement('style')
        style.media = link.media
        style.textContent = response.css.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/gi, (match, _quote: string, source: string) => {
          if (source.trim().startsWith('#')) return match
          return `url("${new URL(source.trim(), url).href.replaceAll('"', '%22')}")`
        })
        link.replaceWith(style)
      } catch {
        // Accessible CSSOM rules and inline styles remain available if a sheet
        // cannot be loaded. Fetch failures do not discard the article HTML.
      }
    }
  }))
  return original
}
