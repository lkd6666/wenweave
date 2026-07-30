type HtmlToken = {
  value: string
  kind: 'tag' | 'text' | 'declaration'
  name?: string
  closing?: boolean
  selfClosing?: boolean
}

const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr',
])

const RAW_TEXT_TAGS = new Set(['pre', 'script', 'style', 'textarea'])
const STRUCTURAL_VOID_TAGS = new Set(['base', 'col', 'hr', 'img', 'link', 'meta'])
const TEXT_LINE_LENGTH = 120

function findTagEnd(html: string, start: number): number {
  let quote = ''
  for (let index = start + 1; index < html.length; index += 1) {
    const character = html[index]
    if (quote) {
      if (character === quote) quote = ''
      continue
    }
    if (character === '"' || character === "'") {
      quote = character
    } else if (character === '>') {
      return index
    }
  }
  return html.length - 1
}

function compactTagWhitespace(value: string): string {
  let result = ''
  let quote = ''
  let pendingWhitespace = false

  for (const character of value) {
    if (quote) {
      result += character
      if (character === quote) quote = ''
      continue
    }
    if (character === '"' || character === "'") {
      if (pendingWhitespace && result && !result.endsWith('<')) result += ' '
      pendingWhitespace = false
      result += character
      quote = character
      continue
    }
    if (/\s/.test(character)) {
      pendingWhitespace = true
      continue
    }
    if (pendingWhitespace && result && character !== '>' && character !== '/') result += ' '
    pendingWhitespace = false
    result += character
  }

  return result
}

function tokeniseHtml(html: string): HtmlToken[] {
  const tokens: HtmlToken[] = []
  let index = 0
  let rawTextTag: string | null = null

  while (index < html.length) {
    if (rawTextTag) {
      const lowerHtml = html.toLowerCase()
      const closingIndex = lowerHtml.indexOf(`</${rawTextTag}`, index)
      if (closingIndex === -1) {
        tokens.push({ kind: 'text', value: html.slice(index) })
        break
      }
      if (closingIndex > index) tokens.push({ kind: 'text', value: html.slice(index, closingIndex) })
      index = closingIndex
      rawTextTag = null
    }

    const nextTag = html.indexOf('<', index)
    if (nextTag === -1) {
      if (index < html.length) tokens.push({ kind: 'text', value: html.slice(index) })
      break
    }
    if (nextTag > index) tokens.push({ kind: 'text', value: html.slice(index, nextTag) })

    if (html.startsWith('<!--', nextTag)) {
      const commentEnd = html.indexOf('-->', nextTag + 4)
      const end = commentEnd === -1 ? html.length : commentEnd + 3
      tokens.push({ kind: 'declaration', value: html.slice(nextTag, end) })
      index = end
      continue
    }

    const end = findTagEnd(html, nextTag)
    const value = compactTagWhitespace(html.slice(nextTag, end + 1))
    const match = /^<\s*(\/)?\s*([a-zA-Z][\w:-]*)\b/.exec(value)
    if (!match) {
      tokens.push({ kind: 'declaration', value })
      index = end + 1
      continue
    }

    const name = match[2].toLowerCase()
    const closing = Boolean(match[1])
    const selfClosing = closing || /\/\s*>$/.test(value) || VOID_TAGS.has(name)
    tokens.push({ kind: 'tag', value, name, closing, selfClosing })
    index = end + 1
    if (!closing && !selfClosing && RAW_TEXT_TAGS.has(name)) rawTextTag = name
  }

  return tokens
}

/**
 * Format source without parsing or rewriting tags, attributes, or text. It
 * expands nested elements while retaining raw-text elements. Long paragraph
 * text remains one source line so source structure stays easy to scan.
 */
export function formatHtml(html: string): string {
  if (!html.trim()) return html

  const tokens = tokeniseHtml(html)
  const lines: string[] = []
  let currentLine = ''
  let indent = 0
  let lastKind: 'open' | 'close' | 'inline' | 'text' | 'declaration' | null = null
  const stack: Array<{ name: string; indent: number }> = []

  const flushLine = () => {
    if (currentLine.trim()) lines.push(currentLine.trimEnd())
    currentLine = ''
  }
  const write = (value: string, level = indent) => {
    if (!currentLine) currentLine = `${'  '.repeat(Math.max(0, level))}${value}`
    else currentLine += value
  }
  const startBlockLine = () => {
    if (currentLine.trim()) flushLine()
  }
  for (const token of tokens) {
    if (token.kind === 'text') {
      if (!token.value) continue
      if (/^\s+$/.test(token.value)) {
        // A line break between tags is source indentation rather than article text.
        // Keep a literal single space because it can separate adjacent inline nodes.
        if (!/[\r\n]/.test(token.value)) write(token.value)
        continue
      }
      const shouldStartTextLine = token.value.trim().length > TEXT_LINE_LENGTH
      if (shouldStartTextLine && currentLine.trim()) startBlockLine()
      write(token.value)
      lastKind = 'text'
      continue
    }

    if (token.kind === 'declaration') {
      if (currentLine.trim()) flushLine()
      write(token.value, 0)
      lastKind = 'declaration'
      continue
    }

    const name = token.name ?? ''
    if (token.closing) {
      const stackIndex = [...stack].map((item) => item.name).lastIndexOf(name)
      const opened = stackIndex >= 0 ? stack[stackIndex] : undefined
      if (opened) {
        indent = opened.indent
        stack.splice(stackIndex)
      } else {
        indent = Math.max(0, indent - 1)
      }
      if (lastKind === 'close') startBlockLine()
      write(token.value)
      lastKind = 'close'
      continue
    }

    if (token.selfClosing) {
      if (STRUCTURAL_VOID_TAGS.has(name) && currentLine.trim()) startBlockLine()
      else if (lastKind === 'close') startBlockLine()
      write(token.value)
      lastKind = STRUCTURAL_VOID_TAGS.has(name) ? 'close' : 'inline'
      continue
    }

    if (currentLine.trim()) startBlockLine()
    write(token.value)
    stack.push({ name, indent })
    indent += 1
    lastKind = 'open'
  }

  flushLine()
  return lines.join('\n')
}
