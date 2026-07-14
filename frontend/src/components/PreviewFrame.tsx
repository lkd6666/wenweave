import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { SelectedElementContext } from '../types'
import { sanitizeSelectedElement } from '../utils/selectedElements'

export type PreviewMode = 'browse' | 'select' | 'edit'

export interface PreviewFrameHandle {
  flushPendingChange: () => void
  openImagePickerForInsert: () => void
}

interface PreviewFrameProps {
  html: string
  revision: number
  mode: PreviewMode
  brightness: number
  selectedElements: SelectedElementContext[]
  onHtmlChange: (html: string) => void
  onUploadImage: (file: File) => Promise<string>
  onToggleSelection: (element: SelectedElementContext, selected: boolean) => void
  onClearSelections: () => void
}

const EMPTY_PREVIEW_HTML = '<p style="color:#999;text-align:center;margin-top:40px;">暂无内容，可通过对话让 AI 生成排版</p>'
const MAX_IMAGE_HISTORY_ENTRIES = 20
const ACCEPTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif', 'image/bmp'])

function extensionForImageType(contentType: string): string {
  const extensionByType: Record<string, string> = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/avif': 'avif',
    'image/bmp': 'bmp',
  }
  return extensionByType[contentType] ?? 'png'
}

/**
 * 公众号文章画布：选择模式只建立多个源码引用，直接编辑模式才允许修改 iframe 内容。
 * 选中 class 仅用于预览，序列化和发给 AI 的 HTML 都会自动剥离该 class。
 */
const PreviewFrame = forwardRef<PreviewFrameHandle, PreviewFrameProps>(function PreviewFrame({
  html,
  revision,
  mode,
  brightness,
  selectedElements,
  onHtmlChange,
  onUploadImage,
  onToggleSelection,
  onClearSelections,
}, ref) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const shellRef = useRef<HTMLDivElement>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const selectedNodesRef = useRef<HTMLElement[]>([])
  const imageInputRef = useRef<HTMLInputElement>(null)
  const imageActionRef = useRef<HTMLButtonElement | null>(null)
  const activeImageRef = useRef<HTMLImageElement | null>(null)
  const imageInputModeRef = useRef<'replace' | 'insert'>('replace')
  const pendingInsertRangeRef = useRef<Range | null>(null)
  const uploadingImageRef = useRef(false)
  const imageUndoStackRef = useRef<string[]>([])
  const imageRedoStackRef = useRef<string[]>([])
  const srcDocRef = useRef<string | null>(null)
  const renderedHtmlRef = useRef(html)
  const htmlRef = useRef(html)
  const previewReadyRef = useRef(false)
  const modeRef = useRef(mode)
  const onHtmlChangeRef = useRef(onHtmlChange)
  const onUploadImageRef = useRef(onUploadImage)
  const onToggleSelectionRef = useRef(onToggleSelection)
  const onClearSelectionsRef = useRef(onClearSelections)
  const inputTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [contentHeight, setContentHeight] = useState(240)

  modeRef.current = mode
  htmlRef.current = html
  onHtmlChangeRef.current = onHtmlChange
  onUploadImageRef.current = onUploadImage
  onToggleSelectionRef.current = onToggleSelection
  onClearSelectionsRef.current = onClearSelections

  useEffect(
    () => () => {
      resizeObserverRef.current?.disconnect()
      if (inputTimerRef.current) clearTimeout(inputTimerRef.current)
      imageActionRef.current?.remove()
    },
    [],
  )

  const clearDomSelection = () => {
    selectedNodesRef.current.forEach((element) => element.classList.remove('ai-element-selected'))
    selectedNodesRef.current = []
  }

  const updateEditingState = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const editable = modeRef.current === 'edit'
    // 显式写 attribute，且在选择模式继续拦截输入事件，防止浏览器保留上一轮 contenteditable 状态。
    body.contentEditable = editable ? 'true' : 'false'
    body.setAttribute('contenteditable', editable ? 'true' : 'false')
    body.classList.toggle('ai-preview-editing', editable)
    body.classList.toggle('ai-preview-selecting', modeRef.current === 'select')
  }

  useEffect(() => {
    updateEditingState()
    if (mode !== 'edit') removeImageAction()
    if (mode !== 'select') {
      clearDomSelection()
      if (selectedElements.length) onClearSelectionsRef.current()
    }
  }, [mode, revision, selectedElements.length])

  useEffect(() => {
    if (selectedElements.length) return
    clearDomSelection()
  }, [selectedElements])

  const srcDoc = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
  <style>
    html, body {
      width: 100%;
      box-sizing: border-box;
      overflow: hidden;
    }
    body {
      margin: 0;
      padding: 16px 12px 32px;
      background: #fff;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
      font-size: 15px;
      line-height: 2;
      color: #000;
      word-wrap: break-word;
    }
    img { max-width: 100%; height: auto; }
    table { max-width: 100%; }
    .ai-preview-selecting * { cursor: pointer !important; }
    .ai-preview-selecting *:hover { outline: 1px dashed #91caff; outline-offset: 2px; }
    .ai-preview-editing { cursor: text; caret-color: #1677ff; }
    .ai-preview-editing img { cursor: pointer; }
    .ai-preview-editing img:hover { outline: 2px solid #91caff; outline-offset: 2px; }
    .ai-element-selected { outline: 2px solid #1677ff !important; outline-offset: 2px; }
    .ai-preview-image-action {
      position: fixed;
      z-index: 2147483647;
      min-width: 100px;
      height: 30px;
      padding: 0 10px;
      border: 0;
      border-radius: 4px;
      background: #1677ff;
      box-shadow: 0 2px 8px rgba(22, 119, 255, 0.3);
      color: #fff;
      font: 600 13px/30px -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
      cursor: pointer;
    }
    .ai-preview-image-action:hover { background: #4096ff; }
    .ai-preview-image-action:disabled { cursor: wait; opacity: 0.75; }
  </style>
</head>
<body>${html || EMPTY_PREVIEW_HTML}</body>
</html>`
  if (srcDocRef.current === null) srcDocRef.current = srcDoc

  const syncHeight = () => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    const body = document.body
    const view = document.defaultView
    const bodyTop = body.getBoundingClientRect().top
    const bodyPaddingBottom = Number.parseFloat(view?.getComputedStyle(body).paddingBottom ?? '0') || 0
    let contentBottom = 0

    // scrollHeight is never smaller than an iframe's viewport. After a full
    // rewrite replaces a long article with a short one, using it would retain
    // the old iframe height and leave a large blank area at the bottom.
    for (const element of body.querySelectorAll<HTMLElement>('*')) {
      if (element.dataset.previewImageAction || view?.getComputedStyle(element).position === 'fixed') continue
      const bounds = element.getBoundingClientRect()
      if (bounds.width || bounds.height) contentBottom = Math.max(contentBottom, bounds.bottom - bodyTop)
    }
    const height = Math.max(160, contentBottom + bodyPaddingBottom)
    // Keep the iframe a few pixels taller than its measured document so the
    // browser never creates a second scrollbar because of rounding.
    setContentHeight(Math.ceil(height) + 2)
  }

  const replacePreviewBody = (nextHtml: string) => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return false
    const previousScrollTop = shellRef.current?.scrollTop ?? 0
    clearDomSelection()
    removeImageAction()
    body.innerHTML = nextHtml || EMPTY_PREVIEW_HTML
    renderedHtmlRef.current = nextHtml
    syncHeight()
    window.requestAnimationFrame(() => {
      const shell = shellRef.current
      if (shell) shell.scrollTop = previousScrollTop
    })
    return true
  }

  useLayoutEffect(() => {
    if (!previewReadyRef.current || renderedHtmlRef.current === html) return
    imageUndoStackRef.current = []
    imageRedoStackRef.current = []
    replacePreviewBody(html)
  }, [html])

  const cleanClone = (element: HTMLElement) => {
    const clone = element.cloneNode(true) as HTMLElement
    clone.classList.remove('ai-element-selected')
    clone.querySelectorAll('.ai-element-selected').forEach((node) => node.classList.remove('ai-element-selected'))
    return clone
  }

  const serialiseBody = (body: HTMLElement) => {
    const clone = body.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.ai-element-selected').forEach((node) => node.classList.remove('ai-element-selected'))
    clone.querySelectorAll('[data-preview-image-action]').forEach((node) => node.remove())
    return clone.innerHTML
  }

  const recordImageChange = (previousHtml: string) => {
    imageUndoStackRef.current.push(previousHtml)
    if (imageUndoStackRef.current.length > MAX_IMAGE_HISTORY_ENTRIES) imageUndoStackRef.current.shift()
    imageRedoStackRef.current = []
  }

  const restoreImageHistory = (direction: 'undo' | 'redo') => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return false
    const sourceStack = direction === 'undo' ? imageUndoStackRef.current : imageRedoStackRef.current
    const targetHtml = sourceStack.pop()
    if (targetHtml === undefined) return false
    const currentHtml = serialiseBody(body)
    const destinationStack = direction === 'undo' ? imageRedoStackRef.current : imageUndoStackRef.current
    destinationStack.push(currentHtml)
    replacePreviewBody(targetHtml)
    onHtmlChangeRef.current(targetHtml)
    return true
  }

  const makeSelector = (element: HTMLElement, body: HTMLElement) => {
    const segments: string[] = []
    let current: HTMLElement | null = element
    while (current && current !== body) {
      const tag = current.tagName.toLowerCase()
      const siblings = Array.from(current.parentElement?.children ?? []).filter((node) => node.tagName === current?.tagName)
      segments.unshift(`${tag}:nth-of-type(${Math.max(1, siblings.indexOf(current) + 1)})`)
      current = current.parentElement
    }
    return segments.join(' > ')
  }

  const selectionTarget = (element: HTMLElement, body: HTMLElement): HTMLElement | null => {
    const svg = element.closest('svg')
    if (!svg || !body.contains(svg)) return element

    // SVG 的 rect/path/g 往往只是绘制层，编辑意图通常属于外层卡片或段落。
    const container = svg.closest('section, article, figure, li, blockquote')
    if (container && container !== body) return container as HTMLElement
    const parent = svg.parentElement
    return parent && parent !== body ? parent : null
  }

  const selectionContext = (element: HTMLElement, body: HTMLElement): SelectedElementContext => {
    const clone = cleanClone(element)
    return sanitizeSelectedElement({
      selector: makeSelector(element, body),
      tag_name: element.tagName.toLowerCase(),
      html: clone.outerHTML,
      text: (clone.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 2000),
    })
  }

  const toggleSelection = (element: HTMLElement, body: HTMLElement) => {
    const context = selectionContext(element, body)
    const index = selectedNodesRef.current.indexOf(element)
    if (index >= 0) {
      element.classList.remove('ai-element-selected')
      selectedNodesRef.current.splice(index, 1)
      onToggleSelectionRef.current(context, false)
    } else {
      if (selectedElements.length >= 12) return
      element.classList.add('ai-element-selected')
      selectedNodesRef.current.push(element)
      onToggleSelectionRef.current(context, true)
    }
  }

  const emitCurrentHtmlChange = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const nextHtml = serialiseBody(body)
    // 父组件以草稿作为输入时，标记 iframe 已渲染到同一版本，避免输入后被回写重置。
    renderedHtmlRef.current = nextHtml
    onHtmlChangeRef.current(nextHtml)
  }

  const emitHtmlChange = () => {
    if (modeRef.current !== 'edit') return
    if (inputTimerRef.current) clearTimeout(inputTimerRef.current)
    inputTimerRef.current = setTimeout(() => {
      inputTimerRef.current = null
      emitCurrentHtmlChange()
    }, 180)
  }

  const removeImageAction = () => {
    imageActionRef.current?.remove()
    imageActionRef.current = null
    activeImageRef.current = null
  }

  const openImageAction = (image: HTMLImageElement) => {
    const document = image.ownerDocument
    if (!document.body) return
    removeImageAction()
    const imageBounds = image.getBoundingClientRect()
    const buttonWidth = 100
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'ai-preview-image-action'
    button.dataset.previewImageAction = 'true'
    button.setAttribute('contenteditable', 'false')
    button.textContent = '替换图片'
    Object.assign(button.style, {
      position: 'fixed',
      zIndex: '2147483647',
      minWidth: '100px',
      height: '30px',
      padding: '0 10px',
      border: '0',
      borderRadius: '4px',
      background: '#1677ff',
      boxShadow: '0 2px 8px rgba(22, 119, 255, 0.3)',
      color: '#fff',
      font: "600 13px/30px -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      cursor: 'pointer',
    })
    button.style.left = `${Math.max(8, Math.min(document.documentElement.clientWidth - buttonWidth - 8, imageBounds.right - buttonWidth - 6))}px`
    button.style.top = `${Math.max(8, imageBounds.top + 8)}px`
    button.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      imageInputModeRef.current = 'replace'
      imageInputRef.current?.click()
    })
    document.body.append(button)
    activeImageRef.current = image
    imageActionRef.current = button
  }

  const captureCaretRange = (): Range | null => {
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const selection = document?.defaultView?.getSelection()
    if (!body || !selection?.rangeCount) return null
    const range = selection.getRangeAt(0)
    return body.contains(range.commonAncestorContainer) ? range.cloneRange() : null
  }

  const insertUploadedImage = async (file: File, range: Range | null) => {
    if (uploadingImageRef.current || modeRef.current !== 'edit') return
    uploadingImageRef.current = true
    try {
      const contentType = file.type.toLowerCase()
      const needsFilename = !file.name || !/\.(?:avif|bmp|gif|jpe?g|png|webp)$/i.test(file.name)
      const uploadFile = ACCEPTED_IMAGE_TYPES.has(contentType) && needsFilename
        ? new File([file], `pasted-image.${extensionForImageType(contentType)}`, { type: contentType })
        : file
      const url = await onUploadImageRef.current(uploadFile)
      const document = iframeRef.current?.contentDocument
      const body = document?.body
      if (!body || modeRef.current !== 'edit') return

      const previousHtml = serialiseBody(body)
      const image = document.createElement('img')
      image.src = url
      image.alt = ''
      image.addEventListener('load', syncHeight, { once: true })
      if (range && body.contains(range.commonAncestorContainer)) {
        range.deleteContents()
        range.insertNode(image)
        const selection = document.defaultView?.getSelection()
        const afterImage = document.createRange()
        afterImage.setStartAfter(image)
        afterImage.collapse(true)
        selection?.removeAllRanges()
        selection?.addRange(afterImage)
      } else {
        const paragraph = document.createElement('p')
        paragraph.append(image)
        body.append(paragraph)
      }
      recordImageChange(previousHtml)
      const nextHtml = serialiseBody(body)
      renderedHtmlRef.current = nextHtml
      onHtmlChangeRef.current(nextHtml)
      syncHeight()
    } finally {
      uploadingImageRef.current = false
    }
  }

  const openImagePickerForInsert = () => {
    if (modeRef.current !== 'edit' || uploadingImageRef.current) return
    removeImageAction()
    imageInputModeRef.current = 'insert'
    pendingInsertRangeRef.current = captureCaretRange()
    imageInputRef.current?.click()
  }

  const handleImageFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0]
    const inputMode = imageInputModeRef.current
    const insertRange = pendingInsertRangeRef.current
    const target = activeImageRef.current
    imageInputModeRef.current = 'replace'
    pendingInsertRangeRef.current = null
    event.currentTarget.value = ''
    event.currentTarget.blur()
    if (!file || uploadingImageRef.current || modeRef.current !== 'edit') return
    if (inputMode === 'insert') {
      await insertUploadedImage(file, insertRange)
      return
    }
    if (!target) return
    uploadingImageRef.current = true
    const action = imageActionRef.current
    if (action) {
      action.disabled = true
      action.textContent = '上传中...'
    }
    try {
      const url = await onUploadImageRef.current(file)
      if (!target.isConnected || !target.ownerDocument.body) return
      const previousHtml = serialiseBody(target.ownerDocument.body)
      target.src = url
      target.removeAttribute('srcset')
      target.removeAttribute('sizes')
      target.addEventListener('load', syncHeight, { once: true })
      recordImageChange(previousHtml)
      const nextHtml = serialiseBody(target.ownerDocument.body)
      renderedHtmlRef.current = nextHtml
      onHtmlChangeRef.current(nextHtml)
      syncHeight()
      removeImageAction()
      target.ownerDocument.defaultView?.focus()
    } catch {
      // 上传方法会在编辑页展示具体错误，这里只恢复预览内操作按钮。
    } finally {
      uploadingImageRef.current = false
      if (action?.isConnected) {
        action.disabled = false
        action.textContent = '替换图片'
      }
    }
  }

  useImperativeHandle(ref, () => ({
    flushPendingChange: () => {
      if (!inputTimerRef.current) return
      clearTimeout(inputTimerRef.current)
      inputTimerRef.current = null
      emitCurrentHtmlChange()
    },
    openImagePickerForInsert,
  }))

  const handleLoad = () => {
    resizeObserverRef.current?.disconnect()
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    if (!body) return
    previewReadyRef.current = true
    if (renderedHtmlRef.current !== htmlRef.current) {
      replacePreviewBody(htmlRef.current)
    }
    updateEditingState()
    const handleClick = (event: Event) => {
      // iframe 的节点属于另一个 window，不能使用父页面 HTMLElement 的 instanceof 判断。
      const target = event.target && (event.target as Node).nodeType === 1 ? (event.target as HTMLElement) : null
      if (!target || target === body || target.tagName === 'STYLE' || target.tagName === 'SCRIPT') return
      if (target.closest('[data-preview-image-action]')) return
      const image = target.closest('img')
      if (image && modeRef.current === 'edit') {
        event.preventDefault()
        event.stopPropagation()
        openImageAction(image as HTMLImageElement)
        return
      }
      if (modeRef.current !== 'select') {
        removeImageAction()
        return
      }
      event.preventDefault()
      event.stopPropagation()
      const selectedTarget = selectionTarget(target, body)
      if (selectedTarget) toggleSelection(selectedTarget, body)
    }
    const preventSelectionModeEdit = (event: Event) => {
      if (modeRef.current === 'select') event.preventDefault()
    }
    const handlePaste = (event: ClipboardEvent) => {
      if (modeRef.current === 'select') {
        event.preventDefault()
        return
      }
      if (modeRef.current !== 'edit') return

      const imageItem = Array.from(event.clipboardData?.items ?? []).find((item) => (
        item.kind === 'file' && ACCEPTED_IMAGE_TYPES.has(item.type.toLowerCase())
      ))
      const imageFile = imageItem?.getAsFile()
      if (imageFile) {
        event.preventDefault()
        event.stopPropagation()
        void insertUploadedImage(imageFile, captureCaretRange())
        return
      }

      // Do not let rich clipboard HTML silently add a data: or remote image to
      // the draft. Image clipboard items use the OSS upload path above.
      if (/<img\b|data:image\//i.test(event.clipboardData?.getData('text/html') ?? '')) {
        event.preventDefault()
      }
    }
    const handleHistoryShortcut = (event: KeyboardEvent) => {
      if (modeRef.current !== 'edit' || (!event.ctrlKey && !event.metaKey) || event.altKey) return
      const key = event.key.toLowerCase()
      const direction = key === 'y' || (key === 'z' && event.shiftKey)
        ? 'redo'
        : key === 'z'
          ? 'undo'
          : null
      if (!direction || !restoreImageHistory(direction)) return
      event.preventDefault()
      event.stopPropagation()
    }
    const handleInput = () => {
      if (modeRef.current === 'edit') emitHtmlChange()
    }
    body.addEventListener('click', handleClick, true)
    body.addEventListener('beforeinput', preventSelectionModeEdit, true)
    body.addEventListener('paste', handlePaste, true)
    body.addEventListener('drop', preventSelectionModeEdit, true)
    body.addEventListener('keydown', handleHistoryShortcut, true)
    body.addEventListener('keydown', preventSelectionModeEdit, true)
    body.addEventListener('input', handleInput)
    syncHeight()
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(syncHeight)
      observer.observe(body)
      observer.observe(document.documentElement)
      resizeObserverRef.current = observer
    }
  }

  return (
    <div className={`preview-shell preview-mode-${mode}`} ref={shellRef}>
      <div className="preview-device">
        {mode === 'select' && selectedElements.length > 0 && <div className="preview-selection-count">已选 {selectedElements.length}</div>}
        <iframe
          ref={iframeRef}
          title="排版预览"
          className="preview-iframe"
          sandbox="allow-same-origin"
          scrolling="no"
          srcDoc={srcDocRef.current}
          style={{ height: contentHeight, filter: `brightness(${brightness / 100})` }}
          onLoad={handleLoad}
        />
      </div>
      <input
        ref={imageInputRef}
        className="preview-image-input"
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,image/avif,image/bmp"
        onChange={(event) => { void handleImageFileChange(event) }}
      />
    </div>
  )
})

export default PreviewFrame
