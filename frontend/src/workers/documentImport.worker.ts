import type { ParsedImport, ParsedImportAsset } from '../imports/types'
import { readWordImageOccurrences } from '../imports/docxCropMetadata'
import { applyWordImportFormatting, readWordImportFormatting } from '../imports/wordImportFormatting'
import { cropImageBlob, isFullCropRect, serializeCropRect } from '../utils/imageCrop'
import {
  buildPdfTextBlocks,
  createPdfImageBlock,
  orderPdfBlocks,
  renderPdfBlocks,
  shouldRasterizePdfPage,
  type PdfTextItemLike,
  type PdfTextStyleLike,
} from '../imports/pdfLayout'
import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

type ParseMessage = {
  type: 'parse'
  filename: string
  extension: 'pdf' | 'docx'
  buffer: ArrayBuffer
}

type PdfImageObject = {
  width?: number
  height?: number
  data?: Uint8ClampedArray | Uint8Array
  bitmap?: ImageBitmap
}

const extensionForContentType = (contentType: string) => {
  const type = contentType.toLowerCase().split(';', 1)[0]
  if (type === 'image/jpeg') return 'jpg'
  if (type === 'image/svg+xml') return 'svg'
  if (type === 'image/gif') return 'gif'
  if (type === 'image/webp') return 'webp'
  if (type === 'image/avif') return 'avif'
  if (type === 'image/bmp') return 'bmp'
  return 'png'
}

const base64Bytes = (base64: string) => {
  const decoded = atob(base64)
  const bytes = new Uint8Array(decoded.length)
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index)
  return bytes
}

const report = (percent: number, detail: string) => {
  postMessage({ type: 'progress', progress: { stage: percent < 20 ? 'reading' : percent < 90 ? 'parsing' : 'extracting', percent, detail } })
}

function wordImageStyle(occurrence: Awaited<ReturnType<typeof readWordImageOccurrences>>[number] | undefined): string {
  const styles = ['max-width:100%', 'height:auto', 'box-sizing:border-box']
  if (occurrence?.displaySize?.widthPx) styles.unshift(`width:${occurrence.displaySize.widthPx}px`)
  return `${styles.join(';')};`
}

async function parseWord(buffer: ArrayBuffer): Promise<ParsedImport> {
  report(16, '正在读取 Word 正文与图片…')
  const [occurrences, formatting, imported] = await Promise.all([
    readWordImageOccurrences(buffer),
    readWordImportFormatting(buffer),
    import('mammoth'),
  ])
  const mammoth = (imported.default ?? imported) as any
  const assets: ParsedImportAsset[] = []
  const sourceAssetsByRelationship = new Map<string, ParsedImportAsset>()
  const warnings: string[] = []
  let imageIndex = 0
  const result = await mammoth.convertToHtml(
    { arrayBuffer: buffer },
    {
      convertImage: mammoth.images.inline(async (image: any) => {
        const instanceNumber = imageIndex + 1
        const occurrence = occurrences[imageIndex]
        imageIndex += 1
        const contentType = String(image.contentType || 'image/png').toLowerCase()
        const blob = new Blob([base64Bytes(await image.read('base64'))], { type: contentType })
        const sourceKey = occurrence?.relationshipId ?? `instance-${instanceNumber}`
        let sourceAsset = sourceAssetsByRelationship.get(sourceKey)
        if (!sourceAsset) {
          const clientId = `word-source-${sourceAssetsByRelationship.size + 1}`
          sourceAsset = {
            clientId,
            filename: `${clientId}.${extensionForContentType(contentType)}`,
            contentType,
            blob,
          }
          sourceAssetsByRelationship.set(sourceKey, sourceAsset)
          assets.push(sourceAsset)
        }
        const sourceUrl = `direct-import://asset/${sourceAsset.clientId}`
        const cropRect = occurrence?.cropRect
        const style = wordImageStyle(occurrence)
        if (!cropRect || isFullCropRect(cropRect)) {
          report(Math.min(88, 30 + imageIndex * 3), `已提取 ${imageIndex} 张 Word 图片…`)
          return { src: sourceUrl, style }
        }

        try {
          const croppedBlob = await cropImageBlob(blob, cropRect)
          const clientId = `word-crop-${instanceNumber}`
          const croppedContentType = croppedBlob.type || 'image/png'
          assets.push({
            clientId,
            filename: `${clientId}.${extensionForContentType(croppedContentType)}`,
            contentType: croppedContentType,
            blob: croppedBlob,
          })
          report(Math.min(88, 30 + imageIndex * 3), `已还原 ${imageIndex} 张 Word 图片的裁剪…`)
          return {
            src: `direct-import://asset/${clientId}`,
            style,
            'data-crop-source': sourceUrl,
            'data-crop-rect': serializeCropRect(cropRect),
          }
        } catch (error) {
          const detail = error instanceof Error ? error.message : '无法还原裁剪'
          warnings.push(`第 ${instanceNumber} 张 Word 图片未还原裁剪：${detail}`)
          report(Math.min(88, 30 + imageIndex * 3), `已提取 ${imageIndex} 张 Word 图片…`)
          return { src: sourceUrl, style }
        }
      }),
    },
  )
  if (occurrences.length !== imageIndex) {
    warnings.push('部分 Word 图片无法与裁剪信息对应，已按原图导入。')
  }
  report(92, 'Word 解析完成，正在准备上传…')
  return { html: applyWordImportFormatting(result.value || '<p>（Word 未提取到正文内容）</p>', formatting), assets, warnings }
}

function multiplyMatrix(left: number[], right: number[]) {
  return [
    left[0] * right[0] + left[2] * right[1],
    left[1] * right[0] + left[3] * right[1],
    left[0] * right[2] + left[2] * right[3],
    left[1] * right[2] + left[3] * right[3],
    left[0] * right[4] + left[2] * right[5] + left[4],
    left[1] * right[4] + left[3] * right[5] + left[5],
  ]
}

async function resolvePdfObject(objects: { get: (id: string, callback?: (value: unknown) => void) => unknown }, id: string) {
  try {
    const value = objects.get(id)
    if (value !== undefined) return value
  } catch {
    // PDF.js throws while the image object is still resolving; use its callback API below.
  }
  return new Promise<unknown>((resolve) => objects.get(id, resolve))
}

async function imageObjectToPng(value: unknown): Promise<Blob | null> {
  const image = value as PdfImageObject
  if (image.bitmap) {
    const canvas = new OffscreenCanvas(image.bitmap.width, image.bitmap.height)
    canvas.getContext('2d')?.drawImage(image.bitmap, 0, 0)
    return canvas.convertToBlob({ type: 'image/png' })
  }
  if (!image.width || !image.height || !image.data) return null
  const source = image.data
  const expectedRgbaLength = image.width * image.height * 4
  let rgba: Uint8ClampedArray
  if (source.length === expectedRgbaLength) {
    rgba = new Uint8ClampedArray(source)
  } else if (source.length === image.width * image.height * 3) {
    rgba = new Uint8ClampedArray(expectedRgbaLength)
    for (let index = 0; index < image.width * image.height; index += 1) {
      const sourceOffset = index * 3
      const targetOffset = index * 4
      rgba[targetOffset] = source[sourceOffset]
      rgba[targetOffset + 1] = source[sourceOffset + 1]
      rgba[targetOffset + 2] = source[sourceOffset + 2]
      rgba[targetOffset + 3] = 255
    }
  } else if (source.length === image.width * image.height) {
    rgba = new Uint8ClampedArray(expectedRgbaLength)
    for (let index = 0; index < source.length; index += 1) {
      const offset = index * 4
      rgba[offset] = source[index]
      rgba[offset + 1] = source[index]
      rgba[offset + 2] = source[index]
      rgba[offset + 3] = 255
    }
  } else {
    return null
  }
  const canvas = new OffscreenCanvas(image.width, image.height)
  const context = canvas.getContext('2d')
  if (!context) return null
  const imageData = context.createImageData(image.width, image.height)
  imageData.data.set(rgba)
  context.putImageData(imageData, 0, 0)
  return canvas.convertToBlob({ type: 'image/png' })
}

async function renderPdfPageToPng(page: { getViewport: (options: { scale: number }) => { width: number; height: number }; render: (options: any) => { promise: Promise<unknown> } }, width: number, height: number) {
  const scale = Math.max(0.75, Math.min(1.5, Math.sqrt(2400000 / Math.max(1, width * height))))
  const viewport = page.getViewport({ scale })
  const canvas = new OffscreenCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height))
  const context = canvas.getContext('2d')
  if (!context) return null
  await page.render({ canvasContext: context, viewport }).promise
  return canvas.convertToBlob({ type: 'image/png' })
}

async function parsePdf(buffer: ArrayBuffer): Promise<ParsedImport> {
  report(16, '正在读取 PDF 正文与图片…')
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  // The parser runs in our own worker. PDF.js falls back to its in-process worker there,
  // which still needs an explicit Vite-managed module URL.
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  const task = pdfjs.getDocument({ data: new Uint8Array(buffer) })
  const pdf = await task.promise
  const assets: ParsedImportAsset[] = []
  const pageHtml: string[] = []
  let skippedImages = 0
  let rasterizedPages = 0
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber)
    const [textContent, operatorList] = await Promise.all([page.getTextContent(), page.getOperatorList()])
    const viewport = page.getViewport({ scale: 1 })
    const pageView = page.view as unknown as number[]
    const pageWidth = pageView.length >= 4 ? Math.abs(pageView[2] - pageView[0]) : viewport.width
    const pageHeight = pageView.length >= 4 ? Math.abs(pageView[3] - pageView[1]) : viewport.height
    const textItemCount = textContent.items.filter((item) => typeof (item as { str?: unknown }).str === 'string' && Boolean((item as { str: string }).str.trim())).length
    const imageOps = new Set([pdfjs.OPS.paintImageXObject, pdfjs.OPS.paintXObject, pdfjs.OPS.paintInlineImageXObject, pdfjs.OPS.paintImageMaskXObject, pdfjs.OPS.paintInlineImageXObjectGroup, pdfjs.OPS.paintImageXObjectRepeat, pdfjs.OPS.paintImageMaskXObjectGroup, pdfjs.OPS.paintImageMaskXObjectRepeat])
    const imageOpCount = operatorList.fnArray.filter((fn) => imageOps.has(fn)).length
    const pathCount = operatorList.fnArray.filter((fn) => fn === pdfjs.OPS.constructPath || fn === pdfjs.OPS.rectangle).length
    const rasterizePage = shouldRasterizePdfPage({ textItemCount, imageCount: imageOpCount, pathCount, rotation: page.rotate })
    const blocks = rasterizePage ? [] : buildPdfTextBlocks(
      textContent.items as PdfTextItemLike[],
      textContent.styles as Record<string, PdfTextStyleLike>,
      pageHeight,
    )
    let pageImageCount = 0
    if (rasterizePage) {
      const blob = await renderPdfPageToPng(page, pageWidth, pageHeight)
      if (blob) {
        pageImageCount += 1
        const clientId = `pdf-p${pageNumber}-page-${pageImageCount}`
        assets.push({ clientId, filename: `${clientId}.png`, contentType: 'image/png', blob })
        blocks.push(createPdfImageBlock(clientId, [1, 0, 0, 1, 0, 0], pageHeight, 0, { width: pageWidth, height: pageHeight }))
      }
    }
    if (!rasterizePage || blocks.length === 0) {
      const objects = (page as unknown as { objs: { get: (id: string, callback?: (value: unknown) => void) => unknown } }).objs
      const stateStack: number[][] = []
      let transform = [1, 0, 0, 1, 0, 0]
      const imageAssets = new Map<string, string>()
      const appendImage = async (imageValue: unknown, imageTransform: number[], objectId: string, rect?: { x?: number; y?: number; width?: number; height?: number }) => {
      let clientId = objectId ? imageAssets.get(objectId) : undefined
      if (!clientId) {
        const blob = await imageObjectToPng(imageValue)
        if (!blob) {
          skippedImages += 1
          return
        }
        pageImageCount += 1
        clientId = `pdf-p${pageNumber}-image-${pageImageCount}`
        if (objectId) imageAssets.set(objectId, clientId)
        assets.push({ clientId, filename: `${clientId}.png`, contentType: 'image/png', blob })
      }
        blocks.push(createPdfImageBlock(clientId, imageTransform, pageHeight, operatorList.fnArray.length + blocks.length, rect))
      }
      for (let index = 0; index < operatorList.fnArray.length; index += 1) {
      const fn = operatorList.fnArray[index]
      const args = (operatorList.argsArray[index] ?? []) as unknown[]
      if (fn === pdfjs.OPS.save) {
        stateStack.push([...transform])
      } else if (fn === pdfjs.OPS.restore) {
        transform = stateStack.pop() ?? [1, 0, 0, 1, 0, 0]
      } else if (fn === pdfjs.OPS.transform && args.length >= 6) {
        transform = multiplyMatrix(transform, args.slice(0, 6).map(Number))
      } else if (fn === pdfjs.OPS.paintImageXObjectRepeat) {
        try {
          const objectId = typeof args[0] === 'string' ? args[0] : ''
          const imageValue = objectId ? await resolvePdfObject(objects, objectId) : null
          const image = imageValue as PdfImageObject
          const scaleX = Number(args[1]) || 1
          const scaleY = Number(args[2]) || 1
          const positions = Array.isArray(args[3]) ? args[3] : []
          for (let position = 0; position + 1 < positions.length; position += 2) {
            await appendImage(
              imageValue,
              multiplyMatrix(transform, [scaleX, 0, 0, scaleY, Number(positions[position]), Number(positions[position + 1])]),
              objectId,
              { width: image.width, height: image.height },
            )
          }
        } catch (error) {
          skippedImages += 1
          console.warn('PDF repeated image conversion failed', error)
        }
      } else if (fn === pdfjs.OPS.paintInlineImageXObjectGroup) {
        try {
          const imageValue = args[0]
          const map = Array.isArray(args[1]) ? args[1] : []
          for (const entry of map) {
            if (!entry || typeof entry !== 'object') continue
            const groupEntry = entry as { transform?: number[]; x?: number; y?: number; w?: number; h?: number }
            const entryTransform = Array.isArray(groupEntry.transform) ? groupEntry.transform : [1, 0, 0, 1, 0, 0]
            await appendImage(imageValue, multiplyMatrix(transform, entryTransform), '', {
              x: Number(groupEntry.x) || 0,
              y: Number(groupEntry.y) || 0,
              width: Number(groupEntry.w) || 1,
              height: Number(groupEntry.h) || 1,
            })
          }
        } catch (error) {
          skippedImages += 1
          console.warn('PDF image group conversion failed', error)
        }
      } else if (
        fn === pdfjs.OPS.paintImageXObject ||
        fn === pdfjs.OPS.paintXObject ||
        fn === pdfjs.OPS.paintInlineImageXObject ||
        fn === pdfjs.OPS.paintImageMaskXObject
      ) {
        try {
          const objectId = typeof args[0] === 'string' ? args[0] : ''
          const imageValue = objectId ? await resolvePdfObject(objects, objectId) : args[0]
          await appendImage(imageValue, transform, objectId)
        } catch (error) {
          skippedImages += 1
          console.warn('PDF embedded image conversion failed', error)
        }
      }
      }
    }
    if (rasterizePage && blocks.length > 0) rasterizedPages += 1
    pageHtml.push(renderPdfBlocks(orderPdfBlocks(blocks, pageWidth, pageHeight), pageWidth))
    const skippedDetail = skippedImages ? `，已跳过 ${skippedImages} 张不兼容图片` : ''
    report(20 + Math.round((pageNumber / pdf.numPages) * 70), `正在解析 PDF 第 ${pageNumber}/${pdf.numPages} 页${skippedDetail}…`)
  }
  report(92, 'PDF 解析完成，正在准备上传…')
  const warnings = rasterizedPages > 0
    ? [`PDF 中有 ${rasterizedPages} 页版面过于复杂，已按页面图像导入以保留表格、线框和原始颜色。`]
    : undefined
  return { html: pageHtml.join('\n') || '<p>（PDF 未提取到正文内容）</p>', assets, warnings }
}

addEventListener('message', async (event: MessageEvent<ParseMessage>) => {
  if (event.data.type !== 'parse') return
  try {
    const result = event.data.extension === 'docx'
      ? await parseWord(event.data.buffer)
      : await parsePdf(event.data.buffer)
    postMessage({ type: 'complete', result })
  } catch (error) {
    postMessage({ type: 'error', message: error instanceof Error ? error.message : '文档解析失败' })
  }
})
