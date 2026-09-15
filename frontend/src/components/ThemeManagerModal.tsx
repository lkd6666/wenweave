import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Spin,
  Tag,
  message,
} from 'antd'
import {
  EditOutlined,
  EyeOutlined,
  FileImageOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { gzhThemesApi } from '../api/gzhThemes'
import { ApiError } from '../api/client'
import ModelSelector from './ModelSelector'
import type {
  AIModelItem,
  GzhThemeCreatePayload,
  GzhThemeGeneration,
  GzhThemeManagerItem,
  GzhThemeReferenceAsset,
  GzhThemeVersion,
} from '../types'
import { frameThemeDocument } from '../utils/themePreview'
import { SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import { AiImageGeneration } from './AiOutput'

interface ThemeManagerModalProps {
  open: boolean
  modelId: number | null
  models: AIModelItem[]
  onClose: () => void
  onThemesChanged: () => void | Promise<void>
}

interface WizardDraft {
  theme: GzhThemeManagerItem | null
  name: string
  slug: string
  description: string
  accentColor: string
  scenarios: string
  brief: string
}

const EMPTY_WIZARD: WizardDraft = {
  theme: null,
  name: '',
  slug: '',
  description: '',
  accentColor: '',
  scenarios: '',
  brief: '',
}

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? String(error.detail) : fallback
}

function splitScenarios(value: string) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 12)
}

function isModelConnectionError(value: string) {
  return /connection|connect|network|timeout|temporarily unavailable|service unavailable|bad gateway/i.test(value)
}

function versionLabel(version: GzhThemeVersion) {
  return `v${version.version}`
}

export default function ThemeManagerModal({ open, modelId, models, onClose, onThemesChanged }: ThemeManagerModalProps) {
  const [themes, setThemes] = useState<GzhThemeManagerItem[]>([])
  const [previews, setPreviews] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizard, setWizard] = useState<WizardDraft>(EMPTY_WIZARD)
  const [assets, setAssets] = useState<GzhThemeReferenceAsset[]>([])
  const [uploading, setUploading] = useState(false)
  const [generation, setGeneration] = useState<GzhThemeGeneration | null>(null)
  const [generationModelId, setGenerationModelId] = useState<number | null>(modelId)
  const [generationBusy, setGenerationBusy] = useState(false)
  const [adjustment, setAdjustment] = useState('')
  const [saving, setSaving] = useState(false)
  const [previewVersion, setPreviewVersion] = useState<GzhThemeVersion | null>(null)
  const [previewHtml, setPreviewHtml] = useState('')
  const [publishingId, setPublishingId] = useState<number | null>(null)
  const [advancedForm] = Form.useForm<GzhThemeCreatePayload>()
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const generationProgress = generation?.progress
  const generationProgressTotal = Math.max(0, generationProgress?.total ?? 0)
  const generationProgressCurrent = Math.min(generationProgressTotal, Math.max(0, generationProgress?.current ?? 0))
  const generationProgressPercent = generationProgressTotal
    ? Math.round((generationProgressCurrent / generationProgressTotal) * 100)
    : 0

  const loadThemes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const items = await gzhThemesApi.listManaged()
      setThemes(items)
      const previewIds = items.map((item) => item.active_version_id).filter((item): item is number => Boolean(item))
      const resolved = await Promise.all(previewIds.map(async (id) => {
        try {
          const result = await gzhThemesApi.previewVersion(id)
          return [id, result.html] as const
        } catch {
          return [id, ''] as const
        }
      }))
      setPreviews(Object.fromEntries(resolved))
    } catch (err) {
      setError(errorText(err, '自定义模板加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void loadThemes()
  }, [loadThemes, open])

  useEffect(() => {
    if (!generation || !['pending', 'running'].includes(generation.status)) return
    const timer = window.setTimeout(() => {
      void gzhThemesApi.getGeneration(generation.id)
        .then((next) => setGeneration(next))
        .catch((err) => setError(errorText(err, '主题生成状态读取失败')))
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [generation])

  useEffect(() => {
    setGenerationModelId((current) => {
      if (current !== null && models.some((model) => model.id === current)) return current
      return models.find((model) => model.id === modelId)?.id ?? models[0]?.id ?? null
    })
  }, [modelId, models])

  const closeWizard = () => {
    setWizardOpen(false)
    setWizard(EMPTY_WIZARD)
    setAssets([])
    setGeneration(null)
    setAdjustment('')
    setGenerationBusy(false)
  }

  const openWizard = (theme: GzhThemeManagerItem | null = null) => {
    setError(null)
    setAssets([])
    setGeneration(null)
    setAdjustment('')
    setWizard(theme ? {
      theme,
      name: theme.name,
      slug: theme.key.replace(/^custom:/, ''),
      description: theme.description,
      accentColor: theme.accent_color,
      scenarios: theme.scenarios.join('、'),
      brief: `请基于「${theme.name}」做一套新的版本，保留它适合的内容场景，但按以下要求调整：`,
    } : EMPTY_WIZARD)
    setWizardOpen(true)
  }

  const uploadReferences = async (files: FileList | null) => {
    if (!files?.length || uploading) return
    const selected = Array.from(files).slice(0, Math.max(0, 5 - assets.length))
    if (!selected.length) {
      message.warning('最多上传 5 张参考图')
      return
    }
    setUploading(true)
    try {
      const uploaded = await Promise.all(selected.map((file) => gzhThemesApi.uploadReferenceAsset(file)))
      setAssets((previous) => [...previous, ...uploaded])
    } catch (err) {
      message.error(errorText(err, '参考图上传失败'))
    } finally {
      setUploading(false)
      if (uploadInputRef.current) uploadInputRef.current.value = ''
    }
  }

  const createGeneration = async (extraInstruction = '') => {
    if (!generationModelId) {
      message.warning('请选择 AI 模型')
      return
    }
    const previousFailure = generation?.status === 'failed' ? generation.error_message.trim() : ''
    const previousValidationFeedback = previousFailure && !isModelConnectionError(previousFailure) ? previousFailure : ''
    const brief = [
      wizard.brief.trim(),
      previousValidationFeedback ? `上一轮服务端校验反馈（必须修复）：${previousValidationFeedback}` : '',
      extraInstruction ? `补充调整：${extraInstruction.trim()}` : '',
    ].filter(Boolean).join('\n\n')
    if (brief.length < 8) {
      message.warning('请先描述希望的模板风格')
      return
    }
    setGenerationBusy(true)
    setError(null)
    try {
      const created = await gzhThemesApi.createGeneration({
        model_id: generationModelId,
        brief,
        name_hint: wizard.name.trim(),
        slug_hint: wizard.theme ? '' : wizard.slug.trim(),
        accent_color: wizard.accentColor.trim(),
        scenarios: splitScenarios(wizard.scenarios),
        reference_asset_ids: assets.map((item) => item.id),
        ...(wizard.theme ? { theme_id: wizard.theme.id } : {}),
      })
      setGeneration(created)
      setAdjustment('')
    } catch (err) {
      setError(errorText(err, '主题生成任务创建失败'))
    } finally {
      setGenerationBusy(false)
    }
  }

  const cancelGeneration = async () => {
    if (!generation) return
    try {
      setGeneration(await gzhThemesApi.cancelGeneration(generation.id))
    } catch (err) {
      setError(errorText(err, '取消主题生成失败'))
    }
  }

  const saveDraft = async () => {
    if (!generation || generation.status !== 'succeeded') return
    setSaving(true)
    try {
      await gzhThemesApi.saveGeneration(generation.id, {
        name: wizard.name.trim(),
        slug: wizard.theme ? '' : wizard.slug.trim(),
        description: wizard.description.trim(),
        accent_color: wizard.accentColor.trim(),
        scenarios: splitScenarios(wizard.scenarios),
      })
      message.success(wizard.theme ? '新版本草稿已保存' : '模板草稿已保存')
      closeWizard()
      await loadThemes()
    } catch (err) {
      setError(errorText(err, '保存主题草稿失败'))
    } finally {
      setSaving(false)
    }
  }

  const openVersionPreview = async (version: GzhThemeVersion) => {
    setPreviewVersion(version)
    setPreviewHtml('')
    try {
      const result = await gzhThemesApi.previewVersion(version.id)
      setPreviewHtml(result.html)
    } catch (err) {
      message.error(errorText(err, '模板预览加载失败'))
    }
  }

  const publishVersion = async (version: GzhThemeVersion) => {
    setPublishingId(version.id)
    try {
      await gzhThemesApi.publishVersion(version.id)
      message.success('新版本已发布，后续文章可以使用它')
      await loadThemes()
      await onThemesChanged()
    } catch (err) {
      message.error(errorText(err, '模板发布失败'))
    } finally {
      setPublishingId(null)
    }
  }

  const archive = async (theme: GzhThemeManagerItem) => {
    try {
      await gzhThemesApi.archiveTheme(theme.id)
      message.success('模板已归档，不再出现在用户主题库中')
      await loadThemes()
      await onThemesChanged()
    } catch (err) {
      message.error(errorText(err, '归档模板失败'))
    }
  }

  const importAdvanced = async () => {
    try {
      const values = await advancedForm.validateFields()
      await gzhThemesApi.createCustomTheme({
        ...values,
        name: values.name.trim(),
        slug: values.slug.trim(),
        description: values.description.trim(),
        scenarios: Array.isArray(values.scenarios)
          ? values.scenarios.map((item) => item.trim()).filter(Boolean)
          : splitScenarios(String(values.scenarios ?? '')),
        source_markdown: values.source_markdown.trim(),
        preview_html: values.preview_html.trim(),
      })
      message.success('高级导入已保存为草稿')
      advancedForm.resetFields()
      await loadThemes()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    }
  }

  return (
    <>
      <Modal
        title="管理模板"
        open={open}
        onCancel={onClose}
        footer={<Button onClick={onClose}>关闭</Button>}
        width={980}
        destroyOnHidden
        className="theme-manager-modal"
      >
        <div className="theme-manager-toolbar">
          <div><strong>自定义模板</strong><span>用风格描述和参考图生成，发布前先预览整套组件。</span></div>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openWizard()} disabled={!models.length}>新建模板</Button>
        </div>
        {!models.length && <Alert type="info" showIcon message="暂无可用 AI 模型，请联系管理员配置" style={{ marginBottom: 12 }} />}
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        {loading ? <div className="theme-manager-loading"><Spin /></div> : themes.length ? (
          <div className="theme-manager-grid">
            {themes.map((theme) => {
              const activePreview = theme.active_version_id ? previews[theme.active_version_id] : ''
              const drafts = theme.versions.filter((version) => version.status === 'draft')
              return (
                <article className="theme-manager-card" key={theme.id}>
                  <div className="theme-manager-card-preview" style={{ borderTopColor: theme.accent_color }}>
                    {activePreview ? <iframe title={`${theme.name} 缩略预览`} sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(activePreview)} /> : <FileImageOutlined />}
                  </div>
                  <div className="theme-manager-card-body">
                    <div className="theme-manager-card-title">
                      <strong>{theme.name}</strong>
                      <Tag color={theme.status === 'published' ? 'green' : theme.status === 'archived' ? 'default' : 'gold'}>
                        {theme.status === 'published' ? `已发布 v${theme.active_version ?? 1}` : theme.status === 'archived' ? '已归档' : '草稿'}
                      </Tag>
                    </div>
                    <p>{theme.description || '尚未填写简介'}</p>
                    <div className="theme-manager-card-tags">{theme.scenarios.slice(0, 3).map((item) => <Tag key={item}>{item}</Tag>)}</div>
                    <div className="theme-manager-version-line">
                      {theme.versions.map((version) => <Button key={version.id} type="text" size="small" onClick={() => void openVersionPreview(version)}>{versionLabel(version)}{version.status === 'draft' ? ' 草稿' : ''}</Button>)}
                    </div>
                    <div className="theme-manager-card-actions">
                      {theme.active_version_id && <Button size="small" icon={<EyeOutlined />} onClick={() => {
                        const active = theme.versions.find((item) => item.id === theme.active_version_id)
                        if (active) void openVersionPreview(active)
                      }}>预览</Button>}
                      {theme.status !== 'archived' && <Button size="small" icon={<EditOutlined />} onClick={() => openWizard(theme)} disabled={!modelId}>调整</Button>}
                      {drafts.map((version) => (
                        <Popconfirm key={version.id} title={`发布 ${versionLabel(version)}？`} description="它会成为所有用户后续可选的版本。" okText="发布" cancelText="取消" onConfirm={() => void publishVersion(version)}>
                          <Button size="small" type="primary" icon={<SendOutlined />} loading={publishingId === version.id}>发布 {versionLabel(version)}</Button>
                        </Popconfirm>
                      ))}
                      {theme.status !== 'archived' && <Popconfirm title={`归档「${theme.name}」？`} description="归档后用户不能再选择它，历史文章不受影响。" okText="归档" cancelText="取消" onConfirm={() => void archive(theme)}>
                        <Button size="small" danger icon={<InboxOutlined />}>归档</Button>
                      </Popconfirm>}
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有自定义模板" />}
        <Collapse
          className="theme-manager-advanced"
          items={[{
            key: 'advanced-import',
            label: '高级：导入已有组件库',
            children: <Form form={advancedForm} layout="vertical" className="theme-manager-import-form">
              <div className="theme-manager-form-grid">
                <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入模板名称' }]}><Input /></Form.Item>
                <Form.Item name="slug" label="模板标识" rules={[{ required: true, pattern: /^[a-z0-9][a-z0-9-]*$/, message: '只支持小写字母、数字和连字符' }]}><Input /></Form.Item>
              </div>
              <Form.Item name="description" label="简介"><Input.TextArea autoSize={{ minRows: 2, maxRows: 3 }} /></Form.Item>
              <Form.Item name="scenarios" label="适用场景"><Input placeholder="用逗号分隔，例如：教程、复盘" onBlur={(event) => advancedForm.setFieldValue('scenarios', splitScenarios(event.target.value))} /></Form.Item>
              <Form.Item name="accent_color" label="主题色" initialValue="#1677ff"><Input type="color" /></Form.Item>
              <Form.Item name="source_markdown" label="组件库源文档" rules={[{ required: true, min: 200, message: '请提供至少 200 个字符的组件库' }]}><Input.TextArea className="theme-manager-source-input" autoSize={{ minRows: 8, maxRows: 16 }} /></Form.Item>
              <Form.Item name="preview_html" label="预览 HTML（可选）"><Input.TextArea className="theme-manager-source-input" autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
              <Button onClick={() => void importAdvanced()}>校验并保存草稿</Button>
            </Form>,
          }]}
        />
      </Modal>

      <Modal
        title={wizard.theme ? `调整「${wizard.theme.name}」` : '新建模板草稿'}
        open={wizardOpen}
        onCancel={closeWizard}
        footer={null}
        width={980}
        destroyOnHidden
        className="theme-wizard-modal"
      >
        <div className="theme-wizard-layout">
          <section className="theme-wizard-form">
            <label>生成模型
              <ModelSelector models={models} value={generationModelId} onChange={setGenerationModelId} disabled={Boolean(generation && ['pending', 'running'].includes(generation.status))} />
            </label>
            <label>想要的模板风格 <b>*</b></label>
            <Input.TextArea value={wizard.brief} onChange={(event) => setWizard((current) => ({ ...current, brief: event.target.value }))} maxLength={4000} autoSize={{ minRows: 7, maxRows: 12 }} placeholder="例如：深色但不压抑的技术复盘，标题像实验记录，正文留白充足，重点使用细线和数据标签。" />
            <div className="theme-manager-form-grid">
              <label>模板名称（可选）<Input value={wizard.name} onChange={(event) => setWizard((current) => ({ ...current, name: event.target.value }))} placeholder="留空时自动命名" /></label>
              {!wizard.theme && <label>模板标识（可选）<Input value={wizard.slug} onChange={(event) => setWizard((current) => ({ ...current, slug: event.target.value }))} placeholder="留空时自动生成" /></label>}
            </div>
            <div className="theme-manager-form-grid">
              <label>主题色（可选）<Input value={wizard.accentColor} onChange={(event) => setWizard((current) => ({ ...current, accentColor: event.target.value }))} placeholder="#1677ff 或“墨绿”" /></label>
              <label>适用场景（可选）<Input value={wizard.scenarios} onChange={(event) => setWizard((current) => ({ ...current, scenarios: event.target.value }))} placeholder="教程、复盘、品牌故事" /></label>
            </div>
            <div className="theme-wizard-reference-head"><span>参考图（可选，最多 5 张）</span><Button size="small" icon={<FileImageOutlined />} loading={uploading} onClick={() => uploadInputRef.current?.click()}>上传参考图</Button></div>
            <input ref={uploadInputRef} className="theme-wizard-file-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple onChange={(event) => void uploadReferences(event.target.files)} />
            {assets.length > 0 && <div className="theme-wizard-assets">{assets.map((asset) => <Tag closable key={asset.id} onClose={() => setAssets((items) => items.filter((item) => item.id !== asset.id))}>{asset.filename}</Tag>)}</div>}
            <Button type="primary" size="large" block icon={generation ? <ReloadOutlined /> : <PlusOutlined />} loading={generationBusy} disabled={!generationModelId || ['pending', 'running'].includes(generation?.status ?? '')} onClick={() => void createGeneration()}>{generation ? '按当前要求重新生成' : '生成整套模板预览'}</Button>
            {generation && ['pending', 'running'].includes(generation.status) && <Button block icon={<StopOutlined />} onClick={() => void cancelGeneration()}>停止生成</Button>}
          </section>
          <section className="theme-wizard-result">
            {generation && ['pending', 'running'].includes(generation.status) && (
              <div className="theme-wizard-progress">
                <AiImageGeneration
                  status="running"
                  title={generationProgress?.stage === 'repairing' ? '正在修复当前主题批次' : '正在生成主题组件与文章配方'}
                  detail={generationProgress?.message || '正在准备生成任务。'}
                />
                <Progress
                  percent={generationProgressPercent}
                  size="small"
                  format={() => generationProgressTotal ? `${generationProgressCurrent}/${generationProgressTotal}` : '准备中'}
                />
              </div>
            )}
            {generation?.status === 'failed' && (
              <>
                <AiImageGeneration status="error" title={isModelConnectionError(generation.error_message) ? '模型连接已中断' : '主题生成未通过检查'} detail={generation.error_message || '请调整风格描述后再次生成。'} />
                {!isModelConnectionError(generation.error_message) && <Input.TextArea value={adjustment} onChange={(event) => setAdjustment(event.target.value)} autoSize={{ minRows: 2, maxRows: 4 }} maxLength={2000} placeholder="补充调整要求，例如：所有容器使用 section，不要使用 div" />}
                <div className="theme-wizard-result-actions"><Button icon={<ReloadOutlined />} loading={generationBusy} onClick={() => void createGeneration(adjustment)}>{isModelConnectionError(generation.error_message) ? '重新连接模型' : '按检查结果修复'}</Button></div>
              </>
            )}
            {generation?.status === 'cancelled' && <AiImageGeneration status="cancelled" title="主题生成已停止" detail="可调整要求后重新生成。" />}
            {generation?.status === 'succeeded' && (
              <>
                <AiImageGeneration status="success" title="整套组件预览已生成" detail={`${generation.component_count} 个组件 · ${generation.recipe_count} 组文章配方 · 严格检查通过`} />
                <div className="theme-wizard-result-head"><div><strong>整套组件预览</strong><span>{generation.component_count} 个组件 · {generation.recipe_count} 组文章配方</span></div><Tag color="green">严格检查通过</Tag></div>
                <iframe className="theme-wizard-preview-frame" title="候选主题预览" sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(generation.preview_html, 'full')} />
                <Input.TextArea value={adjustment} onChange={(event) => setAdjustment(event.target.value)} autoSize={{ minRows: 2, maxRows: 4 }} maxLength={2000} placeholder="继续调整，例如：引用块更轻一些，不要使用目录卡片" />
                <div className="theme-wizard-result-actions"><Button icon={<ReloadOutlined />} disabled={!adjustment.trim()} onClick={() => void createGeneration(adjustment)}>按调整要求重生成</Button><Button type="primary" icon={<SendOutlined />} loading={saving} onClick={() => void saveDraft()}>保存为草稿</Button></div>
                {generation.validation.length > 0 && <div className="theme-wizard-validation">{generation.validation.filter((item) => item.level !== 'INFO').slice(0, 4).map((item, index) => <span key={`${item.message}-${index}`}>{item.message}</span>)}</div>}
              </>
            )}
            {!generation && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="填写左侧风格描述后生成整套预览" />}
          </section>
        </div>
      </Modal>

      <Modal title={previewVersion ? `${versionLabel(previewVersion)} 模板预览` : '模板预览'} open={Boolean(previewVersion)} onCancel={() => setPreviewVersion(null)} footer={null} width={840} destroyOnHidden className="theme-preview-modal">
        {previewHtml ? <iframe className="theme-preview-frame" title="模板版本预览" sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(previewHtml, 'full')} /> : <div className="theme-manager-loading"><Spin /></div>}
      </Modal>
    </>
  )
}
