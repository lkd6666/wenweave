import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Descriptions, Input, Modal, Spin } from 'antd'
import { LinkOutlined, ReloadOutlined } from '@ant-design/icons'
import { layoutReferencesApi } from '../api/layoutReferences'
import { ApiError } from '../api/client'
import type { LayoutReferencePreview } from '../types'

interface LayoutImitationModalProps {
  open: boolean
  streaming: boolean
  modelAvailable: boolean
  onClose: () => void
  onConfirm: (reference: LayoutReferencePreview) => void
}

function previewDocument(referenceHtml: string) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:" />
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #fff; }
    body { padding: 16px 14px 28px; color: #182230; font: 15px/1.85 -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; overflow-wrap: anywhere; }
    article, section, div, figure, blockquote { max-width: 100%; }
    p { margin: 0 0 1em; }
    h1, h2, h3, h4, h5, h6 { line-height: 1.45; }
    table { width: 100%; max-width: 100%; border-collapse: collapse; }
    td, th { min-width: 0; }
    .layout-reference-image { display: block; min-height: 96px; margin: 10px 0; padding: 34px 12px; border: 1px dashed #b7c6d9; background: #f5f8fc; color: #77879a; text-align: center; font-size: 12px; }
  </style>
</head>
<body>${referenceHtml}</body>
</html>`
}

export default function LayoutImitationModal({
  open,
  streaming,
  modelAvailable,
  onClose,
  onConfirm,
}: LayoutImitationModalProps) {
  const [url, setUrl] = useState('')
  const [reference, setReference] = useState<LayoutReferencePreview | null>(null)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) return
    setUrl('')
    setReference(null)
    setError(null)
    setParsing(false)
  }, [open])

  const srcDoc = useMemo(() => reference ? previewDocument(reference.preview_html) : '', [reference])

  const parseReference = async () => {
    const value = url.trim()
    if (!value) {
      setError('请输入公开文章链接')
      return
    }
    setParsing(true)
    setError(null)
    setReference(null)
    try {
      setReference(await layoutReferencesApi.preview(value))
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : '解析参考页面失败，请稍后重试')
    } finally {
      setParsing(false)
    }
  }

  const confirm = () => {
    if (!reference || streaming || !modelAvailable) return
    onConfirm(reference)
  }

  return (
    <Modal
      title="模仿排版"
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnHidden
      footer={(
        <div className="layout-imitation-modal-actions">
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" disabled={!reference || streaming || !modelAvailable} onClick={confirm}>
            确认并开始模仿
          </Button>
        </div>
      )}
    >
      <div className="layout-imitation-modal-content">
        <div className="layout-imitation-url-row">
          <Input
            value={url}
            disabled={parsing || streaming}
            prefix={<LinkOutlined />}
            placeholder="粘贴公开文章链接（公众号文章优先）"
            onChange={(event) => {
              setUrl(event.target.value)
              setReference(null)
              setError(null)
            }}
            onPressEnter={() => { void parseReference() }}
          />
          <Button icon={<ReloadOutlined />} loading={parsing} disabled={streaming} onClick={() => { void parseReference() }}>
            解析
          </Button>
        </div>
        {!modelAvailable && <Alert type="warning" showIcon message="请先在排版助手中选择可用模型" />}
        {error && <Alert type="error" showIcon message={error} />}
        {parsing && <div className="layout-imitation-loading"><Spin tip="正在提取参考排版…" /></div>}
        {reference && !parsing && (
          <>
            <Descriptions className="layout-imitation-meta" size="small" column={1} bordered>
              <Descriptions.Item label="参考文章">{reference.title}</Descriptions.Item>
              <Descriptions.Item label="来源">{reference.site_name}</Descriptions.Item>
              <Descriptions.Item label="提取范围">{reference.summary.extracted_from}，{reference.summary.block_count} 个排版块，{reference.summary.image_slots} 个图片位置</Descriptions.Item>
            </Descriptions>
            {reference.warning && <Alert type="warning" showIcon message={reference.warning} />}
            <div className="layout-imitation-preview">
              <iframe title="参考排版预览" sandbox="" srcDoc={srcDoc} />
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
