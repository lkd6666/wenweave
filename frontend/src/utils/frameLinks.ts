const DISALLOWED_LINK_PROTOCOL = /^\s*(?:data|file|javascript|vbscript):/i

/** Keep rich-content previews isolated while permitting user-initiated links. */
export const SANDBOX_ALLOW_NEW_WINDOW = 'allow-popups allow-popups-to-escape-sandbox'
export const SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW = `allow-same-origin ${SANDBOX_ALLOW_NEW_WINDOW}`

function isSafeLinkHref(href: string): boolean {
  return Boolean(href.trim()) && !href.startsWith('#') && !DISALLOWED_LINK_PROTOCOL.test(href)
}

export function markLinksToOpenInNewWindow(root: ParentNode): void {
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
 * Normalizes links in an article fragment before it is embedded in a trusted
 * iframe document. Keeping this separate is important for documents that use
 * CSP nonces: browsers deliberately hide nonce attributes during DOM
 * serialization, so serializing the complete document would invalidate its
 * trusted scripts.
 */
export function articleHtmlWithNewWindowLinks(html: string): string {
  const document = new DOMParser().parseFromString(html, 'text/html')
  markLinksToOpenInNewWindow(document)
  return document.body.innerHTML
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
