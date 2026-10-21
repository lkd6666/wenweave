import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { ClipboardEvent, DragEvent, KeyboardEvent, MouseEvent, PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import CloseOutlinedIcon from '@ant-design/icons-svg/es/asn/CloseOutlined'
import DownOutlinedIcon from '@ant-design/icons-svg/es/asn/DownOutlined'
import { Button, Image, Modal, Tooltip } from 'antd'
import { CloseOutlined } from '@ant-design/icons'
import type { ChatImageAttachment, SelectedElementContext, TemplateItem } from '../types'
import ElementRenderPreview from './ElementRenderPreview'

export interface PromptComposerHandle {
  getPayload: () => { message: string; references: SelectedElementContext[]; templateIds: number[]; imageIds: string[] }
  focus: () => void
}

interface PromptComposerProps {
  value: string
  references: SelectedElementContext[]
  templates: TemplateItem[]
  images?: ChatImageAttachment[]
  disabled?: boolean
  onChange: (value: string) => void
  onSubmit: () => void
  onRemoveReference: (index: number) => void
  onDuplicateReference: (index: number) => void
  onMoveReference: (fromIndex: number, toIndex: number) => void
  onRemoveTemplate: (templateId: number) => void
  onRemoveImage?: (image: ChatImageAttachment) => void
  onMoveImage?: (fromIndex: number, toIndex: number) => void
  acceptImages?: boolean
  onPasteImages?: (files: File[]) => void
}

const PLACEHOLDER = '输入排版指令…（Shift+Enter 换行，Enter 发送）'
const PREVIEW_CLOSE_DELAY_MS = 180
const EMPTY_IMAGES: ChatImageAttachment[] = []
const TOKEN_SELECTOR = '[data-reference-token], [data-template-token], [data-image-token], [data-image-group]'
const CLOSE_ICON = typeof CloseOutlinedIcon.icon === 'function'
  ? CloseOutlinedIcon.icon('currentColor', 'currentColor')
  : CloseOutlinedIcon.icon
const DOWN_ICON = typeof DownOutlinedIcon.icon === 'function'
  ? DownOutlinedIcon.icon('currentColor', 'currentColor')
  : DownOutlinedIcon.icon

function createIcon(definition: typeof CLOSE_ICON) {
  const namespace = 'http://www.w3.org/2000/svg'
  const icon = document.createElementNS(namespace, 'svg')
  Object.entries({ ...definition.attrs, width: '1em', height: '1em', fill: 'currentColor', 'aria-hidden': 'true' })
    .forEach(([name, value]) => icon.setAttribute(name, String(value)))
  for (const child of definition.children ?? []) {
    const path = document.createElementNS(namespace, child.tag)
    Object.entries(child.attrs).forEach(([name, value]) => path.setAttribute(name, String(value)))
    icon.append(path)
  }
  return icon
}

function escapeHtml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function isSameReference(left: SelectedElementContext, right: SelectedElementContext) {
  return left.selector === right.selector && left.tag_name === right.tag_name && left.html === right.html
}

/**
 * The editor DOM is only a presentation of the selected anchors. A click can
 * submit before React has inserted the corresponding token, so never allow a
 * temporarily stale DOM to erase references owned by the parent state.
 */
export function resolveOutgoingReferences(
  tokenReferences: SelectedElementContext[],
  selectedReferences: SelectedElementContext[],
): SelectedElementContext[] {
  if (tokenReferences.length !== selectedReferences.length) return selectedReferences
  const unmatchedSelected = [...selectedReferences]
  for (const reference of tokenReferences) {
    const matchIndex = unmatchedSelected.findIndex((selected) => isSameReference(reference, selected))
    if (matchIndex < 0) return selectedReferences
    unmatchedSelected.splice(matchIndex, 1)
  }
  return tokenReferences
}

/** 文本、元素和组件模板共用同一行流；令牌本身不可编辑，但可拖拽和移除。 */
const PromptComposer = forwardRef<PromptComposerHandle, PromptComposerProps>(function PromptComposer(
  { value, references, templates, images = EMPTY_IMAGES, disabled, onChange, onSubmit, onRemoveReference, onDuplicateReference, onMoveReference, onRemoveTemplate, onRemoveImage, onMoveImage, acceptImages = false, onPasteImages },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null)
  const lastEmittedValueRef = useRef('')
  const draggingTokenRef = useRef<HTMLElement | null>(null)
  const caretRef = useRef<Range | null>(null)
  const removedImageIdsRef = useRef(new Set<string>())
  const composingRef = useRef(false)
  const previewCloseTimerRef = useRef<number | null>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const [hoveredPreview, setHoveredPreview] = useState<{ context: SelectedElementContext; left: number; top: number; width: number } | null>(null)
  const [previewImage, setPreviewImage] = useState<ChatImageAttachment | null>(null)
  const [expandedImageIds, setExpandedImageIds] = useState<string[] | null>(null)

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

  const referenceTokenNodes = () => Array.from(editorRef.current?.querySelectorAll<HTMLElement>('[data-reference-token]') ?? [])
  const templateTokenNodes = () => Array.from(editorRef.current?.querySelectorAll<HTMLElement>('[data-template-token]') ?? [])
  const imageTokenNodes = () => Array.from(editorRef.current?.querySelectorAll<HTMLElement>('[data-image-token]') ?? [])

  const saveCaret = () => {
    const selection = window.getSelection()
    if (selection?.rangeCount && editorRef.current?.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      const range = selection.getRangeAt(0).cloneRange()
      const container = range.startContainer
      const token = (container instanceof HTMLElement ? container : container.parentElement)?.closest(TOKEN_SELECTOR)
      if (token) { range.setStartAfter(token); range.collapse(true) }
      caretRef.current = range
    }
  }

  const contextFromToken = (token: HTMLElement): SelectedElementContext | null => {
    try {
      return JSON.parse(decodeURIComponent(token.dataset.referenceContext ?? '')) as SelectedElementContext
    } catch {
      return null
    }
  }

  const templateFromToken = (token: HTMLElement): Pick<TemplateItem, 'id' | 'name'> | null => {
    try {
      const context = JSON.parse(decodeURIComponent(token.dataset.templateContext ?? '')) as Pick<TemplateItem, 'id' | 'name'>
      return typeof context.id === 'number' && typeof context.name === 'string' ? context : null
    } catch {
      return null
    }
  }

  const refreshLabels = () => {
    referenceTokenNodes().forEach((token, index) => {
      const label = token.querySelector<HTMLElement>('[data-reference-label]')
      const context = contextFromToken(token)
      const text = context ? `@元素${index + 1} <${context.tag_name}>` : ''
      if (label && label.textContent !== text) label.textContent = text
    })
    templateTokenNodes().forEach((token, index) => {
      const label = token.querySelector<HTMLElement>('[data-template-label]')
      const template = templateFromToken(token)
      const text = template ? `@组件${index + 1} <${template.name}>` : ''
      if (label && label.textContent !== text) label.textContent = text
    })
    imageTokenNodes().forEach((token, index) => {
      const label = token.querySelector<HTMLElement>('[data-image-label]')
      const text = `@图片${index + 1}`
      if (label && label.textContent !== text) label.textContent = text
    })
    editorRef.current?.querySelectorAll<HTMLElement>('[data-image-group]').forEach((group) => {
      const tokens = Array.from(group.querySelectorAll<HTMLElement>('[data-image-token]'))
      const first = tokens[0]?.querySelector('[data-image-label]')?.textContent ?? ''
      const last = tokens.at(-1)?.querySelector('[data-image-label]')?.textContent?.replace('@图片', '') ?? ''
      const label = group.querySelector('[data-image-group-label]')!
      const text = `${first}-${last} · ${tokens.length} 张`
      if (label.textContent !== text) label.textContent = text
      const open = group.querySelector<HTMLButtonElement>('[data-image-group-action="open"]')!
      open.setAttribute('aria-label', `查看 ${tokens.length} 张引用图片`)
      const thumbnails = group.querySelector<HTMLElement>('[data-image-group-thumbnails]')!
      const previewImages = tokens.slice(0, 3).map((token) => token.querySelector('img')!)
      const previewKey = JSON.stringify(previewImages.map((image) => image.getAttribute('src')))
      if (thumbnails.dataset.previewKey !== previewKey) {
        thumbnails.replaceChildren(...previewImages.map((image) => {
          const thumbnail = image.cloneNode() as HTMLImageElement
          thumbnail.removeAttribute('data-image-preview')
          thumbnail.alt = ''
          return thumbnail
        }))
        thumbnails.dataset.previewKey = previewKey
      }
    })
  }

  const groupAdjacentImages = () => {
    const editor = editorRef.current
    if (!editor || composingRef.current) return
    const runs: Array<{ parent: HTMLElement; nodes: Node[]; tokens: HTMLElement[]; existing?: HTMLElement }> = []
    const collectRuns = (parent: HTMLElement) => {
      let nodes: Node[] = []
      const collect = () => {
        const imageNodes = nodes.filter((node): node is HTMLElement => node instanceof HTMLElement)
        const tokens = imageNodes.flatMap((node) => node.dataset.imageToken !== undefined
          ? [node] : Array.from(node.querySelectorAll<HTMLElement>('[data-image-token]')))
        const existing = imageNodes.find((node) => node.dataset.imageGroup !== undefined)
        if ((existing && tokens.length < 2) || (tokens.length >= 2 && (imageNodes.length > 1 || !existing))) {
          runs.push({ parent, nodes, tokens, existing })
        }
        nodes = []
      }
      for (const node of Array.from(parent.childNodes)) {
        if (node instanceof HTMLElement && node.matches('[data-image-token], [data-image-group]')
          || node.nodeType === Node.TEXT_NODE && !node.textContent?.replace(/\u200b/g, '')) {
          nodes.push(node)
        } else {
          collect()
          if (node instanceof HTMLElement && !node.matches(TOKEN_SELECTOR)) collectRuns(node)
        }
      }
      collect()
    }
    collectRuns(editor)
    if (!runs.length) return
    const selection = window.getSelection()
    const selectedRange = selection?.rangeCount ? selection.getRangeAt(0) : null
    const range = selectedRange && editor.contains(selectedRange.commonAncestorContainer) ? selectedRange : caretRef.current
    // A zero-width anchor keeps Chromium IME input after the atomic group.
    const marker = document.createTextNode('\u200b')
    if (range?.collapsed && editor.contains(range.commonAncestorContainer)) range.cloneRange().insertNode(marker)
    for (const { parent, nodes, tokens, existing } of runs) {
      if (tokens.length < 2) {
        if (existing) existing.replaceWith(...tokens)
      } else {
        const group = existing ?? document.createElement('span')
        if (!existing) {
          group.className = 'prompt-image-group'
          group.dataset.imageGroup = 'true'
          group.contentEditable = 'false'
          group.draggable = true
          const items = document.createElement('span')
          items.dataset.imageGroupItems = 'true'
          items.hidden = true
          const open = document.createElement('button')
          open.type = 'button'
          open.className = 'prompt-image-group-open'
          open.dataset.imageGroupAction = 'open'
          open.title = '查看引用图片'
          const thumbnails = document.createElement('span')
          thumbnails.className = 'prompt-image-group-thumbnails'
          thumbnails.dataset.imageGroupThumbnails = 'true'
          const label = document.createElement('span')
          label.dataset.imageGroupLabel = 'true'
          open.append(thumbnails, label, createIcon(DOWN_ICON))
          const remove = document.createElement('button')
          remove.type = 'button'
          remove.dataset.imageGroupAction = 'remove'
          remove.setAttribute('aria-label', '移除这组图片')
          remove.title = '移除这组图片'
          remove.append(createIcon(CLOSE_ICON))
          group.append(items, open, remove)
        }
        parent.insertBefore(group, nodes[0]!)
        group.querySelector('[data-image-group-items]')!.append(...tokens)
        nodes.forEach((node) => { if (node !== group && node.parentNode === parent) parent.removeChild(node) })
      }
    }
    if (editor.contains(marker)) {
      const restored = document.createRange()
      restored.setStart(marker, 1)
      restored.collapse(true)
      caretRef.current = restored.cloneRange()
      if (document.activeElement === editor) {
        selection?.removeAllRanges()
        selection?.addRange(restored)
      }
    }
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

  const createTemplateToken = (template: TemplateItem) => {
    const token = document.createElement('span')
    token.className = 'prompt-template-token'
    token.setAttribute('contenteditable', 'false')
    token.draggable = true
    token.dataset.templateToken = 'true'
    token.dataset.templateContext = encodeURIComponent(JSON.stringify({ id: template.id, name: template.name }))
    token.innerHTML = `<span class="prompt-template-label" data-template-label>@组件 &lt;${escapeHtml(template.name)}&gt;</span><button type="button" data-template-action="remove" aria-label="移除组件" title="移除组件">x</button>`
    return token
  }

  const createImageToken = (image: ChatImageAttachment) => {
    const token = document.createElement('span')
    token.className = 'prompt-image-token'
    token.contentEditable = 'false'
    token.draggable = true
    token.dataset.imageToken = image.id
    token.title = image.filename
    const thumbnail = document.createElement('img')
    thumbnail.src = image.preview_url
    thumbnail.alt = image.filename
    thumbnail.draggable = false
    thumbnail.dataset.imagePreview = 'true'
    thumbnail.title = '预览图片'
    const label = document.createElement('span')
    label.dataset.imageLabel = 'true'
    const name = document.createElement('span')
    name.className = 'prompt-image-name'
    name.textContent = image.filename
    const remove = document.createElement('button')
    remove.type = 'button'
    remove.dataset.imageAction = 'remove'
    remove.setAttribute('aria-label', `移除图片 ${image.filename}`)
    remove.title = '移除图片'
    remove.append(createIcon(CLOSE_ICON))
    token.append(thumbnail, label, name, remove)
    return token
  }

  const appendTokenAtCaret = (token: HTMLElement) => {
    const editor = editorRef.current
    if (!editor) return
    const selection = window.getSelection()
    const activeRange = selection?.rangeCount ? selection.getRangeAt(0) : null
    const range = activeRange && editor.contains(activeRange.commonAncestorContainer) ? activeRange : caretRef.current
    if (range && editor.contains(range.commonAncestorContainer)) {
      const container = range.startContainer
      const parentToken = (container instanceof HTMLElement ? container : container.parentElement)?.closest(TOKEN_SELECTOR)
      if (parentToken) { range.setStartAfter(parentToken); range.collapse(true) }
      range.insertNode(token)
      range.setStartAfter(token)
      range.collapse(true)
      caretRef.current = range.cloneRange()
      if (document.activeElement === editor) {
        selection?.removeAllRanges()
        selection?.addRange(range)
      }
    } else {
      editor.append(token)
    }
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
      saveCaret()
    }
  }

  const payload = () => {
    const editor = editorRef.current
    const references: SelectedElementContext[] = []
    const templateIds: number[] = []
    const imageIds: string[] = []
    if (!editor) return { message: '', references, templateIds, imageIds }
    const readNode = (node: Node): string => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent?.replace(/\u200b/g, '') ?? ''
      if (node.nodeType !== Node.ELEMENT_NODE) return ''
      const element = node as HTMLElement
      if (element.dataset.imageGroup !== undefined) {
        return Array.from(element.querySelectorAll('[data-image-token]')).map(readNode).join('')
      }
      if (element.dataset.referenceToken !== undefined) {
        const context = contextFromToken(element)
        if (!context) return ''
        references.push(context)
        return `@元素${references.length}`
      }
      if (element.dataset.templateToken !== undefined) {
        const template = templateFromToken(element)
        if (!template) return ''
        templateIds.push(template.id)
        return `@组件${templateIds.length}`
      }
      if (element.dataset.imageToken !== undefined) {
        imageIds.push(element.dataset.imageToken)
        return `@图片${imageIds.length}`
      }
      if (element.tagName === 'BR') return '\n'
      const text = Array.from(element.childNodes).map(readNode).join('')
      return /^(DIV|P)$/.test(element.tagName) ? `${text}\n` : text
    }
    const message = Array.from(editor.childNodes).map(readNode).join('').replace(/[ \t]+\n/g, '\n').trim()
    return { message, references, templateIds, imageIds }
  }

  const emitChange = () => {
    saveCaret()
    groupAdjacentImages()
    refreshLabels()
    saveCaret()
    const current = payload()
    const presentImageIds = new Set(current.imageIds)
    images.forEach((image) => {
      if (!presentImageIds.has(image.id) && !removedImageIdsRef.current.has(image.id)) {
        removedImageIdsRef.current.add(image.id)
        onRemoveImage?.(image)
      }
    })
    const nextValue = current.message
    lastEmittedValueRef.current = nextValue
    onChange(nextValue)
  }

  useImperativeHandle(ref, () => ({
    getPayload: payload,
    focus: () => editorRef.current?.focus(),
  }))

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    if (value !== lastEmittedValueRef.current) {
      const fragments = value.split(/(@(?:元素|组件|图片)\d+)/g)
      const nodes: Node[] = []
      for (const fragment of fragments) {
        const matched = /^@(元素|组件|图片)(\d+)$/.exec(fragment)
        const index = matched ? Number(matched[2]) - 1 : -1
        const context = matched?.[1] === '元素' ? references[index] : undefined
        const template = matched?.[1] === '组件' ? templates[index] : undefined
        const image = matched?.[1] === '图片' ? images[index] : undefined
        nodes.push(context ? createToken(context) : template ? createTemplateToken(template) : image ? createImageToken(image) : document.createTextNode(fragment))
      }
      editor.replaceChildren(...nodes)
      caretRef.current = null
      lastEmittedValueRef.current = value
    }
    const unmatchedReferences = [...references]
    referenceTokenNodes().forEach((token) => {
      const context = contextFromToken(token)
      const index = context ? unmatchedReferences.findIndex((item) => isSameReference(item, context)) : -1
      if (index < 0) token.remove()
      else unmatchedReferences.splice(index, 1)
    })
    unmatchedReferences.forEach((reference) => appendTokenAtCaret(createToken(reference)))
    const templateIds = new Set(templates.map((template) => template.id))
    templateTokenNodes().forEach((token) => {
      const template = templateFromToken(token)
      if (!template || !templateIds.has(template.id)) token.remove()
    })
    const presentTemplates = new Set(templateTokenNodes().map(templateFromToken).flatMap((template) => template ? [template.id] : []))
    templates.filter((template) => !presentTemplates.has(template.id)).forEach((template) => appendTokenAtCaret(createTemplateToken(template)))
    const imageIds = new Set(images.map((image) => image.id))
    imageTokenNodes().forEach((token) => {
      const image = images.find((image) => image.id === token.dataset.imageToken)
      if (!image || removedImageIdsRef.current.has(image.id)) token.remove()
      else {
        const thumbnail = token.querySelector('img')!
        if (thumbnail.getAttribute('src') !== image.preview_url) thumbnail.src = image.preview_url
      }
    })
    for (const id of removedImageIdsRef.current) {
      if (!imageIds.has(id)) removedImageIdsRef.current.delete(id)
    }
    const presentImages = new Set(imageTokenNodes().map((token) => token.dataset.imageToken))
    images.filter((image) => !presentImages.has(image.id) && !removedImageIdsRef.current.has(image.id)).forEach((image) => appendTokenAtCaret(createImageToken(image)))
    groupAdjacentImages()
    refreshLabels()
    const nextValue = payload().message
    if (nextValue !== value) {
      lastEmittedValueRef.current = nextValue
      onChange(nextValue)
    }
  }, [value, references, templates, images, onChange])

  useEffect(() => {
    document.addEventListener('selectionchange', saveCaret)
    return () => document.removeEventListener('selectionchange', saveCaret)
  }, [])

  useEffect(() => {
    if (hoveredPreview && !references.some((reference) => isSameReference(reference, hoveredPreview.context))) {
      closePreview()
    }
  }, [hoveredPreview, references])

  useEffect(() => () => cancelPreviewClose(), [])

  const indexOfToken = (token: HTMLElement) => referenceTokenNodes().indexOf(token)

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (disabled) return
    const target = event.target as HTMLElement
    const groupAction = target.closest<HTMLElement>('[data-image-group-action]')
    const group = target.closest<HTMLElement>('[data-image-group]')
    if (group && groupAction) {
      event.preventDefault()
      event.stopPropagation()
      if (groupAction.dataset.imageGroupAction === 'open') {
        setExpandedImageIds(Array.from(group.querySelectorAll<HTMLElement>('[data-image-token]')).map((token) => token.dataset.imageToken!))
      } else {
        group.remove()
        emitChange()
      }
      return
    }
    const imageToken = target.closest<HTMLElement>('[data-image-token]')
    if (imageToken) {
      const image = images.find((image) => image.id === imageToken.dataset.imageToken)
      if (image && target.closest('[data-image-preview]')) setPreviewImage(image)
      if (image && target.closest('[data-image-action="remove"]')) {
        event.preventDefault()
        event.stopPropagation()
        imageToken.remove()
        refreshLabels()
        emitChange()
      }
      return
    }
    const actionButton = target.closest<HTMLButtonElement>('[data-reference-action], [data-template-action]')
    const referenceToken = target.closest<HTMLElement>('[data-reference-token]')
    const templateToken = target.closest<HTMLElement>('[data-template-token]')
    if (!actionButton || (!referenceToken && !templateToken)) return
    event.preventDefault()
    event.stopPropagation()
    if (referenceToken) {
      const index = indexOfToken(referenceToken)
      if (index < 0) return
      if (actionButton.dataset.referenceAction === 'duplicate') {
        const copy = referenceToken.cloneNode(true) as HTMLElement
        referenceToken.insertAdjacentElement('afterend', copy)
        refreshLabels()
        onDuplicateReference(index)
        emitChange()
      } else {
        closePreview()
        referenceToken.remove()
        refreshLabels()
        onRemoveReference(index)
        emitChange()
      }
      return
    }
    if (templateToken && actionButton.dataset.templateAction === 'remove') {
      const template = templateFromToken(templateToken)
      if (!template) return
      templateToken.remove()
      refreshLabels()
      onRemoveTemplate(template.id)
      emitChange()
    }
  }

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    const token = (event.target as HTMLElement).closest<HTMLElement>(TOKEN_SELECTOR)
    if (disabled) { event.preventDefault(); return }
    if (!token) return
    draggingTokenRef.current = token
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', '')
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    const editor = editorRef.current
    const dragged = draggingTokenRef.current
    if (!editor || !dragged) return
    event.preventDefault()
    const sourceIndex = indexOfToken(dragged)
    const previousImageIds = imageTokenNodes().map((token) => token.dataset.imageToken!)
    const target = (event.target as HTMLElement).closest<HTMLElement>(TOKEN_SELECTOR)
    if (target && target !== dragged) {
      const placeAfter = event.clientX > target.getBoundingClientRect().left + target.getBoundingClientRect().width / 2
      target.insertAdjacentElement(placeAfter ? 'afterend' : 'beforebegin', dragged)
    } else if (!target) {
      const caretRange = document.caretRangeFromPoint?.(event.clientX, event.clientY)
      if (caretRange && editor.contains(caretRange.startContainer)) {
        caretRange.insertNode(dragged)
      } else {
        editor.append(dragged)
      }
    }
    const destinationIndex = indexOfToken(dragged)
    if (sourceIndex >= 0 && destinationIndex >= 0 && sourceIndex !== destinationIndex) onMoveReference(sourceIndex, destinationIndex)
    imageTokenNodes().forEach((token, destinationIndex) => {
      const sourceIndex = previousImageIds.indexOf(token.dataset.imageToken!)
      if (sourceIndex >= 0 && sourceIndex !== destinationIndex) {
        previousImageIds.splice(destinationIndex, 0, previousImageIds.splice(sourceIndex, 1)[0]!)
        onMoveImage?.(sourceIndex, destinationIndex)
      }
    })
    draggingTokenRef.current = null
    refreshLabels()
    emitChange()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit()
    }
  }

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    if (disabled) return
    const imageFiles = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null)
    event.preventDefault()
    if (imageFiles.length > 0 && acceptImages) {
      onPasteImages?.(imageFiles)
    }
    insertPlainTextAtCaret(event.clipboardData.getData('text/plain'))
    saveCaret()
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

  const expandedImages = (expandedImageIds ?? []).flatMap((id) => {
    const image = images.find((image) => image.id === id)
    return image && !removedImageIdsRef.current.has(id) ? [image] : []
  })

  const removeExpandedImage = (image: ChatImageAttachment) => {
    imageTokenNodes().filter((token) => token.dataset.imageToken === image.id).forEach((token) => token.remove())
    emitChange()
    setExpandedImageIds((ids) => ids?.filter((id) => id !== image.id) ?? null)
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
        onCompositionStart={() => { composingRef.current = true }}
        onCompositionEnd={() => { composingRef.current = false; emitChange() }}
        onBlur={saveCaret}
        onKeyUp={saveCaret}
        onMouseUp={saveCaret}
        onClick={handleClick}
        onDragStart={handleDragStart}
        onDragEnd={() => { draggingTokenRef.current = null }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
      />
      <Modal title={`引用图片（${expandedImages.length} 张）`} open={expandedImages.length > 0} footer={null} width={620} onCancel={() => setExpandedImageIds(null)}>
        <div className="prompt-image-group-list">
          {expandedImages.map((image) => <div className="prompt-image-group-item" key={image.id}>
            <button type="button" className="prompt-image-group-preview" aria-label={`预览图片 ${image.filename}`} title="预览图片" onClick={() => setPreviewImage(image)}>
              <img src={image.preview_url} alt={image.filename} loading="lazy" />
            </button>
            <div className="prompt-image-group-meta">
              <span>@图片{imageTokenNodes().findIndex((token) => token.dataset.imageToken === image.id) + 1}</span>
              <strong title={image.filename}>{image.filename}</strong>
            </div>
            <Tooltip title="移除图片" placement="left"><Button type="text" size="small" disabled={disabled} aria-label={`移除图片 ${image.filename}`} icon={<CloseOutlined />} onClick={() => removeExpandedImage(image)} /></Tooltip>
          </div>)}
        </div>
      </Modal>
      {previewImage && <div hidden>
        <Image src={previewImage.preview_url} alt={previewImage.filename} preview={{ open: true, onOpenChange: (open) => { if (!open) setPreviewImage(null) } }} />
      </div>}
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
