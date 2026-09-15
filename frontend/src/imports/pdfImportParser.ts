import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import type { ImportParseProgress, ParsedImport, ParsedImportAsset } from './types'
import {
  hasRasterImageTransform,
  pdfImageDisplayAspectRatio,
  pdfMatrixToImageTransform,
  rasterImageTransformKey,
  transformImageBlob,
} from '../utils/imageTransform'
import {
  buildPdfTextBlocks,
  createPdfImageBlock,
  orderPdfBlocks,
  renderPdfBlocks,
  shouldRasterizePdfPage,
  type PdfTextItemLike,
  type PdfTextStyleLike,
} from './pdfLayout'

type PdfImageObject = {
  width?: number
  height?: number
  data?: Uint8ClampedArray | Uint8Array
  bitmap?: ImageBitmap
}

const multiplyMatrix = (left: number[], right: number[]) => [
  left[0] * right[0] + left[2] * right[1],
  left[1] * right[0] + left[3] * right[1],
  left[0] * right[2] + left[2] * right[3],
  left[1] * right[2] + left[3] * right[3],
  left[0] * right[4] + left[2] * right[5] + left[4],
  left[1] * right[4] + left[3] * right[5] + left[5],
]

async function resolvePdfObject(objects: { get: (id: string, callback?: (value: unknown) => void) => unknown }, id: string) {
  try {
    const value = objects.get(id)
    if (value !== undefined) return value
  } catch {
    // PDF.js may still be resolving an image object after the operator list is returned.
  }
  return new Promise<unknown>((resolve) => objects.get(id, resolve))
}

function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
}

async function renderPdfPageToPng(page: { getViewport: (options: { scale: number }) => { width: number; height: number }; render: (options: any) => { promise: Promise<unknown> } }, width: number, height: number) {
  const scale = Math.max(0.75, Math.min(1.5, Math.sqrt(2400000 / Math.max(1, width * height))))
  const viewport = page.getViewport({ scale })
  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)
  const context = canvas.getContext('2d')
  if (!context) return null
  await page.render({ canvasContext: context, viewport }).promise
  return canvasToBlob(canvas)
}

async function imageObjectToPng(value: unknown): Promise<Blob | null> {
  const image = value as PdfImageObject
  if (image.bitmap) {
    const canvas = document.createElement('canvas')
    canvas.width = image.bitmap.width
    canvas.height = image.bitmap.height
    canvas.getContext('2d')?.drawImage(image.bitmap, 0, 0)
    return canvasToBlob(canvas)
  }
  if (!image.width || !image.height || !image.data) return null

  const source = image.data
  const pixelCount = image.width * image.height
  const rgba = new Uint8ClampedArray(pixelCount * 4)
  if (source.length === rgba.length) {
    rgba.set(source)
  } else if (source.length === pixelCount * 3) {
    for (let index = 0; index < pixelCount; index += 1) {
      const sourceOffset = index * 3
      const targetOffset = index * 4
      rgba[targetOffset] = source[sourceOffset]
      rgba[targetOffset + 1] = source[sourceOffset + 1]
      rgba[targetOffset + 2] = source[sourceOffset + 2]
      rgba[targetOffset + 3] = 255
    }
  } else if (source.length === pixelCount) {
    for (let index = 0; index < pixelCount; index += 1) {
      const targetOffset = index * 4
      rgba[targetOffset] = source[index]
      rgba[targetOffset + 1] = source[index]
      rgba[targetOffset + 2] = source[index]
      rgba[targetOffset + 3] = 255
    }
  } else {
    return null
  }

  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height
  const context = canvas.getContext('2d')
  if (!context) return null
  context.putImageData(new ImageData(rgba, image.width, image.height), 0, 0)
  return canvasToBlob(canvas)
}

const yieldToBrowser = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

export async function parsePdfInBrowser(
  buffer: ArrayBuffer,
  onProgress: (progress: ImportParseProgress) => void,
  signal?: AbortSignal,
): Promise<ParsedImport> {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  onProgress({ stage: 'parsing', percent: 12, detail: '正在打开 PDF…' })
  const task = pdfjs.getDocument({ data: new Uint8Array(buffer) })
  const pdf = await task.promise
  const assets: ParsedImportAsset[] = []
  const htmlParts: string[] = []
  let skippedImages = 0
  let rasterizedPages = 0

  try {
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')
      const page = await pdf.getPage(pageNumber)
      const [textContent, operatorList] = await Promise.all([page.getTextContent(), page.getOperatorList()])
      const viewport = page.getViewport({ scale: 1 })
      const pageView = page.view as unknown as number[]
      const pageWidth = pageView.length >= 4 ? Math.abs(pageView[2] - pageView[0]) : viewport.width
      const pageHeight = pageView.length >= 4 ? Math.abs(pageView[3] - pageView[1]) : viewport.height
      const textItemCount = textContent.items.filter((item) => typeof (item as { str?: unknown }).str === 'string' && Boolean((item as { str: string }).str.trim())).length
      const imageOps = new Set([pdfjs.OPS.paintImageXObject, pdfjs.OPS.paintXObject, pdfjs.OPS.paintInlineImageXObject, pdfjs.OPS.paintImageMaskXObject, pdfjs.OPS.paintInlineImageXObjectGroup, pdfjs.OPS.paintImageXObjectRepeat, pdfjs.OPS.paintImageMaskXObjectGroup, pdfjs.OPS.paintImageMaskXObjectRepeat])
      const imageCount = operatorList.fnArray.filter((fn) => imageOps.has(fn)).length
      const pathCount = operatorList.fnArray.filter((fn) => fn === pdfjs.OPS.constructPath || fn === pdfjs.OPS.rectangle).length
      const rasterizePage = shouldRasterizePdfPage({ textItemCount, imageCount, pathCount, rotation: page.rotate })
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
        const rasterTransform = pdfMatrixToImageTransform(imageTransform)
        const imageWidth = Math.max(0.01, rect?.width ?? 1)
        const imageHeight = Math.max(0.01, rect?.height ?? 1)
        const displayAspectRatio = pdfImageDisplayAspectRatio(imageTransform, imageWidth, imageHeight)
        const transformKey = rasterImageTransformKey(rasterTransform)
        const aspectKey = displayAspectRatio ? Math.round(displayAspectRatio * 1000) / 1000 : 'unknown'
        const assetKey = objectId ? `${objectId}:${transformKey}:${aspectKey}` : ''
        let clientId = assetKey ? imageAssets.get(assetKey) : undefined
        if (!clientId) {
          let blob = await imageObjectToPng(imageValue)
          if (!blob) {
            skippedImages += 1
            return
          }
          if (hasRasterImageTransform(rasterTransform)) {
            try {
              blob = await transformImageBlob(blob, rasterTransform, {
                outputAspectRatio: displayAspectRatio,
              })
            } catch (error) {
              console.warn('PDF image transform conversion failed; preserving the original pixels', error)
            }
          }
          pageImageCount += 1
          clientId = `pdf-p${pageNumber}-image-${pageImageCount}`
          if (assetKey) imageAssets.set(assetKey, clientId)
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
      htmlParts.push(renderPdfBlocks(orderPdfBlocks(blocks, pageWidth, pageHeight), pageWidth))
      const skippedDetail = skippedImages ? `，已跳过 ${skippedImages} 张不兼容图片` : ''
      onProgress({
        stage: 'parsing',
        percent: 15 + Math.round((pageNumber / pdf.numPages) * 75),
        detail: `正在解析 PDF 第 ${pageNumber}/${pdf.numPages} 页${skippedDetail}…`,
      })
      await yieldToBrowser()
    }
  } finally {
    await pdf.destroy()
  }
  onProgress({ stage: 'extracting', percent: 92, detail: 'PDF 解析完成，正在准备上传…' })
  const warnings = rasterizedPages > 0
    ? [`PDF 中有 ${rasterizedPages} 页版面过于复杂，已按页面图像导入以保留表格、线框和原始颜色。`]
    : undefined
  return { html: htmlParts.join('\n') || '<p>（PDF 未提取到正文内容）</p>', assets, warnings }
}
