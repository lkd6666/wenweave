import type { SelectedElementContext, SelectedElementLocator } from '../types'

export const MAX_SELECTED_ELEMENT_COUNT = 12
export const MAX_SELECTED_ELEMENT_HTML_CHARS = 12_000
export const MAX_SELECTED_ELEMENTS_HTML_CHARS = 48_000
export const MAX_SELECTED_ELEMENT_TEXT_CHARS = 1_000

// Selected elements are context for the Agent, never an image transport. This
// covers data: URLs in attributes and inline CSS without touching document HTML.
const DATA_URI_PATTERN = /data:([a-z][a-z0-9+.-]{0,127}(?:\/[a-z0-9+.-]+)?)(?:;[a-z0-9!#$&^_.+-]+)*,[^"'<>)]*/gi
const TRUNCATION_MARKER = '\n<!-- selected element context truncated -->'

function inlineDataIdentity(value: string): string {
  // Keep a stable, content-derived identity for an embedded resource without
  // placing its Base64 payload in the message. FNV-1a runs over UTF-8 bytes so
  // the Python resolver can reproduce the same value from current HTML.
  let hash = 0xcbf29ce484222325n
  for (const byte of new TextEncoder().encode(value)) {
    hash ^= BigInt(byte)
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn
  }
  return hash.toString(16).padStart(16, '0')
}

function redactInlineDataForIdentity(value: string): string {
  return value.replace(DATA_URI_PATTERN, (match, mediaType: string) => (
    `[inline ${mediaType.toLowerCase().split('/', 1)[0]} data identity:${inlineDataIdentity(match)}]`
  ))
}

const sanitizeLocator = (locator: SelectedElementContext['locator']): SelectedElementLocator | undefined => {
  if (!locator || typeof locator !== 'object') return undefined
  const fingerprint = locator.fingerprint
  if (!fingerprint || typeof fingerprint !== 'object') return undefined
  const stableAttributes = Object.entries(fingerprint.stable_attributes ?? {})
    .slice(0, 16)
    .reduce<Record<string, string>>((result, [key, value]) => {
      const normalizedKey = String(key).toLowerCase().trim()
      if (!normalizedKey || !/^(id|src|srcset|href|xlink:href|name|data-[a-z0-9_-]+)$/.test(normalizedKey)) return result
      result[normalizedKey] = redactInlineDataForIdentity(String(value ?? '')).slice(0, 2048)
      return result
    }, {})
  const siblingIndex = Number(locator.sibling_index)
  return {
    path: String(locator.path ?? '').slice(0, 1024),
    parent_path: String(locator.parent_path ?? '').slice(0, 1024),
    sibling_index: Number.isInteger(siblingIndex) && siblingIndex > 0 ? Math.min(siblingIndex, 10000) : 0,
    fingerprint: {
      tag_name: String(fingerprint.tag_name ?? '').slice(0, 64),
      stable_attributes: stableAttributes,
      text: String(fingerprint.text ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_SELECTED_ELEMENT_TEXT_CHARS),
    },
  }
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value
  return `${value.slice(0, Math.max(0, maxLength - TRUNCATION_MARKER.length))}${TRUNCATION_MARKER}`
}

export function sanitizeSelectedElement(element: SelectedElementContext): SelectedElementContext {
  const html = String(element.html ?? '').replace(DATA_URI_PATTERN, (_match, mediaType: string) => (
    `[inline ${mediaType.toLowerCase().split('/', 1)[0]} data omitted]`
  ))
  const sanitized: SelectedElementContext = {
    selector: String(element.selector ?? '').slice(0, 1024),
    tag_name: String(element.tag_name ?? '').slice(0, 64),
    html: truncate(html, MAX_SELECTED_ELEMENT_HTML_CHARS),
    text: String(element.text ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_SELECTED_ELEMENT_TEXT_CHARS),
    locator: sanitizeLocator(element.locator),
  }
  if (element.kind === 'image' || element.kind === 'element') sanitized.kind = element.kind
  if (element.source_attribute === 'src' || element.source_attribute === 'href' || element.source_attribute === 'xlink:href') {
    sanitized.source_attribute = element.source_attribute
  }
  if (element.source_fingerprint) sanitized.source_fingerprint = String(element.source_fingerprint).slice(0, 128)
  return sanitized
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
