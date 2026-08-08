import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, PointerEvent as ReactPointerEvent } from 'react'
import { Button, ColorPicker, Drawer, InputNumber, Popover, Segmented, Select, Tooltip, message } from 'antd'
import BarsOutlined from '@ant-design/icons/BarsOutlined'
import {
  AlignCenterOutlined,
  AlignLeftOutlined,
  AlignRightOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  BgColorsOutlined,
  BoldOutlined,
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  DragOutlined,
  ItalicOutlined,
  MoreOutlined,
  PictureOutlined,
  PlusOutlined,
  RedoOutlined,
  RobotOutlined,
  StarOutlined,
  UndoOutlined,
  UnderlineOutlined,
} from '@ant-design/icons'
import type { SelectedElementContext } from '../types'
import {
  BLOCK_EDITING_TRANSIENT_CLASS,
  BLOCK_HOVER_TRANSIENT_CLASS,
  BLOCK_HANDLE_ATTRIBUTE,
  TEXT_BLOCK_SELECTOR,
  areConsecutiveSiblingBlocks,
  findEditableBlock,
  isInsideTableCell,
  nextBlockSelection,
  sortBlocksInDocumentOrder,
  stripBlockEditingMarkup,
} from '../utils/blockEditing'
import { sanitizeSelectedElement } from '../utils/selectedElements'
import { frameDocumentWithNewWindowLinks, markLinksToOpenInNewWindow, SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import { documentsApi } from '../api/documents'
import ImageCropModal from './ImageCropModal'
import type { CropRect } from '../utils/imageCrop'
import { ImageCropError, cropImageBlob, isFullCropRect, parseCropRect, serializeCropRect } from '../utils/imageCrop'

export type PreviewMode = 'browse' | 'select' | 'edit'
type MobileEditTarget = 'text' | 'block'
type MobileEditorPanel = 'text-style' | 'block-style' | 'block-actions' | 'image-actions' | null

export interface PreviewFrameHandle {
  flushPendingChange: () => void
  copyArticle: () => Promise<'copied' | 'empty' | 'failed'>
  openImagePickerForInsert: () => void
  insertTemplateHtml: (html: string, placement: 'append' | 'caret') => boolean
  undo: () => boolean
  redo: () => boolean
}

interface PreviewFrameProps {
  html: string
  revision: number
  active: boolean
  mode: PreviewMode
  brightness: number
  compact: boolean
  selectedElements: SelectedElementContext[]
  onHtmlChange: (html: string) => void
  onUploadImage: (file: File) => Promise<string>
  onToggleSelection: (element: SelectedElementContext, selected: boolean) => void
  onAttachSelectedBlocks: (elements: SelectedElementContext[]) => void
  onCollectTemplateHtml: (html: string) => void
  onHistoryStateChange: (state: { canUndo: boolean; canRedo: boolean }) => void
  onCaretAvailabilityChange: (available: boolean) => void
}

const EMPTY_PREVIEW_HTML = '<p style="color:#999;text-align:center;margin-top:40px;">暂无内容，可通过对话让 AI 生成排版</p>'
const MAX_EDIT_HISTORY_ENTRIES = 100
const ACCEPTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif', 'image/bmp'])
const BLOCK_SELECTOR = TEXT_BLOCK_SELECTOR
const SYSTEM_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
const MIXED_VALUE = '__mixed__'
const TEXT_TOOLBAR_GAP = 10
const FONT_OPTIONS = [
  { value: SYSTEM_FONT_FAMILY, label: '系统默认' },
  { value: 'Microsoft YaHei', label: '微软雅黑' },
  { value: 'SimSun', label: '宋体' },
  { value: 'KaiTi', label: '楷体' },
  { value: 'Arial', label: 'Arial' },
]
const LINE_HEIGHT_OPTIONS = ['1', '1.2', '1.4', '1.5', '1.6', '1.8', '2', '2.4']

function isCrossOriginHttpSource(source: string): boolean {
  try {
    const parsed = new URL(source, window.location.href)
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.origin !== window.location.origin
  } catch {
    return false
  }
}

async function readCropSource(source: string): Promise<Blob> {
  // A displayed cross-origin image can be perfectly valid while its bytes are
  // unreadable to fetch/canvas. Prefer the authenticated same-origin proxy,
  // then retain a direct fallback for sources whose server already allows CORS
  // but cannot be reached by the application server.
  let proxyError: unknown
  const crossOrigin = isCrossOriginHttpSource(source)
  if (crossOrigin) {
    try {
      return await documentsApi.fetchCropSource(source)
    } catch (error) {
      proxyError = error
      // Fall through to the browser request below.
    }
  }

  try {
    const response = await fetch(source, {
      mode: 'cors',
      credentials: crossOrigin ? 'omit' : 'same-origin',
    })
    if (!response.ok) throw new ImageCropError('无法读取原图')
    return response.blob()
  } catch (error) {
    if (proxyError instanceof Error) throw new ImageCropError(proxyError.message)
    if (error instanceof ImageCropError) throw error
    throw new ImageCropError('无法读取原图')
  }
}

interface BlockStyleValues {
  alignment: string
  background: string | null
  borderRadius: number | null
  borderWidth: number | null
  color: string | null
  fontFamily: string
  fontSize: number | null
  lineHeight: string
  margin: number | null
  padding: number | null
  textIndent: number | null
}

interface ImageCropSession {
  source: string
  initialRect: CropRect | null
  hasExistingCrop: boolean
}

const EMPTY_BLOCK_STYLE: BlockStyleValues = {
  alignment: 'left',
  background: null,
  borderRadius: null,
  borderWidth: null,
  color: null,
  fontFamily: SYSTEM_FONT_FAMILY,
  fontSize: null,
  lineHeight: '2',
  margin: null,
  padding: null,
  textIndent: null,
}

function normaliseFontFamily(value: string): string {
  return value.replace(/["']/g, '').replace(/\s+/g, ' ').trim().toLowerCase()
}

function toolbarFontValue(value: string): string {
  const match = FONT_OPTIONS.find((option) => normaliseFontFamily(option.value) === normaliseFontFamily(value))
  return match?.value ?? value
}

function toolbarFontLabel(value: string): string {
  return value.split(',')[0].replace(/["']/g, '').trim() || '系统默认'
}

function toolbarLineHeight(style: CSSStyleDeclaration | null): string {
  if (!style) return '2'
  const lineHeight = Number.parseFloat(style.lineHeight)
  const fontSize = Number.parseFloat(style.fontSize)
  if (!Number.isFinite(lineHeight) || !Number.isFinite(fontSize) || fontSize <= 0) return 'normal'
  return Number((lineHeight / fontSize).toFixed(2)).toString()
}

function toolbarTextIndent(style: CSSStyleDeclaration): number {
  const indent = Number.parseFloat(style.textIndent)
  const fontSize = Number.parseFloat(style.fontSize)
  if (!Number.isFinite(indent) || !Number.isFinite(fontSize) || fontSize <= 0) return 0
  return Number((indent / fontSize).toFixed(1))
}

function commonValue<T>(values: T[]): T | null {
  if (values.length === 0) return null
  return values.every((value) => value === values[0]) ? values[0] : null
}

function toolbarAlignment(value: string): string {
  if (value === 'start') return 'left'
  if (value === 'end') return 'right'
  return value || 'left'
}

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
  active,
  mode,
  brightness,
  compact,
  selectedElements,
  onHtmlChange,
  onUploadImage,
  onToggleSelection,
  onAttachSelectedBlocks,
  onCollectTemplateHtml,
  onHistoryStateChange,
  onCaretAvailabilityChange,
}, ref) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const shellRef = useRef<HTMLDivElement>(null)
  const textToolbarRef = useRef<HTMLDivElement>(null)
  const blockToolbarRef = useRef<HTMLDivElement>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const selectedNodesRef = useRef<HTMLElement[]>([])
  const selectedBlocksRef = useRef<HTMLElement[]>([])
  const activeBlockRef = useRef<HTMLElement | null>(null)
  const hoveredBlockRef = useRef<HTMLElement | null>(null)
  const blockHandleRef = useRef<HTMLButtonElement | null>(null)
  const blockDropIndicatorRef = useRef<HTMLDivElement | null>(null)
  const blockHandleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blockDragCleanupRef = useRef<(() => void) | null>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const imageActionRef = useRef<HTMLDivElement | null>(null)
  const activeImageRef = useRef<HTMLImageElement | null>(null)
  const cropTargetRef = useRef<HTMLImageElement | null>(null)
  const imageInputModeRef = useRef<'replace' | 'insert'>('replace')
  const pendingInsertRangeRef = useRef<Range | null>(null)
  const pendingBlockImageInsertionRef = useRef<HTMLElement | null>(null)
  const uploadingImageRef = useRef(false)
  const editUndoStackRef = useRef<string[]>([])
  const editRedoStackRef = useRef<string[]>([])
  const pendingInputHistoryRef = useRef<string | null>(null)
  const textSelectionRangeRef = useRef<Range | null>(null)
  const pendingTextFormatRangeRef = useRef<Range | null>(null)
  const textToolbarTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const textToolbarBasePositionRef = useRef({ top: 0, left: 0 })
  const textToolbarOffsetRef = useRef({ top: 0, left: 0 })
  const textToolbarAnchorRef = useRef<{ top: number; bottom: number; left: number } | null>(null)
  const selectionNodeIdsRef = useRef(new WeakMap<Node, number>())
  const nextSelectionNodeIdRef = useRef(1)
  const selectionSignatureRef = useRef('')
  const srcDocRef = useRef<string | null>(null)
  const renderedHtmlRef = useRef(html)
  const htmlRef = useRef(html)
  const previewReadyRef = useRef(false)
  const modeRef = useRef(mode)
  const compactRef = useRef(compact)
  const mobileEditTargetRef = useRef<MobileEditTarget>('text')
  const mobileBlockMultiSelectRef = useRef(false)
  const mobileEditorPanelRef = useRef<MobileEditorPanel>(null)
  const onHtmlChangeRef = useRef(onHtmlChange)
  const onUploadImageRef = useRef(onUploadImage)
  const onToggleSelectionRef = useRef(onToggleSelection)
  const onAttachSelectedBlocksRef = useRef(onAttachSelectedBlocks)
  const onCollectTemplateHtmlRef = useRef(onCollectTemplateHtml)
  const onHistoryStateChangeRef = useRef(onHistoryStateChange)
  const onCaretAvailabilityChangeRef = useRef(onCaretAvailabilityChange)
  const inputTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [contentHeight, setContentHeight] = useState(240)
  const [textToolbarPosition, setTextToolbarPosition] = useState<{ top: number; left: number } | null>(null)
  const [blockToolbarPosition, setBlockToolbarPosition] = useState<{ top: number; left: number } | null>(null)
  const [blockSelectionCount, setBlockSelectionCount] = useState(0)
  const [blockStyle, setBlockStyle] = useState<BlockStyleValues>(EMPTY_BLOCK_STYLE)
  const [textToolbarColor, setTextToolbarColor] = useState<string | null>('#1f1f1f')
  const [textToolbarFontFamily, setTextToolbarFontFamily] = useState(SYSTEM_FONT_FAMILY)
  const [textToolbarFontSize, setTextToolbarFontSize] = useState<number | null>(null)
  const [textToolbarLetterSpacing, setTextToolbarLetterSpacing] = useState<number | null>(null)
  const [textToolbarLineHeight, setTextToolbarLineHeight] = useState('2')
  const [textToolbarTextIndent, setTextToolbarTextIndent] = useState<number | null>(null)
  const [textToolbarMarginLeft, setTextToolbarMarginLeft] = useState<number | null>(null)
  const [textToolbarMarginRight, setTextToolbarMarginRight] = useState<number | null>(null)
  const [textToolbarAlignment, setTextToolbarAlignment] = useState('left')
  const [textToolbarBold, setTextToolbarBold] = useState<boolean | null>(false)
  const [textToolbarItalic, setTextToolbarItalic] = useState<boolean | null>(false)
  const [textToolbarUnderline, setTextToolbarUnderline] = useState<boolean | null>(false)
  const [imageCropSession, setImageCropSession] = useState<ImageCropSession | null>(null)
  const [croppingImage, setCroppingImage] = useState(false)
  const [mobileEditTarget, setMobileEditTarget] = useState<MobileEditTarget>('text')
  const [mobileBlockMultiSelect, setMobileBlockMultiSelect] = useState(false)
  const [mobileEditorPanel, setMobileEditorPanel] = useState<MobileEditorPanel>(null)

  modeRef.current = mode
  compactRef.current = compact
  mobileEditTargetRef.current = mobileEditTarget
  mobileBlockMultiSelectRef.current = mobileBlockMultiSelect
  mobileEditorPanelRef.current = mobileEditorPanel
  htmlRef.current = html
  onHtmlChangeRef.current = onHtmlChange
  onUploadImageRef.current = onUploadImage
  onToggleSelectionRef.current = onToggleSelection
  onAttachSelectedBlocksRef.current = onAttachSelectedBlocks
  onCollectTemplateHtmlRef.current = onCollectTemplateHtml
  onHistoryStateChangeRef.current = onHistoryStateChange
  onCaretAvailabilityChangeRef.current = onCaretAvailabilityChange

  useEffect(
    () => () => {
      resizeObserverRef.current?.disconnect()
      if (inputTimerRef.current) clearTimeout(inputTimerRef.current)
      if (textToolbarTimerRef.current) clearTimeout(textToolbarTimerRef.current)
      if (blockHandleTimerRef.current) clearTimeout(blockHandleTimerRef.current)
      imageActionRef.current?.remove()
      blockHandleRef.current?.remove()
      blockDropIndicatorRef.current?.remove()
      blockDragCleanupRef.current?.()
    },
    [],
  )

  useLayoutEffect(() => {
    const shell = shellRef.current
    const toolbar = textToolbarRef.current
    const anchor = textToolbarAnchorRef.current
    if (!shell || !toolbar || !anchor || !textToolbarPosition) return
    if (textToolbarOffsetRef.current.top !== 0 || textToolbarOffsetRef.current.left !== 0) return
    const toolbarHeight = toolbar.offsetHeight
    if (!toolbarHeight) return
    const viewportTop = shell.scrollTop + 8
    const viewportBottom = shell.scrollTop + shell.clientHeight - 8
    const spaceAbove = anchor.top - viewportTop
    const spaceBelow = viewportBottom - anchor.bottom
    const top = spaceBelow >= toolbarHeight + TEXT_TOOLBAR_GAP || spaceBelow >= spaceAbove
      ? anchor.bottom + TEXT_TOOLBAR_GAP
      : anchor.top - toolbarHeight - TEXT_TOOLBAR_GAP
    if (Math.abs(textToolbarPosition.top - top) < 1 && Math.abs(textToolbarPosition.left - anchor.left) < 1) return
    const nextPosition = { top: Math.max(8, top), left: anchor.left }
    textToolbarBasePositionRef.current = nextPosition
    setTextToolbarPosition(nextPosition)
  }, [textToolbarPosition])

  useEffect(() => {
    if (blockSelectionCount === 0) return
    const shell = shellRef.current
    if (!shell) return
    const reposition = () => updateBlockToolbarPosition()
    shell.addEventListener('scroll', reposition, { passive: true })
    window.addEventListener('resize', reposition)
    return () => {
      shell.removeEventListener('scroll', reposition)
      window.removeEventListener('resize', reposition)
    }
  }, [blockSelectionCount])

  const clearDomSelection = () => {
    selectedNodesRef.current.forEach((element) => element.classList.remove('ai-element-selected'))
    selectedNodesRef.current = []
  }

  const updateEditingState = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const editable = modeRef.current === 'edit'
    const mobileBlockEditing = compactRef.current && editable && mobileEditTargetRef.current === 'block'
    // 显式写 attribute，且在选择模式继续拦截输入事件，防止浏览器保留上一轮 contenteditable 状态。
    body.contentEditable = editable ? 'true' : 'false'
    body.setAttribute('contenteditable', editable ? 'true' : 'false')
    body.classList.toggle('ai-preview-editing', editable)
    body.classList.toggle('ai-preview-selecting', modeRef.current === 'select')
    body.classList.toggle('ai-preview-mobile-block-editing', mobileBlockEditing)
  }

  useEffect(() => {
    updateEditingState()
    if (mode !== 'edit') {
      onCaretAvailabilityChangeRef.current(false)
      removeImageAction()
      removeBlockHandle()
      clearBlockSelection()
      textSelectionRangeRef.current = null
      pendingTextFormatRangeRef.current = null
      setTextToolbarPosition(null)
    }
    if (mode !== 'select') {
      clearDomSelection()
    }
    if (!compact || mode !== 'edit') {
      setMobileEditTarget('text')
      setMobileBlockMultiSelect(false)
      setMobileEditorPanel(null)
    }
  }, [compact, mode, revision])

  useEffect(() => {
    if (selectedElements.length) return
    clearDomSelection()
  }, [selectedElements])

  if (srcDocRef.current === null) {
    srcDocRef.current = frameDocumentWithNewWindowLinks(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
  <meta name="referrer" content="no-referrer" />
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
    /* Content images keep their own layout rules so replacement only changes src. */
    table { max-width: 100%; }
    .ai-preview-selecting * { cursor: pointer !important; }
    .ai-preview-selecting *:hover { outline: 1px dashed #91caff; outline-offset: 2px; }
    .ai-preview-editing { cursor: text; caret-color: #1677ff; }
    .ai-preview-editing:not(.ai-preview-mobile-block-editing),
    .ai-preview-editing:not(.ai-preview-mobile-block-editing) * {
      /* Imported article markup can disable user selection. Text
         mode must always leave the native long-press and drag selection free. */
      -webkit-touch-callout: default !important;
      -webkit-user-select: text !important;
      user-select: text !important;
    }
    .ai-preview-editing img { cursor: pointer; }
    .ai-preview-editing img:hover { outline: 2px solid #91caff; outline-offset: 2px; }
    .ai-preview-editing img.ai-preview-image-selected { outline: 2px solid #1677ff; outline-offset: 2px; }
    .ai-preview-mobile-block-editing,
    .ai-preview-mobile-block-editing * {
      cursor: pointer !important;
      -webkit-user-select: none !important;
      user-select: none !important;
    }
    .ai-element-selected { outline: 2px solid #1677ff !important; outline-offset: 2px; }
    .ai-preview-editing .ai-block-hovered { outline: 1px solid #91caff; outline-offset: 2px; }
    .ai-preview-editing .ai-block-selected { outline: 2px solid #1677ff !important; outline-offset: 3px; }
    .ai-preview-block-handle {
      position: fixed;
      z-index: 2147483646;
      display: grid;
      width: 20px;
      height: 28px;
      padding: 0;
      place-items: center;
      border: 1px solid #91caff;
      border-radius: 3px;
      background: #fff;
      box-shadow: 0 2px 6px rgba(22, 119, 255, 0.2);
      color: #1677ff;
      font: 700 13px/1 monospace;
      cursor: grab;
    }
    .ai-preview-block-handle:active { cursor: grabbing; }
    .ai-preview-block-drop-indicator {
      position: fixed;
      z-index: 2147483647;
      height: 2px;
      border-radius: 2px;
      background: #1677ff;
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8);
      pointer-events: none;
    }
    .ai-preview-image-actions {
      position: fixed;
      z-index: 2147483647;
      height: 30px;
      display: flex;
      overflow: hidden;
      border-radius: 4px;
      box-shadow: 0 2px 8px rgba(22, 119, 255, 0.3);
    }
    .ai-preview-image-action {
      min-width: 76px;
      height: 30px;
      padding: 0 10px;
      border: 0;
      background: #1677ff;
      color: #fff;
      font: 600 13px/30px -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
      cursor: pointer;
    }
    .ai-preview-image-action:hover { background: #4096ff; }
    .ai-preview-image-action:disabled { cursor: wait; opacity: 0.75; }
  </style>
</head>
<body>${html || EMPTY_PREVIEW_HTML}</body>
</html>`)
  }

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

  const resetMobileEditingUi = () => {
    mobileEditTargetRef.current = 'text'
    mobileBlockMultiSelectRef.current = false
    mobileEditorPanelRef.current = null
    setMobileEditTarget('text')
    setMobileBlockMultiSelect(false)
    setMobileEditorPanel(null)
  }

  const replacePreviewBody = (nextHtml: string) => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return false
    const previousScrollTop = shellRef.current?.scrollTop ?? 0
    clearDomSelection()
    clearBlockSelection()
    removeImageAction()
    cropTargetRef.current = null
    setImageCropSession(null)
    removeBlockHandle()
    textSelectionRangeRef.current = null
    pendingTextFormatRangeRef.current = null
    setTextToolbarPosition(null)
    resetMobileEditingUi()
    body.innerHTML = nextHtml || EMPTY_PREVIEW_HTML
    markLinksToOpenInNewWindow(body)
    renderedHtmlRef.current = nextHtml
    syncHeight()
    window.requestAnimationFrame(() => {
      const shell = shellRef.current
      if (shell) shell.scrollTop = previousScrollTop
    })
    return true
  }

  const ensureRenderedHtml = () => {
    if (!previewReadyRef.current || renderedHtmlRef.current === htmlRef.current) return
    replacePreviewBody(htmlRef.current)
  }

  useLayoutEffect(() => {
    if (!active || !previewReadyRef.current || renderedHtmlRef.current === html) return
    editUndoStackRef.current = []
    editRedoStackRef.current = []
    pendingInputHistoryRef.current = null
    onHistoryStateChangeRef.current({ canUndo: false, canRedo: false })
    replacePreviewBody(html)
  }, [active, html])

  const cleanClone = (element: HTMLElement) => {
    const clone = element.cloneNode(true) as HTMLElement
    clone.classList.remove('ai-element-selected')
    clone.querySelectorAll('.ai-element-selected').forEach((node) => node.classList.remove('ai-element-selected'))
    clone.classList.remove('ai-preview-image-selected')
    clone.querySelectorAll('.ai-preview-image-selected').forEach((node) => node.classList.remove('ai-preview-image-selected'))
    stripBlockEditingMarkup(clone)
    return clone
  }

  const serialiseBody = (body: HTMLElement) => {
    const clone = body.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.ai-element-selected').forEach((node) => node.classList.remove('ai-element-selected'))
    clone.querySelectorAll('.ai-preview-image-selected').forEach((node) => node.classList.remove('ai-preview-image-selected'))
    clone.querySelectorAll('[data-preview-image-action]').forEach((node) => node.remove())
    stripBlockEditingMarkup(clone)
    return clone.innerHTML
  }

  const copyArticle = async (): Promise<'copied' | 'empty' | 'failed'> => {
    ensureRenderedHtml()
    const frameDocument = iframeRef.current?.contentDocument
    const body = frameDocument?.body
    if (!frameDocument || !body) return 'failed'

    const html = serialiseBody(body).trim()
    if (!html || html === EMPTY_PREVIEW_HTML) return 'empty'

    const plainTextContainer = frameDocument.createElement('div')
    plainTextContainer.innerHTML = html
    const plainText = plainTextContainer.textContent?.trim() ?? ''

    try {
      if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
        await navigator.clipboard.write([
          new ClipboardItem({
            'text/html': new Blob([html], { type: 'text/html' }),
            'text/plain': new Blob([plainText], { type: 'text/plain' }),
          }),
        ])
        return 'copied'
      }
    } catch {
      // Some embedded browsers reject asynchronous clipboard writes. Use the
      // native selection path below, which preserves a rich HTML fragment.
    }

    const selection = frameDocument.defaultView?.getSelection()
    if (!selection) return 'failed'
    const previousRanges = Array.from(
      { length: selection.rangeCount },
      (_, index) => selection.getRangeAt(index).cloneRange(),
    )
    const copyContainer = frameDocument.createElement('div')
    copyContainer.contentEditable = 'true'
    copyContainer.tabIndex = -1
    copyContainer.style.cssText = 'position:fixed;left:-10000px;top:0;width:1px;height:1px;overflow:hidden;'
    copyContainer.innerHTML = html

    let copied = false
    try {
      body.append(copyContainer)
      copyContainer.focus({ preventScroll: true })
      const range = frameDocument.createRange()
      range.selectNodeContents(copyContainer)
      selection.removeAllRanges()
      selection.addRange(range)
      copied = frameDocument.execCommand('copy')
    } catch {
      copied = false
    } finally {
      copyContainer.remove()
      selection.removeAllRanges()
      for (const range of previousRanges) {
        if (range.commonAncestorContainer.isConnected) selection.addRange(range)
      }
    }

    return copied ? 'copied' : 'failed'
  }

  const recordEditChange = (previousHtml: string) => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body || previousHtml === serialiseBody(body)) return
    if (editUndoStackRef.current.at(-1) === previousHtml) return
    editUndoStackRef.current.push(previousHtml)
    if (editUndoStackRef.current.length > MAX_EDIT_HISTORY_ENTRIES) editUndoStackRef.current.shift()
    editRedoStackRef.current = []
    onHistoryStateChangeRef.current({ canUndo: true, canRedo: false })
  }

  const restoreEditHistory = (direction: 'undo' | 'redo') => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return false
    const sourceStack = direction === 'undo' ? editUndoStackRef.current : editRedoStackRef.current
    const targetHtml = sourceStack.pop()
    if (targetHtml === undefined) return false
    const currentHtml = serialiseBody(body)
    const destinationStack = direction === 'undo' ? editRedoStackRef.current : editUndoStackRef.current
    destinationStack.push(currentHtml)
    pendingInputHistoryRef.current = null
    onHistoryStateChangeRef.current({
      canUndo: editUndoStackRef.current.length > 0,
      canRedo: editRedoStackRef.current.length > 0,
    })
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

  const selectionStableAttributes = (element: HTMLElement) => {
    const attributes: Record<string, string> = {}
    element.getAttributeNames().forEach((name) => {
      const key = name.toLowerCase()
      if (!/^(id|src|srcset|href|name|data-[a-z0-9_-]+)$/.test(key)) return
      const value = element.getAttribute(name)
      if (value) attributes[key] = value
    })
    return attributes
  }

  const selectionFingerprintText = (clone: HTMLElement) => {
    // Match the source-side parser's text normalisation. `textContent` alone
    // joins adjacent inline nodes, while replacing tags with whitespace keeps
    // a span/a selection stable across browser and source parsing.
    const container = clone.ownerDocument.createElement('div')
    container.innerHTML = clone.outerHTML.replace(/<[^>]+>/g, ' ')
    return (container.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 1000)
  }

  const selectionSiblingIndex = (element: HTMLElement) => {
    const siblings = Array.from(element.parentElement?.children ?? [])
      .filter((node) => node.tagName === element.tagName)
    const index = siblings.indexOf(element)
    return index >= 0 ? index + 1 : 0
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
    const selector = makeSelector(element, body)
    const parent = element.parentElement && element.parentElement !== body ? element.parentElement : null
    const text = (clone.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 2000)
    const fingerprintText = selectionFingerprintText(clone)
    return sanitizeSelectedElement({
      selector,
      tag_name: element.tagName.toLowerCase(),
      html: clone.outerHTML,
      text,
      locator: {
        path: selector,
        parent_path: parent ? makeSelector(parent, body) : '',
        sibling_index: selectionSiblingIndex(element),
        fingerprint: {
          tag_name: element.tagName.toLowerCase(),
          stable_attributes: selectionStableAttributes(element),
          text: fingerprintText,
        },
      },
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

  const selectedBlocks = (body: HTMLElement) => sortBlocksInDocumentOrder(
    selectedBlocksRef.current.filter((block) => body.contains(block)),
  )

  const updateBlockToolbarPosition = () => {
    const iframe = iframeRef.current
    const shell = shellRef.current
    const block = activeBlockRef.current
    if (!iframe || !shell || !block?.isConnected) {
      setBlockToolbarPosition(null)
      return
    }
    const iframeBounds = iframe.getBoundingClientRect()
    const shellBounds = shell.getBoundingClientRect()
    const bounds = block.getBoundingClientRect()
    const toolbarHeight = blockToolbarRef.current?.offsetHeight || 38
    const blockTop = iframeBounds.top - shellBounds.top + shell.scrollTop + bounds.top
    const blockBottom = iframeBounds.top - shellBounds.top + shell.scrollTop + bounds.bottom
    const viewportTop = shell.scrollTop + 8
    const viewportBottom = shell.scrollTop + shell.clientHeight - 8
    const above = blockTop - toolbarHeight - 8
    const below = blockBottom + 8
    const top = above >= viewportTop || below > viewportBottom ? Math.max(viewportTop, above) : below
    const halfWidth = Math.min(190, Math.max(70, shell.clientWidth / 2 - 8))
    const left = Math.max(
      halfWidth,
      Math.min(
        shell.clientWidth - halfWidth,
        iframeBounds.left - shellBounds.left + shell.scrollLeft + bounds.left + bounds.width / 2,
      ),
    )
    setBlockToolbarPosition({ top, left })
  }

  const readBlockStyle = (blocks: HTMLElement[]) => {
    const document = iframeRef.current?.contentDocument
    const view = document?.defaultView
    if (!view || blocks.length === 0) {
      setBlockStyle(EMPTY_BLOCK_STYLE)
      return
    }
    const styles = blocks.map((block) => view.getComputedStyle(block))
    const pixel = (value: string) => {
      const parsed = Number.parseFloat(value)
      return Number.isFinite(parsed) ? Math.round(parsed) : null
    }
    const uniformPixel = (style: CSSStyleDeclaration, properties: string[]) => {
      const values = properties.map((property) => pixel(style.getPropertyValue(property)))
      return values.every((value) => value !== null && value === values[0]) ? values[0] : null
    }
    const background = commonValue(styles.map((style) => {
      const value = style.backgroundColor
      return value === 'transparent' || value === 'rgba(0, 0, 0, 0)' ? '' : value
    }))
    const fontFamily = commonValue(styles.map((style) => toolbarFontValue(style.fontFamily)))
    const lineHeight = commonValue(styles.map(toolbarLineHeight))
    const alignment = commonValue(styles.map((style) => toolbarAlignment(style.textAlign)))
    setBlockStyle({
      alignment: alignment ?? MIXED_VALUE,
      background: background || null,
      borderRadius: commonValue(styles.map((style) => uniformPixel(style, ['border-top-left-radius', 'border-top-right-radius', 'border-bottom-right-radius', 'border-bottom-left-radius']))),
      borderWidth: commonValue(styles.map((style) => uniformPixel(style, ['border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width']))),
      color: commonValue(styles.map((style) => style.color)),
      fontFamily: fontFamily ?? MIXED_VALUE,
      fontSize: commonValue(styles.map((style) => pixel(style.fontSize))),
      lineHeight: lineHeight ?? MIXED_VALUE,
      margin: commonValue(styles.map((style) => uniformPixel(style, ['margin-top', 'margin-right', 'margin-bottom', 'margin-left']))),
      padding: commonValue(styles.map((style) => uniformPixel(style, ['padding-top', 'padding-right', 'padding-bottom', 'padding-left']))),
      textIndent: commonValue(styles.map(toolbarTextIndent)),
    })
  }

  const setBlockSelection = (blocks: HTMLElement[], activeBlock: HTMLElement | null = blocks.at(-1) ?? null) => {
    selectedBlocksRef.current.forEach((block) => block.classList.remove(BLOCK_EDITING_TRANSIENT_CLASS))
    const body = iframeRef.current?.contentDocument?.body
    const nextBlocks = body ? blocks.filter((block) => body.contains(block)) : []
    const ordered = sortBlocksInDocumentOrder(nextBlocks)
    ordered.forEach((block) => block.classList.add(BLOCK_EDITING_TRANSIENT_CLASS))
    selectedBlocksRef.current = ordered
    activeBlockRef.current = activeBlock && ordered.includes(activeBlock) ? activeBlock : ordered.at(-1) ?? null
    setBlockSelectionCount(ordered.length)
    if (ordered.length === 0) {
      setBlockToolbarPosition(null)
      setBlockStyle(EMPTY_BLOCK_STYLE)
      return
    }
    readBlockStyle(ordered)
    updateBlockToolbarPosition()
  }

  const clearBlockSelection = () => {
    selectedBlocksRef.current.forEach((block) => block.classList.remove(BLOCK_EDITING_TRANSIENT_CLASS))
    selectedBlocksRef.current = []
    activeBlockRef.current = null
    setBlockSelectionCount(0)
    setBlockToolbarPosition(null)
    setBlockStyle(EMPTY_BLOCK_STYLE)
  }

  const changeMobileEditTarget = (target: MobileEditTarget) => {
    if (!compactRef.current || mobileEditTargetRef.current === target) return
    clearBlockSelection()
    removeImageAction()
    iframeRef.current?.contentDocument?.defaultView?.getSelection()?.removeAllRanges()
    textSelectionRangeRef.current = null
    setTextToolbarPosition(null)
    onCaretAvailabilityChangeRef.current(false)
    mobileEditTargetRef.current = target
    mobileBlockMultiSelectRef.current = false
    mobileEditorPanelRef.current = null
    setMobileEditTarget(target)
    setMobileBlockMultiSelect(false)
    setMobileEditorPanel(null)
    updateEditingState()
  }

  const finishMobileBlockEditing = () => {
    clearBlockSelection()
    changeMobileEditTarget('text')
  }

  const closeMobileEditorPanel = () => {
    if (mobileEditorPanelRef.current === 'image-actions') removeImageAction()
    mobileEditorPanelRef.current = null
    setMobileEditorPanel(null)
  }

  const openMobileEditorPanel = (panel: Exclude<MobileEditorPanel, null>) => {
    mobileEditorPanelRef.current = panel
    setMobileEditorPanel(panel)
  }

  const removeBlockHandle = () => {
    if (blockHandleTimerRef.current) clearTimeout(blockHandleTimerRef.current)
    blockHandleTimerRef.current = null
    hoveredBlockRef.current?.classList.remove(BLOCK_HOVER_TRANSIENT_CLASS)
    blockHandleRef.current?.remove()
    blockHandleRef.current = null
    hoveredBlockRef.current = null
  }

  const scheduleBlockHandleHide = () => {
    if (blockHandleTimerRef.current) clearTimeout(blockHandleTimerRef.current)
    blockHandleTimerRef.current = setTimeout(() => removeBlockHandle(), 180)
  }

  const clearBlockDropIndicator = () => {
    blockDropIndicatorRef.current?.remove()
    blockDropIndicatorRef.current = null
  }

  const showBlockDropIndicator = (target: HTMLElement, before: boolean) => {
    const document = target.ownerDocument
    const bounds = target.getBoundingClientRect()
    let indicator = blockDropIndicatorRef.current
    if (!indicator || !indicator.isConnected) {
      indicator = document.createElement('div')
      indicator.dataset.previewBlockDropIndicator = 'true'
      indicator.className = 'ai-preview-block-drop-indicator'
      indicator.setAttribute('contenteditable', 'false')
      document.body.append(indicator)
      blockDropIndicatorRef.current = indicator
    }
    indicator.style.left = `${Math.max(4, Math.round(bounds.left))}px`
    indicator.style.top = `${Math.round((before ? bounds.top : bounds.bottom) - 1)}px`
    indicator.style.width = `${Math.max(16, Math.round(bounds.width))}px`
  }

  const showBlockHandle = (block: HTMLElement) => {
    if (modeRef.current !== 'edit' || !block.isConnected) return
    const document = block.ownerDocument
    if (blockHandleTimerRef.current) clearTimeout(blockHandleTimerRef.current)
    blockHandleTimerRef.current = null
    let handle = blockHandleRef.current
    if (!handle || !handle.isConnected) {
      handle = document.createElement('button')
      handle.type = 'button'
      handle.dataset.previewBlockHandle = 'true'
      handle.className = 'ai-preview-block-handle'
      handle.setAttribute('contenteditable', 'false')
      handle.setAttribute('aria-label', '拖动块')
      handle.title = '拖动块调整顺序'
      handle.textContent = '::'
      handle.addEventListener('pointerdown', (event) => {
        const target = hoveredBlockRef.current
        if (target) beginBlockDrag(event, target)
      })
      handle.addEventListener('pointerenter', () => {
        if (blockHandleTimerRef.current) clearTimeout(blockHandleTimerRef.current)
      })
      handle.addEventListener('pointerleave', scheduleBlockHandleHide)
      document.body.append(handle)
      blockHandleRef.current = handle
    }
    if (hoveredBlockRef.current !== block) {
      hoveredBlockRef.current?.classList.remove(BLOCK_HOVER_TRANSIENT_CLASS)
      block.classList.add(BLOCK_HOVER_TRANSIENT_CLASS)
    }
    const bounds = block.getBoundingClientRect()
    handle.style.left = `${Math.max(2, Math.round(bounds.left - 24))}px`
    handle.style.top = `${Math.max(4, Math.round(bounds.top + Math.min(8, Math.max(0, bounds.height / 2 - 14))))}px`
    hoveredBlockRef.current = block
  }

  const selectEditableBlock = (
    block: HTMLElement,
    event?: Pick<PointerEvent, 'ctrlKey' | 'metaKey' | 'shiftKey'>,
    change: 'replace' | 'toggle' | null = null,
  ) => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body || !body.contains(block)) return
    const current = selectedBlocks(body)
    const toggling = change === 'toggle' || Boolean(event?.ctrlKey || event?.metaKey)
    if (event?.shiftKey && activeBlockRef.current?.parentElement === block.parentElement && block.parentElement) {
      const candidates = Array.from(block.parentElement.children).filter((node): node is HTMLElement => (
        node.nodeType === 1 && findEditableBlock(node as HTMLElement, body) === node
      ))
      const start = candidates.indexOf(activeBlockRef.current)
      const end = candidates.indexOf(block)
      if (start >= 0 && end >= 0) {
        setBlockSelection(candidates.slice(Math.min(start, end), Math.max(start, end) + 1), block)
        return
      }
    }
    if (toggling) {
      const next = nextBlockSelection(current, block, 'toggle')
      setBlockSelection(next, next.includes(block) ? block : next.at(-1) ?? null)
      return
    }
    setBlockSelection(nextBlockSelection(current, block, 'replace'), block)
  }

  const commitBlockMutation = (mutate: (blocks: HTMLElement[], body: HTMLElement) => HTMLElement[] | null) => {
    if (modeRef.current !== 'edit') return
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const blocks = selectedBlocks(body)
    if (blocks.length === 0) return
    const previousHtml = serialiseBody(body)
    const nextSelection = mutate(blocks, body)
    if (!nextSelection || serialiseBody(body) === previousHtml) return
    recordEditChange(previousHtml)
    emitCurrentHtmlChange()
    syncHeight()
    setBlockSelection(nextSelection)
  }

  const selectionCanReorder = (blocks: HTMLElement[]) => (
    blocks.length > 0 && areConsecutiveSiblingBlocks(blocks) && !blocks.some(isInsideTableCell)
  )

  const moveSelectedBlocks = (direction: 'up' | 'down') => {
    commitBlockMutation((blocks) => {
      if (!selectionCanReorder(blocks)) return null
      const parent = blocks[0].parentElement
      if (!parent) return null
      const ordered = sortBlocksInDocumentOrder(blocks)
      const boundary = direction === 'up' ? ordered[0].previousElementSibling : ordered.at(-1)?.nextElementSibling ?? null
      if (!boundary || ordered.includes(boundary as HTMLElement)) return null
      const fragment = parent.ownerDocument.createDocumentFragment()
      ordered.forEach((block) => fragment.append(block))
      if (direction === 'up') parent.insertBefore(fragment, boundary)
      else parent.insertBefore(fragment, boundary.nextSibling)
      return ordered
    })
  }

  const duplicateSelectedBlocks = () => {
    commitBlockMutation((blocks) => {
      const ordered = sortBlocksInDocumentOrder(blocks)
      const parent = ordered[0]?.parentElement
      if (!parent || ordered.some((block) => block.parentElement !== parent)) return null
      const copies = ordered.map((block) => cleanClone(block))
      const after = ordered.at(-1)?.nextSibling ?? null
      const fragment = parent.ownerDocument.createDocumentFragment()
      copies.forEach((copy) => fragment.append(copy))
      parent.insertBefore(fragment, after)
      return copies
    })
  }

  const deleteSelectedBlocks = () => {
    commitBlockMutation((blocks, body) => {
      blocks.forEach((block) => block.remove())
      if (!Array.from(body.children).some((node) => !node.hasAttribute(BLOCK_HANDLE_ATTRIBUTE))) {
        const paragraph = body.ownerDocument.createElement('p')
        paragraph.append(body.ownerDocument.createElement('br'))
        body.append(paragraph)
        return [paragraph]
      }
      return []
    })
  }

  const insertAdjacentParagraph = (direction: 'before' | 'after') => {
    commitBlockMutation((blocks) => {
      if (!selectionCanReorder(blocks)) return null
      const ordered = sortBlocksInDocumentOrder(blocks)
      const parent = ordered[0].parentElement
      if (!parent) return null
      const paragraph = parent.ownerDocument.createElement('p')
      paragraph.append(parent.ownerDocument.createElement('br'))
      const reference = direction === 'before' ? ordered[0] : ordered.at(-1)?.nextSibling ?? null
      parent.insertBefore(paragraph, reference)
      return [paragraph]
    })
  }

  const applySelectedBlockStyle = (property: string, value: string) => {
    commitBlockMutation((blocks) => {
      blocks.forEach((block) => block.style.setProperty(property, value))
      return blocks
    })
  }

  const applySelectedBlockBorderWidth = (width: number) => {
    commitBlockMutation((blocks) => {
      blocks.forEach((block) => {
        block.style.borderWidth = `${width}px`
        if (width > 0 && !block.style.borderStyle) block.style.borderStyle = 'solid'
        if (width > 0 && !block.style.borderColor) block.style.borderColor = '#d9d9d9'
      })
      return blocks
    })
  }

  const attachSelectedBlocksToAi = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const contexts = selectedBlocks(body).map((block) => selectionContext(block, body))
    if (contexts.length) onAttachSelectedBlocksRef.current(contexts)
  }

  const collectSelectedBlocks = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    const html = selectedBlocks(body).map((block) => cleanClone(block).outerHTML).join('')
    if (html) onCollectTemplateHtmlRef.current(html)
  }

  const collectImage = (image: HTMLImageElement) => {
    const body = image.ownerDocument.body
    if (!body || !body.contains(image)) return
    const link = image.closest('a')
    const source = link && body.contains(link) ? link : image
    onCollectTemplateHtmlRef.current(cleanClone(source).outerHTML)
  }

  const beginBlockDrag = (event: PointerEvent, block: HTMLElement) => {
    if (modeRef.current !== 'edit') return
    event.preventDefault()
    event.stopPropagation()
    selectEditableBlock(block, event)
    const document = block.ownerDocument
    const body = document.body
    const movingBlocks = selectedBlocks(body)
    if (!selectionCanReorder(movingBlocks)) return
    blockDragCleanupRef.current?.()
    const origin = { x: event.clientX, y: event.clientY }
    let dragging = false
    let drop: { before: boolean; target: HTMLElement } | null = null
    const onMove = (moveEvent: PointerEvent) => {
      if (!dragging && Math.hypot(moveEvent.clientX - origin.x, moveEvent.clientY - origin.y) < 5) return
      dragging = true
      const rawTarget = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)
      const target = rawTarget && rawTarget.nodeType === Node.ELEMENT_NODE
        ? findEditableBlock(rawTarget as HTMLElement, body)
        : null
      if (!target || target.parentElement !== movingBlocks[0].parentElement || movingBlocks.includes(target) || isInsideTableCell(target)) {
        drop = null
        clearBlockDropIndicator()
        return
      }
      const bounds = target.getBoundingClientRect()
      drop = { target, before: moveEvent.clientY < bounds.top + bounds.height / 2 }
      showBlockDropIndicator(target, drop.before)
    }
    const finish = () => {
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', finish)
      document.removeEventListener('pointercancel', finish)
      blockDragCleanupRef.current = null
      clearBlockDropIndicator()
      if (!dragging || !drop) return
      commitBlockMutation((blocks) => {
        if (!selectionCanReorder(blocks) || !blocks.includes(block) || drop === null) return null
        const ordered = sortBlocksInDocumentOrder(blocks)
        const parent = ordered[0].parentElement
        if (!parent || drop.target.parentElement !== parent) return null
        const reference = drop.before ? drop.target : drop.target.nextSibling
        if (reference && ordered.includes(reference as HTMLElement)) return null
        const fragment = parent.ownerDocument.createDocumentFragment()
        ordered.forEach((item) => fragment.append(item))
        parent.insertBefore(fragment, reference)
        return ordered
      })
    }
    blockDragCleanupRef.current = finish
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', finish)
    document.addEventListener('pointercancel', finish)
  }

  const emitCurrentHtmlChange = () => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body) return
    markLinksToOpenInNewWindow(body)
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

  const updateTextToolbar = () => {
    if (modeRef.current !== 'edit') {
      textSelectionRangeRef.current = null
      setTextToolbarPosition(null)
      return
    }
    const iframe = iframeRef.current
    const shell = shellRef.current
    const document = iframe?.contentDocument
    const body = document?.body
    const selection = document?.defaultView?.getSelection()
    if (!iframe || !shell || !body || !selection?.rangeCount || selection.isCollapsed) {
      textSelectionRangeRef.current = null
      setTextToolbarPosition(null)
      return
    }
    const range = selection.getRangeAt(0)
    if (!body.contains(range.commonAncestorContainer)) {
      textSelectionRangeRef.current = null
      setTextToolbarPosition(null)
      return
    }
    const bounds = range.getBoundingClientRect()
    if (!bounds.width && !bounds.height) return
    const iframeBounds = iframe.getBoundingClientRect()
    const shellBounds = shell.getBoundingClientRect()
    const textSource = range.startContainer.nodeType === Node.ELEMENT_NODE
      ? range.startContainer as HTMLElement
      : range.startContainer.parentElement
    const paragraph = textSource?.closest<HTMLElement>(BLOCK_SELECTOR)
      ?? Array.from(body.querySelectorAll<HTMLElement>(BLOCK_SELECTOR)).find((block) => range.intersectsNode(block))
    const computedStyle = textSource ? document.defaultView?.getComputedStyle(textSource) : null
    const textStyles: CSSStyleDeclaration[] = []
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if ((node.textContent ?? '').trim() && range.intersectsNode(node) && node.parentElement) {
        textStyles.push(document.defaultView?.getComputedStyle(node.parentElement) ?? computedStyle ?? document.defaultView!.getComputedStyle(body))
      }
    }
    if (textStyles.length === 0 && computedStyle) textStyles.push(computedStyle)
    const paragraphNodes = Array.from(body.querySelectorAll<HTMLElement>(BLOCK_SELECTOR)).filter((block) => range.intersectsNode(block))
    if (paragraphNodes.length === 0 && paragraph) paragraphNodes.push(paragraph)
    const paragraphStyles = paragraphNodes.map((block) => document.defaultView?.getComputedStyle(block)).filter((style): style is CSSStyleDeclaration => Boolean(style))
    if (paragraphStyles.length === 0 && computedStyle) paragraphStyles.push(computedStyle)
    const fontFamily = commonValue(textStyles.map((style) => toolbarFontValue(style.fontFamily)))
    const color = commonValue(textStyles.map((style) => style.color))
    const fontSize = commonValue(textStyles.map((style) => Math.round(Number.parseFloat(style.fontSize))))
    const letterSpacing = commonValue(textStyles.map((style) => {
      const value = Number.parseFloat(style.letterSpacing)
      return Number.isFinite(value) ? Number(value.toFixed(1)) : 0
    }))
    const fontWeight = commonValue(textStyles.map((style) => style.fontWeight === 'bold' || Number.parseInt(style.fontWeight, 10) >= 600))
    const fontStyle = commonValue(textStyles.map((style) => style.fontStyle === 'italic'))
    const textDecoration = commonValue(textStyles.map((style) => style.textDecorationLine.includes('underline')))
    const lineHeight = commonValue(paragraphStyles.map((style) => toolbarLineHeight(style)))
    const textIndent = commonValue(paragraphStyles.map(toolbarTextIndent))
    const marginLeft = commonValue(paragraphStyles.map((style) => Math.round(Number.parseFloat(style.marginLeft))))
    const marginRight = commonValue(paragraphStyles.map((style) => Math.round(Number.parseFloat(style.marginRight))))
    const alignment = commonValue(paragraphStyles.map((style) => toolbarAlignment(style.textAlign)))
    setTextToolbarColor(color)
    setTextToolbarFontFamily(fontFamily ?? MIXED_VALUE)
    setTextToolbarFontSize(Number.isFinite(fontSize ?? Number.NaN) ? fontSize : null)
    setTextToolbarLetterSpacing(Number.isFinite(letterSpacing ?? Number.NaN) ? letterSpacing : null)
    setTextToolbarLineHeight(lineHeight ?? MIXED_VALUE)
    setTextToolbarTextIndent(Number.isFinite(textIndent ?? Number.NaN) ? textIndent : null)
    setTextToolbarMarginLeft(Number.isFinite(marginLeft ?? Number.NaN) ? marginLeft : null)
    setTextToolbarMarginRight(Number.isFinite(marginRight ?? Number.NaN) ? marginRight : null)
    setTextToolbarAlignment(alignment ?? MIXED_VALUE)
    setTextToolbarBold(fontWeight)
    setTextToolbarItalic(fontStyle)
    setTextToolbarUnderline(textDecoration)
    textSelectionRangeRef.current = range.cloneRange()
    pendingTextFormatRangeRef.current = null
    const toolbarHalfWidth = Math.min(200, Math.max(16, shell.clientWidth / 2 - 8))
    const selectionTop = iframeBounds.top - shellBounds.top + shell.scrollTop + bounds.top
    const selectionBottom = iframeBounds.top - shellBounds.top + shell.scrollTop + bounds.bottom
    const basePosition = {
      top: selectionBottom + TEXT_TOOLBAR_GAP,
      left: Math.max(toolbarHalfWidth, Math.min(shell.clientWidth - toolbarHalfWidth, iframeBounds.left - shellBounds.left + shell.scrollLeft + bounds.left + bounds.width / 2)),
    }
    textToolbarAnchorRef.current = { top: selectionTop, bottom: selectionBottom, left: basePosition.left }
    const hasCustomPosition = textToolbarOffsetRef.current.top !== 0 || textToolbarOffsetRef.current.left !== 0
    if (!hasCustomPosition) textToolbarBasePositionRef.current = basePosition
    const nextPosition = hasCustomPosition
      ? {
          top: textToolbarBasePositionRef.current.top + textToolbarOffsetRef.current.top,
          left: textToolbarBasePositionRef.current.left + textToolbarOffsetRef.current.left,
        }
      : basePosition
    setTextToolbarPosition({
      top: Math.max(8, nextPosition.top),
      left: Math.max(toolbarHalfWidth, Math.min(shell.clientWidth - toolbarHalfWidth, nextPosition.left)),
    })
  }

  const nodeSelectionId = (node: Node) => {
    let id = selectionNodeIdsRef.current.get(node)
    if (!id) {
      id = nextSelectionNodeIdRef.current++
      selectionNodeIdsRef.current.set(node, id)
    }
    return id
  }

  const scheduleTextToolbarUpdate = () => {
    const document = iframeRef.current?.contentDocument
    const selection = document?.defaultView?.getSelection()
    if (!selection?.rangeCount || selection.isCollapsed) {
      // Opening a mobile formatting drawer moves focus out of the iframe. Keep
      // the last real text range until that drawer is closed so its controls
      // still act on the selected text.
      if (compactRef.current && mobileEditorPanelRef.current === 'text-style' && textSelectionRangeRef.current) return
      if (textToolbarTimerRef.current) clearTimeout(textToolbarTimerRef.current)
      textToolbarTimerRef.current = null
      textSelectionRangeRef.current = null
      setTextToolbarPosition(null)
      return
    }
    const range = selection.getRangeAt(0)
    const signature = `${nodeSelectionId(range.startContainer)}:${range.startOffset}-${nodeSelectionId(range.endContainer)}:${range.endOffset}`
    if (signature !== selectionSignatureRef.current) {
      selectionSignatureRef.current = signature
      textToolbarOffsetRef.current = { top: 0, left: 0 }
    }
    if (textToolbarTimerRef.current) clearTimeout(textToolbarTimerRef.current)
    textToolbarTimerRef.current = setTimeout(() => {
      textToolbarTimerRef.current = null
      updateTextToolbar()
    }, 180)
  }

  const beginTextToolbarDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const shell = shellRef.current
    const position = textToolbarPosition
    if (!shell || !position) return
    event.preventDefault()
    const origin = { x: event.clientX, y: event.clientY, top: position.top, left: position.left }
    const onMove = (moveEvent: PointerEvent) => {
      const toolbarHalfWidth = Math.min(200, Math.max(16, shell.clientWidth / 2 - 8))
      const next = {
        top: Math.max(8, Math.min(shell.scrollHeight - 8, origin.top + moveEvent.clientY - origin.y)),
        left: Math.max(toolbarHalfWidth, Math.min(shell.clientWidth - toolbarHalfWidth, origin.left + moveEvent.clientX - origin.x)),
      }
      textToolbarOffsetRef.current = {
        top: next.top - textToolbarBasePositionRef.current.top,
        left: next.left - textToolbarBasePositionRef.current.left,
      }
      setTextToolbarPosition(next)
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const preserveMobileTextSelection = (event: ReactPointerEvent<HTMLElement>) => {
    if (
      compactRef.current
      && mobileEditTargetRef.current === 'text'
      && textSelectionRangeRef.current
    ) event.preventDefault()
  }

  const preserveTextSelectionForFormatter = (event: { preventDefault: () => void }) => {
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const selection = document?.defaultView?.getSelection()
    if (!body) return
    const selectedRange = selection?.rangeCount && !selection.isCollapsed
      ? selection.getRangeAt(0)
      : null
    const range = selectedRange && body.contains(selectedRange.commonAncestorContainer)
      ? selectedRange
      : textSelectionRangeRef.current
    if (!range || !body.contains(range.commonAncestorContainer)) return
    const savedRange = range.cloneRange()
    textSelectionRangeRef.current = savedRange
    pendingTextFormatRangeRef.current = savedRange.cloneRange()
    // Formatting controls live outside the iframe. Avoid letting their focus
    // collapse the article selection before ColorPicker emits its final value.
    event.preventDefault()
  }

  const applyTextCommand = (command: string, value?: string) => {
    if (modeRef.current !== 'edit') return
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const range = pendingTextFormatRangeRef.current ?? textSelectionRangeRef.current
    if (!document || !body || !range || !body.contains(range.commonAncestorContainer)) {
      pendingTextFormatRangeRef.current = null
      return
    }
    const previousHtml = serialiseBody(body)
    const selectedLinks = command === 'foreColor'
      ? Array.from(body.querySelectorAll<HTMLAnchorElement>('a')).filter((link) => range.intersectsNode(link))
      : []
    const selection = document.defaultView?.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    body.focus()
    if (['foreColor', 'fontName', 'fontSize'].includes(command)) {
      document.execCommand('styleWithCSS', false, 'true')
    }
    const commandApplied = document.execCommand(command, false, value)
    // Native foreColor wraps the link in a colored span. A link's own default
    // color takes precedence over that inherited span color, so persist the
    // selected color on the anchor itself as well.
    if (command === 'foreColor' && value) {
      selectedLinks.forEach((link) => {
        link.style.color = value
      })
    }
    if (!commandApplied && selectedLinks.length === 0) {
      pendingTextFormatRangeRef.current = null
      return
    }
    pendingTextFormatRangeRef.current = null
    recordEditChange(previousHtml)
    emitCurrentHtmlChange()
    syncHeight()
    window.requestAnimationFrame(updateTextToolbar)
  }

  const applyBlockStyle = (property: 'textAlign' | 'lineHeight' | 'textIndent' | 'fontFamily' | 'fontSize' | 'letterSpacing' | 'marginLeft' | 'marginRight', value: string) => {
    if (modeRef.current !== 'edit') return
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const range = textSelectionRangeRef.current
    if (!document || !body || !range || !body.contains(range.commonAncestorContainer)) return
    const previousHtml = serialiseBody(body)
    const blocks = Array.from(body.querySelectorAll<HTMLElement>(BLOCK_SELECTOR))
      .filter((block) => range.intersectsNode(block))
    const targets = blocks.length > 0
      ? blocks
      : [range.startContainer.parentElement?.closest<HTMLElement>(BLOCK_SELECTOR)].filter(Boolean) as HTMLElement[]
    if (targets.length === 0) return
    targets.forEach((target) => { target.style[property] = value })
    recordEditChange(previousHtml)
    emitCurrentHtmlChange()
    syncHeight()
    window.requestAnimationFrame(updateTextToolbar)
  }

  const applyTextStyle = (property: 'fontFamily' | 'fontSize' | 'letterSpacing', value: string) => {
    if (modeRef.current !== 'edit') return
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const range = textSelectionRangeRef.current
    if (!document || !body || !range || !body.contains(range.commonAncestorContainer)) return
    const startBlock = range.startContainer.parentElement?.closest<HTMLElement>(BLOCK_SELECTOR)
    const endBlock = range.endContainer.parentElement?.closest<HTMLElement>(BLOCK_SELECTOR)
    if (!startBlock || !endBlock || startBlock !== endBlock) {
      applyBlockStyle(property, value)
      return
    }
    const previousHtml = serialiseBody(body)
    const fragment = range.extractContents()
    const span = document.createElement('span')
    span.style[property] = value
    span.append(fragment)
    range.insertNode(span)
    const selection = document.defaultView?.getSelection()
    const nextRange = document.createRange()
    nextRange.selectNodeContents(span)
    selection?.removeAllRanges()
    selection?.addRange(nextRange)
    textSelectionRangeRef.current = nextRange.cloneRange()
    recordEditChange(previousHtml)
    emitCurrentHtmlChange()
    syncHeight()
    window.requestAnimationFrame(updateTextToolbar)
  }

  const removeImageAction = () => {
    activeImageRef.current?.classList.remove('ai-preview-image-selected')
    imageActionRef.current?.remove()
    imageActionRef.current = null
    activeImageRef.current = null
    if (mobileEditorPanelRef.current === 'image-actions') {
      mobileEditorPanelRef.current = null
      setMobileEditorPanel(null)
    }
  }

  const deleteImage = (image: HTMLImageElement): boolean => {
    const body = image.ownerDocument.body
    if (modeRef.current !== 'edit' || !body || !body.contains(image)) return false
    const previousHtml = serialiseBody(body)
    const link = image.closest('a')
    image.remove()
    if (link && !link.textContent?.trim() && link.children.length === 0) link.remove()
    removeImageAction()
    recordEditChange(previousHtml)
    const nextHtml = serialiseBody(body)
    renderedHtmlRef.current = nextHtml
    onHtmlChangeRef.current(nextHtml)
    syncHeight()
    return true
  }

  const openImageAction = (image: HTMLImageElement) => {
    const document = image.ownerDocument
    if (!document.body) return
    removeImageAction()
    if (compactRef.current) {
      image.classList.add('ai-preview-image-selected')
      activeImageRef.current = image
      openMobileEditorPanel('image-actions')
      return
    }
    const imageBounds = image.getBoundingClientRect()
    const actionWidth = 318
    const actions = document.createElement('div')
    actions.className = 'ai-preview-image-actions'
    actions.dataset.previewImageAction = 'true'
    actions.setAttribute('contenteditable', 'false')
    Object.assign(actions.style, {
      position: 'fixed',
      zIndex: '2147483647',
      height: '30px',
    })
    const createActionButton = (label: string, title: string) => {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'ai-preview-image-action'
      button.textContent = label
      button.title = title
      button.setAttribute('aria-label', title)
      return button
    }
    const replaceButton = createActionButton('替换', '替换图片')
    replaceButton.dataset.previewImageReplace = 'true'
    replaceButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      imageInputModeRef.current = 'replace'
      imageInputRef.current?.click()
    })
    const cropButton = createActionButton('裁剪', '裁剪图片')
    cropButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      openImageCrop(image)
    })
    const deleteButton = createActionButton('删除', '删除图片')
    deleteButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      deleteImage(image)
    })
    const collectButton = createActionButton('收藏', '收藏到组件库')
    collectButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      collectImage(image)
    })
    actions.append(replaceButton, cropButton, deleteButton, collectButton)
    actions.style.left = `${Math.max(8, Math.min(document.documentElement.clientWidth - actionWidth - 8, imageBounds.right - actionWidth - 6))}px`
    actions.style.top = `${Math.max(8, imageBounds.top + 8)}px`
    document.body.append(actions)
    image.classList.add('ai-preview-image-selected')
    activeImageRef.current = image
    imageActionRef.current = actions
  }

  const openImagePickerForReplacement = () => {
    if (modeRef.current !== 'edit' || uploadingImageRef.current || !activeImageRef.current?.isConnected) return
    imageInputModeRef.current = 'replace'
    imageInputRef.current?.click()
  }

  const openImageCrop = (image: HTMLImageElement) => {
    const source = image.dataset.cropSource || image.currentSrc || image.src
    if (!source) {
      message.error('找不到图片原图，无法裁剪')
      return
    }
    cropTargetRef.current = image
    setImageCropSession({
      source,
      initialRect: parseCropRect(image.dataset.cropRect),
      hasExistingCrop: Boolean(image.dataset.cropSource),
    })
    removeImageAction()
  }

  const commitImageMutation = (target: HTMLImageElement, previousHtml: string) => {
    const body = target.ownerDocument.body
    recordEditChange(previousHtml)
    const nextHtml = serialiseBody(body)
    renderedHtmlRef.current = nextHtml
    onHtmlChangeRef.current(nextHtml)
    syncHeight()
  }

  const resetImageCrop = () => {
    const session = imageCropSession
    const target = cropTargetRef.current
    if (!session || !target?.isConnected || !target.ownerDocument.body) return
    const previousHtml = serialiseBody(target.ownerDocument.body)
    target.src = session.source
    target.removeAttribute('data-crop-source')
    target.removeAttribute('data-crop-rect')
    target.addEventListener('load', syncHeight, { once: true })
    commitImageMutation(target, previousHtml)
    setImageCropSession(null)
    cropTargetRef.current = null
    removeImageAction()
  }

  const applyImageCrop = async (rect: CropRect) => {
    const session = imageCropSession
    const target = cropTargetRef.current
    if (!session || !target?.isConnected || !target.ownerDocument.body) {
      message.error('图片已发生变化，请重新选择裁剪')
      setImageCropSession(null)
      return
    }
    if (isFullCropRect(rect)) {
      if (session.hasExistingCrop) resetImageCrop()
      else setImageCropSession(null)
      return
    }

    setCroppingImage(true)
    try {
      const sourceBlob = await readCropSource(session.source)
      const croppedBlob = await cropImageBlob(sourceBlob, rect)
      const contentType = croppedBlob.type || 'image/png'
      const filename = contentType === 'image/jpeg' ? 'cropped-image.jpg' : 'cropped-image.png'
      const file = new File([croppedBlob], filename, { type: contentType })
      const url = await onUploadImageRef.current(file)
      if (!target.isConnected || !target.ownerDocument.body) throw new ImageCropError('图片已发生变化，请重新选择裁剪')
      const previousHtml = serialiseBody(target.ownerDocument.body)
      target.src = url
      target.dataset.cropSource = session.source
      target.dataset.cropRect = serializeCropRect(rect)
      target.removeAttribute('srcset')
      target.removeAttribute('sizes')
      target.addEventListener('load', syncHeight, { once: true })
      commitImageMutation(target, previousHtml)
      setImageCropSession(null)
      cropTargetRef.current = null
      removeImageAction()
      target.ownerDocument.defaultView?.focus()
      message.success('图片裁剪已应用')
    } catch (error) {
      const detail = error instanceof ImageCropError ? error.message : '无法读取原图或上传裁剪图片，请确认图片地址允许跨域读取'
      message.error(detail)
    } finally {
      setCroppingImage(false)
    }
  }

  const captureCaretRange = (): Range | null => {
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    const selection = document?.defaultView?.getSelection()
    if (!body || !selection?.rangeCount) return null
    const range = selection.getRangeAt(0)
    return body.contains(range.commonAncestorContainer) ? range.cloneRange() : null
  }

  const captureCollapsedCaretRange = (): Range | null => {
    if (modeRef.current !== 'edit') return null
    const range = captureCaretRange()
    return range?.collapsed ? range : null
  }

  const reportCaretAvailability = () => {
    onCaretAvailabilityChangeRef.current(Boolean(captureCollapsedCaretRange()))
  }

  const insertTemplateHtml = (templateHtml: string, placement: 'append' | 'caret'): boolean => {
    ensureRenderedHtml()
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    if (!body || !templateHtml.trim()) return false
    const previousHtml = serialiseBody(body)
    const range = placement === 'caret' ? captureCollapsedCaretRange() : null
    if (placement === 'caret' && !range) return false

    const fragment = document.createRange().createContextualFragment(templateHtml)
    fragment.querySelectorAll<HTMLImageElement>('img[src]').forEach((image) => {
      const source = image.getAttribute('src')?.trim()
      if (/^https?:\/\//i.test(source ?? '')) image.setAttribute('referrerpolicy', 'no-referrer')
    })
    const lastNode = fragment.lastChild
    if (!lastNode) return false

    if (placement === 'caret' && range) {
      range.deleteContents()
      range.insertNode(fragment)
      const selection = document.defaultView?.getSelection()
      const after = document.createRange()
      after.setStartAfter(lastNode)
      after.collapse(true)
      selection?.removeAllRanges()
      selection?.addRange(after)
    } else {
      if (body.innerHTML === EMPTY_PREVIEW_HTML) body.innerHTML = ''
      body.append(fragment)
    }
    markLinksToOpenInNewWindow(body)
    recordEditChange(previousHtml)
    const nextHtml = serialiseBody(body)
    renderedHtmlRef.current = nextHtml
    onHtmlChangeRef.current(nextHtml)
    syncHeight()
    reportCaretAvailability()
    return true
  }

  const insertUploadedImage = async (file: File, range: Range | null, afterBlock: HTMLElement | null = null) => {
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
      image.style.display = 'block'
      image.style.maxWidth = '100%'
      image.style.height = 'auto'
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
        if (afterBlock?.isConnected && afterBlock.parentElement) {
          afterBlock.parentElement.insertBefore(paragraph, afterBlock.nextSibling)
        } else {
          body.append(paragraph)
        }
        setBlockSelection([paragraph], paragraph)
      }
      recordEditChange(previousHtml)
      const nextHtml = serialiseBody(body)
      renderedHtmlRef.current = nextHtml
      onHtmlChangeRef.current(nextHtml)
      syncHeight()
    } finally {
      uploadingImageRef.current = false
    }
  }

  const openImagePickerForInsert = (afterSelectedBlock = false) => {
    if (modeRef.current !== 'edit' || uploadingImageRef.current) return
    removeImageAction()
    imageInputModeRef.current = 'insert'
    pendingInsertRangeRef.current = captureCaretRange()
    const body = iframeRef.current?.contentDocument?.body
    pendingBlockImageInsertionRef.current = afterSelectedBlock && body
      ? selectedBlocks(body).at(-1) ?? null
      : null
    imageInputRef.current?.click()
  }

  const handleImageFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0]
    const inputMode = imageInputModeRef.current
    const insertRange = pendingInsertRangeRef.current
    const afterBlock = pendingBlockImageInsertionRef.current
    const target = activeImageRef.current
    imageInputModeRef.current = 'replace'
    pendingInsertRangeRef.current = null
    pendingBlockImageInsertionRef.current = null
    event.currentTarget.value = ''
    event.currentTarget.blur()
    if (!file || uploadingImageRef.current || modeRef.current !== 'edit') return
    if (inputMode === 'insert') {
      await insertUploadedImage(file, insertRange, afterBlock)
      return
    }
    if (!target) return
    uploadingImageRef.current = true
    const action = imageActionRef.current
    const replaceAction = action?.querySelector<HTMLButtonElement>('[data-preview-image-replace]') ?? null
    if (replaceAction) {
      replaceAction.disabled = true
      replaceAction.textContent = '上传中...'
    }
    try {
      const url = await onUploadImageRef.current(file)
      if (!target.isConnected || !target.ownerDocument.body) return
      const previousHtml = serialiseBody(target.ownerDocument.body)
      target.src = url
      target.removeAttribute('data-crop-source')
      target.removeAttribute('data-crop-rect')
      target.removeAttribute('srcset')
      target.removeAttribute('sizes')
      target.addEventListener('load', syncHeight, { once: true })
      recordEditChange(previousHtml)
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
      if (replaceAction?.isConnected) {
        replaceAction.disabled = false
        replaceAction.textContent = '替换'
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
    copyArticle,
    openImagePickerForInsert,
    insertTemplateHtml,
    undo: () => restoreEditHistory('undo'),
    redo: () => restoreEditHistory('redo'),
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
    let textSelectionPressTimer: ReturnType<typeof setTimeout> | null = null
    let textSelectionAutoScrollFrame: number | null = null
    let textSelectionGesture: {
      anchor: Range
      active: boolean
      point: { x: number; y: number } | null
      startPoint: { x: number; y: number }
    } | null = null

    const isMobileTextEditing = () => (
      compactRef.current
      && modeRef.current === 'edit'
      && mobileEditTargetRef.current === 'text'
    )
    const selectedTextRange = () => {
      const selection = document.defaultView?.getSelection()
      if (!selection?.rangeCount || selection.isCollapsed) return null
      const range = selection.getRangeAt(0)
      return body.contains(range.commonAncestorContainer) ? range : null
    }
    const viewportPointFromTouch = (touch: Touch) => {
      const bounds = iframeRef.current?.getBoundingClientRect()
      if (!bounds) return null
      return { x: bounds.left + touch.clientX, y: bounds.top + touch.clientY }
    }
    const rangeAtViewportPoint = (point: { x: number; y: number }) => {
      const bounds = iframeRef.current?.getBoundingClientRect()
      if (!bounds) return null
      const pointDocument = document as Document & {
        caretPositionFromPoint?: (x: number, y: number) => CaretPosition | null
        caretRangeFromPoint?: (x: number, y: number) => Range | null
      }
      const x = point.x - bounds.left
      const y = point.y - bounds.top
      const legacyRange = pointDocument.caretRangeFromPoint?.(x, y)
      if (legacyRange && body.contains(legacyRange.commonAncestorContainer)) return legacyRange
      const position = pointDocument.caretPositionFromPoint?.(x, y)
      if (!position || !body.contains(position.offsetNode)) return null
      const range = document.createRange()
      range.setStart(position.offsetNode, position.offset)
      range.collapse(true)
      return range
    }
    const setTextSelectionToPoint = (point: { x: number; y: number }) => {
      const gesture = textSelectionGesture
      if (!gesture) return false
      const end = rangeAtViewportPoint(point)
      if (!end) return false
      const range = document.createRange()
      try {
        range.setStart(gesture.anchor.startContainer, gesture.anchor.startOffset)
        range.setEnd(end.startContainer, end.startOffset)
      } catch {
        range.setStart(end.startContainer, end.startOffset)
        range.setEnd(gesture.anchor.startContainer, gesture.anchor.startOffset)
      }
      const selection = document.defaultView?.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)
      return true
    }
    const selectionScrollDelta = (point: { x: number; y: number }) => {
      const shell = shellRef.current
      if (!shell) return 0
      const shellBounds = shell.getBoundingClientRect()
      const dockTop = shell.querySelector<HTMLElement>('.preview-mobile-edit-dock')?.getBoundingClientRect().top
      const viewportTop = shellBounds.top + 36
      const viewportBottom = Math.min(shellBounds.bottom - 28, (dockTop ?? shellBounds.bottom) - 14)
      if (point.y < viewportTop) return -Math.max(5, Math.round((viewportTop - point.y) / 3))
      if (point.y > viewportBottom) return Math.max(5, Math.round((point.y - viewportBottom) / 3))
      return 0
    }
    const scheduleTextSelectionAutoScroll = () => {
      if (textSelectionAutoScrollFrame !== null) return
      const scroll = () => {
        textSelectionAutoScrollFrame = null
        const gesture = textSelectionGesture
        if (!gesture?.active || !gesture.point || !isMobileTextEditing()) return
        const delta = selectionScrollDelta(gesture.point)
        if (!delta) return
        const shell = shellRef.current
        if (!shell) return
        const previousTop = shell.scrollTop
        shell.scrollTop += delta
        if (shell.scrollTop === previousTop) return
        setTextSelectionToPoint(gesture.point)
        textSelectionAutoScrollFrame = window.requestAnimationFrame(scroll)
      }
      textSelectionAutoScrollFrame = window.requestAnimationFrame(scroll)
    }
    const clearTextSelectionGesture = () => {
      if (textSelectionPressTimer) clearTimeout(textSelectionPressTimer)
      textSelectionPressTimer = null
      if (textSelectionAutoScrollFrame !== null) window.cancelAnimationFrame(textSelectionAutoScrollFrame)
      textSelectionAutoScrollFrame = null
      textSelectionGesture = null
    }
    const handleTextSelectionTouchStart = (event: TouchEvent) => {
      if (!isMobileTextEditing() || event.touches.length !== 1 || selectedTextRange()) return
      const target = event.target && (event.target as Node).nodeType === Node.ELEMENT_NODE ? event.target as HTMLElement : null
      if (!target || target.closest('img, [data-preview-image-action], [data-preview-block-handle]')) return
      const point = viewportPointFromTouch(event.touches[0])
      if (!point) return
      const anchor = rangeAtViewportPoint(point)
      if (!anchor) return
      clearTextSelectionGesture()
      textSelectionGesture = { anchor, active: false, point: null, startPoint: point }
      textSelectionPressTimer = setTimeout(() => {
        if (textSelectionGesture) textSelectionGesture.active = true
        textSelectionPressTimer = null
      }, 360)
    }
    const handleTextSelectionTouchMove = (event: TouchEvent) => {
      const gesture = textSelectionGesture
      if (!gesture || !isMobileTextEditing() || event.touches.length !== 1) return
      const point = viewportPointFromTouch(event.touches[0])
      if (!point) return
      if (!gesture.active) {
        if (Math.hypot(point.x - gesture.startPoint.x, point.y - gesture.startPoint.y) > 8) clearTextSelectionGesture()
        return
      }
      if (event.cancelable) event.preventDefault()
      gesture.point = point
      setTextSelectionToPoint(point)
      scheduleTextSelectionAutoScroll()
    }
    const handleClick = (event: Event) => {
      // iframe 的节点属于另一个 window，不能使用父页面 HTMLElement 的 instanceof 判断。
      const target = event.target && (event.target as Node).nodeType === 1 ? (event.target as HTMLElement) : null
      if (!target || target.tagName === 'STYLE' || target.tagName === 'SCRIPT') return
      if (target.closest('[data-preview-image-action], [data-preview-block-handle]')) return
      const image = target.closest('img')
      if (image && modeRef.current === 'edit') {
        event.preventDefault()
        event.stopPropagation()
        if (compactRef.current && mobileEditTargetRef.current === 'block') {
          const block = findEditableBlock(image as HTMLElement, body)
          if (block) {
            document.defaultView?.getSelection()?.removeAllRanges()
            textSelectionRangeRef.current = null
            setTextToolbarPosition(null)
            selectEditableBlock(block, undefined, mobileBlockMultiSelectRef.current ? 'toggle' : 'replace')
          }
          return
        }
        clearBlockSelection()
        openImageAction(image as HTMLImageElement)
        return
      }
      if (modeRef.current === 'edit') {
        if (compactRef.current && mobileEditTargetRef.current === 'block') {
          const block = findEditableBlock(target, body)
          event.preventDefault()
          event.stopPropagation()
          if (!block) return
          document.defaultView?.getSelection()?.removeAllRanges()
          textSelectionRangeRef.current = null
          setTextToolbarPosition(null)
          selectEditableBlock(block, undefined, mobileBlockMultiSelectRef.current ? 'toggle' : 'replace')
          removeImageAction()
          return
        }
        // 移动端文字目标不触碰正文点击，让浏览器的长按、拖拽和原生
        // 选区手柄完整接管，避免与块编辑状态更新争夺同一个手势。
        if (compactRef.current) return
        // 直接编辑模式的普通单击必须交给 contenteditable 创建真实光标。
        // 块操作仍可通过 Alt+单击或左侧拖动柄进入，避免与文本插入点冲突。
        if ((event as MouseEvent).altKey) {
          const block = findEditableBlock(target, body)
          if (block) {
            event.preventDefault()
            event.stopPropagation()
            document.defaultView?.getSelection()?.removeAllRanges()
            setTextToolbarPosition(null)
            selectEditableBlock(block, event as MouseEvent)
            removeImageAction()
            return
          }
        }
        clearBlockSelection()
        removeImageAction()
        // Do not prevent the native click. The browser will set the caret and
        // the iframe's selectionchange listener will enable caret insertion.
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
    const handlePointerOver = (event: PointerEvent) => {
      if (modeRef.current !== 'edit' || compactRef.current) return
      const target = event.target && (event.target as Node).nodeType === 1 ? event.target as HTMLElement : null
      if (!target || target.closest('[data-preview-image-action], [data-preview-block-handle], [data-preview-block-drop-indicator]')) return
      const block = findEditableBlock(target, body)
      if (block) showBlockHandle(block)
    }
    const handlePointerOut = (event: PointerEvent) => {
      if (modeRef.current !== 'edit' || compactRef.current) return
      const related = event.relatedTarget && (event.relatedTarget as Node).nodeType === 1 ? event.relatedTarget as HTMLElement : null
      if (related?.closest('[data-preview-block-handle]')) return
      const nextBlock = related ? findEditableBlock(related, body) : null
      if (nextBlock) {
        showBlockHandle(nextBlock)
        return
      }
      scheduleBlockHandleHide()
    }
    const preventSelectionModeEdit = (event: Event) => {
      if (modeRef.current === 'select' || (compactRef.current && mobileEditTargetRef.current === 'block')) event.preventDefault()
    }
    const handleBeforeInput = (event: Event) => {
      if (modeRef.current === 'select' || (compactRef.current && mobileEditTargetRef.current === 'block')) {
        event.preventDefault()
        return
      }
      if (modeRef.current !== 'edit') return
      const inputEvent = event as InputEvent
      if (inputEvent.inputType === 'historyUndo' || inputEvent.inputType === 'historyRedo') return
      pendingInputHistoryRef.current = serialiseBody(body)
    }
    const handlePaste = (event: ClipboardEvent) => {
      if (modeRef.current === 'select' || (compactRef.current && mobileEditTargetRef.current === 'block')) {
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
      if ((!event.ctrlKey && !event.metaKey) || event.altKey) return
      const key = event.key.toLowerCase()
      const direction = key === 'y' || (key === 'z' && event.shiftKey)
        ? 'redo'
        : key === 'z'
          ? 'undo'
          : null
      if (!direction || !restoreEditHistory(direction)) return
      event.preventDefault()
      event.stopPropagation()
    }
    const handleBlockShortcut = (event: KeyboardEvent) => {
      if (modeRef.current !== 'edit' || event.key !== 'Escape' || selectedBlocksRef.current.length === 0) return
      clearBlockSelection()
      event.preventDefault()
      event.stopPropagation()
    }
    const handleDeleteShortcut = (event: KeyboardEvent) => {
      if (
        modeRef.current !== 'edit'
        || (event.key !== 'Delete' && event.key !== 'Backspace')
        || event.ctrlKey
        || event.metaKey
        || event.altKey
      ) return
      const image = activeImageRef.current
      if (image && deleteImage(image)) {
        event.preventDefault()
        event.stopPropagation()
        return
      }
      if (selectedBlocksRef.current.length === 0) return
      deleteSelectedBlocks()
      event.preventDefault()
      event.stopPropagation()
    }
    const handleInput = () => {
      if (modeRef.current !== 'edit') return
      const previousHtml = pendingInputHistoryRef.current
      pendingInputHistoryRef.current = null
      if (previousHtml !== null) recordEditChange(previousHtml)
      emitHtmlChange()
    }
    const handleSelectionChange = () => {
      scheduleTextToolbarUpdate()
      reportCaretAvailability()
    }
    body.addEventListener('click', handleClick, true)
    body.addEventListener('touchstart', handleTextSelectionTouchStart, { capture: true, passive: true })
    body.addEventListener('touchmove', handleTextSelectionTouchMove, { capture: true, passive: false })
    body.addEventListener('touchend', clearTextSelectionGesture, true)
    body.addEventListener('touchcancel', clearTextSelectionGesture, true)
    body.addEventListener('pointerover', handlePointerOver, true)
    body.addEventListener('pointerout', handlePointerOut, true)
    body.addEventListener('beforeinput', handleBeforeInput, true)
    body.addEventListener('paste', handlePaste, true)
    body.addEventListener('drop', preventSelectionModeEdit, true)
    body.addEventListener('keydown', handleHistoryShortcut, true)
    body.addEventListener('keydown', handleBlockShortcut, true)
    body.addEventListener('keydown', handleDeleteShortcut, true)
    body.addEventListener('keydown', preventSelectionModeEdit, true)
    body.addEventListener('input', handleInput)
    document.addEventListener('selectionchange', handleSelectionChange)
    syncHeight()
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(syncHeight)
      observer.observe(body)
      observer.observe(document.documentElement)
      resizeObserverRef.current = observer
    }
  }

  const textToolbarFontOptions = textToolbarFontFamily === MIXED_VALUE
    ? [{ value: MIXED_VALUE, label: '混合', disabled: true }, ...FONT_OPTIONS]
    : FONT_OPTIONS.some((option) => option.value === textToolbarFontFamily)
    ? FONT_OPTIONS
    : [{ value: textToolbarFontFamily, label: toolbarFontLabel(textToolbarFontFamily) }, ...FONT_OPTIONS]
  const textToolbarLineHeightOptions = textToolbarLineHeight === MIXED_VALUE
    ? [MIXED_VALUE, ...LINE_HEIGHT_OPTIONS]
    : LINE_HEIGHT_OPTIONS.includes(textToolbarLineHeight)
    ? LINE_HEIGHT_OPTIONS
    : [textToolbarLineHeight, ...LINE_HEIGHT_OPTIONS]
  const blockStyleFontOptions = blockStyle.fontFamily === MIXED_VALUE
    ? [{ value: MIXED_VALUE, label: '混合', disabled: true }, ...FONT_OPTIONS]
    : FONT_OPTIONS.some((option) => option.value === blockStyle.fontFamily)
    ? FONT_OPTIONS
    : [{ value: blockStyle.fontFamily, label: toolbarFontLabel(blockStyle.fontFamily) }, ...FONT_OPTIONS]
  const blockStyleLineHeightOptions = blockStyle.lineHeight === MIXED_VALUE
    ? [MIXED_VALUE, ...LINE_HEIGHT_OPTIONS]
    : LINE_HEIGHT_OPTIONS.includes(blockStyle.lineHeight)
    ? LINE_HEIGHT_OPTIONS
    : [blockStyle.lineHeight, ...LINE_HEIGHT_OPTIONS]
  const editableBlocks = (() => {
    const body = iframeRef.current?.contentDocument?.body
    return body ? selectedBlocks(body) : []
  })()
  const canReorderSelectedBlocks = selectionCanReorder(editableBlocks)
  const blockStyleContent = (
    <div className="preview-block-style-panel">
      <div className="preview-block-style-row">
        <span>对齐</span>
        <Tooltip title="左对齐"><Button aria-label="块左对齐" type={blockStyle.alignment === 'left' ? 'primary' : 'default'} size="small" icon={<AlignLeftOutlined />} onClick={() => applySelectedBlockStyle('text-align', 'left')} /></Tooltip>
        <Tooltip title="居中"><Button aria-label="块居中" type={blockStyle.alignment === 'center' ? 'primary' : 'default'} size="small" icon={<AlignCenterOutlined />} onClick={() => applySelectedBlockStyle('text-align', 'center')} /></Tooltip>
        <Tooltip title="右对齐"><Button aria-label="块右对齐" type={blockStyle.alignment === 'right' ? 'primary' : 'default'} size="small" icon={<AlignRightOutlined />} onClick={() => applySelectedBlockStyle('text-align', 'right')} /></Tooltip>
        <Tooltip title="两端对齐"><Button aria-label="块两端对齐" type={blockStyle.alignment === 'justify' ? 'primary' : 'default'} size="small" icon={<BarsOutlined />} onClick={() => applySelectedBlockStyle('text-align', 'justify')} /></Tooltip>
      </div>
      <label className="preview-block-style-field preview-block-style-field-font">
        <span>字体</span>
        <Select aria-label="块字体" size="small" value={blockStyle.fontFamily} options={blockStyleFontOptions} onChange={(value) => applySelectedBlockStyle('font-family', value === SYSTEM_FONT_FAMILY ? 'sans-serif' : value)} />
      </label>
      <label className="preview-block-style-field">
        <span>字号</span>
        <InputNumber aria-label="块字号" size="small" min={8} max={72} precision={0} value={blockStyle.fontSize} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockStyle('font-size', `${value}px`) }} />
      </label>
      <label className="preview-block-style-field preview-block-style-field-color">
        <span>文字</span>
        <ColorPicker aria-label="块文字颜色" size="small" value={blockStyle.color ?? undefined} onChangeComplete={(color) => applySelectedBlockStyle('color', color.toHexString())} />
      </label>
      <label className="preview-block-style-field">
        <span>行距</span>
        <Select aria-label="块行距" size="small" value={blockStyle.lineHeight} options={blockStyleLineHeightOptions.map((value) => ({ value, label: value === MIXED_VALUE ? '混合' : value }))} onChange={(value) => applySelectedBlockStyle('line-height', value)} />
      </label>
      <label className="preview-block-style-field">
        <span>首缩</span>
        <InputNumber aria-label="块首行缩进" size="small" min={0} max={10} step={0.1} precision={1} value={blockStyle.textIndent} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockStyle('text-indent', `${value}em`) }} />
      </label>
      <div className="preview-block-style-divider" />
      <label className="preview-block-style-field preview-block-style-field-color">
        <span>底色</span>
        <ColorPicker aria-label="块背景颜色" size="small" value={blockStyle.background ?? undefined} onChangeComplete={(color) => applySelectedBlockStyle('background-color', color.toHexString())} />
      </label>
      <label className="preview-block-style-field">
        <span>内距</span>
        <InputNumber aria-label="块内边距" size="small" min={0} max={160} precision={0} value={blockStyle.padding} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockStyle('padding', `${value}px`) }} />
      </label>
      <label className="preview-block-style-field">
        <span>外距</span>
        <InputNumber aria-label="块外边距" size="small" min={0} max={160} precision={0} value={blockStyle.margin} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockStyle('margin', `${value}px`) }} />
      </label>
      <label className="preview-block-style-field">
        <span>边框</span>
        <InputNumber aria-label="块边框宽度" size="small" min={0} max={20} precision={0} value={blockStyle.borderWidth} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockBorderWidth(value) }} />
      </label>
      <label className="preview-block-style-field">
        <span>圆角</span>
        <InputNumber aria-label="块圆角" size="small" min={0} max={80} precision={0} value={blockStyle.borderRadius} placeholder="混合" onChange={(value) => { if (typeof value === 'number') applySelectedBlockStyle('border-radius', `${value}px`) }} />
      </label>
    </div>
  )
  const textToolbarContent = (
    <>
      <div className="preview-text-toolbar-actions">
        <Tooltip title="拖动工具栏">
          <Button aria-label="拖动工具栏" className="preview-text-toolbar-drag" type="text" size="small" icon={<DragOutlined />} onPointerDown={beginTextToolbarDrag} />
        </Tooltip>
        <Tooltip title={textToolbarBold === null ? '加粗：混合' : '加粗'}>
          <Button aria-label="加粗" className={textToolbarBold === null ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarBold ? 'primary' : 'default'} size="small" icon={<BoldOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyTextCommand('bold')} />
        </Tooltip>
        <Tooltip title={textToolbarItalic === null ? '斜体：混合' : '斜体'}>
          <Button aria-label="斜体" className={textToolbarItalic === null ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarItalic ? 'primary' : 'default'} size="small" icon={<ItalicOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyTextCommand('italic')} />
        </Tooltip>
        <Tooltip title={textToolbarUnderline === null ? '下划线：混合' : '下划线'}>
          <Button aria-label="下划线" className={textToolbarUnderline === null ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarUnderline ? 'primary' : 'default'} size="small" icon={<UnderlineOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyTextCommand('underline')} />
        </Tooltip>
        <Tooltip title={textToolbarAlignment === MIXED_VALUE ? '对齐方式：混合' : '左对齐'}>
          <Button aria-label="左对齐" className={textToolbarAlignment === MIXED_VALUE ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarAlignment === 'left' ? 'primary' : 'default'} size="small" icon={<AlignLeftOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyBlockStyle('textAlign', 'left')} />
        </Tooltip>
        <Tooltip title={textToolbarAlignment === MIXED_VALUE ? '对齐方式：混合' : '居中'}>
          <Button aria-label="居中" className={textToolbarAlignment === MIXED_VALUE ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarAlignment === 'center' ? 'primary' : 'default'} size="small" icon={<AlignCenterOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyBlockStyle('textAlign', 'center')} />
        </Tooltip>
        <Tooltip title={textToolbarAlignment === MIXED_VALUE ? '对齐方式：混合' : '右对齐'}>
          <Button aria-label="右对齐" className={textToolbarAlignment === MIXED_VALUE ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarAlignment === 'right' ? 'primary' : 'default'} size="small" icon={<AlignRightOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyBlockStyle('textAlign', 'right')} />
        </Tooltip>
        <Tooltip title={textToolbarAlignment === MIXED_VALUE ? '对齐方式：混合' : '两端对齐'}>
          <Button aria-label="两端对齐" className={textToolbarAlignment === MIXED_VALUE ? 'preview-text-toolbar-mixed' : undefined} type={textToolbarAlignment === 'justify' ? 'primary' : 'default'} size="small" icon={<BarsOutlined />} onMouseDown={(event) => event.preventDefault()} onClick={() => applyBlockStyle('textAlign', 'justify')} />
        </Tooltip>
      </div>
      <div className="preview-text-toolbar-fields">
        <label className="preview-text-toolbar-field preview-text-toolbar-field-font">
          <span>字体</span>
          <Select aria-label="字体" className="preview-text-toolbar-font" size="small" value={textToolbarFontFamily} options={textToolbarFontOptions} onChange={(value) => { setTextToolbarFontFamily(value); applyTextCommand('fontName', value === SYSTEM_FONT_FAMILY ? 'sans-serif' : value) }} />
        </label>
        <label className="preview-text-toolbar-field">
          <span>字号</span>
          <InputNumber aria-label="字号" className="preview-text-toolbar-size" size="small" min={8} max={72} step={1} precision={0} value={textToolbarFontSize} placeholder="混合" onChange={(value) => { if (typeof value === 'number') { setTextToolbarFontSize(value); applyTextStyle('fontSize', `${value}px`) } }} />
        </label>
        <label className="preview-text-toolbar-field preview-text-toolbar-field-color">
          <span>颜色</span>
          <span onMouseDownCapture={preserveTextSelectionForFormatter}>
            <ColorPicker aria-label="文字颜色" size="small" value={textToolbarColor ?? undefined} onChangeComplete={(color) => { setTextToolbarColor(color.toHexString()); applyTextCommand('foreColor', color.toHexString()) }} />
          </span>
          {textToolbarColor === null && <span className="preview-text-toolbar-mixed-value">混合</span>}
        </label>
        <label className="preview-text-toolbar-field">
          <span>字距</span>
          <InputNumber aria-label="字间距" className="preview-text-toolbar-letter-spacing" size="small" min={-4} max={20} step={0.1} precision={1} value={textToolbarLetterSpacing} placeholder="混合" onChange={(value) => { if (typeof value === 'number') { setTextToolbarLetterSpacing(value); applyTextStyle('letterSpacing', `${value}px`) } }} />
        </label>
        <label className="preview-text-toolbar-field">
          <span>行距</span>
          <Select aria-label="行间距" className="preview-text-toolbar-line-height" size="small" value={textToolbarLineHeight} options={textToolbarLineHeightOptions.map((value) => ({ value, label: value === MIXED_VALUE ? '混合' : value === 'normal' ? '默认' : value }))} onChange={(value) => { setTextToolbarLineHeight(value); applyBlockStyle('lineHeight', value) }} />
        </label>
        <label className="preview-text-toolbar-field">
          <span>首缩</span>
          <InputNumber aria-label="首行缩进（字符）" className="preview-text-toolbar-margin" size="small" min={0} max={10} step={0.1} precision={1} value={textToolbarTextIndent} placeholder="混合" onChange={(value) => { if (typeof value === 'number') { setTextToolbarTextIndent(value); applyBlockStyle('textIndent', `${value}em`) } }} />
        </label>
        <label className="preview-text-toolbar-field">
          <span>左距</span>
          <InputNumber aria-label="左距" className="preview-text-toolbar-margin" size="small" min={0} max={160} step={1} precision={0} value={textToolbarMarginLeft} placeholder="混合" onChange={(value) => { if (typeof value === 'number') { setTextToolbarMarginLeft(value); applyBlockStyle('marginLeft', `${value}px`) } }} />
        </label>
        <label className="preview-text-toolbar-field">
          <span>右距</span>
          <InputNumber aria-label="右距" className="preview-text-toolbar-margin" size="small" min={0} max={160} step={1} precision={0} value={textToolbarMarginRight} placeholder="混合" onChange={(value) => { if (typeof value === 'number') { setTextToolbarMarginRight(value); applyBlockStyle('marginRight', `${value}px`) } }} />
        </label>
      </div>
    </>
  )

  return (
    <div className={`preview-shell preview-mode-${mode}${compact ? ' preview-shell-compact' : ''}`} ref={shellRef}>
      <div className="preview-device">
        {mode === 'select' && selectedElements.length > 0 && <div className="preview-selection-count">已选 {selectedElements.length}</div>}
        <iframe
          ref={iframeRef}
          title="排版预览"
          className="preview-iframe"
          sandbox={SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW}
          scrolling="no"
          srcDoc={srcDocRef.current}
          style={{ height: contentHeight, filter: `brightness(${brightness / 100})` }}
          onLoad={handleLoad}
        />
      </div>
      {!compact && blockToolbarPosition && blockSelectionCount > 0 && (
        <div
          ref={blockToolbarRef}
          className="preview-block-toolbar"
          style={{ top: blockToolbarPosition.top, left: blockToolbarPosition.left }}
        >
          <span className="preview-block-toolbar-count">{blockSelectionCount} 块</span>
          <div className="preview-block-toolbar-actions">
            <Tooltip title="上移"><Button aria-label="上移块" type="text" size="small" icon={<ArrowUpOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => moveSelectedBlocks('up')} /></Tooltip>
            <Tooltip title="下移"><Button aria-label="下移块" type="text" size="small" icon={<ArrowDownOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => moveSelectedBlocks('down')} /></Tooltip>
            <Tooltip title="复制"><Button aria-label="复制块" type="text" size="small" icon={<CopyOutlined />} onClick={duplicateSelectedBlocks} /></Tooltip>
            <Tooltip title="删除"><Button aria-label="删除块" danger type="text" size="small" icon={<DeleteOutlined />} onClick={deleteSelectedBlocks} /></Tooltip>
            <Tooltip title="在上方插入段落"><Button aria-label="在上方插入段落" className="preview-block-toolbar-insert" type="text" size="small" icon={<PlusOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => insertAdjacentParagraph('before')}>上方</Button></Tooltip>
            <Tooltip title="在下方插入段落"><Button aria-label="在下方插入段落" className="preview-block-toolbar-insert" type="text" size="small" icon={<PlusOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => insertAdjacentParagraph('after')}>下方</Button></Tooltip>
            <Tooltip title="在选块后插入图片"><Button aria-label="在选块后插入图片" type="text" size="small" icon={<PictureOutlined />} onClick={() => openImagePickerForInsert(true)} /></Tooltip>
            <Tooltip title="撤销"><Button aria-label="撤销块操作" type="text" size="small" icon={<UndoOutlined />} onClick={() => restoreEditHistory('undo')} /></Tooltip>
            <Tooltip title="重做"><Button aria-label="重做块操作" type="text" size="small" icon={<RedoOutlined />} onClick={() => restoreEditHistory('redo')} /></Tooltip>
            <Popover title="块样式" trigger="click" placement="bottom" content={blockStyleContent}>
              <Tooltip title="块样式"><Button aria-label="编辑块样式" type="text" size="small" icon={<BgColorsOutlined />} /></Tooltip>
            </Popover>
            <Tooltip title="交给 AI"><Button aria-label="将选块附加给 AI" type="primary" size="small" icon={<RobotOutlined />} onClick={attachSelectedBlocksToAi} /></Tooltip>
            <Tooltip title="收藏到组件库"><Button aria-label="收藏选中内容到组件库" type="text" size="small" icon={<StarOutlined />} onClick={collectSelectedBlocks} /></Tooltip>
          </div>
        </div>
      )}
      {!compact && textToolbarPosition && (
        <div
          ref={textToolbarRef}
          className="preview-text-toolbar"
          style={{ top: textToolbarPosition.top, left: textToolbarPosition.left }}
        >
          {textToolbarContent}
        </div>
      )}
      {compact && mode === 'edit' && (
        <div className="preview-mobile-edit-dock" aria-label="移动端直接编辑工具">
          <Segmented<MobileEditTarget>
            className="preview-mobile-edit-target"
            size="small"
            value={mobileEditTarget}
            onChange={(value) => changeMobileEditTarget(value)}
            options={[
              { label: '文字编辑', value: 'text' },
              { label: '选区块', value: 'block' },
            ]}
          />
          {mobileEditTarget === 'text' ? (
            <div className="preview-mobile-edit-actions">
              <Tooltip title="文字格式">
                <Button aria-label="文字格式" icon={<BgColorsOutlined />} disabled={!textToolbarPosition} onPointerDown={preserveMobileTextSelection} onClick={() => openMobileEditorPanel('text-style')} />
              </Tooltip>
              <Tooltip title="插入图片">
                <Button aria-label="插入图片" icon={<PictureOutlined />} onPointerDown={preserveMobileTextSelection} onClick={() => openImagePickerForInsert()} />
              </Tooltip>
              <Tooltip title="撤销">
                <Button aria-label="撤销" icon={<UndoOutlined />} disabled={editUndoStackRef.current.length === 0} onClick={() => restoreEditHistory('undo')} />
              </Tooltip>
              <Tooltip title="重做">
                <Button aria-label="重做" icon={<RedoOutlined />} disabled={editRedoStackRef.current.length === 0} onClick={() => restoreEditHistory('redo')} />
              </Tooltip>
            </div>
          ) : (
            <div className="preview-mobile-edit-actions preview-mobile-block-actions">
              <span className="preview-mobile-block-selection-count">{blockSelectionCount ? `已选 ${blockSelectionCount} 块` : '未选块'}</span>
              <Button className="preview-mobile-block-multi-select" size="small" type={mobileBlockMultiSelect ? 'primary' : 'default'} onClick={() => {
                const next = !mobileBlockMultiSelectRef.current
                mobileBlockMultiSelectRef.current = next
                setMobileBlockMultiSelect(next)
              }}>
                多选
              </Button>
              {blockSelectionCount > 0 && (
                <>
                  <Tooltip title="上移"><Button aria-label="上移块" type="text" icon={<ArrowUpOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => moveSelectedBlocks('up')} /></Tooltip>
                  <Tooltip title="下移"><Button aria-label="下移块" type="text" icon={<ArrowDownOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => moveSelectedBlocks('down')} /></Tooltip>
                  <Tooltip title="复制"><Button aria-label="复制块" type="text" icon={<CopyOutlined />} onClick={duplicateSelectedBlocks} /></Tooltip>
                  <Tooltip title="删除"><Button aria-label="删除块" danger type="text" icon={<DeleteOutlined />} onClick={deleteSelectedBlocks} /></Tooltip>
                  <Tooltip title="块样式"><Button aria-label="编辑块样式" type="text" icon={<BgColorsOutlined />} onClick={() => openMobileEditorPanel('block-style')} /></Tooltip>
                  <Tooltip title="更多块操作"><Button aria-label="更多块操作" type="text" icon={<MoreOutlined />} onClick={() => openMobileEditorPanel('block-actions')} /></Tooltip>
                </>
              )}
              <Button className="preview-mobile-block-finish" size="small" type="primary" icon={<CheckOutlined />} onClick={finishMobileBlockEditing}>完成</Button>
            </div>
          )}
        </div>
      )}
      {compact && mobileEditorPanel && (
        <Drawer
          className="preview-mobile-editor-drawer"
          title={mobileEditorPanel === 'text-style' ? '文字格式' : mobileEditorPanel === 'block-style' ? '块样式' : mobileEditorPanel === 'block-actions' ? '块操作' : '图片操作'}
          placement="bottom"
          size="min(72dvh, 640px)"
          open
          onClose={closeMobileEditorPanel}
        >
          {mobileEditorPanel === 'text-style' && <div className="preview-mobile-style-panel">{textToolbarContent}</div>}
          {mobileEditorPanel === 'block-style' && <div className="preview-mobile-style-panel">{blockStyleContent}</div>}
          {mobileEditorPanel === 'block-actions' && (
            <div className="preview-mobile-action-sheet">
              <Button icon={<PlusOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => insertAdjacentParagraph('before')}>在上方插入段落</Button>
              <Button icon={<PlusOutlined />} disabled={!canReorderSelectedBlocks} onClick={() => insertAdjacentParagraph('after')}>在下方插入段落</Button>
              <Button icon={<PictureOutlined />} onClick={() => openImagePickerForInsert(true)}>在选块后插入图片</Button>
              <Button icon={<RobotOutlined />} type="primary" onClick={attachSelectedBlocksToAi}>交给 AI</Button>
              <Button icon={<StarOutlined />} onClick={collectSelectedBlocks}>收藏到组件库</Button>
              <Button icon={<UndoOutlined />} disabled={editUndoStackRef.current.length === 0} onClick={() => restoreEditHistory('undo')}>撤销</Button>
              <Button icon={<RedoOutlined />} disabled={editRedoStackRef.current.length === 0} onClick={() => restoreEditHistory('redo')}>重做</Button>
            </div>
          )}
          {mobileEditorPanel === 'image-actions' && (
            <div className="preview-mobile-action-sheet">
              <Button icon={<PictureOutlined />} onClick={openImagePickerForReplacement}>替换图片</Button>
              <Button icon={<BgColorsOutlined />} onClick={() => {
                const image = activeImageRef.current
                if (image) openImageCrop(image)
              }}>裁剪图片</Button>
              <Button danger icon={<DeleteOutlined />} onClick={() => {
                const image = activeImageRef.current
                if (image) deleteImage(image)
              }}>删除图片</Button>
              <Button icon={<StarOutlined />} onClick={() => {
                const image = activeImageRef.current
                if (image) collectImage(image)
                closeMobileEditorPanel()
              }}>收藏到组件库</Button>
            </div>
          )}
        </Drawer>
      )}
      {imageCropSession && (
        <ImageCropModal
          open
          source={imageCropSession.source}
          initialRect={imageCropSession.initialRect}
          saving={croppingImage}
          onCancel={() => {
            if (croppingImage) return
            setImageCropSession(null)
            cropTargetRef.current = null
          }}
          onApply={(rect) => { void applyImageCrop(rect) }}
          onReset={imageCropSession.hasExistingCrop ? resetImageCrop : null}
        />
      )}
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
