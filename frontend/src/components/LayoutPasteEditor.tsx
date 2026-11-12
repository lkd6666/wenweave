import { useEffect, useRef } from 'react'
import { MAX_LAYOUT_PASTE_BYTES, plainTextLayoutHtml, sanitizeLayoutPasteHtml } from '../utils/layoutPasteHtml'

interface Props {
  value: string
  disabled: boolean
  onChange: (html: string, text: string) => void
  onError: (message: string) => void
}

const EDITOR_DOCUMENT = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<style>
*{box-sizing:border-box}html{min-height:100%;background:#fff}body{margin:0;min-height:100vh;padding:14px;color:#182230;font:15px/1.85 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;overflow-wrap:anywhere;outline:none}
body:empty:before{content:'复制文章后粘贴，直接显示排版；也可以输入文字。';color:#9ca3af;pointer-events:none}
article,section,div,figure,blockquote,img,svg,table{max-width:100%}p{margin:0 0 1em}table{border-collapse:collapse}a{cursor:text}
</style></head><body contenteditable="true" role="textbox" aria-label="参考原文" aria-multiline="true"></body></html>`

export default function LayoutPasteEditor({ value, disabled, onChange, onError }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const cleanupRef = useRef<(() => void) | null>(null)
  const latestRef = useRef({ value, disabled, onChange, onError })
  latestRef.current = { value, disabled, onChange, onError }

  useEffect(() => {
    const body = frameRef.current?.contentDocument?.body
    if (!body) return
    if (body.innerHTML !== value) body.innerHTML = value
  }, [value])

  useEffect(() => {
    const body = frameRef.current?.contentDocument?.body
    if (!body) return
    body.contentEditable = String(!disabled)
    body.setAttribute('aria-disabled', String(disabled))
  }, [disabled])

  useEffect(() => () => cleanupRef.current?.(), [])

  const attachEditor = () => {
    cleanupRef.current?.()
    const document = frameRef.current?.contentDocument
    const body = document?.body
    if (!document || !body) return
    body.innerHTML = latestRef.current.value
    body.contentEditable = String(!latestRef.current.disabled)
    body.setAttribute('aria-disabled', String(latestRef.current.disabled))

    const emit = () => {
      const text = body.innerText ?? body.textContent ?? ''
      const html = !text.trim() && !body.querySelector('img,svg,table,hr,[style]') ? '' : body.innerHTML
      latestRef.current.onChange(html, text)
    }
    const paste = (event: ClipboardEvent) => {
      event.preventDefault()
      if (latestRef.current.disabled) return
      const rich = event.clipboardData?.getData('text/html') ?? ''
      const text = event.clipboardData?.getData('text/plain') ?? ''
      if (!rich && !text) return
      if (new TextEncoder().encode(rich || text).byteLength > MAX_LAYOUT_PASTE_BYTES) {
        latestRef.current.onError('粘贴内容不能超过 5MB')
        return
      }
      const html = rich ? sanitizeLayoutPasteHtml(rich) : plainTextLayoutHtml(text)
      body.focus()
      // execCommand preserves the browser's undo history for rich paste.
      // The Range fallback also supports engines without that editing command.
      const previousHtml = body.innerHTML
      let inserted = false
      try { inserted = document.execCommand?.('insertHTML', false, html) ?? false } catch { /* Use the Range fallback. */ }
      // Sandboxed Chromium can return false even after it changes the document.
      if (!inserted && body.innerHTML === previousHtml) {
        const selection = document.getSelection()
        const range = selection?.rangeCount ? selection.getRangeAt(0) : document.createRange()
        if (!body.contains(range.commonAncestorContainer)) {
          range.selectNodeContents(body)
          range.collapse(false)
        }
        range.deleteContents()
        const fragment = range.createContextualFragment(html)
        const last = fragment.lastChild
        range.insertNode(fragment)
        if (last) range.setStartAfter(last)
        range.collapse(true)
        selection?.removeAllRanges()
        selection?.addRange(range)
      }
      emit()
    }
    const preventNavigation = (event: Event) => {
      if (event.type === 'drop' || (event.target as Element | null)?.closest?.('a')) event.preventDefault()
    }
    body.addEventListener('input', emit)
    body.addEventListener('paste', paste)
    body.addEventListener('click', preventNavigation)
    body.addEventListener('drop', preventNavigation)
    cleanupRef.current = () => {
      body.removeEventListener('input', emit)
      body.removeEventListener('paste', paste)
      body.removeEventListener('click', preventNavigation)
      body.removeEventListener('drop', preventNavigation)
    }
  }

  return <iframe ref={frameRef} className="layout-paste-editor" title="参考原文编辑区"
    sandbox="allow-same-origin" referrerPolicy="no-referrer" aria-disabled={disabled}
    srcDoc={EDITOR_DOCUMENT} onLoad={attachEditor} />
}
