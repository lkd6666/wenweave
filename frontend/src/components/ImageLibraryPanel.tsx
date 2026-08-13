import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Alert, Button, Checkbox, Dropdown, Empty, Image, Input, InputNumber, Modal, Pagination, Popconfirm, Select, Space, Spin, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import { DeleteOutlined, EditOutlined, EyeOutlined, MoreOutlined, PictureOutlined, ReloadOutlined, StopOutlined, UploadOutlined } from '@ant-design/icons'
import { imageLibraryApi } from '../api/imageLibrary'
import { imageGenerationsApi } from '../api/imageGenerations'
import { imageSearchesApi } from '../api/imageSearches'
import { modelsApi } from '../api/models'
import { ApiError } from '../api/client'
import type { AIImageModelItem, ImageGenerationItem, ImageLibraryAsset, ImageLibrarySource, ImageSearchCandidate, ImageSearchOrientation, ImageSearchResult, PreviewImageTarget } from '../types'

const { Text } = Typography
const PAGE_SIZE = 18

interface Props {
  documentId: number
  sessionId: number | null
  initialModelId?: number | null
  disabled?: boolean
  applicationTarget: 'image' | 'block' | 'caret' | null
  selectedImage: PreviewImageTarget | null
  onApply: (url: string, alt: string) => boolean
  onSetCover: (assetId: string) => Promise<void>
  command?: { id: number; tab: 'library' | 'search' | 'generate'; editCurrentImage?: boolean } | null
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? String(error.detail) : fallback
}

const sourceLabels: Record<ImageLibrarySource, string> = { upload: '上传', ai: 'AI', search: '搜图' }

function ImagePreviewAction({ src, alt }: { src: string; alt: string }) {
  const [open, setOpen] = useState(false)
  return <>
    <Tooltip title="预览图片">
      <Button size="small" aria-label={`预览图片：${alt}`} icon={<EyeOutlined />} onClick={() => setOpen(true)} />
    </Tooltip>
    <span className="image-library-preview-source" aria-hidden="true">
      <Image src={src} alt={alt} preview={{ visible: open, onVisibleChange: setOpen }} />
    </span>
  </>
}

function ImageCardTitle({ text }: { text: string }) {
  const value = text.trim() || '图片'
  return <Tooltip title={value} placement="topLeft" mouseEnterDelay={0.2}>
    <strong>{value}</strong>
  </Tooltip>
}

function MobileImageActions({ onRename, onRemove }: {
  onRename: () => void
  onRemove: () => void
}) {
  return <Dropdown
    trigger={['click']}
    menu={{
      items: [
        { key: 'rename', icon: <EditOutlined />, label: '重命名' },
        { key: 'remove', icon: <DeleteOutlined />, label: '移出图库', danger: true },
      ],
      onClick: ({ key }) => {
        if (key === 'rename') onRename()
        if (key === 'remove') Modal.confirm({
          title: '从图片库移出这张图片？',
          content: '不会影响文章和历史版本中的图片。',
          okText: '移出',
          okButtonProps: { danger: true },
          cancelText: '取消',
          onOk: onRemove,
        })
      },
    }}
  >
    <Button className="image-library-mobile-more" size="small" aria-label="更多图片操作" icon={<MoreOutlined />} />
  </Dropdown>
}

export default function ImageLibraryPanel({ documentId, sessionId, initialModelId = null, disabled, applicationTarget, selectedImage, onApply, onSetCover, command = null }: Props) {
  const [tab, setTab] = useState<'library' | 'search' | 'generate'>('library')
  const [assets, setAssets] = useState<ImageLibraryAsset[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [mode, setMode] = useState<'personal' | 'shared'>('personal')
  const [query, setQuery] = useState('')
  const [source, setSource] = useState<'all' | ImageLibrarySource>('all')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [renaming, setRenaming] = useState<ImageLibraryAsset | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [savingRename, setSavingRename] = useState(false)
  const [settingCoverId, setSettingCoverId] = useState('')

  const [searchQuery, setSearchQuery] = useState('')
  const [searchOrientation, setSearchOrientation] = useState<ImageSearchOrientation>('any')
  const [searchResult, setSearchResult] = useState<ImageSearchResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [applyingSearchId, setApplyingSearchId] = useState('')

  const [models, setModels] = useState<AIImageModelItem[]>([])
  const [modelId, setModelId] = useState<number | null>(initialModelId)
  const [generations, setGenerations] = useState<ImageGenerationItem[]>([])
  const [prompt, setPrompt] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [aspectRatio, setAspectRatio] = useState<'square' | 'portrait' | 'landscape'>('landscape')
  const [quality, setQuality] = useState('auto')
  const [timeoutSeconds, setTimeoutSeconds] = useState(180)
  const [editCurrentImage, setEditCurrentImage] = useState(false)
  const [creating, setCreating] = useState(false)
  const [refreshingGeneration, setRefreshingGeneration] = useState(false)
  const searchCacheRef = useRef(new Map<string, ImageSearchResult>())
  const generationRefreshRef = useRef<Promise<ImageGenerationItem> | null>(null)
  const uploadInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!command) return
    setTab(command.tab)
    setEditCurrentImage(Boolean(command.editCurrentImage))
  }, [command])

  const loadLibrary = useCallback(async (nextPage: number) => {
    setLoading(true)
    try {
      const result = await imageLibraryApi.list({ q: query.trim(), source, page: nextPage, page_size: PAGE_SIZE })
      setAssets(result.items)
      setTotal(result.total)
      setMode(result.mode)
      setSelectedIds((ids) => ids.filter((id) => result.items.some((item) => item.id === id)))
    } catch (error) {
      message.error(errorMessage(error, '加载图片库失败'))
    } finally {
      setLoading(false)
    }
  }, [query, source])

  useEffect(() => { void loadLibrary(1); setPage(1) }, [documentId, query, source, loadLibrary])

  useEffect(() => {
    if (tab !== 'generate') return
    void Promise.all([modelsApi.listImage(), imageGenerationsApi.list(documentId)]).then(([nextModels, nextGenerations]) => {
      setModels(nextModels)
      setGenerations(nextGenerations)
      setModelId((current) => current ?? initialModelId ?? nextModels.find((item) => item.is_default)?.id ?? nextModels[0]?.id ?? null)
    }).catch((error) => message.error(errorMessage(error, '加载图片模型失败')))
  }, [documentId, initialModelId, tab])

  const activeGeneration = generations.find((item) => ['pending', 'running'].includes(item.status)) ?? null
  const refreshGeneration = useCallback(async (generationId: string, showError = false) => {
    const existingRequest = generationRefreshRef.current
    if (existingRequest) {
      try { await existingRequest } catch (error) { if (showError) message.error(errorMessage(error, '刷新图片任务失败')) }
      return
    }
    const request = imageGenerationsApi.get(documentId, generationId)
    generationRefreshRef.current = request
    try {
      const next = await request
      setGenerations((items) => items.map((item) => item.id === next.id ? next : item))
      if (next.status === 'succeeded') void loadLibrary(1)
    } catch (error) {
      if (showError) message.error(errorMessage(error, '刷新图片任务失败'))
    } finally {
      if (generationRefreshRef.current === request) generationRefreshRef.current = null
    }
  }, [documentId, loadLibrary])

  useEffect(() => {
    if (tab !== 'generate' || !activeGeneration) return
    const timer = window.setInterval(() => {
      void refreshGeneration(activeGeneration.id)
    }, 1800)
    return () => window.clearInterval(timer)
  }, [activeGeneration, refreshGeneration, tab])

  const manualRefreshGeneration = async () => {
    if (!activeGeneration || refreshingGeneration) return
    setRefreshingGeneration(true)
    try { await refreshGeneration(activeGeneration.id, true) } finally { setRefreshingGeneration(false) }
  }

  const selectedModel = models.find((item) => item.id === modelId) ?? null
  const allGenerated = useMemo(() => generations.flatMap((generation) => generation.assets.map((asset) => ({ generation, asset }))), [generations])
  const apply = (url: string, alt: string) => {
    if (!applicationTarget || !onApply(url, alt)) {
      message.warning('请先在画布中放置光标、选择一个块或点击现有图片')
      return false
    }
    message.success(applicationTarget === 'image' ? '已替换当前图片，可按 Ctrl+Z 撤销' : '已插入图片，可按 Ctrl+Z 撤销')
    return true
  }

  const uploadFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? [])
    event.currentTarget.value = ''
    if (!files.length || uploading) return
    const batch = files.slice(0, 20)
    if (files.length > 20) message.warning('每次最多上传 20 张图片')
    setUploading(true)
    void imageLibraryApi.upload(documentId, batch).then(() => {
      message.success(`已上传 ${batch.length} 张图片`)
      return loadLibrary(1)
    }).catch((error) => message.error(errorMessage(error, '上传图片失败'))).finally(() => setUploading(false))
  }

  const rename = async () => {
    if (!renaming || !renameValue.trim()) return
    setSavingRename(true)
    try {
      const updated = await imageLibraryApi.rename(renaming.id, renameValue.trim())
      setAssets((items) => items.map((item) => item.id === updated.id ? updated : item))
      setRenaming(null)
      message.success('图片名称已更新')
    } catch (error) {
      message.error(errorMessage(error, '重命名失败'))
    } finally {
      setSavingRename(false)
    }
  }

  const remove = async (ids: string[]) => {
    try {
      if (ids.length === 1) await imageLibraryApi.remove(ids[0])
      else await imageLibraryApi.removeMany(ids)
      setSelectedIds([])
      message.success(ids.length === 1 ? '已移出图片库' : `已移出 ${ids.length} 张图片`)
      await loadLibrary(page)
    } catch (error) {
      message.error(errorMessage(error, '移出图片库失败'))
    }
  }

  const setCover = async (assetId: string) => {
    setSettingCoverId(assetId)
    try { await onSetCover(assetId) } finally { setSettingCoverId('') }
  }

  const searchImages = async (nextPage = 1) => {
    const value = searchQuery.trim()
    if (value.length < 2) { message.warning('请输入至少 2 个字符的搜图关键词'); return }
    const key = JSON.stringify([documentId, value, nextPage, searchOrientation])
    setSearching(true)
    try {
      const cached = searchCacheRef.current.get(key)
      const result = cached ?? await imageSearchesApi.search(documentId, { query: value, page: nextPage, orientation: searchOrientation })
      searchCacheRef.current.set(key, result)
      setSearchResult(result)
    } catch (error) {
      message.error(errorMessage(error, '搜图服务暂时不可用'))
    } finally {
      setSearching(false)
    }
  }

  const applySearch = async (candidate: ImageSearchCandidate) => {
    if (!applicationTarget) { message.warning('请先在画布中选择图片位置'); return }
    setApplyingSearchId(candidate.id)
    try {
      const asset = await imageLibraryApi.importSearch(documentId, candidate.token)
      if (apply(asset.url, asset.name)) {
        setPage(1)
        await loadLibrary(1)
      } else {
        await imageLibraryApi.remove(asset.id).catch(() => undefined)
      }
    } catch (error) {
      message.error(errorMessage(error, '保存搜索图片失败'))
    } finally {
      setApplyingSearchId('')
    }
  }

  const setSearchCover = async (candidate: ImageSearchCandidate) => {
    setApplyingSearchId(candidate.id)
    let asset: ImageLibraryAsset | null = null
    try {
      asset = await imageLibraryApi.importSearch(documentId, candidate.token)
      await onSetCover(asset.id)
      setPage(1)
      await loadLibrary(1)
    } catch (error) {
      if (asset) await imageLibraryApi.remove(asset.id).catch(() => undefined)
      if (!asset) {
        message.error(errorMessage(error, '设置搜索图片为封面失败'))
      }
    } finally {
      setApplyingSearchId('')
    }
  }

  const createGeneration = async () => {
    if (!modelId || prompt.trim().length < 3) { message.warning('请选择图片模型并填写图片描述'); return }
    if (editCurrentImage && !selectedImage) { message.warning('请先点击画布中的图片'); return }
    if (editCurrentImage && !(selectedModel?.operations ?? []).includes('edit')) { message.warning('当前模型不支持 AI 图片编辑'); return }
    setCreating(true)
    try {
      const generation = await imageGenerationsApi.create(documentId, {
        model_id: modelId,
        session_id: sessionId,
        operation: editCurrentImage ? 'edit' : 'generate',
        prompt: prompt.trim(),
        quantity,
        aspect_ratio: aspectRatio,
        quality,
        timeout_seconds: timeoutSeconds,
        source_image_url: editCurrentImage ? selectedImage?.sourceUrl : undefined,
        target_image_index: editCurrentImage ? selectedImage?.imageIndex : undefined,
      })
      setGenerations((items) => [generation, ...items])
      setPrompt('')
    } catch (error) {
      message.error(errorMessage(error, '创建图片任务失败'))
    } finally {
      setCreating(false)
    }
  }

  const libraryTab = <div className="image-library-content">
    <div className="image-library-toolbar">
      <Input.Search allowClear placeholder="搜索图片" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Select aria-label="图片来源" value={source} onChange={setSource} options={[{ value: 'all', label: '全部来源' }, { value: 'upload', label: '上传' }, { value: 'ai', label: 'AI' }, { value: 'search', label: '搜图' }]} />
      <input ref={uploadInputRef} type="file" hidden multiple accept="image/jpeg,image/png,image/gif,image/webp,image/avif,image/bmp" onChange={uploadFiles} />
      <Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={disabled || uploading} aria-label="上传图片" onClick={() => uploadInputRef.current?.click()} />
      <Tooltip title="刷新"><Button icon={<ReloadOutlined />} aria-label="刷新图片库" onClick={() => void loadLibrary(page)} /></Tooltip>
    </div>
    <div className="image-library-summary"><Text type="secondary">{mode === 'shared' ? '全员共享图库' : '个人图库'} · {total} 张</Text>{selectedIds.length > 0 && <Popconfirm title={`移出选中的 ${selectedIds.length} 张图片？`} onConfirm={() => void remove(selectedIds)}><Button danger size="small" icon={<DeleteOutlined />}>批量移出</Button></Popconfirm>}</div>
    {loading ? <div className="resource-library-loading"><Spin size="small" /></div> : assets.length ? <>
      <div className="image-library-grid">{assets.map((asset) => <article className="image-library-card" key={asset.id}>
        <button type="button" className="image-library-apply" disabled={disabled} title={applicationTarget === 'image' ? '替换当前图片' : '插入到画布所选位置'} onClick={() => apply(asset.url, asset.name)}>
          <img src={asset.url} alt={asset.name} />
        </button>
        <Checkbox className="image-library-select" checked={selectedIds.includes(asset.id)} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...ids, asset.id] : ids.filter((id) => id !== asset.id))} />
        <div className="image-library-card-actions">
          <ImagePreviewAction src={asset.url} alt={asset.name} />
          <Tooltip title="设为封面"><Button size="small" aria-label={`设为封面：${asset.name}`} icon={<PictureOutlined />} loading={settingCoverId === asset.id} onClick={() => void setCover(asset.id)} /></Tooltip>
          <span className="image-library-desktop-actions">
            {asset.can_manage && <Tooltip title="重命名"><Button size="small" icon={<EditOutlined />} onClick={() => { setRenaming(asset); setRenameValue(asset.name) }} /></Tooltip>}
            {asset.can_manage && <Popconfirm title="从图片库移出这张图片？" description="不会影响文章和历史版本中的图片。" onConfirm={() => void remove([asset.id])}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>}
          </span>
          {asset.can_manage && <MobileImageActions onRename={() => { setRenaming(asset); setRenameValue(asset.name) }} onRemove={() => void remove([asset.id])} />}
        </div>
        <div className="image-library-card-meta"><ImageCardTitle text={asset.name} /><span><Tag bordered={false}>{sourceLabels[asset.source]}</Tag>{asset.width > 0 && asset.height > 0 ? `${asset.width}×${asset.height}` : ''}</span></div>
      </article>)}</div>
      <Pagination size="small" current={page} pageSize={PAGE_SIZE} total={total} showSizeChanger={false} hideOnSinglePage onChange={(next) => { setPage(next); void loadLibrary(next) }} />
    </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有图片，上传或生成一张吧" />}
  </div>

  const searchTab = <Space orientation="vertical" size={10} style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="全网图片版权需自行确认" />
    <Space.Compact style={{ width: '100%' }}><Input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onPressEnter={() => void searchImages()} placeholder="输入搜图关键词" /><Button type="primary" loading={searching} onClick={() => void searchImages()}>搜索</Button></Space.Compact>
    <Select value={searchOrientation} onChange={setSearchOrientation} options={[{ value: 'any', label: '不限方向' }, { value: 'landscape', label: '横图' }, { value: 'portrait', label: '竖图' }, { value: 'square', label: '方图' }]} />
    {searchResult?.items.length ? <><div className="image-library-grid">{searchResult.items.map((candidate) => <article className="image-library-card" key={candidate.id}>
      <button type="button" className="image-library-apply" disabled={disabled || Boolean(applyingSearchId)} onClick={() => void applySearch(candidate)}><img src={candidate.preview_url} alt={candidate.title} /></button>
      <div className="image-library-card-actions"><ImagePreviewAction src={candidate.preview_url} alt={candidate.title || '搜索图片'} /><Tooltip title="设为封面"><Button size="small" aria-label={`设为封面：${candidate.title || '搜索图片'}`} icon={<PictureOutlined />} loading={applyingSearchId === candidate.id} disabled={disabled || Boolean(applyingSearchId)} onClick={() => void setSearchCover(candidate)} /></Tooltip></div>
      <div className="image-library-card-meta"><ImageCardTitle text={candidate.title || '搜索图片'} /><span>{candidate.width && candidate.height ? `${candidate.width}×${candidate.height}` : candidate.engine}</span></div>
    </article>)}</div><Pagination size="small" current={searchResult.page} pageSize={12} total={searchResult.next_page ? searchResult.page * 12 + 12 : (searchResult.page - 1) * 12 + searchResult.items.length} showSizeChanger={false} onChange={(next) => void searchImages(next)} /></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={searching ? '正在搜索' : '输入关键词开始搜图'} />}
  </Space>

  const generateTab = <Space orientation="vertical" size={10} style={{ width: '100%' }}>
    {models.length ? <>
      <Select value={modelId ?? undefined} onChange={setModelId} style={{ width: '100%' }} options={models.map((model) => ({ value: model.id, label: model.display_name }))} />
      {selectedImage && <Checkbox checked={editCurrentImage} onChange={(event) => setEditCurrentImage(event.target.checked)}>编辑画布中选中的图片</Checkbox>}
      <Input.TextArea rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={editCurrentImage ? '描述希望如何修改当前图片' : '描述画面主体、风格、色彩和构图'} />
      <Space wrap><Select value={aspectRatio} onChange={setAspectRatio} options={(selectedModel?.supported_aspect_ratios.length ? selectedModel.supported_aspect_ratios : ['landscape', 'portrait', 'square']).map((value) => ({ value, label: value === 'landscape' ? '横图' : value === 'portrait' ? '竖图' : '方图' }))} /><Select value={quality} onChange={setQuality} options={(selectedModel?.supported_qualities.length ? selectedModel.supported_qualities : ['auto']).map((value) => ({ value, label: `质量 ${value}` }))} /><InputNumber min={1} max={4} value={quantity} onChange={(value) => setQuantity(value ?? 1)} /><InputNumber aria-label="生成超时（秒）" min={30} max={1800} step={30} value={timeoutSeconds} onChange={(value) => setTimeoutSeconds(value ?? 180)} addonBefore="超时" addonAfter="秒" /></Space>
      <Space wrap><Button type="primary" loading={creating} disabled={Boolean(activeGeneration)} onClick={() => void createGeneration()}>{editCurrentImage ? '生成编辑结果' : '生成图片'}</Button>{activeGeneration && <Button icon={<ReloadOutlined />} loading={refreshingGeneration} onClick={() => void manualRefreshGeneration()}>刷新</Button>}{activeGeneration && <Button icon={<StopOutlined />} onClick={() => void imageGenerationsApi.cancel(documentId, activeGeneration.id).then((next) => setGenerations((items) => items.map((item) => item.id === next.id ? next : item)))}>取消</Button>}</Space>
      {generations[0]?.status === 'failed' && <Alert type="error" showIcon message="最近一次生成失败" description={generations[0].error_message} />}
      {allGenerated.length ? <div className="image-library-grid">{allGenerated.map(({ asset, generation }) => {
        const imageUrl = asset.library_url || asset.url
        return <article className="image-library-card" key={asset.id}><button type="button" className="image-library-apply" disabled={disabled} onClick={() => apply(imageUrl, generation.prompt)}><img src={imageUrl} alt={generation.prompt} /></button><div className="image-library-card-actions"><ImagePreviewAction src={imageUrl} alt={generation.prompt} /><Tooltip title={asset.library_asset_id ? '设为封面' : '正在保存到图库'}><Button size="small" aria-label={`设为封面：${generation.prompt}`} icon={<PictureOutlined />} loading={settingCoverId === asset.library_asset_id} disabled={!asset.library_asset_id} onClick={() => void setCover(asset.library_asset_id)} /></Tooltip></div><div className="image-library-card-meta"><ImageCardTitle text={generation.prompt} /><span><Tag bordered={false}>AI</Tag>{asset.width}×{asset.height}</span></div></article>
      })}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={activeGeneration ? '正在生成图片' : '生成结果会自动保存到图库'} />}
    </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用图片模型" />}
  </Space>

  return <section className="image-library-panel">
    <div className={`image-library-target${applicationTarget ? ' has-target' : ''}`}><PictureOutlined /><span>{applicationTarget === 'image' ? '点击图片将替换当前画布图片' : applicationTarget ? '点击图片将插入所选区域之后' : '先在画布放置光标、选择块或点击图片'}</span></div>
    <Tabs size="small" activeKey={tab} onChange={(key) => setTab(key as typeof tab)} items={[{ key: 'library', label: '图库', children: libraryTab }, { key: 'search', label: '搜图', children: searchTab }, { key: 'generate', label: 'AI 生图', children: generateTab }]} />
    <Modal title="重命名图片" open={Boolean(renaming)} onCancel={() => setRenaming(null)} onOk={() => void rename()} confirmLoading={savingRename}><Input value={renameValue} maxLength={256} onChange={(event) => setRenameValue(event.target.value)} onPressEnter={() => void rename()} /></Modal>
  </section>
}
