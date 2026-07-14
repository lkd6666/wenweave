import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import type { ImportParseProgress, ParsedImport, ParsedImportAsset } from './types'

type PdfTextItem = { str: string; transform: number[] }
type PdfImageObject = {
  width?: number
  height?: number
  data?: Uint8ClampedArray | Uint8Array
  bitmap?: ImageBitmap
}

const htmlEscape = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const isPdfTextItem = (value: unknown): value is PdfTextItem => {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<PdfTextItem>
  return typeof item.str === 'string' && Array.isArray(item.transform) && item.transform.length >= 6
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

  try {
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')
      const page = await pdf.getPage(pageNumber)
      const [textContent, operatorList] = await Promise.all([page.getTextContent(), page.getOperatorList()])
      const blocks: Array<{ x: number; y: number; html: string }> = []
      const lines = new Map<number, PdfTextItem[]>()
      for (const item of textContent.items) {
        if (!isPdfTextItem(item) || !item.str.trim()) continue
        const lineY = Math.round(item.transform[5] / 3) * 3
        const items = lines.get(lineY) ?? []
        items.push(item)
        lines.set(lineY, items)
      }
      for (const [y, items] of lines) {
        items.sort((left, right) => left.transform[4] - right.transform[4])
        const text = items.map((item) => item.str).join('').trim()
        if (text) blocks.push({ x: items[0]?.transform[4] ?? 0, y, html: `<p>${htmlEscape(text)}</p>` })
      }

      const objects = (page as unknown as { objs: { get: (id: string, callback?: (value: unknown) => void) => unknown } }).objs
      const stateStack: number[][] = []
      let transform = [1, 0, 0, 1, 0, 0]
      let pageImageCount = 0
      for (let index = 0; index < operatorList.fnArray.length; index += 1) {
        const fn = operatorList.fnArray[index]
        const args = (operatorList.argsArray[index] ?? []) as unknown[]
        if (fn === pdfjs.OPS.save) {
          stateStack.push([...transform])
        } else if (fn === pdfjs.OPS.restore) {
          transform = stateStack.pop() ?? [1, 0, 0, 1, 0, 0]
        } else if (fn === pdfjs.OPS.transform && args.length >= 6) {
          transform = multiplyMatrix(transform, args.slice(0, 6).map(Number))
        } else if (
          fn === pdfjs.OPS.paintImageXObject ||
          fn === pdfjs.OPS.paintXObject ||
          fn === pdfjs.OPS.paintInlineImageXObject ||
          fn === pdfjs.OPS.paintImageMaskXObject
        ) {
          try {
            const objectId = typeof args[0] === 'string' ? args[0] : ''
            const imageValue = objectId ? await resolvePdfObject(objects, objectId) : args[0]
            const blob = await imageObjectToPng(imageValue)
            if (!blob) {
              skippedImages += 1
              continue
            }
            pageImageCount += 1
            const clientId = `pdf-p${pageNumber}-image-${pageImageCount}`
            assets.push({ clientId, filename: `${clientId}.png`, contentType: 'image/png', blob })
            blocks.push({
              x: transform[4],
              y: transform[5],
              html: `<p><img src="direct-import://asset/${clientId}" alt="图片" style="max-width:100%;height:auto;" /></p>`,
            })
          } catch (error) {
            skippedImages += 1
            console.warn('PDF embedded image conversion failed', error)
          }
        }
      }
      blocks.sort((left, right) => right.y - left.y || left.x - right.x)
      htmlParts.push(...blocks.map((block) => block.html))
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
  return { html: htmlParts.join('\n') || '<p>（PDF 未提取到正文内容）</p>', assets }
}
