import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Image, Input, InputNumber, Modal, Pagination, Radio, Select, Space, Spin, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import { CheckCircleOutlined, DeleteOutlined, EditOutlined, HistoryOutlined, PictureOutlined, ReloadOutlined, SelectOutlined, StopOutlined } from '@ant-design/icons'
import { imageGenerationsApi, type ImageGenerationWorkspaceBlock } from '../api/imageGenerations'
import { imageSearchesApi } from '../api/imageSearches'
import { modelsApi } from '../api/models'
import { chatApi } from '../api/chat'
import { ApiError } from '../api/client'
import type { AIImageModelItem, ImageGenerationItem, ImageSearchCandidate, ImageSearchOrientation, ImageSearchResult, PreviewImageTarget, SelectedElementContext } from '../types'
import { AiImageGeneration, AiInlineCitation, AiWebSearch } from './AiOutput'

const { Text, Paragraph } = Typography
const CANDIDATE_PAGE_SIZE = 6

const normalizeWorkspacePath = (value: string) => {
  const parts = value.split(' > ').map((part) => part.trim()).filter(Boolean)
  const bodyIndex = parts.findIndex((part) => /^body:nth-of-type\(\d+\)$/i.test(part))
  return bodyIndex >= 0 ? parts.slice(bodyIndex + 1).join(' > ') : parts.join(' > ')
}

export interface AppliedImageChange {
  kind: 'replace' | 'insert'
  target?: PreviewImageTarget
  anchorPath?: string
  nextUrl: string
  alt?: string
}

interface Props {
  open: boolean
  documentId: number
  sessionId: number | null
  onClose: () => void
  onApplied?: (change?: AppliedImageChange) => void
  initialModelId?: number | null
  selectedBlock?: SelectedElementContext | null
  mode?: 'generate' | 'edit'
  imageTarget?: PreviewImageTarget | null
  onRequestInsertTarget?: () => void
}

export default function AIImageGenerationModal({ open, documentId, sessionId, onClose, onApplied, initialModelId = null, selectedBlock = null, mode = 'generate', imageTarget = null, onRequestInsertTarget }: Props) {
  const [models, setModels] = useState<AIImageModelItem[]>([])
  const [generations, setGenerations] = useState<ImageGenerationItem[]>([])
  const [modelId, setModelId] = useState<number | null>(null)
  const [purpose, setPurpose] = useState<'cover' | 'body'>('body')
  const [prompt, setPrompt] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [aspectRatio, setAspectRatio] = useState<'square' | 'portrait' | 'landscape'>('landscape')
  const [quality, setQuality] = useState('auto')
  const [savingSettings, setSavingSettings] = useState(false)
  const [creating, setCreating] = useState(false)
  const [loading, setLoading] = useState(false)
  const [workspace, setWorkspace] = useState<{ revision: string; blocks: ImageGenerationWorkspaceBlock[] } | null>(null)
  const [insertBlockId, setInsertBlockId] = useState('')
  const [resolvedPreviewBlock, setResolvedPreviewBlock] = useState<ImageGenerationWorkspaceBlock | null>(null)
  const [candidatePage, setCandidatePage] = useState(1)
  const [activeTab, setActiveTab] = useState<'search' | 'generate'>('search')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchOrientation, setSearchOrientation] = useState<ImageSearchOrientation>('any')
  const [searchResult, setSearchResult] = useState<ImageSearchResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [applyingSearchId, setApplyingSearchId] = useState('')
  const searchPageCacheRef = useRef(new Map<string, ImageSearchResult>())
  const searchPageRequestsRef = useRef(new Map<string, Promise<ImageSearchResult>>())
  const searchDocumentIdRef = useRef(documentId)

  const selectedModel = models.find((model) => model.id === modelId) ?? null
  const replacesCurrentImage = imageTarget !== null
  const editingCurrentImage = replacesCurrentImage && mode === 'edit'
  const activeGeneration = generations.find((item) => item.status === 'pending' || item.status === 'running')
  // The API returns generations newest first. Only show an error for the
  // current latest task; an older failed attempt must not remain above a new
  // successful result.
  const latestGeneration = generations[0] ?? null
  const latestFailedGeneration = latestGeneration?.status === 'failed' && latestGeneration.error_message
    ? latestGeneration
    : null
  const latestCancelledGeneration = latestGeneration?.status === 'cancelled'
    ? latestGeneration
    : null
  const selectedPreviewBlock = useMemo(() => {
    if (!selectedBlock || !workspace) return null
    const selector = selectedBlock.selector.trim()
    const locatorPath = selectedBlock.locator?.path?.trim() || selector
    const selectedPaths = [selector, locatorPath]
      .map(normalizeWorkspacePath)
      .filter(Boolean)
    const candidates = workspace.blocks.filter((block) => {
      if (block.block_id === selector) return true
      const blockPath = normalizeWorkspacePath(block.path)
      return selectedPaths.some((path) => blockPath === path || path.startsWith(`${blockPath} > `))
    })
    return candidates.sort((left, right) => normalizeWorkspacePath(right.path).length - normalizeWorkspacePath(left.path).length)[0] ?? null
  }, [selectedBlock, workspace])
  const selectedWorkspaceBlock = useMemo(() => {
    if (!insertBlockId) return null
    return workspace?.blocks.find((block) => block.block_id === insertBlockId)
      ?? (resolvedPreviewBlock?.block_id === insertBlockId ? resolvedPreviewBlock : null)
  }, [insertBlockId, resolvedPreviewBlock, workspace])
  const allAssets = useMemo(() => generations.flatMap((generation) => generation.assets.map((asset) => ({ asset, generation }))), [generations])
  const totalCandidatePages = Math.max(1, Math.ceil(allAssets.length / CANDIDATE_PAGE_SIZE))
  const currentCandidatePage = Math.min(candidatePage, totalCandidatePages)
  const pagedAssets = useMemo(() => {
    const start = (currentCandidatePage - 1) * CANDIDATE_PAGE_SIZE
    return allAssets.slice(start, start + CANDIDATE_PAGE_SIZE)
  }, [allAssets, currentCandidatePage])

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

  const loadSearchPage = useCallback((query: string, page: number, orientation: ImageSearchOrientation) => {
    const key = JSON.stringify([documentId, query, page, orientation])
    const cached = searchPageCacheRef.current.get(key)
    if (cached) return Promise.resolve(cached)
    const pending = searchPageRequestsRef.current.get(key)
    if (pending) return pending
    const request = imageSearchesApi.search(documentId, { query, page, orientation }).then((result) => {
      searchPageCacheRef.current.set(key, result)
      return result
    }).finally(() => {
      searchPageRequestsRef.current.delete(key)
    })
    searchPageRequestsRef.current.set(key, request)
    return request
  }, [documentId])

  const saveSettings = async () => {
    if (!sessionId || !modelId) return
    setSavingSettings(true)
    try { await chatApi.updateImageSettings(documentId, sessionId, { image_model_id: modelId }); message.success('已保存 Agent 图片模型') } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '保存图片模型失败') } finally { setSavingSettings(false) }
  }

  useEffect(() => {
    if (searchDocumentIdRef.current === documentId) return
    searchDocumentIdRef.current = documentId
    searchPageCacheRef.current.clear()
    searchPageRequestsRef.current.clear()
    setSearchQuery('')
    setSearchOrientation('any')
    setSearchResult(null)
  }, [documentId])
  useEffect(() => {
    if (!open) return
    setModelId(initialModelId)
    setCandidatePage(1)
    setActiveTab(mode === 'edit' ? 'generate' : 'search')
    setPurpose('body')
    void refresh()
  }, [open, documentId, initialModelId, imageTarget, mode, refresh])
  useEffect(() => {
    if (candidatePage > totalCandidatePages) setCandidatePage(totalCandidatePages)
  }, [candidatePage, totalCandidatePages])
  useEffect(() => {
    if (!open) return
    setInsertBlockId(selectedPreviewBlock?.block_id ?? '')
  }, [open, selectedPreviewBlock?.block_id])
  useEffect(() => {
    if (!open || !selectedBlock) {
      setResolvedPreviewBlock(null)
      return
    }
    let cancelled = false
    void imageGenerationsApi.resolveWorkspace(documentId, selectedBlock).then((resolved) => {
      if (cancelled) return
      setResolvedPreviewBlock(resolved.block)
      setInsertBlockId(resolved.block.block_id)
    }).catch(() => {
      if (!cancelled) setResolvedPreviewBlock(null)
    })
    return () => { cancelled = true }
  }, [documentId, open, selectedBlock])
  const activeGenerationId = activeGeneration?.id
  useEffect(() => {
    if (!open || !activeGenerationId) return
    const timer = window.setInterval(() => { void imageGenerationsApi.get(documentId, activeGenerationId).then((next) => setGenerations((items) => items.map((item) => item.id === next.id ? next : item))).catch(() => undefined) }, 1800)
    return () => window.clearInterval(timer)
  }, [open, documentId, activeGenerationId])

  const create = async () => {
    if (!modelId || prompt.trim().length < 3) { message.warning('请选择图片模型并填写图片描述'); return }
    if (editingCurrentImage && !(selectedModel?.operations ?? []).includes('edit')) { message.warning('当前图片模型不支持 AI 图片编辑，请切换模型'); return }
    setCreating(true)
    try {
      const generation = await imageGenerationsApi.create(documentId, {
        model_id: modelId,
        session_id: sessionId,
        purpose: replacesCurrentImage ? 'body' : purpose,
        operation: editingCurrentImage ? 'edit' : 'generate',
        prompt: prompt.trim(),
        quantity,
        aspect_ratio: aspectRatio,
        quality,
        source_image_url: imageTarget?.sourceUrl,
        target_image_index: imageTarget?.imageIndex,
      })
      setGenerations((items) => [generation, ...items])
      setCandidatePage(1)
      setPrompt('')
    } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '创建图片任务失败') } finally { setCreating(false) }
  }

  const apply = async (generation: ImageGenerationItem, asset: ImageGenerationItem['assets'][number]) => {
    const targetBlock = selectedWorkspaceBlock
    // In AI 换图 mode, existing candidates from regular AI 配图 tasks can
    // also be used for the fixed image target shown at the top of the modal.
    const replacesImage = generation.target_image_index >= 0 || replacesCurrentImage
    if (!replacesImage && generation.purpose !== 'cover' && !targetBlock) { message.warning('请选择插入位置'); return }
    try {
      const payload = generation.purpose === 'cover' && !replacesImage ? { target: 'cover' as const } : replacesImage ? {
        target: 'body' as const,
        revision: workspace?.revision ?? '',
        source_image_url: generation.target_image_index >= 0 ? generation.source_image_url : imageTarget?.sourceUrl,
        source_image_hash: generation.target_image_index >= 0 ? generation.source_image_hash : '',
        target_image_index: generation.target_image_index >= 0 ? generation.target_image_index : imageTarget?.imageIndex,
        alt: imageTarget?.alt || generation.prompt.slice(0, 120),
      } : {
        target: 'body' as const,
        revision: workspace?.revision ?? '',
        anchor_block_id: targetBlock?.block_id ?? '',
        expected_hash: targetBlock?.expected_hash ?? '',
        alt: generation.prompt.slice(0, 120),
      }
      const next = await imageGenerationsApi.apply(documentId, generation.id, asset.id, payload)
      setGenerations((items) => items.map((item) => item.id === next.id ? next : item))
      message.success(replacesImage ? '已替换当前图片' : generation.purpose === 'cover' ? '已设为文章封面' : '已插入正文')
      const replacementTarget = generation.target_image_index >= 0
        ? { sourceUrl: generation.source_image_url, imageIndex: generation.target_image_index, alt: imageTarget?.alt || '' }
        : imageTarget
      onApplied?.(replacesImage && replacementTarget
        ? { kind: 'replace', target: replacementTarget, nextUrl: asset.url }
        : !replacesImage && generation.purpose !== 'cover' && targetBlock
          ? { kind: 'insert', anchorPath: targetBlock.path, nextUrl: asset.url, alt: generation.prompt.slice(0, 120) }
          : undefined)
      // Applying an inline image changes the document revision and regenerates
      // all source-based block IDs. Refresh the workspace before another
      // candidate is applied so its anchor/hash pair is current.
      if (!replacesImage && generation.purpose !== 'cover') {
        const nextWorkspace = await imageGenerationsApi.workspace(documentId)
        setWorkspace(nextWorkspace)
        const refreshedTarget = targetBlock && nextWorkspace.blocks.find((block) => (
          block.path === targetBlock.path && block.expected_hash === targetBlock.expected_hash
        ))
        setInsertBlockId(refreshedTarget?.block_id ?? '')
      }
    } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '应用图片失败') }
  }

  const searchImages = async (page = 1) => {
    const query = searchQuery.trim()
    if (query.length < 2) { message.warning('请输入至少 2 个字符的搜图关键词'); return }
    setSearching(true)
    try {
      const result = await loadSearchPage(query, page, searchOrientation)
      setSearchResult(result)
      if (result.next_page) {
        void loadSearchPage(query, result.next_page, searchOrientation).catch(() => undefined)
      }
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '搜图服务暂时不可用')
    } finally {
      setSearching(false)
    }
  }

  const applySearched = async (candidate: ImageSearchCandidate) => {
    const targetBlock = selectedWorkspaceBlock
    if (!replacesCurrentImage && purpose === 'body' && !targetBlock) {
      message.warning('请选择插入位置')
      return
    }
    setApplyingSearchId(candidate.id)
    try {
      const payload = replacesCurrentImage ? {
        candidate_token: candidate.token,
        target: 'body' as const,
        revision: workspace?.revision ?? '',
        source_image_url: imageTarget?.sourceUrl,
        target_image_index: imageTarget?.imageIndex,
        alt: imageTarget?.alt || candidate.title,
      } : purpose === 'cover' ? {
        candidate_token: candidate.token,
        target: 'cover' as const,
        alt: candidate.title,
      } : {
        candidate_token: candidate.token,
        target: 'body' as const,
        revision: workspace?.revision ?? '',
        anchor_block_id: targetBlock?.block_id ?? '',
        expected_hash: targetBlock?.expected_hash ?? '',
        alt: candidate.title,
      }
      const result = await imageSearchesApi.apply(documentId, payload)
      message.success(replacesCurrentImage ? '已替换当前图片' : purpose === 'cover' ? '已设为文章封面' : '已插入正文')
      onApplied?.(replacesCurrentImage && imageTarget
        ? { kind: 'replace', target: imageTarget, nextUrl: result.url }
        : purpose === 'body' && targetBlock
          ? { kind: 'insert', anchorPath: targetBlock.path, nextUrl: result.url, alt: candidate.title }
          : undefined)
      if (result.target !== 'cover') {
        const nextWorkspace = await imageGenerationsApi.workspace(documentId)
        setWorkspace(nextWorkspace)
        const refreshedTarget = targetBlock && nextWorkspace.blocks.find((block) => (
          block.path === targetBlock.path && block.expected_hash === targetBlock.expected_hash
        ))
        setInsertBlockId(refreshedTarget?.block_id ?? '')
      }
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '应用搜索图片失败')
    } finally {
      setApplyingSearchId('')
    }
  }

  const remove = async (generation: ImageGenerationItem, assetId: string) => {
    try { await imageGenerationsApi.removeAsset(documentId, generation.id, assetId); setGenerations((items) => items.map((item) => item.id === generation.id ? { ...item, assets: item.assets.filter((asset) => asset.id !== assetId) } : item)) } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '删除候选图失败') }
  }

  const cancel = async () => {
    if (!activeGeneration) return
    try { const next = await imageGenerationsApi.cancel(documentId, activeGeneration.id); setGenerations((items) => items.map((item) => item.id === next.id ? next : item)) } catch (error) { message.error(error instanceof ApiError ? String(error.detail) : '取消任务失败') }
  }

  const insertTarget = !replacesCurrentImage && purpose === 'body' && <div className="ai-image-generation-insert-target">
    <div className="ai-image-generation-insert-target-copy">
      <Text strong>正文插入位置</Text>
      {selectedWorkspaceBlock
        ? <><Text type="secondary">图片会紧跟在下面这段内容之后</Text><Paragraph ellipsis={{ rows: 2 }} className="ai-image-generation-insert-target-preview">{selectedWorkspaceBlock.text || '（空段落）'}</Paragraph></>
        : <Text type="secondary">尚未选择位置。点击“在预览中选择”，再点文章中要插入到其后的段落。</Text>}
    </div>
    <Space className="ai-image-generation-insert-target-actions" wrap>
      <Button icon={<SelectOutlined />} type={selectedWorkspaceBlock ? 'default' : 'primary'} onClick={() => onRequestInsertTarget?.()}>在预览中选择</Button>
      {selectedWorkspaceBlock && <Button size="small" onClick={() => setInsertBlockId('')}>重新选择</Button>}
    </Space>
  </div>

  const searchTab = <Space orientation="vertical" size={12} style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="全网图片版权需自行确认" description="搜索结果来自互联网，应用前请核对原作者、来源页和授权范围。" />
    <Space.Compact style={{ width: '100%' }}>
      <Input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onPressEnter={() => void searchImages()} placeholder="输入主题、地点、人物或产品关键词" />
      <Button type="primary" loading={searching} onClick={() => void searchImages()}>搜图</Button>
    </Space.Compact>
    <Space wrap>
      <Select value={searchOrientation} onChange={setSearchOrientation} options={[{ value: 'any', label: '不限方向' }, { value: 'landscape', label: '横图' }, { value: 'portrait', label: '竖图' }, { value: 'square', label: '方图' }]} />
      {searchResult && <Text type="secondary">第 {searchResult.page} 页 · {searchResult.items.length} 张</Text>}
    </Space>
    {searching && !searchResult && <AiWebSearch query={searchQuery || '正在搜索图片'} running />}
    {searchResult?.items.length ? <>
      <AiWebSearch query={searchQuery} sources={searchResult.items.slice(0, 4).map((candidate) => ({ label: candidate.title || candidate.engine || '图片来源', href: candidate.source_page_url }))} />
      <div className="ai-image-generation-candidates">{searchResult.items.map((candidate) => {
        const actionDisabled = Boolean(applyingSearchId) || (!replacesCurrentImage && purpose === 'body' && !selectedWorkspaceBlock)
        const actionLabel = replacesCurrentImage ? '替换当前图片' : purpose === 'cover' ? '设为封面' : '插入到所选位置'
        return <article key={candidate.id} className="ai-image-generation-candidate">
          <Image className="ai-image-generation-candidate-preview" src={candidate.preview_url} width="100%" height={150} style={{ objectFit: 'cover' }} preview />
          <Tooltip title={candidate.title} placement="topLeft">
            <Paragraph className="ai-image-generation-candidate-prompt" ellipsis={{ rows: 2 }}>{candidate.title || '图片搜索结果'}</Paragraph>
          </Tooltip>
          <div className="ai-image-generation-candidate-tags">
            <Tag bordered={false}>{candidate.engine}</Tag>
            {candidate.width && candidate.height && <Tag bordered={false}>{candidate.width} × {candidate.height}</Tag>}
          </div>
          <div className="ai-image-generation-candidate-actions">
            <Button size="small" type="primary" loading={applyingSearchId === candidate.id} disabled={actionDisabled} onClick={() => void applySearched(candidate)}>{actionLabel}</Button>
            <span className="ai-image-search-source-link"><AiInlineCitation href={candidate.source_page_url}>来源</AiInlineCitation></span>
          </div>
        </article>
      })}</div>
      <Pagination
        className="ai-image-generation-candidates-pagination"
        size="small"
        current={searchResult.page}
        pageSize={12}
        total={searchResult.next_page ? searchResult.page * 12 + 12 : (searchResult.page - 1) * 12 + searchResult.items.length}
        showLessItems
        showSizeChanger={false}
        hideOnSinglePage
        onChange={(page) => void searchImages(page)}
      />
    </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={searching ? '正在搜索图片' : '输入关键词开始搜图'} />}
  </Space>

  const generateTab = models.length === 0 ? <Empty description="暂无可用图片模型；搜图不受影响" /> : <Space orientation="vertical" size={12} style={{ width: '100%' }}>
    <Space wrap>
      <Select style={{ minWidth: 200 }} value={modelId ?? undefined} onChange={setModelId} options={models.map((model) => ({ value: model.id, label: `${model.display_name}${editingCurrentImage && !(model.operations ?? []).includes('edit') ? '（不支持编辑）' : ''}`, disabled: editingCurrentImage && !(model.operations ?? []).includes('edit') }))} />
    </Space>
    <Input.TextArea rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={editingCurrentImage ? '描述希望如何修改当前图片，例如保留人物和构图，改为水彩风格' : replacesCurrentImage ? '描述要替换成的新画面主体、风格、色彩和构图' : '描述画面主体、风格、色彩和构图'} />
    <Space wrap>
      <Select value={aspectRatio} onChange={setAspectRatio} options={(selectedModel?.supported_aspect_ratios.length ? selectedModel.supported_aspect_ratios : ['landscape', 'portrait', 'square']).map((value) => ({ value, label: value === 'landscape' ? '横图' : value === 'portrait' ? '竖图' : '方图' }))} />
      <Select value={quality} onChange={setQuality} options={(selectedModel?.supported_qualities.length ? selectedModel.supported_qualities : ['auto', 'medium', 'high']).map((value) => ({ value, label: `质量 ${value}` }))} />
      <InputNumber min={1} max={4} value={quantity} onChange={(value) => setQuantity(value ?? 1)} addonBefore="数量" />
      <Button type="primary" loading={creating} disabled={Boolean(activeGeneration)} onClick={() => void create()}>{editingCurrentImage ? '生成编辑候选' : '生成候选图'}</Button>
      {activeGeneration && <Button icon={<StopOutlined />} onClick={() => void cancel()}>取消任务</Button>}
      <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>刷新</Button>
      {sessionId && <Button size="small" loading={savingSettings} onClick={() => void saveSettings()}>保存 Agent 图片模型</Button>}
    </Space>
    {replacesCurrentImage && <Text type="secondary">候选图不会自动修改正文；请选择候选后点击“替换当前图片”。</Text>}
    {activeGeneration && <AiImageGeneration status="running" title={editingCurrentImage ? '正在生成图片编辑候选' : '正在生成候选图'} detail="生成完成后会自动显示在下方，可随时取消任务。" />}
    {latestFailedGeneration && <AiImageGeneration status="error" title="最近一次图片生成失败" detail={latestFailedGeneration.error_message} />}
    {latestCancelledGeneration && <AiImageGeneration status="cancelled" title="最近一次图片生成已取消" detail="可调整描述后重新生成候选图。" />}
    {allAssets.some(({ asset }) => asset.is_currently_applied) && <AiImageGeneration status="success" title="候选图已应用至文章" detail="当前文章已使用标记为“已在文章中”的候选图。" />}
    {allAssets.length === 0 && !activeGeneration ? <AiImageGeneration status="idle" title="等待生成图片" detail="生成结果会显示在这里。" /> : <>
      <div className="ai-image-generation-candidates">{pagedAssets.map(({ asset, generation }) => {
        const insertsBody = !replacesCurrentImage && generation.target_image_index < 0 && generation.purpose !== 'cover'
        // Reusing a generated image as an inline illustration is intentional:
        // the same asset can appear in multiple sections. "is_applied" only
        // protects retention/deletion, while replacement and cover actions
        // remain protected against redundant application.
        const actionDisabled = insertsBody
          ? !selectedWorkspaceBlock
          : asset.is_currently_applied
        const actionLabel = replacesCurrentImage || generation.target_image_index >= 0 ? '替换当前图片' : generation.purpose === 'cover' ? '设为封面' : '插入到所选位置'
        const actionHint = insertsBody && !selectedWorkspaceBlock
          ? '请先在上方选择插入位置'
          : insertsBody && asset.is_currently_applied
            ? '再次插入到所选位置'
            : asset.is_currently_applied
              ? '图片已在文章中'
              : actionLabel
        return <article key={asset.id} className="ai-image-generation-candidate">
          <Image className="ai-image-generation-candidate-preview" src={asset.url} width="100%" height={150} style={{ objectFit: 'cover' }} preview />
          <Tooltip title={generation.prompt} placement="topLeft"><Paragraph className="ai-image-generation-candidate-prompt" ellipsis={{ rows: 2 }}>{generation.prompt}</Paragraph></Tooltip>
          <div className="ai-image-generation-candidate-actions"><Tooltip title={actionHint}><span className="ai-image-generation-candidate-action-wrap"><Button size="small" type="primary" disabled={actionDisabled} onClick={() => void apply(generation, asset)}>{actionLabel}</Button></span></Tooltip><Tooltip title={asset.is_applied ? '图片已被历史版本引用，不能删除' : '删除候选图'}><Button size="small" danger icon={<DeleteOutlined />} aria-label="删除候选图" disabled={asset.is_applied} onClick={() => void remove(generation, asset.id)} /></Tooltip></div>
          <div className="ai-image-generation-candidate-tags">{generation.operation === 'edit' && <Tag bordered={false} color="blue" icon={<EditOutlined />}>AI 编辑</Tag>}{asset.is_currently_applied ? <Tag bordered={false} color="green" icon={<CheckCircleOutlined />}>已在文章中</Tag> : asset.is_applied && <Tag bordered={false} color="gold" icon={<HistoryOutlined />}>历史版本已引用</Tag>}</div>
        </article>
      })}</div>
      <Pagination className="ai-image-generation-candidates-pagination" size="small" current={currentCandidatePage} pageSize={CANDIDATE_PAGE_SIZE} total={allAssets.length} showLessItems showSizeChanger={false} hideOnSinglePage onChange={setCandidatePage} />
    </>}
  </Space>

  return <Modal title={<Space><PictureOutlined />{editingCurrentImage ? 'AI 图片编辑' : replacesCurrentImage ? '替换图片' : '配图'}</Space>} open={open} onCancel={onClose} footer={null} width={760}>
    {loading ? <Spin /> : <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      {replacesCurrentImage && <Space align="start" style={{ width: '100%' }}><Image src={imageTarget.sourceUrl} width={96} height={72} style={{ objectFit: 'cover' }} preview /><Text type="secondary">将替换当前文章中的这张图片。找到候选后，仍需手动确认替换。</Text></Space>}
      {!replacesCurrentImage && <Radio.Group value={purpose} onChange={(event) => setPurpose(event.target.value)} options={[{ label: '正文配图', value: 'body' }, { label: '文章封面', value: 'cover' }]} />}
      {insertTarget}
      <Tabs activeKey={editingCurrentImage ? 'generate' : activeTab} onChange={(key) => setActiveTab(key as 'search' | 'generate')} items={[
        ...(!editingCurrentImage ? [{ key: 'search', label: '搜图', children: searchTab }] : []),
        { key: 'generate', label: 'AI 生图', children: generateTab },
      ]} />
    </Space>}
  </Modal>
}
