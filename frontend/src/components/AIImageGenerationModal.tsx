import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Empty, Image, Input, InputNumber, Modal, Radio, Select, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { DeleteOutlined, PictureOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { imageGenerationsApi } from '../api/imageGenerations'
import { modelsApi } from '../api/models'
import { chatApi } from '../api/chat'
import { ApiError } from '../api/client'
import type { AIImageModelItem, ImageGenerationItem, SelectedElementContext } from '../types'

const { Text, Paragraph } = Typography

interface Props {
  open: boolean
  documentId: number
  sessionId: number | null
  onClose: () => void
  onApplied?: () => void
  initialModelId?: number | null
  initialAutoEnabled?: boolean
  selectedBlock?: SelectedElementContext | null
}

export default function AIImageGenerationModal({ open, documentId, sessionId, onClose, onApplied, initialModelId = null, initialAutoEnabled = false, selectedBlock = null }: Props) {
  const [models, setModels] = useState<AIImageModelItem[]>([])
  const [generations, setGenerations] = useState<ImageGenerationItem[]>([])
  const [modelId, setModelId] = useState<number | null>(null)
  const [purpose, setPurpose] = useState<'cover' | 'body'>('cover')
  const [prompt, setPrompt] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [aspectRatio, setAspectRatio] = useState<'square' | 'portrait' | 'landscape'>('landscape')
  const [quality, setQuality] = useState('auto')
  const [autoEnabled, setAutoEnabled] = useState(initialAutoEnabled)
  const [savingSettings, setSavingSettings] = useState(false)
  const [creating, setCreating] = useState(false)
  const [loading, setLoading] = useState(false)
  const [workspace, setWorkspace] = useState<{ revision: string; blocks: Array<{ block_id: string; expected_hash: string; text: string }> } | null>(null)

  const selectedModel = models.find((model) => model.id === modelId) ?? null
  const activeGeneration = generations.find((item) => item.status === 'pending' || item.status === 'running')
  const latestFailedGeneration = generations.find((item) => item.status === 'failed' && item.error_message)
  const selectedWorkspaceBlock = selectedBlock ? workspace?.blocks.find((block) => block.block_id === selectedBlock.selector) : null
  const allAssets = useMemo(() => generations.flatMap((generation) => generation.assets.map((asset) => ({ asset, generation }))), [generations])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [nextModels, nextGenerations, nextWorkspace] = await Promise.all([modelsApi.listImage(), imageGenerationsApi.list(documentId), imageGenerationsApi.workspace(documentId)])
      setModels(nextModels)
      setGenerations(nextGenerations)
      setWorkspace(nextWorkspace)
      if (nextModels.length) {
        const preferredModelId = initialModelId ?? nextModels.find((item) => item.is_default)?.id ?? nextModels[0].id
        setModelId((currentModelId) => currentModelId ?? preferredModelId)
      }
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '加载图片模型失败')
    } finally {
      setLoading(false)
    }
  }, [documentId, initialModelId])

  const saveSettings = async () => {
    if (!sessionId || !modelId) return
    setSavingSettings(true)
    try { await chatApi.updateImageSettings(documentId, sessionId, { image_model_id: modelId, auto_image_generation_enabled: autoEnabled }); message.success(autoEnabled ? '已允许本次对话自动配图' : '会话图片设置已保存') } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '保存会话图片设置失败') } finally { setSavingSettings(false) }
  }

  useEffect(() => {
    if (!open) return
    setModelId(initialModelId)
    setAutoEnabled(initialAutoEnabled)
    void refresh()
  }, [open, documentId, initialModelId, initialAutoEnabled, refresh])
  const activeGenerationId = activeGeneration?.id
  useEffect(() => {
    if (!open || !activeGenerationId) return
    const timer = window.setInterval(() => { void imageGenerationsApi.get(documentId, activeGenerationId).then((next) => setGenerations((items) => items.map((item) => item.id === next.id ? next : item))).catch(() => undefined) }, 1800)
    return () => window.clearInterval(timer)
  }, [open, documentId, activeGenerationId])

  const create = async () => {
    if (!modelId || prompt.trim().length < 3) { message.warning('请选择图片模型并填写图片描述'); return }
    setCreating(true)
    try {
      const generation = await imageGenerationsApi.create(documentId, { model_id: modelId, session_id: sessionId, purpose, prompt: prompt.trim(), quantity, aspect_ratio: aspectRatio, quality })
      setGenerations((items) => [generation, ...items])
      setPrompt('')
    } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '创建图片任务失败') } finally { setCreating(false) }
  }

  const apply = async (generation: ImageGenerationItem, assetId: string) => {
    const targetBlock = selectedWorkspaceBlock
    if (generation.purpose !== 'cover' && !targetBlock) { message.info('请先在预览中选择目标段落后应用'); return }
    try {
      const payload = generation.purpose === 'cover' ? { target: 'cover' as const } : {
        target: 'body' as const,
        revision: workspace?.revision ?? '',
        anchor_block_id: targetBlock?.block_id ?? '',
        expected_hash: targetBlock?.expected_hash ?? '',
        alt: generation.prompt.slice(0, 120),
      }
      const next = await imageGenerationsApi.apply(documentId, generation.id, assetId, payload)
      setGenerations((items) => items.map((item) => item.id === next.id ? next : item))
      message.success(generation.purpose === 'cover' ? '已设为文章封面' : '已插入正文')
      onApplied?.()
    } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '应用图片失败') }
  }

  const remove = async (generation: ImageGenerationItem, assetId: string) => {
    try { await imageGenerationsApi.removeAsset(documentId, generation.id, assetId); setGenerations((items) => items.map((item) => item.id === generation.id ? { ...item, assets: item.assets.filter((asset) => asset.id !== assetId) } : item)) } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '删除候选图失败') }
  }

  const cancel = async () => {
    if (!activeGeneration) return
    try { const next = await imageGenerationsApi.cancel(documentId, activeGeneration.id); setGenerations((items) => items.map((item) => item.id === next.id ? next : item)) } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '取消任务失败') }
  }

  return <Modal title={<Space><PictureOutlined />AI 配图</Space>} open={open} onCancel={onClose} footer={null} width={760} destroyOnHidden>
    {loading ? <Spin /> : models.length === 0 ? <Empty description="暂无可用图片模型，请联系管理员配置" /> : <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Space wrap>
        <Select style={{ minWidth: 200 }} value={modelId ?? undefined} onChange={setModelId} options={models.map((model) => ({ value: model.id, label: model.display_name }))} />
        <Radio.Group value={purpose} onChange={(event) => setPurpose(event.target.value)} options={[{ label: '生成封面', value: 'cover' }, { label: '正文候选', value: 'body' }]} />
      </Space>
      <Input.TextArea rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="描述画面主体、风格、色彩和构图" />
      <Space wrap>
        <Select value={aspectRatio} onChange={setAspectRatio} options={(selectedModel?.supported_aspect_ratios.length ? selectedModel.supported_aspect_ratios : ['landscape', 'portrait', 'square']).map((value) => ({ value, label: value === 'landscape' ? '横图' : value === 'portrait' ? '竖图' : '方图' }))} />
        <Select value={quality} onChange={setQuality} options={(selectedModel?.supported_qualities.length ? selectedModel.supported_qualities : ['auto', 'medium', 'high']).map((value) => ({ value, label: `质量 ${value}` }))} />
        <InputNumber min={1} max={4} value={quantity} onChange={(value) => setQuantity(value ?? 1)} addonBefore="数量" />
        <Button type="primary" loading={creating} disabled={Boolean(activeGeneration)} onClick={() => void create()}>生成候选图</Button>
        {activeGeneration && <Button icon={<StopOutlined />} onClick={() => void cancel()}>取消任务</Button>}
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>刷新</Button>
      </Space>
      {sessionId && <Space><Switch checked={autoEnabled} onChange={setAutoEnabled} /><Text>允许 Agent 自动配图</Text><Button size="small" loading={savingSettings} onClick={() => void saveSettings()}>保存会话设置</Button></Space>}
      {purpose === 'body' && <Text type="secondary">候选图不会自动修改正文；应用前请在预览中选中目标段落。当前选择：{selectedBlock?.text?.slice(0, 40) || '未选择'}</Text>}
      {latestFailedGeneration && <Alert
        type="error"
        showIcon
        message="最近一次图片生成失败"
        description={<Text style={{ display: 'block', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{latestFailedGeneration.error_message}</Text>}
      />}
      {allAssets.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成结果会显示在这里" /> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 12 }}>{allAssets.map(({ asset, generation }) => <div key={asset.id} style={{ border: '1px solid #e8e8e8', padding: 8 }}><Image src={asset.url} width="100%" height={150} style={{ objectFit: 'cover' }} preview /><Paragraph ellipsis={{ rows: 2 }} style={{ margin: '8px 0 4px' }}>{generation.prompt}</Paragraph><Space><Button size="small" type="primary" disabled={asset.is_applied || (generation.purpose === 'body' && !selectedWorkspaceBlock)} onClick={() => void apply(generation, asset.id)}>{generation.purpose === 'cover' ? '设为封面' : '插入正文'}</Button><Button size="small" danger icon={<DeleteOutlined />} disabled={asset.is_applied} onClick={() => void remove(generation, asset.id)} /></Space>{asset.is_applied && <Tag color="green" style={{ marginLeft: 6 }}>已应用</Tag>}</div>)}</div>}
    </Space>}
  </Modal>
}
