import { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Spin, Tag } from 'antd'
import { LinkOutlined, PictureOutlined } from '@ant-design/icons'
import type { WebArticleImportPreview } from '../api/documents'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import type { WechatVerificationDetail } from '../utils/layoutCaptureBridge'
import { WechatCaptureFallback, type CaptureUiState } from './WechatCaptureFallback'

interface LinkImportReviewModalProps {
  open: boolean
  loading: boolean
  importing: boolean
  preview: WebArticleImportPreview | null
  error: string
  wechatFallback: WechatVerificationDetail | null
  captureState: CaptureUiState
  captureError: string | null
  onClose: () => void
  onPreview: (url: string) => void
  onUrlChange: () => void
  onDetectExtension: () => void
  onStartCapture: () => void
  onConfirm: () => void
}

export default function LinkImportReviewModal({
  open,
  loading,
  importing,
  preview,
  error,
  wechatFallback,
  captureState,
  captureError,
  onClose,
  onPreview,
  onUrlChange,
  onDetectExtension,
  onStartCapture,
  onConfirm,
}: LinkImportReviewModalProps) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    if (!open) setUrl('')
  }, [open])

  const captureBusy = ['opening', 'awaiting_verification', 'capturing', 'uploading'].includes(captureState)
  const busy = loading || importing || captureBusy
  const requestPreview = () => onPreview(url.trim())

  return (
    <Modal
      title="导入文章链接"
      open={open}
      width={1060}
      className="import-review-modal link-import-review-modal"
      destroyOnClose
      onCancel={loading || importing ? undefined : onClose}
      footer={(
        <div className="link-import-review-actions">
          <Button disabled={loading || importing} onClick={onClose}>取消</Button>
          <Button loading={loading} disabled={!url.trim() || importing || captureBusy} onClick={requestPreview}>
            {preview ? '重新抓取' : '抓取文章'}
          </Button>
          <Button type="primary" loading={importing} disabled={!preview || loading} onClick={onConfirm}>
            确认导入
          </Button>
        </div>
      )}
    >
      <Input
        value={url}
        autoFocus
        disabled={busy}
        prefix={<LinkOutlined />}
        placeholder="粘贴公开 HTTPS 文章链接"
        onChange={(event) => {
          setUrl(event.target.value)
          onUrlChange()
        }}
        onPressEnter={requestPreview}
      />
      {loading && <div className="import-preview-loading"><Spin description="正在抓取文章与正文图片…" /></div>}
      {error && !loading && <Alert style={{ marginTop: 16 }} type="error" showIcon message="链接导入失败" description={error} />}
      {wechatFallback && !loading && (
        <WechatCaptureFallback
          verification={wechatFallback}
          state={captureState}
          error={captureError}
          purpose="web_article_import"
          onDetect={onDetectExtension}
          onStart={onStartCapture}
        />
      )}
      {preview && !loading && (
        <>
          <div className="import-review-header link-import-review-header">
            <LinkOutlined className="import-file-icon import-file-icon-markdown" />
            <span>{preview.title}</span>
            <Tag color="cyan">链接文章</Tag>
            <Tag>{`图片 ${preview.image_count}`}</Tag>
          </div>
          {preview.cover_preview_url && (
            <section className="link-import-cover-status" aria-label="导入封面">
              <div className="link-import-cover-info">
                <strong><PictureOutlined /> 已拉取文章封面</strong>
                <span>
                  {preview.cover_requires_crops
                    ? '已按中心裁剪预览两种封面规格。'
                    : '公众号文章以原图适配预览，不设置裁剪范围。'}
                </span>
              </div>
              <div className="link-import-cover-specs">
                {[
                  { label: '2.35 : 1', aspect: 2.35 },
                  { label: '1 : 1', aspect: 1 },
                ].map((spec) => (
                  <figure
                    key={spec.label}
                    className={'link-import-cover-spec' + (preview.cover_requires_crops ? ' is-cropped' : ' is-original')}
                  >
                    <div className="link-import-cover-spec-frame" style={{ aspectRatio: String(spec.aspect) }}>
                      <img src={preview.cover_preview_url ?? undefined} alt={spec.label + ' 封面预览'} />
                    </div>
                    <figcaption>{spec.label}</figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}
          {preview.warnings.map((warning) => (
            <Alert key={warning} style={{ marginBottom: 12 }} type="warning" showIcon message={warning} />
          ))}
          <div className="import-review-frame">
            <iframe
              title="文章链接导入预览"
              className="import-preview-iframe"
              sandbox={SANDBOX_ALLOW_NEW_WINDOW}
              srcDoc={frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:28px;font:15px/1.8 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2937}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #d1d5db;padding:6px}pre{white-space:pre-wrap}</style></head><body>${preview.preview_html}</body></html>`)}
            />
          </div>
        </>
      )}
    </Modal>
  )
}
