import { useEffect, useRef, useState } from 'react'
import { Alert, Empty, Segmented, Spin } from 'antd'
import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import MarkdownContent from './MarkdownContent'
import {
  STORAGE_PREVIEW_FETCH_LIMIT_BYTES,
  type StoragePreviewKind,
} from '../utils/storagePreview'

interface StorageFilePreviewProps {
  filename: string
  size: number
  url: string
  kind: StoragePreviewKind
}

type MarkdownPreviewMode = 'rendered' | 'source'

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function oversizedPreviewError(): string {
  return '文件超过 50 MB，无法在浏览器中安全预览，请在新窗口打开或下载。'
}

function readErrorMessage(error: unknown, filename: string): string {
  if (error instanceof TypeError) {
    return `无法读取“${filename}”。请确认 OSS CORS 允许当前前端域名的 GET、HEAD 请求。`
  }
  return error instanceof Error ? error.message : `无法读取“${filename}”。`
}

function DocxPreview({ filename, size, url }: Pick<StorageFilePreviewProps, 'filename' | 'size' | 'url'>) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const host = hostRef.current
    if (!host) return undefined
    const controller = new AbortController()
    let active = true
    host.replaceChildren()
    setLoading(true)
    setError('')

    void (async () => {
      try {
        if (size > STORAGE_PREVIEW_FETCH_LIMIT_BYTES) throw new Error(oversizedPreviewError())
        const response = await fetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`无法读取“${filename}”（HTTP ${response.status}）。`)
        const blob = await response.blob()
        const { renderAsync } = await import('docx-preview')
        if (!active || !hostRef.current) return
        host.replaceChildren()
        await renderAsync(blob, host, host, {
          inWrapper: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          ignoreLastRenderedPageBreak: false,
        })
      } catch (error) {
        if (active && !isAbortError(error)) setError(readErrorMessage(error, filename))
      } finally {
        if (active) setLoading(false)
      }
    })()

    return () => {
      active = false
      controller.abort()
      host.replaceChildren()
    }
  }, [filename, size, url])

  return (
    <div className="storage-document-scroll">
      {loading && <div className="storage-preview-loading"><Spin description="正在渲染 Word 文件…" /></div>}
      {error && <Alert type="error" showIcon message={error} />}
      <div ref={hostRef} className={loading || error ? 'storage-docx-render is-hidden' : 'storage-docx-render'} />
    </div>
  )
}

function PdfPreview({ filename, size, url }: Pick<StorageFilePreviewProps, 'filename' | 'size' | 'url'>) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('正在打开 PDF 文件…')

  useEffect(() => {
    const host = hostRef.current
    if (!host) return undefined
    const controller = new AbortController()
    let active = true
    let loadingTask: { destroy: () => void } | null = null
    host.replaceChildren()
    setLoading(true)
    setError('')
    setProgress('正在打开 PDF 文件…')

    void (async () => {
      try {
        if (size > STORAGE_PREVIEW_FETCH_LIMIT_BYTES) throw new Error(oversizedPreviewError())
        const response = await fetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`无法读取“${filename}”（HTTP ${response.status}）。`)
        const buffer = await response.arrayBuffer()
        const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
        const task = pdfjs.getDocument({ data: new Uint8Array(buffer) })
        loadingTask = task
        const documentProxy = await task.promise

        for (let pageNumber = 1; pageNumber <= documentProxy.numPages; pageNumber += 1) {
          if (!active) return
          setProgress(`正在渲染 PDF 第 ${pageNumber}/${documentProxy.numPages} 页…`)
          const page = await documentProxy.getPage(pageNumber)
          const viewport = page.getViewport({ scale: 1.4 })
          const canvas = document.createElement('canvas')
          const context = canvas.getContext('2d')
          if (!context) throw new Error('浏览器无法创建 PDF 预览画布。')
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          canvas.className = 'storage-pdf-canvas'
          const pageElement = document.createElement('article')
          pageElement.className = 'storage-pdf-page'
          pageElement.append(canvas)
          host.append(pageElement)
          await page.render({ canvas, canvasContext: context, viewport }).promise
          page.cleanup()
        }
      } catch (error) {
        if (active && !isAbortError(error)) setError(readErrorMessage(error, filename))
      } finally {
        if (active) setLoading(false)
      }
    })()

    return () => {
      active = false
      controller.abort()
      loadingTask?.destroy()
      host.replaceChildren()
    }
  }, [filename, size, url])

  return (
    <div className="storage-pdf-scroll">
      {loading && <div className="storage-preview-loading"><Spin description={progress} /></div>}
      {error && <Alert type="error" showIcon message={error} />}
      <div ref={hostRef} className={loading || error ? 'storage-pdf-render is-hidden' : 'storage-pdf-render'} />
    </div>
  )
}

function TextPreview({ filename, size, url, markdown }: Pick<StorageFilePreviewProps, 'filename' | 'size' | 'url'> & { markdown: boolean }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [markdownMode, setMarkdownMode] = useState<MarkdownPreviewMode>('rendered')

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setContent('')
    setLoading(true)
    setError('')
    setMarkdownMode('rendered')

    void (async () => {
      try {
        if (size > STORAGE_PREVIEW_FETCH_LIMIT_BYTES) throw new Error(oversizedPreviewError())
        const response = await fetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`无法读取“${filename}”（HTTP ${response.status}）。`)
        const text = await response.text()
        if (active) setContent(text)
      } catch (error) {
        if (active && !isAbortError(error)) setError(readErrorMessage(error, filename))
      } finally {
        if (active) setLoading(false)
      }
    })()

    return () => {
      active = false
      controller.abort()
    }
  }, [filename, size, url])

  if (loading) return <div className="storage-preview-loading"><Spin description={markdown ? '正在加载 Markdown 文件…' : '正在加载文本文件…'} /></div>
  if (error) return <Alert type="error" showIcon message={error} />

  if (!markdown) {
    return <pre className="storage-text-preview"><code>{content}</code></pre>
  }

  return (
    <section className="storage-markdown-preview">
      <div className="storage-markdown-toolbar">
        <Segmented<MarkdownPreviewMode>
          size="small"
          value={markdownMode}
          onChange={(value) => setMarkdownMode(value)}
          options={[
            { label: '预览', value: 'rendered' },
            { label: '原文', value: 'source' },
          ]}
        />
      </div>
      {markdownMode === 'rendered' ? (
        <div className="storage-markdown-rendered"><MarkdownContent content={content} /></div>
      ) : (
        <pre className="storage-text-preview"><code>{content}</code></pre>
      )}
    </section>
  )
}

export default function StorageFilePreview({ filename, size, url, kind }: StorageFilePreviewProps) {
  if (kind === 'image') {
    return <img className="storage-image-preview" src={url} alt={filename} />
  }
  if (kind === 'video') {
    return <video className="storage-video-preview" src={url} controls />
  }
  if (kind === 'pdf') {
    return <PdfPreview filename={filename} size={size} url={url} />
  }
  if (kind === 'docx') {
    return <DocxPreview filename={filename} size={size} url={url} />
  }
  if (kind === 'markdown') {
    return <TextPreview filename={filename} size={size} url={url} markdown />
  }
  if (kind === 'text') {
    return <TextPreview filename={filename} size={size} url={url} markdown={false} />
  }

  return <Empty description="该文件类型不支持内嵌预览，请在新窗口打开或下载。" image={Empty.PRESENTED_IMAGE_SIMPLE} />
}
