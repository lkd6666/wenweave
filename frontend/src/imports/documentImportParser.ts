import type { ImportParseProgress, ParsedImport } from './types'
import { parsePdfInBrowser } from './pdfImportParser'

interface WorkerProgressMessage {
  type: 'progress'
  progress: ImportParseProgress
}

interface WorkerCompleteMessage {
  type: 'complete'
  result: ParsedImport
}

interface WorkerErrorMessage {
  type: 'error'
  message: string
}

type WorkerMessage = WorkerProgressMessage | WorkerCompleteMessage | WorkerErrorMessage

export async function parseImportFile(
  file: File,
  onProgress: (progress: ImportParseProgress) => void,
  signal?: AbortSignal,
): Promise<ParsedImport> {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension !== 'pdf' && extension !== 'docx') {
    throw new Error('仅支持 PDF 或 Word(.docx) 文件')
  }

  onProgress({ stage: 'reading', percent: 2, detail: '正在读取原始文件…' })
  const buffer = await file.arrayBuffer()
  if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')

  if (extension === 'pdf') {
    return parsePdfInBrowser(buffer, onProgress, signal)
  }

  return new Promise<ParsedImport>((resolve, reject) => {
    const worker = new Worker(new URL('../workers/documentImport.worker.ts', import.meta.url), { type: 'module' })
    const abort = () => {
      worker.terminate()
      reject(new DOMException('导入已取消', 'AbortError'))
    }
    const cleanup = () => {
      worker.terminate()
      signal?.removeEventListener('abort', abort)
    }

    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      const message = event.data
      if (message.type === 'progress') {
        onProgress(message.progress)
        return
      }
      cleanup()
      if (message.type === 'complete') {
        resolve(message.result)
      } else {
        reject(new Error(message.message))
      }
    }
    worker.onerror = (event) => {
      cleanup()
      reject(new Error(event.message || '浏览器解析文档时发生错误'))
    }
    worker.onmessageerror = () => {
      cleanup()
      reject(new Error('浏览器无法接收文档解析结果，请刷新页面后重试'))
    }
    signal?.addEventListener('abort', abort, { once: true })
    worker.postMessage({ type: 'parse', filename: file.name, extension, buffer }, [buffer])
  })
}
