import { useEffect, useState } from 'react'
import { Alert, Modal, Progress, Spin, Tag } from 'antd'
import { FilePdfOutlined, FileTextOutlined, FileWordOutlined } from '@ant-design/icons'
import type { DirectImportProgress } from '../imports/directImportUpload'
import { parseImportFile } from '../imports/documentImportParser'
import { createParsedImportPreview } from '../imports/parsedImportPreview'
import type { ParsedImport } from '../imports/types'
import { frameDocumentWithNewWindowLinks, SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

interface ImportReviewModalProps {
  file: File | null
  open: boolean
  importing: boolean
  progress: DirectImportProgress | null
  importError: string
  onCancel: () => void
  onConfirm: (preparedImport: ParsedImport | null) => void
}

/** 上传前在本机校对原始文件，确认后才把文件交给后端解析、上传图片和创建文档。 */
export default function ImportReviewModal({ file, open, importing, progress, importError, onCancel, onConfirm }: ImportReviewModalProps) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [parsedHtml, setParsedHtml] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [preparedImport, setPreparedImport] = useState<ParsedImport | null>(null)
  const extension = file?.name.split('.').pop()?.toLowerCase()
  const isPdf = extension === 'pdf'
  const isMarkdown = extension === 'md'
  const fileTypeLabel = isPdf ? 'PDF' : isMarkdown ? 'Markdown' : 'Word'

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setPdfUrl(null)
    setParsedHtml('')
    setPreviewError('')
    setPreparedImport(null)
    if (!file || !open) return undefined

    if (isPdf) {
      objectUrl = URL.createObjectURL(file)
      setPdfUrl(objectUrl)
      return () => URL.revokeObjectURL(objectUrl!)
    }

    let preview: ReturnType<typeof createParsedImportPreview> | null = null
    setLoadingPreview(true)
    parseImportFile(file, () => {})
      .then((parsed) => {
        if (!active) return
        preview = createParsedImportPreview(parsed)
        setPreparedImport(parsed)
        setParsedHtml(preview.html || '<p>未读取到可预览的正文内容。</p>')
      })
      .catch(() => {
        if (active) setPreviewError(`无法在浏览器中预览该 ${fileTypeLabel} 文件。`)
      })
      .finally(() => {
        if (active) setLoadingPreview(false)
      })
    return () => {
      active = false
      preview?.revoke()
    }
  }, [file, fileTypeLabel, isPdf, open])

  return (
    <Modal
      title="导入前校对"
      open={open}
      width={1060}
      className="import-review-modal"
      destroyOnClose
      onCancel={onCancel}
      okText="确认导入"
      cancelText={importing ? '取消导入' : '取消'}
      okButtonProps={{ loading: importing, disabled: loadingPreview || Boolean(previewError) }}
      onOk={() => onConfirm(preparedImport)}
    >
      <div className="import-review-header">
        {isPdf ? <FilePdfOutlined className="import-file-icon import-file-icon-pdf" /> : isMarkdown ? <FileTextOutlined className="import-file-icon import-file-icon-markdown" /> : <FileWordOutlined className="import-file-icon import-file-icon-word" />}
        <span>{file?.name}</span>
        <Tag color={isPdf ? 'red' : isMarkdown ? 'gold' : 'blue'}>{fileTypeLabel}</Tag>
      </div>
      {previewError ? (
        <Alert type="warning" showIcon message={previewError} />
      ) : (
        <>
          {preparedImport?.warnings?.map((warning) => <Alert key={warning} style={{ marginBottom: 12 }} type="warning" showIcon message={warning} />)}
          <div className="import-review-frame">
            {isPdf && pdfUrl ? (
              <iframe title="PDF 原文件预览" src={pdfUrl} className="import-preview-iframe" />
            ) : loadingPreview ? (
              <div className="import-preview-loading"><Spin description={`正在生成 ${fileTypeLabel} 预览…`} /></div>
            ) : (
              <iframe
                title={`${fileTypeLabel} 内容预览`}
                className="import-preview-iframe"
                // Parsed Word/PDF images use parent-created blob URLs. Keep the
                // preview same-origin so those URLs remain readable; scripts
                // are still blocked because the sandbox grants no script flag.
                sandbox={SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW}
                srcDoc={frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:28px;font:15px/1.8 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2937}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #d1d5db;padding:6px}</style></head><body>${parsedHtml}</body></html>`)}
              />
            )}
          </div>
        </>
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
