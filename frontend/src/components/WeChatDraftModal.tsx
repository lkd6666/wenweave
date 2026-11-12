import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useOperationScope } from '../hooks/useOperationScope'
import ReactCrop, { centerCrop, makeAspectCrop, type PercentCrop } from 'react-image-crop'
import 'react-image-crop/dist/ReactCrop.css'
import {
  Alert,
  Button,
  Divider,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Steps,
  Switch,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import { HistoryOutlined, SendOutlined, UploadOutlined } from '@ant-design/icons'
import { documentsApi, type WeChatDraftPushProgressEvent } from '../api/documents'
import { ApiError } from '../api/client'
import { wechatAccountsApi } from '../api/wechatAccounts'
import type {
  WeChatArticleMetadata,
  WeChatAvailableAccount,
  DocumentDetail,
  WeChatDraftRecord,
} from '../types'

type CropMode = 'pic_crop_235_1' | 'pic_crop_1_1'
type DraftPushStage = WeChatDraftPushProgressEvent['stage']
type DraftSyncMode = 'auto' | 'create'

interface DraftPushProgress {
  stage: DraftPushStage
  percent: number
  detail: string
  status: 'active' | 'success' | 'exception'
}

interface DraftPushActivity extends DraftPushProgress {
  id: number
}

interface WeChatDraftModalProps {
  open: boolean
  documentId: number
  disabled: boolean
  onClose: () => void
  onMetadataSaved: (metadata: WeChatArticleMetadata, title: string) => void
  onDocumentRefreshed: (document: DocumentDetail) => void
}

const CROP_MODE_LABELS: Record<CropMode, string> = {
  pic_crop_235_1: '2.35 : 1',
  pic_crop_1_1: '1 : 1',
}

const DRAFT_PUSH_STAGE_INDEX: Record<DraftPushStage, number> = {
  validating: 0,
  metadata: 1,
  token: 2,
  'body-images': 3,
  cover: 4,
  draft: 5,
  history: 6,
  completed: 6,
}

const DRAFT_PUSH_STEPS = [
  { title: '校验' },
  { title: '保存信息' },
  { title: '公众号授权' },
  { title: '正文图片' },
  { title: '封面' },
  { title: '写入草稿' },
  { title: '保存记录' },
]

const DRAFT_PUSH_STAGE_LABEL: Record<DraftPushStage, string> = {
  validating: '校验推送条件',
  metadata: '保存草稿信息',
  token: '获取公众号授权',
  'body-images': '处理正文图片',
  cover: '处理封面素材',
  draft: '写入微信草稿',
  history: '刷新推送记录',
  completed: '推送完成',
}

function cropAreaToValue(area: PercentCrop) {
  const format = (value: number) => Number((value / 100).toFixed(6)).toString()
  return [format(area.x), format(area.y), format(area.x + area.width), format(area.y + area.height)].join('_')
}

function cropValueToArea(value: string | undefined): PercentCrop | undefined {
  if (!value) return undefined
  const [x1, y1, x2, y2] = value.split('_').map(Number)
  if (![x1, y1, x2, y2].every(Number.isFinite) || x1 < 0 || y1 < 0 || x2 > 1 || y2 > 1 || x1 >= x2 || y1 >= y2) {
    return undefined
  }
  return {
    unit: '%',
    x: x1 * 100,
    y: y1 * 100,
    width: (x2 - x1) * 100,
    height: (y2 - y1) * 100,
  }
}

function defaultCropArea(naturalWidth: number, naturalHeight: number, aspect: number): PercentCrop {
  return centerCrop(
    makeAspectCrop({ unit: '%', width: 100 }, aspect, naturalWidth, naturalHeight),
    naturalWidth,
    naturalHeight,
  )
}

function normalizeCropArea(
  area: PercentCrop | undefined,
  aspect: number,
  naturalWidth: number,
  naturalHeight: number,
): PercentCrop {
  if (!area || !area.width || !area.height) {
    return defaultCropArea(naturalWidth, naturalHeight, aspect)
  }

  const imageAspect = naturalWidth / naturalHeight
  const areaAspect = area.width * imageAspect / area.height
  if (Math.abs(areaAspect - aspect) > 0.01) {
    return defaultCropArea(naturalWidth, naturalHeight, aspect)
  }

  const width = Math.min(area.width, area.height * aspect / imageAspect)
  const height = width * imageAspect / aspect
  const centerX = area.x + area.width / 2
  const centerY = area.y + area.height / 2

  return {
    unit: '%',
    width,
    height,
    x: Math.min(Math.max(centerX - width / 2, 0), 100 - width),
    y: Math.min(Math.max(centerY - height / 2, 0), 100 - height),
  }
}

function initialMetadata(metadata: WeChatArticleMetadata, documentTitle: string): WeChatArticleMetadata {
  return {
    ...metadata,
    title: documentTitle.trim(),
  }
}

function progressActivityLabel(activity: DraftPushActivity): string {
  const imageIndex = activity.detail.match(/正文图片\s+(\d+\/\d+)/)?.[1]
  return imageIndex ? `正文图片 ${imageIndex}` : DRAFT_PUSH_STAGE_LABEL[activity.stage]
}

interface CoverCropPreviewProps {
  source: string
  area: PercentCrop | undefined
  aspect: number
  label: string
}

function CoverCropPreview({ source, area, aspect, label }: CoverCropPreviewProps) {
  const imageStyle = area
    ? {
        width: `${10000 / area.width}%`,
        maxWidth: 'none',
        transform: `translate(${-area.x}%, ${-area.y}%)`,
        transformOrigin: 'top left',
      }
    : undefined
  return (
    <figure className="wechat-cover-preview-item">
      <div className="wechat-cover-preview-frame" style={{ aspectRatio: String(aspect) }}>
        <img className={area ? 'is-cropped' : undefined} src={source} alt={`${label} 封面预览`} style={imageStyle} />
      </div>
      <figcaption>{label}</figcaption>
    </figure>
  )
}

export default function WeChatDraftModal({
  open,
  documentId,
  disabled,
  onClose,
  onMetadataSaved,
  onDocumentRefreshed,
}: WeChatDraftModalProps) {
  const [form] = Form.useForm()
  const [history, setHistory] = useState<WeChatDraftRecord[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [availableAccounts, setAvailableAccounts] = useState<WeChatAvailableAccount[]>([])
  const [refreshingData, setRefreshingData] = useState(open)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [draftPushProgress, setDraftPushProgress] = useState<DraftPushProgress | null>(null)
  const [draftPushActivities, setDraftPushActivities] = useState<DraftPushActivity[]>([])
  const [uploadingCover, setUploadingCover] = useState(false)
  const [cropMode, setCropMode] = useState<CropMode>('pic_crop_235_1')
  const [crop, setCrop] = useState<PercentCrop | undefined>()
  const pushInFlightRef = useRef(false)
  const ownsOperation = useOperationScope(`${documentId}:${open}:${disabled}`)
  useEffect(() => {
    pushInFlightRef.current = false
    setSaving(false)
    setSending(false)
    setUploadingCover(false)
  }, [ownsOperation])
  const coverImageRef = useRef<HTMLImageElement>(null)
  const coverImageDimensionsRef = useRef<{ width: number; height: number } | null>(null)
  const progressRef = useRef<HTMLElement>(null)
  const progressActivityIdRef = useRef(0)
  const hasAutoScrolledProgressRef = useRef(false)
  const selectedAccountId = Form.useWatch('account_id', form) as number | undefined
  const latestSuccessfulDraft = useMemo(
    () => history.find((item) => item.account_id === Number(selectedAccountId) && item.status === 'succeeded' && item.media_id),
    [history, selectedAccountId],
  )

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true)
    try {
      const result = await documentsApi.listWeChatDrafts(documentId)
      if (ownsOperation()) setHistory(result)
    } catch (err) {
      if (!ownsOperation()) return
      message.error(err instanceof ApiError ? String(err.detail) : '加载草稿记录失败')
    } finally {
      if (ownsOperation()) setLoadingHistory(false)
    }
  }, [documentId, ownsOperation])

  useEffect(() => {
    if (!open || disabled || pushInFlightRef.current) return
    let cancelled = false

    setCropMode('pic_crop_235_1')
    setCrop(undefined)
    coverImageDimensionsRef.current = null
    setDraftPushProgress(null)
    setDraftPushActivities([])
    hasAutoScrolledProgressRef.current = false
    setHistory([])
    setAvailableAccounts([])
    setRefreshingData(true)
    setRefreshError(null)

    const refreshOpenData = async () => {
      try {
        const [document, nextAccounts, nextHistory] = await Promise.all([
          documentsApi.get(documentId),
          wechatAccountsApi.available(),
          documentsApi.listWeChatDrafts(documentId),
        ])
        if (cancelled) return

        const next = initialMetadata(document.wechat_metadata, document.title)
        setAvailableAccounts(nextAccounts)
        setHistory(nextHistory)
        form.setFieldsValue({
          ...next,
          only_fans_can_comment: Boolean(next.need_open_comment && next.only_fans_can_comment),
          account_id: nextAccounts[0]?.id,
        })
      } catch (err) {
        if (cancelled) return
        const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '无法刷新推送信息'
        setRefreshError(detail)
      } finally {
        if (!cancelled) setRefreshingData(false)
      }
    }

    void refreshOpenData()
    return () => {
      cancelled = true
    }
  }, [disabled, documentId, form, open, refreshKey])

  useEffect(() => {
    if (!draftPushProgress || hasAutoScrolledProgressRef.current) return
    const frame = window.requestAnimationFrame(() => {
      progressRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end', inline: 'nearest' })
      hasAutoScrolledProgressRef.current = true
    })
    return () => window.cancelAnimationFrame(frame)
  }, [draftPushProgress])

  const interactionDisabled = disabled || refreshingData || Boolean(refreshError)

  const collectMetadata = async (): Promise<WeChatArticleMetadata> => {
    const values = await form.validateFields([
      'title',
      'author',
      'digest',
      'content_source_url',
      'cover_url',
      'pic_crop_235_1',
      'pic_crop_1_1',
      'need_open_comment',
      'only_fans_can_comment',
    ])
    return {
      title: (values.title ?? '').trim(),
      author: (values.author ?? '').trim(),
      digest: (values.digest ?? '').trim(),
      content_source_url: (values.content_source_url ?? '').trim(),
      cover_url: values.cover_url ?? '',
      pic_crop_235_1: values.pic_crop_235_1 ?? '',
      pic_crop_1_1: values.pic_crop_1_1 ?? '',
      need_open_comment: Boolean(values.need_open_comment),
      only_fans_can_comment: Boolean(values.need_open_comment && values.only_fans_can_comment),
    }
  }

  const saveMetadata = async (): Promise<WeChatArticleMetadata | null> => {
    if (!ownsOperation() || interactionDisabled) return null
    try {
      setSaving(true)
      const next = await collectMetadata()
      if (!ownsOperation()) return null
      const updated = await documentsApi.update(documentId, { title: next.title, wechat_metadata: next })
      if (!ownsOperation()) return null
      onMetadataSaved(updated.wechat_metadata, updated.title)
      message.success('公众号草稿信息已保存')
      return updated.wechat_metadata
    } catch (err) {
      if (!ownsOperation()) return null
      if (err instanceof ApiError) message.error(String(err.detail))
      return null
    } finally {
      if (ownsOperation()) setSaving(false)
    }
  }

  const send = async (syncMode: DraftSyncMode) => {
    if (!ownsOperation() || interactionDisabled) return
    let progress: DraftPushProgress = {
      stage: 'validating',
      percent: 3,
      detail: '正在检查当前文章是否已保存，并校验推送表单…',
      status: 'active',
    }
    const updateProgress = (next: Omit<DraftPushProgress, 'status'> & { status?: DraftPushProgress['status'] }) => {
      if (!ownsOperation()) return
      progress = { ...next, status: next.status ?? 'active' }
      setDraftPushProgress(progress)
      setDraftPushActivities((activities) => [
        ...activities,
        { ...progress, id: ++progressActivityIdRef.current },
      ].slice(-8))
    }
    try {
      pushInFlightRef.current = true
      setSending(true)
      setDraftPushProgress(progress)
      setDraftPushActivities([{ ...progress, id: ++progressActivityIdRef.current }])
      const syncValues = await form.validateFields(['account_id'])
      if (!ownsOperation()) return
      const accountId = Number(syncValues.account_id)
      updateProgress({ stage: 'metadata', percent: 9, detail: '目标公众号已确认，正在保存微信标题、封面与评论设置…' })
      const next = await saveMetadata()
      if (!ownsOperation()) return
      if (!next) {
        updateProgress({ stage: 'metadata', percent: 9, detail: '草稿信息保存失败，请检查表单内容后重试', status: 'exception' })
        return
      }
      updateProgress({
        stage: 'validating',
        percent: 18,
        detail: syncMode === 'auto'
          ? '草稿信息已保存，正在自动确定新建或覆盖的目标草稿…'
          : '草稿信息已保存，正在创建新的微信草稿…',
      })
      const result = await documentsApi.streamWeChatDraft(documentId, { accountId, syncMode }, (event) => {
        updateProgress({ ...event })
      })
      const completedVerb = result.sync_mode === 'update' ? '草稿已覆盖' : '草稿已创建'
      updateProgress({ stage: 'history', percent: 99, detail: `${completedVerb}，正在刷新文章和本篇推送记录…` })
      const [refreshedDocument] = await Promise.all([documentsApi.get(documentId), loadHistory()])
      if (!ownsOperation()) return
      onDocumentRefreshed(refreshedDocument)
      updateProgress({ stage: 'completed', percent: 100, detail: `${completedVerb}，推送记录已刷新`, status: 'success' })
      message.success(result.sync_mode === 'update'
        ? `已覆盖「${result.account_name}」草稿箱中的目标图文`
        : `已创建草稿，可在「${result.account_name}」草稿箱查看`)
    } catch (err) {
      if (!ownsOperation()) return
      const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '创建公众号草稿失败'
      updateProgress({ ...progress, detail: `同步失败：${detail}`, status: 'exception' })
      await loadHistory()
      message.error(detail)
    } finally {
      if (ownsOperation()) {
        setSending(false)
        pushInFlightRef.current = false
      }
    }
  }

  const handleCoverUpload = async (file: File) => {
    setUploadingCover(true)
    try {
      const result = await documentsApi.uploadWeChatCover(documentId, file)
      if (!ownsOperation()) return
      form.setFieldsValue({
        cover_url: result.url,
        pic_crop_235_1: '',
        pic_crop_1_1: '',
      })
      coverImageDimensionsRef.current = null
      setCrop(undefined)
      message.success('封面已上传')
    } catch (err) {
      if (!ownsOperation()) return
      message.error(err instanceof ApiError ? String(err.detail) : '封面上传失败')
    } finally {
      if (ownsOperation()) setUploadingCover(false)
    }
  }

  const coverUrl = Form.useWatch('cover_url', form) as string | undefined
  const commentsEnabled = Form.useWatch('need_open_comment', form) as boolean | undefined
  const crop235Value = Form.useWatch('pic_crop_235_1', form) as string | undefined
  const crop1Value = Form.useWatch('pic_crop_1_1', form) as string | undefined
  const cropAspect = cropMode === 'pic_crop_235_1' ? 2.35 : 1
  const crop235Area = useMemo(() => cropValueToArea(crop235Value), [crop235Value])
  const crop1Area = useMemo(() => cropValueToArea(crop1Value), [crop1Value])

  useLayoutEffect(() => {
    const image = coverImageRef.current
    if (!coverUrl || !image) return

    let cancelled = false
    const initializeCrops = () => {
      if (cancelled || !image.naturalWidth || !image.naturalHeight) return
      const { naturalWidth, naturalHeight } = image
      coverImageDimensionsRef.current = { width: naturalWidth, height: naturalHeight }
      const crop235 = normalizeCropArea(cropValueToArea(form.getFieldValue('pic_crop_235_1')), 2.35, naturalWidth, naturalHeight)
      const crop1 = normalizeCropArea(cropValueToArea(form.getFieldValue('pic_crop_1_1')), 1, naturalWidth, naturalHeight)
      form.setFieldsValue({
        pic_crop_235_1: cropAreaToValue(crop235),
        pic_crop_1_1: cropAreaToValue(crop1),
      })
      setCrop(cropMode === 'pic_crop_235_1' ? crop235 : crop1)
    }

    if (image.complete) initializeCrops()
    else image.addEventListener('load', initializeCrops, { once: true })

    return () => {
      cancelled = true
      image.removeEventListener('load', initializeCrops)
    }
  }, [coverUrl, cropMode, form])

  const draftPushProgressPanel = draftPushProgress && (
    <section ref={progressRef} className={`wechat-draft-progress is-${draftPushProgress.status}`} aria-live="polite">
      <div className="wechat-draft-progress-heading">
        <div>
          <strong>{draftPushProgress.status === 'exception' ? '推送未完成' : draftPushProgress.status === 'success' ? '推送完成' : `当前：${DRAFT_PUSH_STAGE_LABEL[draftPushProgress.stage]}`}</strong>
          <span className="wechat-draft-progress-stage">第 {DRAFT_PUSH_STAGE_INDEX[draftPushProgress.stage] + 1} / {DRAFT_PUSH_STEPS.length} 步</span>
        </div>
        <span>{draftPushProgress.percent}%</span>
      </div>
      <Progress percent={draftPushProgress.percent} status={draftPushProgress.status === 'exception' ? 'exception' : draftPushProgress.status === 'success' ? 'success' : 'active'} showInfo={false} />
      <div className="wechat-draft-progress-detail">{draftPushProgress.detail}</div>
      <Steps className="wechat-draft-progress-steps" size="small" responsive={false} current={DRAFT_PUSH_STAGE_INDEX[draftPushProgress.stage]} items={DRAFT_PUSH_STEPS} />
      <ol className="wechat-draft-progress-log" aria-label="推送执行明细">
        {draftPushActivities.map((activity, index) => {
          const isLatest = index === draftPushActivities.length - 1
          return (
            <li key={activity.id} className={activity.status === 'exception' ? 'is-exception' : isLatest && activity.status === 'active' ? 'is-active' : 'is-complete'}>
              <span>{progressActivityLabel(activity)}</span>
              <span>{activity.detail}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )

  return (
    <Modal
      title="推送至公众号草稿箱"
      open={open}
      className="wechat-draft-modal"
      wrapClassName="wechat-draft-modal-wrap"
      width={760}
      destroyOnHidden
      onCancel={onClose}
      footer={(
        <Space className="wechat-draft-footer-actions" wrap>
          <Button onClick={onClose}>关闭</Button>
          {refreshError && <Button onClick={() => setRefreshKey((value) => value + 1)}>重新加载</Button>}
          <Button loading={saving} disabled={interactionDisabled || sending || uploadingCover} onClick={() => void saveMetadata()}>保存信息</Button>
          <Button
            disabled={interactionDisabled || uploadingCover || sending || availableAccounts.length === 0}
            onClick={() => void send('create')}
          >
            新建草稿
          </Button>
          <Tooltip title={refreshingData
            ? '正在刷新最新文章与封面信息'
            : refreshError
              ? '请先重新加载推送信息'
              : disabled
                ? '请先保存正文中的手动修改后再推送'
            : availableAccounts.length === 0
              ? '暂无可用公众号账号'
              : latestSuccessfulDraft
                ? '自动覆盖该公众号最近一次成功同步的草稿'
                : '首次同步将创建新的公众号草稿'}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={sending}
              disabled={interactionDisabled || uploadingCover || sending || availableAccounts.length === 0}
              onClick={() => void send('auto')}
            >
              {sending ? '同步中' : latestSuccessfulDraft ? '更新上次草稿' : '同步草稿'}
            </Button>
          </Tooltip>
        </Space>
      )}
    >
      {refreshingData && <Alert type="info" showIcon message="正在刷新文章、封面和公众号信息…" style={{ marginBottom: 16 }} />}
      {refreshError && <Alert type="error" showIcon message={`刷新推送信息失败：${refreshError}，请重新加载后再试。`} style={{ marginBottom: 16 }} />}
      {disabled && <Alert type="warning" showIcon message="正文有未保存修改，请先保存后再推送，以确保草稿使用当前内容。" style={{ marginBottom: 16 }} />}
      {!refreshingData && availableAccounts.length === 0 && <Alert type="warning" showIcon message="暂无可用公众号账号。请联系管理员配置账号并授予推送权限。" style={{ marginBottom: 16 }} />}
      <Form
        form={form}
        disabled={interactionDisabled || sending || uploadingCover}
        layout="vertical"
        initialValues={{ need_open_comment: false, only_fans_can_comment: false }}
        onValuesChange={(changedValues) => {
          if (changedValues.need_open_comment === false) form.setFieldValue('only_fans_can_comment', false)
        }}
      >
        <Form.Item name="account_id" label="目标公众号" rules={[{ required: true, message: '请选择目标公众号' }]}>
          <Select disabled={interactionDisabled || sending} placeholder="选择公众号" options={availableAccounts.map((account) => ({ value: account.id, label: account.name }))} />
        </Form.Item>
        <Alert
          type="info"
          showIcon
          message={loadingHistory
            ? '正在读取本篇同步记录…'
            : latestSuccessfulDraft
              ? `本次同步将自动覆盖该公众号最近一次成功草稿（${new Date(latestSuccessfulDraft.created_at).toLocaleString()}）。`
              : '该公众号尚无本篇成功同步记录，首次同步将创建新草稿。'}
          style={{ marginBottom: 16 }}
        />
        <div className="wechat-draft-meta-grid">
          <Form.Item name="title" label="文章标题" extra="与系统文章标题同步，用于微信草稿" rules={[{ required: true, whitespace: true, message: '请输入文章标题' }, { max: 64, message: '微信标题不能超过 64 个字' }]}>
            <Input maxLength={64} showCount placeholder="系统文章标题" />
          </Form.Item>
          <Form.Item name="author" label="作者" rules={[{ max: 16, message: '作者不能超过 16 个字' }]}>
            <Input maxLength={16} showCount placeholder="可选" />
          </Form.Item>
        </div>
        <Form.Item name="digest" label="摘要" rules={[{ max: 120, message: '摘要不能超过 120 个字' }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={120} showCount placeholder="可选；留空时不显示摘要，也不会从正文抓取" />
        </Form.Item>
        <Form.Item name="content_source_url" label="原文链接" rules={[{ type: 'url', message: '请输入以 http:// 或 https:// 开头的链接' }]}>
          <Input placeholder="https://example.com/article" />
        </Form.Item>
        <Form.Item name="cover_url" hidden rules={[{ required: true, message: '请上传封面' }]}><Input /></Form.Item>
        <Form.Item name="pic_crop_235_1" hidden><Input /></Form.Item>
        <Form.Item name="pic_crop_1_1" hidden><Input /></Form.Item>
        <div className="wechat-cover-section">
          <div className="wechat-cover-heading">
            <strong>封面</strong>
            <Upload
              accept="image/jpeg,image/png,image/gif,image/bmp"
              showUploadList={false}
              disabled={interactionDisabled || uploadingCover}
              beforeUpload={(file) => {
                if (file.size > 10 * 1024 * 1024) {
                  message.error('封面不能超过 10MB')
                  return Upload.LIST_IGNORE
                }
                return true
              }}
              customRequest={({ file, onSuccess, onError }) => {
                void handleCoverUpload(file as File).then(() => onSuccess?.({}), (error: Error) => onError?.(error))
              }}
            >
              <Button icon={<UploadOutlined />} loading={uploadingCover}>上传封面</Button>
            </Upload>
          </div>
          {coverUrl ? (
            <>
              <div className="wechat-cover-crop-tools">
                <Segmented
                  value={cropMode}
                  onChange={(value) => {
                    const nextMode = value as CropMode
                    const nextAspect = nextMode === 'pic_crop_235_1' ? 2.35 : 1
                    const dimensions = coverImageDimensionsRef.current
                    const savedCrop = cropValueToArea(form.getFieldValue(nextMode))
                    const nextCrop = dimensions
                      ? normalizeCropArea(savedCrop, nextAspect, dimensions.width, dimensions.height)
                      : savedCrop
                    setCropMode(nextMode)
                    setCrop(nextCrop)
                    if (nextCrop) form.setFieldValue(nextMode, cropAreaToValue(nextCrop))
                  }}
                  options={[
                    { label: CROP_MODE_LABELS.pic_crop_235_1, value: 'pic_crop_235_1' },
                    { label: CROP_MODE_LABELS.pic_crop_1_1, value: 'pic_crop_1_1' },
                  ]}
                />
                <span>拖动或调整选框以保存 {CROP_MODE_LABELS[cropMode]} 裁剪范围</span>
              </div>
              <div className="wechat-cover-cropper">
                <ReactCrop
                  key={`${coverUrl}:${cropMode}`}
                  className="wechat-cover-selection"
                  crop={crop}
                  aspect={cropAspect}
                  keepSelection
                  ruleOfThirds
                  onChange={(_pixelCrop, percentCrop) => {
                    setCrop(percentCrop)
                    form.setFieldValue(cropMode, cropAreaToValue(percentCrop))
                  }}
                >
                  <img
                    ref={coverImageRef}
                    src={coverUrl}
                    alt="公众号封面裁剪"
                  />
                </ReactCrop>
              </div>
              <div className="wechat-cover-preview-grid">
                <CoverCropPreview source={coverUrl} area={crop235Area} aspect={2.35} label="2.35 : 1" />
                <CoverCropPreview source={coverUrl} area={crop1Area} aspect={1} label="1 : 1" />
              </div>
            </>
          ) : <div className="wechat-cover-empty">上传 JPG、PNG、GIF 或 BMP 封面，最大 10MB</div>}
        </div>
        <Divider />
        <div className="wechat-comment-settings">
          <Form.Item name="need_open_comment" label="开启评论" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="only_fans_can_comment" label="仅粉丝可评论" valuePropName="checked"><Switch disabled={!commentsEnabled} checkedChildren="仅粉丝" unCheckedChildren="所有人" /></Form.Item>
        </div>
      </Form>
      <Divider titlePlacement="start"><Space><HistoryOutlined />推送记录</Space></Divider>
      <div className="wechat-draft-history">
        <Spin spinning={loadingHistory}>
          {history.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未推送过草稿" /> : (
            <List
              size="small"
              dataSource={history}
              renderItem={(item) => (
                <List.Item className="wechat-draft-history-item">
                  <div>
                    <Space wrap size={[6, 4]}>
                      <strong>{item.account_name}</strong>
                      <span>操作人：{item.created_by_name || '已删除用户'}</span>
                      <Tag color={item.status === 'succeeded' ? 'green' : 'red'}>{item.status === 'succeeded' ? '已同步' : '失败'}</Tag>
                      <Tag color={item.sync_mode === 'update' ? 'orange' : 'blue'}>{item.sync_mode === 'update' ? '覆盖原图文' : '新建图文'}</Tag>
                      <span>{new Date(item.created_at).toLocaleString()}</span>
                    </Space>
                    <div>{item.article_title}</div>
                    {item.status === 'succeeded' && item.media_id && <div className="wechat-draft-history-detail">media_id: {item.media_id}</div>}
                    {item.status === 'failed' && <div className="wechat-draft-history-error">{item.error_message}</div>}
                  </div>
                </List.Item>
              )}
            />
          )}
        </Spin>
      </div>
      {draftPushProgressPanel}
    </Modal>
  )
}
