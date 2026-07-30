import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Modal, Spin, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { documentsApi } from '../api/documents'
import type { DocumentSourceAccess } from '../api/documents'
import { ApiError } from '../api/client'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

const { Text } = Typography

interface SourceDocumentModalProps {
  documentId: number
  currentHtml: string
  open: boolean
  onClose: () => void
}

function htmlPreviewDocument(html: string): string {
  const content = html.trim()
  if (!content) {
    return '<!doctype html><html><body><p style="color:#98a2b3;text-align:center;margin-top:48px;">当前排版稿没有内容</p></body></html>'
  }
  if (/^\s*(?:<!doctype|<html[\s>])/i.test(content)) return frameDocumentWithNewWindowLinks(content)
  return frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:20px 16px 36px;background:#fff;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:2;word-break:break-word}img,table{max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #d1d5db;padding:6px}</style></head><body>${content}</body></html>`)
}

function DocxSourcePreview({ source }: { source: DocumentSourceAccess }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const host = hostRef.current
    if (!host) return undefined
    host.replaceChildren()
    setError('')
    setLoading(true)

    void (async () => {
      try {
        const response = await fetch(source.url)
        if (!response.ok) throw new Error('无法读取 Word 原文件')
        const blob = await response.blob()
        const { renderAsync } = await import('docx-preview')
        if (!active || !hostRef.current) return
        host.replaceChildren()
        await renderAsync(blob, hostRef.current, hostRef.current, {
          inWrapper: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          ignoreLastRenderedPageBreak: false,
        })
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Word 原文件预览失败')
      } finally {
        if (active) setLoading(false)
      }
    })()

    return () => {
      active = false
      host.replaceChildren()
    }
  }, [source.url])

  return (
    <div className="source-original-scroll">
      {loading && <div className="import-preview-loading"><Spin description="正在渲染 Word 原文件…" /></div>}
      {error && <Alert type="error" showIcon message={error} />}
      <div ref={hostRef} className={loading || error ? 'source-docx-render is-hidden' : 'source-docx-render'} />
    </div>
  )
}

function MarkdownSourcePreview({ source }: { source: DocumentSourceAccess }) {
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setContent('')
    setError('')
    setLoading(true)
    void fetch(source.url)
      .then(async (response) => {
        if (!response.ok) throw new Error('无法读取 Markdown 原文件')
        return response.text()
      })
      .then((text) => {
        if (active) setContent(text)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : 'Markdown 原文件预览失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [source.url])

  if (loading) return <div className="import-preview-loading"><Spin description="正在加载 Markdown 原文件…" /></div>
  if (error) return <Alert type="error" showIcon message={error} />
  return <pre className="source-markdown-code"><code>{content}</code></pre>
}

function OriginalSourcePreview({ source }: { source: DocumentSourceAccess }) {
  if (source.content_type === 'application/pdf') {
    return <iframe title={`${source.filename} 原文件`} src={source.url} className="import-preview-iframe" />
  }
  if (source.content_type === 'text/markdown') return <MarkdownSourcePreview source={source} />
  return <DocxSourcePreview source={source} />
}

export default function SourceDocumentModal({ documentId, currentHtml, open, onClose }: SourceDocumentModalProps) {
  const [source, setSource] = useState<DocumentSourceAccess | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const draftPreview = useMemo(() => htmlPreviewDocument(currentHtml), [currentHtml])

  useEffect(() => {
    let active = true
    if (!open) return undefined
    setLoading(true)
    setError('')
    setSource(null)
    void documentsApi.sourceAccess(documentId)
      .then((access) => {
        if (active) setSource(access)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '加载原文件失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [documentId, open])

  return (
    <Modal
      title={source?.filename ? `原文校审 - ${source.filename}` : '原文校审'}
      open={open}
      onCancel={onClose}
      width="min(1440px, calc(100vw - 32px))"
      className="source-document-modal"
      destroyOnHidden
      footer={source && (
        <Button icon={<DownloadOutlined />} onClick={() => window.open(source.url, '_blank', 'noopener,noreferrer')}>
          下载原文件
        </Button>
      )}
    >
      <div className="source-comparison-layout">
        <section className="source-comparison-pane" aria-label="原文件">
          <div className="source-comparison-heading">
            <strong>原文件</strong>
            {source && <Text type="secondary">{source.filename}</Text>}
          </div>
          <div className="source-comparison-content">
            {loading ? (
              <div className="import-preview-loading"><Spin description="正在加载原文件…" /></div>
            ) : error ? (
              <Alert type="error" showIcon message={error} />
            ) : source ? (
              <OriginalSourcePreview source={source} />
            ) : null}
          </div>
        </section>
        <section className="source-comparison-pane" aria-label="当前排版稿">
          <div className="source-comparison-heading">
            <strong>当前排版稿</strong>
            <Text type="secondary">包含未保存修改</Text>
          </div>
          <div className="source-comparison-content">
            <iframe title="当前排版稿" className="import-preview-iframe" sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={draftPreview} />
          </div>
        </section>
      </div>
    </Modal>
  )
}
