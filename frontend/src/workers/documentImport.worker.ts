import type { ParsedImport, ParsedImportAsset } from '../imports/types'
import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

type ParseMessage = {
  type: 'parse'
  filename: string
  extension: 'pdf' | 'docx'
  buffer: ArrayBuffer
}

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

async function parseWord(buffer: ArrayBuffer): Promise<ParsedImport> {
  report(16, '正在读取 Word 正文与图片…')
  const imported = await import('mammoth')
  const mammoth = (imported.default ?? imported) as any
  const assets: ParsedImportAsset[] = []
  const result = await mammoth.convertToHtml(
    { arrayBuffer: buffer },
    {
      convertImage: mammoth.images.inline(async (image: any) => {
        const clientId = `word-image-${assets.length + 1}`
        const contentType = String(image.contentType || 'image/png').toLowerCase()
        const blob = new Blob([base64Bytes(await image.read('base64'))], { type: contentType })
        assets.push({
          clientId,
          filename: `${clientId}.${extensionForContentType(contentType)}`,
          contentType,
          blob,
        })
        report(Math.min(88, 30 + assets.length * 3), `已提取 ${assets.length} 张 Word 图片…`)
        return { src: `direct-import://asset/${clientId}` }
      }),
    },
  )
  report(92, 'Word 解析完成，正在准备上传…')
  return { html: result.value || '<p>（Word 未提取到正文内容）</p>', assets }
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
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber)
    const [textContent, operatorList] = await Promise.all([page.getTextContent(), page.getOperatorList()])
    const blocks: Array<{ x: number; y: number; html: string }> = []
    const lines = new Map<number, PdfTextItem[]>()
    for (const item of textContent.items) {
      if (!isPdfTextItem(item)) continue
      if (!item.str?.trim()) continue
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
    let imageCount = 0
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
        const objectId = typeof args[0] === 'string' ? args[0] : ''
        let blob: Blob | null = null
        try {
          const imageValue = objectId ? await resolvePdfObject(objects, objectId) : args[0]
          blob = await imageObjectToPng(imageValue)
        } catch (error) {
          skippedImages += 1
          console.warn('PDF embedded image conversion failed', error)
          continue
        }
        if (!blob) {
          skippedImages += 1
          continue
        }
        imageCount += 1
        const clientId = `pdf-p${pageNumber}-image-${imageCount}`
        assets.push({ clientId, filename: `${clientId}.png`, contentType: 'image/png', blob })
        blocks.push({
          x: transform[4],
          y: transform[5],
          html: `<p><img src="direct-import://asset/${clientId}" alt="图片" style="max-width:100%;height:auto;" /></p>`,
        })
      }
    }
    blocks.sort((left, right) => right.y - left.y || left.x - right.x)
    pageHtml.push(...blocks.map((block) => block.html))
    const skippedDetail = skippedImages ? `，已跳过 ${skippedImages} 张不兼容图片` : ''
    report(20 + Math.round((pageNumber / pdf.numPages) * 70), `正在解析 PDF 第 ${pageNumber}/${pdf.numPages} 页${skippedDetail}…`)
  }
  report(92, 'PDF 解析完成，正在准备上传…')
  return { html: pageHtml.join('\n') || '<p>（PDF 未提取到正文内容）</p>', assets }
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
