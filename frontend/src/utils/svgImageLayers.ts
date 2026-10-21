export interface SvgImageLayer {
  element: Element
  source: string
  label: string
}

export function collectSvgImageLayers(roots: readonly Element[]): SvgImageLayer[] {
  const seen = new Set<Element>()
  const layers: SvgImageLayer[] = []

  const orderedRoots = [...roots].sort((left, right) => (
    left === right ? 0 : left.compareDocumentPosition(right) & 4 ? -1 : 1
  ))
  for (const root of orderedRoots) {
    const images = root.matches('svg image') ? [root, ...root.querySelectorAll('svg image')] : root.querySelectorAll('svg image')
    for (const image of images) {
      if (seen.has(image)) continue
      seen.add(image)
      layers.push({
        element: image,
        source: image.getAttribute('href')?.trim() || image.getAttribute('xlink:href')?.trim() || '',
        label: image.getAttribute('aria-label')?.trim()
          || image.getAttribute('alt')?.trim()
          || image.getAttribute('title')?.trim()
          || '',
      })
    }
  }

  return layers
}
