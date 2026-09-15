import JSZip from 'jszip'
import { DOMParser } from '@xmldom/xmldom'
import type { CropRect } from '../utils/imageCrop'
import { wordSourceRectToCropRect } from '../utils/imageCrop'
import { hasRasterImageTransform, normalizeImageRotationDegrees, type RasterImageTransform } from '../utils/imageTransform'

export interface WordImageOccurrence {
  cropRect: CropRect | null
  relationshipId: string | null
  transform?: RasterImageTransform
  displaySize?: {
    widthPx: number
    heightPx: number
  }
}

function drawingTransform(drawing: Element): RasterImageTransform | undefined {
  const shapeProperties = descendantElements(drawing, 'spPr')[0]
  const transform = shapeProperties && descendantElements(shapeProperties, 'xfrm')[0]
  if (!transform) return undefined
  const rawRotation = Number(attribute(transform, 'rot'))
  const rotationDegrees = Number.isFinite(rawRotation) ? normalizeImageRotationDegrees(rawRotation / 60_000) : 0
  const flipHorizontal = ['1', 'true', 'on'].includes((attribute(transform, 'flipH') ?? '').toLowerCase())
  const flipVertical = ['1', 'true', 'on'].includes((attribute(transform, 'flipV') ?? '').toLowerCase())
  const result = {
    ...(rotationDegrees ? { rotationDegrees } : {}),
    ...(flipHorizontal ? { flipHorizontal } : {}),
    ...(flipVertical ? { flipVertical } : {}),
  }
  return hasRasterImageTransform(result) ? result : undefined
}

const WORD_DOCUMENT_PATH = 'word/document.xml'
const RELATIONSHIPS_NAMESPACE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

function localName(node: Node) {
  return (node as Element).localName || node.nodeName.split(':').at(-1) || ''
}

function childElements(node: Node) {
  return Array.from(node.childNodes).filter((child): child is Element => child.nodeType === child.ELEMENT_NODE)
}

function descendantElements(node: Node, name: string): Element[] {
  const elements: Element[] = []
  const visit = (current: Node) => {
    for (const child of childElements(current)) {
      if (localName(child) === name) elements.push(child)
      visit(child)
    }
  }
  visit(node)
  return elements
}

function attribute(element: Element, name: string, namespace?: string) {
  if (namespace) {
    const namespaced = element.getAttributeNS(namespace, name)
    if (namespaced) return namespaced
  }
  return element.getAttribute(name) || element.getAttribute(`r:${name}`) || null
}

function cropForBlip(blip: Element): CropRect | null {
  const parent = blip.parentNode
  if (!parent || localName(parent) !== 'blipFill') return null
  const sourceRect = childElements(parent).find((child) => localName(child) === 'srcRect')
  if (!sourceRect) return null
  return wordSourceRectToCropRect({
    left: attribute(sourceRect, 'l'),
    top: attribute(sourceRect, 't'),
    right: attribute(sourceRect, 'r'),
    bottom: attribute(sourceRect, 'b'),
  })
}

function displaySizeForDrawing(drawing: Element): WordImageOccurrence['displaySize'] {
  const container = descendantElements(drawing, 'inline')[0] ?? descendantElements(drawing, 'anchor')[0]
  if (!container) return undefined
  const extent = childElements(container).find((child) => localName(child) === 'extent')
  if (!extent) return undefined
  const cx = Number(attribute(extent, 'cx'))
  const cy = Number(attribute(extent, 'cy'))
  if (!Number.isFinite(cx) || !Number.isFinite(cy) || cx <= 0 || cy <= 0) return undefined
  // DrawingML stores dimensions in EMUs; CSS pixels use 96 DPI.
  return {
    widthPx: Math.round((cx * 96) / 914_400),
    heightPx: Math.round((cy * 96) / 914_400),
  }
}

function appendDrawingOccurrences(drawing: Element, occurrences: WordImageOccurrence[]) {
  const displaySize = displaySizeForDrawing(drawing)
  const transform = drawingTransform(drawing)
  for (const blip of descendantElements(drawing, 'blip')) {
    occurrences.push({
      cropRect: cropForBlip(blip),
      relationshipId: attribute(blip, 'embed', RELATIONSHIPS_NAMESPACE) ?? attribute(blip, 'link', RELATIONSHIPS_NAMESPACE),
      ...(transform ? { transform } : {}),
      ...(displaySize ? { displaySize } : {}),
    })
  }
}

function appendPictOccurrences(pict: Element, occurrences: WordImageOccurrence[]) {
  for (const imageData of descendantElements(pict, 'imagedata')) {
    occurrences.push({ cropRect: null, relationshipId: attribute(imageData, 'id', RELATIONSHIPS_NAMESPACE) })
  }
}

function readOccurrencesFromDocument(document: XMLDocument): WordImageOccurrence[] {
  const occurrences: WordImageOccurrence[] = []
  const visit = (node: Node) => {
    for (const child of childElements(node)) {
      const name = localName(child)
      if (name === 'drawing') {
        appendDrawingOccurrences(child, occurrences)
        continue
      }
      if (name === 'pict') {
        appendPictOccurrences(child, occurrences)
        continue
      }
      visit(child)
    }
  }
  visit(document)
  return occurrences
}

export async function readWordImageOccurrences(buffer: ArrayBuffer): Promise<WordImageOccurrence[]> {
  const zip = await JSZip.loadAsync(buffer)
  const documentFile = zip.file(WORD_DOCUMENT_PATH)
  if (!documentFile) return []
  const xml = await documentFile.async('text')
  const document = new DOMParser().parseFromString(xml, 'application/xml')
  if (document.getElementsByTagName('parsererror').length > 0) throw new Error('Word 文档 XML 无法解析')
  return readOccurrencesFromDocument(document)
}
