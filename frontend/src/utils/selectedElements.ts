import type { SelectedElementContext } from '../types'

export const MAX_SELECTED_ELEMENT_COUNT = 12
export const MAX_SELECTED_ELEMENT_HTML_CHARS = 12_000
export const MAX_SELECTED_ELEMENTS_HTML_CHARS = 48_000
export const MAX_SELECTED_ELEMENT_TEXT_CHARS = 1_000

// Selected elements are context for the Agent, never an image transport. This
// covers data: URLs in attributes and inline CSS without touching document HTML.
const DATA_URI_PATTERN = /data:([a-z][a-z0-9+.-]{0,127}(?:\/[a-z0-9+.-]+)?)(?:;[a-z0-9!#$&^_.+-]+)*,[^"'<>)]*/gi
const TRUNCATION_MARKER = '\n<!-- selected element context truncated -->'

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value
  return `${value.slice(0, Math.max(0, maxLength - TRUNCATION_MARKER.length))}${TRUNCATION_MARKER}`
}

export function sanitizeSelectedElement(element: SelectedElementContext): SelectedElementContext {
  const html = String(element.html ?? '').replace(DATA_URI_PATTERN, (_match, mediaType: string) => (
    `[inline ${mediaType.toLowerCase().split('/', 1)[0]} data omitted]`
  ))
  return {
    selector: String(element.selector ?? '').slice(0, 1024),
    tag_name: String(element.tag_name ?? '').slice(0, 64),
    html: truncate(html, MAX_SELECTED_ELEMENT_HTML_CHARS),
    text: String(element.text ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_SELECTED_ELEMENT_TEXT_CHARS),
  }
}

export function sanitizeSelectedElements(elements: SelectedElementContext[]): SelectedElementContext[] {
  const sanitized: SelectedElementContext[] = []
  let remainingHtmlChars = MAX_SELECTED_ELEMENTS_HTML_CHARS

  for (const element of elements.slice(0, MAX_SELECTED_ELEMENT_COUNT)) {
    if (remainingHtmlChars <= 0) break
    const next = sanitizeSelectedElement(element)
    if (!next.selector || !next.tag_name || !next.html) continue
    const html = truncate(next.html, Math.min(MAX_SELECTED_ELEMENT_HTML_CHARS, remainingHtmlChars))
    sanitized.push({ ...next, html })
    remainingHtmlChars -= html.length
  }

  return sanitized
}
