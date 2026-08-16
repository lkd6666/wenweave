import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Descriptions, Input, Modal, Segmented, Spin } from 'antd'
import {
  LinkOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { layoutReferencesApi } from '../api/layoutReferences'
import { ApiError } from '../api/client'
import type { LayoutReferenceImitationStrength, LayoutReferencePreview } from '../types'
import {
  LayoutCaptureBridge,
  getWechatVerificationDetail,
  resolveWechatCaptureUrl,
  type WechatVerificationDetail,
} from '../utils/layoutCaptureBridge'
import { frameDocumentWithNewWindowLinks, SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import { WechatCaptureFallback, type CaptureUiState } from './WechatCaptureFallback'

export { LayoutCaptureInstallGuide } from './WechatCaptureFallback'

interface LayoutImitationModalProps {
  open: boolean
  streaming: boolean
  modelAvailable: boolean
  onClose: () => void
  onConfirm: (
    reference: LayoutReferencePreview,
    assetsConfirmed: boolean,
    selectedAssetIds: string[],
    imitationStrength: LayoutReferenceImitationStrength,
  ) => void
}

function previewDocument(referenceHtml: string) {
  return frameDocumentWithNewWindowLinks(`<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:" />
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #fff; }
    body { padding: 16px 14px 28px; color: #182230; font: 15px/1.85 -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; overflow-wrap: anywhere; }
    article, section, div, figure, blockquote { max-width: 100%; }
    p { margin: 0 0 1em; }
    h1, h2, h3, h4, h5, h6 { line-height: 1.45; }
    table { width: 100%; max-width: 100%; border-collapse: collapse; }
    td, th { min-width: 0; }
  </style>
</head>
<body>${referenceHtml}</body>
</html>`)
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
  const [wechatFallback, setWechatFallback] = useState<WechatVerificationDetail | null>(null)
  const [captureState, setCaptureState] = useState<CaptureUiState>('idle')
  const [captureError, setCaptureError] = useState<string | null>(null)
  const [assetsConfirmed, setAssetsConfirmed] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [imitationStrength, setImitationStrength] = useState<LayoutReferenceImitationStrength>('structure')
  const bridgeRef = useRef<LayoutCaptureBridge | null>(null)
  const requestVersionRef = useRef(0)

  useEffect(() => {
    if (open) {
      const bridge = new LayoutCaptureBridge((event) => {
        if (event.type === 'status') {
          setCaptureState(event.status)
          setCaptureError(null)
          return
        }
        if (event.type === 'error') {
          setCaptureState('error')
          setCaptureError(event.message)
          return
        }
        setReference(event.preview)
        setUrl(event.preview.canonical_url)
        setSelectedAssetIds(event.preview.assets.filter((asset) => asset.default_selected).map((asset) => asset.asset_id))
        setAssetsConfirmed(false)
        setWechatFallback(null)
        setCaptureState('idle')
        setCaptureError(null)
        setError(null)
      })
      bridgeRef.current = bridge
      return () => {
        requestVersionRef.current += 1
        bridge.dispose()
        if (bridgeRef.current === bridge) bridgeRef.current = null
      }
    }

    setUrl('')
    setReference(null)
    setError(null)
    setWechatFallback(null)
    setCaptureState('idle')
    setCaptureError(null)
    setParsing(false)
    setAssetsConfirmed(false)
    setSelectedAssetIds([])
    setImitationStrength('structure')
  }, [open])

  const srcDoc = useMemo(() => reference ? previewDocument(reference.preview_html) : '', [reference])

  const parseReference = async () => {
    const value = url.trim()
    if (!value) {
      setError('请输入公开文章链接')
      return
    }
    const requestVersion = requestVersionRef.current + 1
    requestVersionRef.current = requestVersion
    bridgeRef.current?.cancel()
    setParsing(true)
    setError(null)
    setWechatFallback(null)
    setCaptureState('idle')
    setCaptureError(null)
    setReference(null)
    setAssetsConfirmed(false)
    setSelectedAssetIds([])
    try {
      const parsed = await layoutReferencesApi.preview(value)
      if (requestVersionRef.current !== requestVersion) return
      setReference(parsed)
      setSelectedAssetIds(parsed.assets.filter((asset) => asset.default_selected).map((asset) => asset.asset_id))
    } catch (err) {
      if (requestVersionRef.current !== requestVersion) return
      const verification = getWechatVerificationDetail(err)
      if (verification) {
        const captureUrl = resolveWechatCaptureUrl(verification.url, value) || verification.url
        const normalizedVerification = { ...verification, url: captureUrl }
        setWechatFallback(normalizedVerification)
        setUrl(captureUrl)
        setCaptureState('checking')
        const connection = await bridgeRef.current?.connect('layout_reference') ?? 'missing'
        if (requestVersionRef.current === requestVersion) {
          setCaptureState(connection === 'available' ? 'ready' : connection)
        }
      } else {
        setError(err instanceof ApiError ? String(err.detail) : '解析参考页面失败，请稍后重试')
      }
    } finally {
      if (requestVersionRef.current === requestVersion) setParsing(false)
    }
  }

  const detectExtension = async () => {
    setCaptureState('checking')
    setCaptureError(null)
    const connection = await bridgeRef.current?.connect('layout_reference') ?? 'missing'
    setCaptureState(connection === 'available' ? 'ready' : connection)
  }

  const startBrowserCapture = async () => {
    if (!wechatFallback || !bridgeRef.current) return
    setCaptureState('opening')
    setCaptureError(null)
    try {
      const session = await layoutReferencesApi.createCaptureSession(wechatFallback.url)
      bridgeRef.current.startSession(session)
    } catch (err) {
      setCaptureState('error')
      setCaptureError(err instanceof ApiError ? String(err.detail) : '创建浏览器采集会话失败，请重试')
    }
  }

  const hasSelectedAssets = selectedAssetIds.length > 0

  const toggleAsset = (assetId: string, checked: boolean) => {
    setSelectedAssetIds((current) => {
      const next = checked ? [...new Set([...current, assetId])] : current.filter((id) => id !== assetId)
      if (!next.length) setAssetsConfirmed(false)
      return next
    })
  }

  const confirm = () => {
    if (!reference || streaming || !modelAvailable || (hasSelectedAssets && !assetsConfirmed)) return
    onConfirm(reference, assetsConfirmed, selectedAssetIds, imitationStrength)
  }

  return (
    <Modal
      title="模仿排版"
      open={open}
      onCancel={onClose}
      width={760}
      className="layout-imitation-modal"
      destroyOnHidden
      footer={(
        <div className="layout-imitation-modal-actions">
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            disabled={!reference || streaming || !modelAvailable || (hasSelectedAssets && !assetsConfirmed)}
            onClick={confirm}
          >
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
              requestVersionRef.current += 1
              bridgeRef.current?.cancel()
              setUrl(event.target.value)
              setReference(null)
              setError(null)
              setWechatFallback(null)
              setCaptureState('idle')
              setCaptureError(null)
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
        {wechatFallback && !parsing && (
          <WechatCaptureFallback
            verification={wechatFallback}
            state={captureState}
            error={captureError}
            purpose="layout_reference"
            onDetect={() => { void detectExtension() }}
            onStart={() => { void startBrowserCapture() }}
          />
        )}
        {reference && !parsing && (
          <>
            <Descriptions className="layout-imitation-meta" size="small" column={1} bordered>
              <Descriptions.Item label="参考文章">{reference.title}</Descriptions.Item>
              <Descriptions.Item label="来源">{reference.site_name}</Descriptions.Item>
              <Descriptions.Item label="提取范围">
                {reference.summary.extracted_from}，{reference.summary.block_count} 个排版块，{reference.summary.image_slots} 个图片位置，已加载 {reference.summary.image_assets} 个素材，已选择 {selectedAssetIds.length} 个
              </Descriptions.Item>
            </Descriptions>
            <div className="layout-imitation-strength">
              <span>模仿强度</span>
              <Segmented
                value={imitationStrength}
                options={[
                  { label: '风格', value: 'style' },
                  { label: '结构', value: 'structure' },
                  { label: '最大还原', value: 'maximum' },
                ]}
                onChange={(value) => setImitationStrength(value as LayoutReferenceImitationStrength)}
              />
              <small>
                {imitationStrength === 'style' && '保留当前结构，主要借鉴颜色、标题和装饰风格。'}
                {imitationStrength === 'structure' && '强力复刻组件层次、关键 flex/对齐、间距和主要尺寸。'}
                {imitationStrength === 'maximum' && '严格复刻复杂容器、flex 关系、尺寸、定位与层叠。'}
              </small>
            </div>
            {reference.warning && <Alert type="warning" showIcon message={reference.warning} />}
            {reference.assets.length > 0 && (
              <div className="layout-imitation-assets" aria-label="参考图片素材选择">
                {reference.assets.map((asset) => {
                  const selected = selectedAssetIds.includes(asset.asset_id)
                  return (
                    <label className={`layout-imitation-asset${selected ? ' is-selected' : ''}`} key={asset.asset_id}>
                      <Checkbox checked={selected} onChange={(event) => toggleAsset(asset.asset_id, event.target.checked)} />
                      <img src={asset.preview_url} alt="" />
                      <span className="layout-imitation-asset-meta">
                        <b>{asset.role}</b>
                        <small>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : asset.content_type}，使用 {asset.usage_count} 次</small>
                      </span>
                    </label>
                  )
                })}
              </div>
            )}
            {hasSelectedAssets && (
              <Checkbox checked={assetsConfirmed} onChange={(event) => setAssetsConfirmed(event.target.checked)}>
                我确认已取得所选参考图片素材的复用授权
              </Checkbox>
            )}
            <div className="layout-imitation-preview">
              <iframe title="参考排版预览" sandbox={SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW} referrerPolicy="no-referrer" srcDoc={srcDoc} />
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
