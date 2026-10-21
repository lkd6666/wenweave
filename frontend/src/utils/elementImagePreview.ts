export function extractImagePreview(html: string): { src: string; alt: string } | null {
  const isSvgImage = /^\s*<image(?=[\s/>])/i.test(html)
  const document = new DOMParser().parseFromString(isSvgImage ? `<svg>${html}</svg>` : html, 'text/html')
  const root = document.body.firstElementChild
  if (!root || document.body.children.length !== 1) return null
  const element = isSvgImage ? root.firstElementChild : root
  if (!element || (isSvgImage ? root.localName !== 'svg' || root.children.length !== 1 || element.localName !== 'image' : element.tagName !== 'IMG')) return null
  return {
    src: isSvgImage
      ? element.getAttribute('href')?.trim() || element.getAttribute('xlink:href')?.trim() || ''
      : element.getAttribute('src') ?? '',
    alt: element.getAttribute('alt') || element.getAttribute('aria-label') || element.getAttribute('title') || '',
  }
}
