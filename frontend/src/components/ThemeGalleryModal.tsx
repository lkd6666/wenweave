import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Checkbox, Empty, Input, Modal, Segmented, Select, Spin, Tag } from 'antd'
import { CheckOutlined, EyeOutlined, LoadingOutlined, SettingOutlined } from '@ant-design/icons'
import { gzhThemesApi } from '../api/gzhThemes'
import { ApiError } from '../api/client'
import type { AIModelItem, GzhApplyMode, GzhThemeItem, GzhThemeManifest, GzhThemeProposal } from '../types'
import { useAuthStore } from '../store/authStore'
import { frameThemeDocument } from '../utils/themePreview'
import { SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import ThemeManagerModal from './ThemeManagerModal'

interface ThemeGalleryModalProps {
  open: boolean
  initialThemeKey?: string | null
  documentId: number
  sessionId: number | null
  modelId: number | null
  models: AIModelItem[]
  disabled?: boolean
  onClose: () => void
  onApproved: (proposal: GzhThemeProposal) => void
}

const MODE_OPTIONS = [
  { label: '完整套用', value: 'full' },
  { label: '克制套用', value: 'restrained' },
  { label: '借鉴关键组件', value: 'key_components' },
]

function componentDisplayName(name: string): string {
  // Vendor component headings often append an English implementation alias
  // after a Chinese display name. Keep the application UI Chinese where a
  // Chinese name is available, while leaving genuinely English custom names.
  const chineseName = name
    .replace(/\bcase\b/gi, '案例')
    .replace(/[A-Za-z][A-Za-z0-9-]*/g, '')
    .replace(/[\s—–-]+$/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
  return /[\u3400-\u9fff]/.test(chineseName) ? chineseName : name
}

export default function ThemeGalleryModal({
  open,
  initialThemeKey = null,
  documentId,
  sessionId,
  modelId,
  models,
  disabled = false,
  onClose,
  onApproved,
}: ThemeGalleryModalProps) {
  const [themes, setThemes] = useState<GzhThemeItem[]>([])
  const [previews, setPreviews] = useState<Record<string, string>>({})
  const [manifests, setManifests] = useState<Record<string, GzhThemeManifest>>({})
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('all')
  const [mode, setMode] = useState<GzhApplyMode>('full')
  const [instructions, setInstructions] = useState('')
  const [recipeId, setRecipeId] = useState('auto')
  const [selectedDecorativeIds, setSelectedDecorativeIds] = useState<string[]>([])
  const [manifestLoading, setManifestLoading] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [managerOpen, setManagerOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isAdmin = useAuthStore((state) => state.user?.role === 'admin')

  const loadThemes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const items = await gzhThemesApi.list()
      setThemes(items)
      setSelectedKey((previous) => previous && items.some((item) => item.key === previous) ? previous : items[0]?.key ?? null)
      const loaded = await Promise.all(items.map(async (item) => {
        try {
          const preview = await gzhThemesApi.preview(item.key)
          return [item.key, preview.html] as const
        } catch {
          return [item.key, ''] as const
        }
      }))
      setPreviews(Object.fromEntries(loaded))
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : '主题库加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void loadThemes()
  }, [loadThemes, open])

  useEffect(() => {
    if (!open || !initialThemeKey) return
    // A thumbnail in the resource panel is an explicit choice. Show that
    // exact theme even when the gallery was previously filtered.
    setFilter('all')
    setSelectedKey(initialThemeKey)
  }, [initialThemeKey, open])

  useEffect(() => {
    if (open) return
    setMode('full')
    setInstructions('')
    setRecipeId('auto')
    setSelectedDecorativeIds([])
    setPreviewOpen(false)
    setManagerOpen(false)
    setError(null)
    setApplying(false)
  }, [open])

  const scenarios = useMemo(() => Array.from(new Set(themes.flatMap((theme) => theme.scenarios))).sort(), [themes])
  const visibleThemes = useMemo(() => filter === 'all' ? themes : themes.filter((theme) => theme.scenarios.includes(filter)), [filter, themes])
  const selected = themes.find((theme) => theme.key === selectedKey) ?? null
  const selectedManifest = selectedKey ? manifests[selectedKey] ?? null : null
  const selectedRecipe = selectedManifest
    ? selectedManifest.recipes.find((item) => item.id === (recipeId === 'auto' ? selectedManifest.recommended_recipe_id : recipeId)) ?? null
    : null
  const componentById = useMemo(
    () => new Map(selectedManifest?.components.map((component) => [component.id, component]) ?? []),
    [selectedManifest],
  )
  const selectedComponentIds = useMemo(() => {
    if (!selectedRecipe) return []
    return [...selectedRecipe.core_component_ids, ...selectedDecorativeIds]
      .filter((item, index, list) => list.indexOf(item) === index)
  }, [selectedDecorativeIds, selectedRecipe])

  useEffect(() => {
    if (!open || !selectedKey) return
    const initialiseRecipe = (manifest: GzhThemeManifest) => {
      const recipe = manifest.recipes.find((item) => item.id === manifest.recommended_recipe_id) ?? manifest.recipes[0]
      setRecipeId('auto')
      setSelectedDecorativeIds(recipe?.decorative_component_ids ?? [])
    }
    if (selectedManifest) {
      initialiseRecipe(selectedManifest)
      setManifestLoading(false)
      return
    }
    let cancelled = false
    setManifestLoading(true)
    gzhThemesApi.manifest(selectedKey)
      .then((manifest) => {
        if (cancelled) return
        setManifests((previous) => ({ ...previous, [selectedKey]: manifest }))
        initialiseRecipe(manifest)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? String(err.detail) : '主题配方加载失败')
      })
      .finally(() => {
        if (!cancelled) setManifestLoading(false)
    })
    return () => { cancelled = true }
  }, [open, selectedKey, selectedManifest])

  const selectRecipe = (nextRecipeId: string) => {
    setRecipeId(nextRecipeId)
    if (!selectedManifest) return
    const recipe = selectedManifest.recipes.find((item) => item.id === (nextRecipeId === 'auto' ? selectedManifest.recommended_recipe_id : nextRecipeId))
    setSelectedDecorativeIds(recipe?.decorative_component_ids ?? [])
  }

  const approveAndApply = async () => {
    if (!selected || disabled || applying) return
    setApplying(true)
    setError(null)
    try {
      const proposal = await gzhThemesApi.createProposal(documentId, {
        theme_key: selected.key,
        apply_mode: mode,
        user_instructions: instructions.trim(),
        // The displayed recommendation is already a concrete vendor recipe.
        // Bind that exact ID instead of asking the server to infer another one
        // from the document after the user has confirmed its components.
        article_type: selectedRecipe?.article_type ?? 'auto',
        recipe_id: selectedRecipe?.id ?? recipeId,
        selected_component_ids: selectedComponentIds,
        session_id: sessionId,
      })
      const approved = await gzhThemesApi.approveProposal(documentId, proposal.id)
      onApproved(approved)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : '主题提案创建失败')
    } finally {
      setApplying(false)
    }
  }

  const confirm = () => {
    if (!selected) return
    const modeLabel = MODE_OPTIONS.find((item) => item.value === mode)?.label ?? mode
    const recipeLabel = selectedRecipe?.article_type ?? '自动推荐'
    const componentLabel = selectedComponentIds
      .map((id) => componentDisplayName(componentById.get(id)?.name ?? id))
      .join('、')
    Modal.confirm({
      title: `应用「${selected.name}」`,
      content: `套用强度：${modeLabel}\n文章类型：${recipeLabel}\n组件组合：${componentLabel || '主题固定结构'}${instructions.trim() ? `\n补充要求：${instructions.trim()}` : ''}\n\n当前文档将按此主题重新排版，并保存为新的版本。`,
      okText: '确认并开始',
      cancelText: '返回设置',
      onOk: approveAndApply,
    })
  }

  return (
    <>
      <Modal
        title="主题模板"
        open={open}
        onCancel={onClose}
        width={1060}
        destroyOnHidden
        className="theme-gallery-modal"
        footer={null}
      >
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        {loading ? <div className="theme-gallery-loading"><Spin /></div> : (
          <div className="theme-gallery-layout">
            <section className="theme-gallery-browser">
              <div className="theme-gallery-filter">
                {isAdmin && <Button type="text" icon={<SettingOutlined />} onClick={() => setManagerOpen(true)}>管理模板</Button>}
                <Select value={filter} onChange={setFilter} options={[{ label: '全部主题', value: 'all' }, ...scenarios.map((item) => ({ label: item, value: item }))]} />
              </div>
              {visibleThemes.length ? (
                <div className="theme-gallery-grid">
                  {visibleThemes.map((theme) => {
                    const active = theme.key === selectedKey
                    const preview = previews[theme.key]
                    return (
                      <button key={theme.key} type="button" className={`theme-gallery-card${active ? ' is-selected' : ''}`} onClick={() => setSelectedKey(theme.key)}>
                        <span className="theme-gallery-card-preview" style={{ borderTopColor: theme.accent_color }}>
                          {preview ? <iframe title={`${theme.name} 预览`} sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(preview)} /> : <LoadingOutlined />}
                        </span>
                        <span className="theme-gallery-card-meta">
                          <strong>{theme.name}</strong>
                          <i style={{ background: theme.accent_color }} />
                          {active && <CheckOutlined />}
                        </span>
                        <span className="theme-gallery-card-scenes">{theme.scenarios.slice(0, 3).join(' · ')}</span>
                      </button>
                    )
                  })}
                </div>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的主题" />}
            </section>
            <aside className="theme-application-settings">
              {selected ? (
                <>
                  <div className="theme-settings-head">
                    <span className="theme-settings-accent" style={{ background: selected.accent_color }} />
                    <div><h3>{selected.name}</h3><p>{selected.description}</p></div>
                  </div>
                  <div className="theme-settings-tags">{selected.scenarios.map((item) => <Tag key={item}>{item}</Tag>)}</div>
                  <Button icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)} disabled={!previews[selected.key]}>预览模板</Button>
                  <label className="theme-settings-label">套用强度</label>
                  <Segmented block value={mode} options={MODE_OPTIONS} onChange={(value) => setMode(value as GzhApplyMode)} />
                  <label className="theme-settings-label">文章类型与组件组合</label>
                  {manifestLoading ? <div className="theme-recipe-loading"><Spin size="small" /> 正在读取模板配方</div> : selectedManifest && selectedRecipe ? (
                    <div className="theme-recipe-settings">
                      <Select
                        value={recipeId}
                        onChange={selectRecipe}
                        options={[
                          { label: `自动推荐（${selectedManifest.recipes.find((item) => item.id === selectedManifest.recommended_recipe_id)?.article_type ?? '默认配方'}）`, value: 'auto' },
                          ...selectedManifest.recipes.map((item) => ({ label: item.article_type, value: item.id })),
                        ]}
                      />
                      <div className="theme-recipe-group">
                        <span>核心组件</span>
                        <div className="theme-component-tags">
                          {selectedRecipe.core_component_ids.map((id) => <Tag color="blue" key={id}>{componentDisplayName(componentById.get(id)?.name ?? id)}</Tag>)}
                        </div>
                      </div>
                      {selectedRecipe.decorative_component_ids.length > 0 && (
                        <div className="theme-recipe-group">
                          <span>可选点缀</span>
                          <Checkbox.Group
                            value={selectedDecorativeIds}
                            onChange={(values) => setSelectedDecorativeIds(values.map(String))}
                            options={selectedRecipe.decorative_component_ids.map((id) => ({ label: componentDisplayName(componentById.get(id)?.name ?? id), value: id }))}
                          />
                        </div>
                      )}
                    </div>
                  ) : <div className="theme-recipe-empty">该模板没有可用的组件配方</div>}
                  <label className="theme-settings-label">补充要求</label>
                  <Input.TextArea value={instructions} onChange={(event) => setInstructions(event.target.value)} maxLength={4000} autoSize={{ minRows: 6, maxRows: 10 }} placeholder="例如：正文保持简洁，只使用章节标题和引用样式" />
                  <Button type="primary" block size="large" loading={applying} disabled={disabled || manifestLoading || !selectedRecipe} onClick={confirm}>应用到全文</Button>
                </>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个主题" />}
            </aside>
          </div>
        )}
      </Modal>
      <Modal
        title={selected ? `${selected.name} 模板预览` : '模板预览'}
        open={previewOpen && Boolean(selected)}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={840}
        destroyOnHidden
        className="theme-preview-modal"
      >
        {selected && previews[selected.key]
          ? <iframe className="theme-preview-frame" title={`${selected.name} 完整预览`} sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(previews[selected.key], 'full')} />
          : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="预览正在加载" />}
      </Modal>
      {isAdmin && <ThemeManagerModal open={managerOpen} modelId={modelId} models={models} onClose={() => setManagerOpen(false)} onThemesChanged={loadThemes} />}
    </>
  )
}
