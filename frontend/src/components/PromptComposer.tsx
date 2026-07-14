import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { ClipboardEvent, DragEvent, KeyboardEvent, MouseEvent, PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import type { SelectedElementContext } from '../types'
import ElementRenderPreview from './ElementRenderPreview'

export interface PromptComposerHandle {
  getPayload: () => { message: string; references: SelectedElementContext[] }
}

interface PromptComposerProps {
  value: string
  references: SelectedElementContext[]
  disabled?: boolean
  onChange: (value: string) => void
  onSubmit: () => void
  onRemoveReference: (index: number) => void
  onDuplicateReference: (index: number) => void
  onMoveReference: (fromIndex: number, toIndex: number) => void
}

const PLACEHOLDER = '输入排版指令…（Shift+Enter 换行，Enter 发送）'
const PREVIEW_CLOSE_DELAY_MS = 180

function escapeHtml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function isSameReference(left: SelectedElementContext, right: SelectedElementContext) {
  return left.selector === right.selector && left.tag_name === right.tag_name && left.html === right.html
}

/** 文本与元素引用共用同一行流；引用令牌本身不可编辑，但可拖拽、复制、移除。 */
const PromptComposer = forwardRef<PromptComposerHandle, PromptComposerProps>(function PromptComposer(
  { value, references, disabled, onChange, onSubmit, onRemoveReference, onDuplicateReference, onMoveReference },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null)
  const lastEmittedValueRef = useRef('')
  const draggingTokenRef = useRef<HTMLElement | null>(null)
  const previewCloseTimerRef = useRef<number | null>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const [hoveredPreview, setHoveredPreview] = useState<{ context: SelectedElementContext; left: number; top: number; width: number } | null>(null)

  const cancelPreviewClose = () => {
    if (previewCloseTimerRef.current !== null) {
      window.clearTimeout(previewCloseTimerRef.current)
      previewCloseTimerRef.current = null
    }
  }

  const closePreview = () => {
    cancelPreviewClose()
    setHoveredPreview(null)
  }

  const schedulePreviewClose = () => {
    cancelPreviewClose()
    previewCloseTimerRef.current = window.setTimeout(() => {
      previewCloseTimerRef.current = null
      setHoveredPreview(null)
    }, PREVIEW_CLOSE_DELAY_MS)
  }

  const tokenNodes = () => Array.from(editorRef.current?.querySelectorAll<HTMLElement>('[data-reference-token]') ?? [])

  const contextFromToken = (token: HTMLElement): SelectedElementContext | null => {
    try {
      return JSON.parse(decodeURIComponent(token.dataset.referenceContext ?? '')) as SelectedElementContext
    } catch {
      return null
    }
  }

  const refreshLabels = () => {
    tokenNodes().forEach((token, index) => {
      const label = token.querySelector<HTMLElement>('[data-reference-label]')
      const context = contextFromToken(token)
      if (label && context) label.textContent = `@元素${index + 1} <${context.tag_name}>`
    })
  }

  const createToken = (context: SelectedElementContext) => {
    const token = document.createElement('span')
    token.className = 'prompt-reference-token'
    token.setAttribute('contenteditable', 'false')
    token.draggable = true
    token.dataset.referenceToken = 'true'
    token.dataset.referenceContext = encodeURIComponent(JSON.stringify(context))
    token.innerHTML = `<span class="prompt-reference-label" data-reference-label>@元素 &lt;${escapeHtml(context.tag_name)}&gt;</span><button type="button" data-reference-action="duplicate" aria-label="重复引用" title="重复引用">+</button><button type="button" data-reference-action="remove" aria-label="移除引用" title="移除引用">x</button>`
    return token
  }

  const appendTokenAtCaret = (context: SelectedElementContext) => {
    const editor = editorRef.current
    if (!editor) return
    const token = createToken(context)
    const selection = window.getSelection()
    const range = selection?.rangeCount && selection.getRangeAt(0)
    if (range && editor.contains(range.commonAncestorContainer)) {
      range.insertNode(token)
      range.setStartAfter(token)
      range.collapse(true)
      selection?.removeAllRanges()
      selection?.addRange(range)
    } else {
      if (editor.childNodes.length) editor.append(document.createTextNode(' '))
      editor.append(token, document.createTextNode(' '))
    }
    refreshLabels()
  }

  const insertPlainTextAtCaret = (value: string) => {
    const editor = editorRef.current
    if (!editor || !value) return
    const selection = window.getSelection()
    const range = selection?.rangeCount && selection.getRangeAt(0)
    const targetRange = range && editor.contains(range.commonAncestorContainer)
      ? range
      : document.createRange()
    if (!range || !editor.contains(range.commonAncestorContainer)) {
      targetRange.selectNodeContents(editor)
      targetRange.collapse(false)
    }
    const fragment = document.createDocumentFragment()
    const lines = value.replace(/\r\n?/g, '\n').split('\n')
    let lastNode: Node | null = null
    lines.forEach((line, index) => {
      const text = document.createTextNode(line)
      fragment.append(text)
      lastNode = text
      if (index < lines.length - 1) {
        const lineBreak = document.createElement('br')
        fragment.append(lineBreak)
        lastNode = lineBreak
      }
    })
    targetRange.deleteContents()
    targetRange.insertNode(fragment)
    if (lastNode) {
      targetRange.setStartAfter(lastNode)
      targetRange.collapse(true)
      selection?.removeAllRanges()
      selection?.addRange(targetRange)
    }
  }

  const payload = () => {
    const editor = editorRef.current
    const references: SelectedElementContext[] = []
    if (!editor) return { message: '', references }
    const readNode = (node: Node): string => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? ''
      if (node.nodeType !== Node.ELEMENT_NODE) return ''
      const element = node as HTMLElement
      if (element.dataset.referenceToken !== undefined) {
        const context = contextFromToken(element)
        if (!context) return ''
        references.push(context)
        return ` @元素${references.length} `
      }
      if (element.tagName === 'BR') return '\n'
      const text = Array.from(element.childNodes).map(readNode).join('')
      return /^(DIV|P)$/.test(element.tagName) ? `${text}\n` : text
    }
    const message = Array.from(editor.childNodes).map(readNode).join('').replace(/[ \t]+\n/g, '\n').trim()
    return { message, references }
  }

  const emitChange = () => {
    const nextValue = payload().message.replace(/@元素\d+/g, '').replace(/[ \t]{2,}/g, ' ').trim()
    lastEmittedValueRef.current = nextValue
    onChange(nextValue)
  }

  useImperativeHandle(ref, () => ({ getPayload: payload }))

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || value === lastEmittedValueRef.current) return
    const fragments = value.split(/(@元素\d+)/g)
    const nodes: Node[] = []
    for (const fragment of fragments) {
      const matchedReference = /^@元素(\d+)$/.exec(fragment)
      const context = matchedReference ? references[Number(matchedReference[1]) - 1] : undefined
      nodes.push(context ? createToken(context) : document.createTextNode(fragment))
    }
    editor.replaceChildren(...nodes)
    refreshLabels()
    lastEmittedValueRef.current = value
  }, [value, references])

  useEffect(() => {
    const tokens = tokenNodes()
    if (tokens.length < references.length) {
      references.slice(tokens.length).forEach(appendTokenAtCaret)
    } else if (tokens.length > references.length) {
      tokens.slice(references.length).forEach((token) => token.remove())
      refreshLabels()
    }
  }, [references])

  useEffect(() => {
    if (hoveredPreview && !references.some((reference) => isSameReference(reference, hoveredPreview.context))) {
      closePreview()
    }
  }, [hoveredPreview, references])

  useEffect(() => () => cancelPreviewClose(), [])

  const indexOfToken = (token: HTMLElement) => tokenNodes().indexOf(token)

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement
    const actionButton = target.closest<HTMLButtonElement>('[data-reference-action]')
    const token = target.closest<HTMLElement>('[data-reference-token]')
    if (!actionButton || !token) return
    event.preventDefault()
    event.stopPropagation()
    const index = indexOfToken(token)
    if (index < 0) return
    if (actionButton.dataset.referenceAction === 'duplicate') {
      const copy = token.cloneNode(true) as HTMLElement
      token.insertAdjacentElement('afterend', copy)
      refreshLabels()
      onDuplicateReference(index)
    } else {
      closePreview()
      token.remove()
      refreshLabels()
      onRemoveReference(index)
      emitChange()
    }
  }

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    const token = (event.target as HTMLElement).closest<HTMLElement>('[data-reference-token]')
    if (!token) return
    draggingTokenRef.current = token
    event.dataTransfer.effectAllowed = 'move'
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    const editor = editorRef.current
    const dragged = draggingTokenRef.current
    if (!editor || !dragged) return
    event.preventDefault()
    const sourceIndex = indexOfToken(dragged)
    const target = (event.target as HTMLElement).closest<HTMLElement>('[data-reference-token]')
    if (target && target !== dragged) {
      const targetIndex = indexOfToken(target)
      const placeAfter = event.clientX > target.getBoundingClientRect().left + target.getBoundingClientRect().width / 2
      target.insertAdjacentElement(placeAfter ? 'afterend' : 'beforebegin', dragged)
      const destinationIndex = placeAfter
        ? (sourceIndex < targetIndex ? targetIndex : targetIndex + 1)
        : (sourceIndex < targetIndex ? targetIndex - 1 : targetIndex)
      onMoveReference(sourceIndex, destinationIndex)
    } else if (!target) {
      const caretRange = document.caretRangeFromPoint?.(event.clientX, event.clientY)
      if (caretRange && editor.contains(caretRange.startContainer)) {
        caretRange.insertNode(dragged)
      } else {
        editor.append(dragged)
      }
      onMoveReference(sourceIndex, indexOfToken(dragged))
    }
    draggingTokenRef.current = null
    refreshLabels()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit()
    }
  }

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    if (disabled) return
    event.preventDefault()
    insertPlainTextAtCaret(event.clipboardData.getData('text/plain'))
    emitChange()
  }

  const handlePointerOver = (event: PointerEvent<HTMLDivElement>) => {
    const token = (event.target as HTMLElement).closest<HTMLElement>('[data-reference-token]')
    if (!token || token.contains(event.relatedTarget as Node | null)) return
    const context = contextFromToken(token)
    if (!context) return
    const tokenRect = token.getBoundingClientRect()
    const panelRect = token.closest<HTMLElement>('.chat-panel')?.getBoundingClientRect()
    const panelLeft = Math.max(8, panelRect?.left ?? 8)
    const panelRight = Math.min(window.innerWidth - 8, panelRect?.right ?? window.innerWidth - 8)
    const panelTop = Math.max(8, panelRect?.top ?? 8)
    const panelBottom = Math.min(window.innerHeight - 8, panelRect?.bottom ?? window.innerHeight - 8)
    const previewWidth = Math.min(228, Math.max(160, panelRight - panelLeft - 16))
    const previewHeight = 140
    const hasRoomBelow = tokenRect.bottom + previewHeight + 8 <= panelBottom
    const maxLeft = Math.max(panelLeft + 8, panelRight - previewWidth - 8)
    cancelPreviewClose()
    setHoveredPreview({
      context,
      left: Math.min(Math.max(panelLeft + 8, tokenRect.left), maxLeft),
      top: hasRoomBelow ? tokenRect.bottom + 6 : Math.max(panelTop + 8, tokenRect.top - previewHeight - 6),
      width: previewWidth,
    })
  }

  const handlePointerOut = (event: PointerEvent<HTMLDivElement>) => {
    const token = (event.target as HTMLElement).closest<HTMLElement>('[data-reference-token]')
    if (!token || token.contains(event.relatedTarget as Node | null)) return
    if (event.relatedTarget instanceof Node && previewRef.current?.contains(event.relatedTarget)) return
    schedulePreviewClose()
  }

  return (
    <div className="prompt-composer-shell">
      <div
        ref={editorRef}
        className="prompt-composer"
        contentEditable={!disabled}
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        aria-label="排版指令"
        data-placeholder={PLACEHOLDER}
        onInput={emitChange}
        onClick={handleClick}
        onDragStart={handleDragStart}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
      />
      {hoveredPreview && (
        createPortal(
          <div
            ref={previewRef}
            className="prompt-reference-render-popover"
            style={{ left: hoveredPreview.left, top: hoveredPreview.top, width: hoveredPreview.width }}
            onPointerEnter={cancelPreviewClose}
            onPointerLeave={schedulePreviewClose}
          >
            <ElementRenderPreview html={hoveredPreview.context.html} />
          </div>,
          document.body,
        )
      )}
    </div>
  )
})

export default PromptComposer
