import { useEffect, useState } from 'react'
import { Alert, Button, Modal, Spin } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { documentsApi } from '../api/documents'
import type { DocumentSourceAccess } from '../api/documents'
import { ApiError } from '../api/client'

interface SourceDocumentModalProps {
  documentId: number
  open: boolean
  onClose: () => void
}

export default function SourceDocumentModal({ documentId, open, onClose }: SourceDocumentModalProps) {
  const [source, setSource] = useState<DocumentSourceAccess | null>(null)
  const [wordHtml, setWordHtml] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    if (!open) return undefined
    setLoading(true)
    setError('')
    setSource(null)
    setWordHtml('')
    void (async () => {
      try {
        const access = await documentsApi.sourceAccess(documentId)
        if (!active) return
        setSource(access)
        if (access.content_type !== 'application/pdf') {
          const response = await fetch(access.url)
          if (!response.ok) throw new Error('无法读取 OSS 中的 Word 原文件')
          const arrayBuffer = await response.arrayBuffer()
          const { default: mammoth } = await import('mammoth')
          const result = await mammoth.convertToHtml({ arrayBuffer })
          if (active) setWordHtml(result.value || '<p>未读取到可预览的正文内容。</p>')
        }
      } catch (err) {
        if (active) setError(err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '加载原文件失败')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [documentId, open])

  const isPdf = source?.content_type === 'application/pdf'
  return (
    <Modal
      title={source?.filename ?? '查看原文件'}
      open={open}
      onCancel={onClose}
      width={1060}
      destroyOnHidden
      footer={source && (
        <Button icon={<DownloadOutlined />} onClick={() => window.open(source.url, '_blank', 'noopener,noreferrer')}>
          下载原文件
        </Button>
      )}
    >
      {loading ? (
        <div className="import-preview-loading"><Spin description="正在加载原文件…" /></div>
      ) : error ? (
        <Alert type="error" showIcon message={error} />
      ) : isPdf && source ? (
        <iframe title={source.filename} src={source.url} className="import-preview-iframe" style={{ height: '68vh' }} />
      ) : source ? (
        <iframe
          title={source.filename}
          className="import-preview-iframe"
          sandbox=""
          style={{ height: '68vh' }}
          srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:28px;font:15px/1.8 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2937}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #d1d5db;padding:6px}</style></head><body>${wordHtml}</body></html>`}
        />
      ) : null}
    </Modal>
  )
}
