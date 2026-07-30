const DISALLOWED_LINK_PROTOCOL = /^\s*(?:data|file|javascript|vbscript):/i
const MINI_PROGRAM_ATTRIBUTE_PREFIX = 'data-miniprogram-'
const STANDARD_TEXT_LINK_COLOR = '#576b95'

/** Keep rich-content previews isolated while permitting user-initiated links. */
export const SANDBOX_ALLOW_NEW_WINDOW = 'allow-popups allow-popups-to-escape-sandbox'
export const SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW = `allow-same-origin ${SANDBOX_ALLOW_NEW_WINDOW}`

function isSafeLinkHref(href: string): boolean {
  return Boolean(href.trim()) && !href.startsWith('#') && !DISALLOWED_LINK_PROTOCOL.test(href)
}

/**
 * WeChat's `weapp_text_link` markup turns a pasted mini-program document link
 * into an attachment card. Keep the destination and label, but render it as a
 * conventional text link in the article and in the editor preview.
 */
export function normaliseWeChatMiniProgramLinks(root: ParentNode): void {
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a')) {
    const hasMiniProgramAttributes = Array.from(anchor.attributes).some((attribute) => (
      attribute.name.toLowerCase().startsWith(MINI_PROGRAM_ATTRIBUTE_PREFIX)
    ))
    if (!anchor.classList.contains('weapp_text_link') && !hasMiniProgramAttributes) continue

    anchor.classList.remove('weapp_text_link')
    if (!anchor.classList.length) anchor.removeAttribute('class')
    for (const attribute of Array.from(anchor.attributes)) {
      if (attribute.name.toLowerCase().startsWith(MINI_PROGRAM_ATTRIBUTE_PREFIX)) {
        anchor.removeAttribute(attribute.name)
      }
    }

    if (!anchor.style.fontSize) anchor.style.fontSize = '15px'
    if (!anchor.style.color) anchor.style.color = STANDARD_TEXT_LINK_COLOR
    if (!anchor.style.textDecoration && !anchor.style.textDecorationLine) {
      anchor.style.textDecoration = 'none'
    }
  }
}

export function markLinksToOpenInNewWindow(root: ParentNode): void {
  normaliseWeChatMiniProgramLinks(root)
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const href = anchor.getAttribute('href') ?? ''
    if (!isSafeLinkHref(href)) continue
    anchor.target = '_blank'
    const rel = new Set((anchor.getAttribute('rel') ?? '').split(/\s+/).filter(Boolean))
    rel.add('noopener')
    rel.add('noreferrer')
    anchor.setAttribute('rel', [...rel].join(' '))
  }
}

/**
 * Adds safe new-window semantics before untrusted rich HTML is assigned to an
 * iframe's srcDoc. DOMParser does not execute the document's scripts.
 */
export function frameDocumentWithNewWindowLinks(html: string): string {
  const document = new DOMParser().parseFromString(html, 'text/html')
  markLinksToOpenInNewWindow(document)
  return `<!doctype html>${document.documentElement.outerHTML}`
}
