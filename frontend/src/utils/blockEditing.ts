export const TEXT_BLOCK_SELECTOR = 'p,h1,h2,h3,h4,h5,h6,li,blockquote,td,th'

export const BLOCK_EDITING_TRANSIENT_CLASS = 'ai-block-selected'
export const BLOCK_HOVER_TRANSIENT_CLASS = 'ai-block-hovered'
export const BLOCK_HANDLE_ATTRIBUTE = 'data-preview-block-handle'
export const BLOCK_DROP_INDICATOR_ATTRIBUTE = 'data-preview-block-drop-indicator'

export type BlockSelectionChange = 'replace' | 'toggle' | 'clear'

const SIMPLE_BLOCK_TAGS = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'BLOCKQUOTE', 'HR', 'IMG'])
const CONTAINER_BLOCK_TAGS = new Set(['SECTION', 'ARTICLE', 'FIGURE', 'TABLE', 'UL', 'OL'])

function isWithinEditorBody(element: HTMLElement, body: HTMLElement): boolean {
  return element !== body && body.contains(element)
}

/**
 * Finds the closest safe editing unit without promoting ordinary nested divs
 * into blocks. A top-level div remains available for HTML imported as a card.
 */
export function findEditableBlock(element: HTMLElement, body: HTMLElement): HTMLElement | null {
  let current: HTMLElement | null = element
  let fallback: HTMLElement | null = null

  while (current && isWithinEditorBody(current, body)) {
    if (current.matches('[data-editor-block]') || CONTAINER_BLOCK_TAGS.has(current.tagName)) return current
    if (SIMPLE_BLOCK_TAGS.has(current.tagName)) {
      if (current.tagName !== 'IMG' || !fallback) fallback = current
      if (current.tagName !== 'IMG') return current
    }
    if (
      current.tagName === 'DIV'
      && current.parentElement === body
      && !current.querySelector(TEXT_BLOCK_SELECTOR)
    ) {
      return current
    }
    current = current.parentElement
  }

  return fallback
}

export function sortBlocksInDocumentOrder(blocks: HTMLElement[]): HTMLElement[] {
  return [...blocks].sort((left, right) => {
    if (left === right) return 0
    return left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
  })
}

/** Applies the selection gestures shared by desktop modifier keys and mobile multi-select. */
export function nextBlockSelection<T>(
  current: readonly T[],
  target: T | null,
  change: BlockSelectionChange,
): T[] {
  if (change === 'clear' || target === null) return []
  if (change === 'replace') return [target]
  return current.includes(target)
    ? current.filter((item) => item !== target)
    : [...current, target]
}

export function areConsecutiveSiblingBlocks(blocks: HTMLElement[]): boolean {
  if (blocks.length === 0) return false
  const parent = blocks[0].parentElement
  if (!parent || blocks.some((block) => block.parentElement !== parent)) return false
  const indexes = sortBlocksInDocumentOrder(blocks).map((block) => Array.prototype.indexOf.call(parent.children, block))
  return indexes.every((index, position) => position === 0 || index === indexes[position - 1] + 1)
}

export function isInsideTableCell(block: HTMLElement): boolean {
  const table = block.closest('table')
  return Boolean(table && table !== block)
}

export function stripBlockEditingMarkup(root: HTMLElement): void {
  root.classList.remove(BLOCK_EDITING_TRANSIENT_CLASS)
  root.classList.remove(BLOCK_HOVER_TRANSIENT_CLASS)
  root.querySelectorAll(`.${BLOCK_EDITING_TRANSIENT_CLASS}`).forEach((node) => node.classList.remove(BLOCK_EDITING_TRANSIENT_CLASS))
  root.querySelectorAll(`.${BLOCK_HOVER_TRANSIENT_CLASS}`).forEach((node) => node.classList.remove(BLOCK_HOVER_TRANSIENT_CLASS))
  root.querySelectorAll(`[${BLOCK_HANDLE_ATTRIBUTE}], [${BLOCK_DROP_INDICATOR_ATTRIBUTE}]`).forEach((node) => node.remove())
}
