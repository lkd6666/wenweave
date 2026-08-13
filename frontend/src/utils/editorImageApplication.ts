export type ImageApplicationMode = 'replace' | 'insert'

export interface ImageApplicationTarget {
  kind: 'image' | 'block' | 'caret'
  node: HTMLImageElement | HTMLElement
}

function containsNode(root: Node, candidate: Node | null): candidate is Node {
  let current = candidate
  while (current) {
    if (current === root) return true
    current = current.parentNode
  }
  return false
}

export function resolveImageApplicationTarget(
  body: HTMLElement,
  image: HTMLImageElement | null,
  block: HTMLElement | null,
  caretBlock: HTMLElement | null,
): ImageApplicationTarget | null {
  if (containsNode(body, image)) return { kind: 'image', node: image as HTMLImageElement }
  if (containsNode(body, block)) return { kind: 'block', node: block as HTMLElement }
  if (containsNode(body, caretBlock)) return { kind: 'caret', node: caretBlock as HTMLElement }
  return null
}

export function applyLibraryImageToDom(
  document: Document,
  body: HTMLElement,
  target: ImageApplicationTarget | null,
  url: string,
  alt: string,
): { mode: ImageApplicationMode; image: HTMLImageElement; paragraph: HTMLElement | null } | null {
  const source = url.trim()
  if (!target || !source || !containsNode(body, target.node)) return null

  if (target.kind === 'image') {
    const image = target.node as HTMLImageElement
    image.setAttribute('src', source)
    image.removeAttribute('data-crop-source')
    image.removeAttribute('data-crop-rect')
    image.removeAttribute('srcset')
    image.removeAttribute('sizes')
    return { mode: 'replace', image, paragraph: null }
  }

  const anchor = target.node as HTMLElement
  const parent = anchor.parentNode
  if (!parent) return null
  const paragraph = document.createElement('p') as HTMLElement
  const image = document.createElement('img') as HTMLImageElement
  image.setAttribute('src', source)
  image.setAttribute('alt', alt.trim())
  image.setAttribute('style', 'display:block;width:100%;max-width:100%;height:auto;')
  paragraph.appendChild(image)
  parent.insertBefore(paragraph, anchor.nextSibling)
  return { mode: 'insert', image, paragraph }
}

export function stepEditHistory(
  direction: 'undo' | 'redo',
  currentHtml: string,
  undoStack: string[],
  redoStack: string[],
): string | null {
  const source = direction === 'undo' ? undoStack : redoStack
  const target = source.pop()
  if (target === undefined) return null
  const destination = direction === 'undo' ? redoStack : undoStack
  destination.push(currentHtml)
  return target
}
