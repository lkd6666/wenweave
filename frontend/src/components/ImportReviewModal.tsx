import { useEffect, useState } from 'react'
import { Alert, Modal, Progress, Spin, Tag } from 'antd'
import { FilePdfOutlined, FileWordOutlined } from '@ant-design/icons'
import type { DirectImportProgress } from '../imports/directImportUpload'

interface ImportReviewModalProps {
  file: File | null
  open: boolean
  importing: boolean
  progress: DirectImportProgress | null
  importError: string
  onCancel: () => void
  onConfirm: () => void
}

/** 上传前在本机校对原始文件，确认后才把文件交给后端解析、上传图片和创建文档。 */
export default function ImportReviewModal({ file, open, importing, progress, importError, onCancel, onConfirm }: ImportReviewModalProps) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [wordHtml, setWordHtml] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [loadingPreview, setLoadingPreview] = useState(false)
  const extension = file?.name.split('.').pop()?.toLowerCase()
  const isPdf = extension === 'pdf'

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setPdfUrl(null)
    setWordHtml('')
    setPreviewError('')
    if (!file || !open) return undefined

    if (isPdf) {
      objectUrl = URL.createObjectURL(file)
      setPdfUrl(objectUrl)
      return () => URL.revokeObjectURL(objectUrl!)
    }

    setLoadingPreview(true)
    file.arrayBuffer()
      .then(async (arrayBuffer) => {
        const { default: mammoth } = await import('mammoth')
        return mammoth.convertToHtml({ arrayBuffer })
      })
      .then((result) => {
        if (active) setWordHtml(result.value || '<p>未读取到可预览的正文内容。</p>')
      })
      .catch(() => {
        if (active) setPreviewError('无法在浏览器中预览该 Word 文件，仍可继续导入后在编辑器中校对。')
      })
      .finally(() => {
        if (active) setLoadingPreview(false)
      })
    return () => {
      active = false
    }
  }, [file, isPdf, open])

  return (
    <Modal
      title="导入前校对"
      open={open}
      width={1060}
      destroyOnClose
      onCancel={onCancel}
      okText="确认导入"
      cancelText={importing ? '取消导入' : '取消'}
      okButtonProps={{ loading: importing, disabled: loadingPreview || Boolean(previewError) }}
      onOk={onConfirm}
    >
      <div className="import-review-header">
        {isPdf ? <FilePdfOutlined className="import-file-icon import-file-icon-pdf" /> : <FileWordOutlined className="import-file-icon import-file-icon-word" />}
        <span>{file?.name}</span>
        <Tag color={isPdf ? 'red' : 'blue'}>{isPdf ? 'PDF' : 'Word'}</Tag>
      </div>
      {previewError ? (
        <Alert type="warning" showIcon message={previewError} />
      ) : (
        <div className="import-review-frame">
          {isPdf && pdfUrl ? (
            <iframe title="PDF 原文件预览" src={pdfUrl} className="import-preview-iframe" />
          ) : loadingPreview ? (
            <div className="import-preview-loading"><Spin description="正在生成 Word 预览…" /></div>
          ) : (
            <iframe
              title="Word 内容预览"
              className="import-preview-iframe"
              sandbox=""
              srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:28px;font:15px/1.8 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2937}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #d1d5db;padding:6px}</style></head><body>${wordHtml}</body></html>`}
            />
          )}
        </div>
      )}
      {importing && progress && (
        <div style={{ marginTop: 16 }}>
          <Progress percent={progress.percent} status="active" />
          <div style={{ color: '#667085', fontSize: 13 }}>{progress.detail}</div>
        </div>
      )}
      {importError && !importing && <Alert style={{ marginTop: 16 }} type="error" showIcon message="导入失败" description={importError} />}
    </Modal>
  )
}
