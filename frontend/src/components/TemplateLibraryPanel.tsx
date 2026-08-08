import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Pagination, Popconfirm, Segmented, Select, Spin, Tooltip, message } from 'antd'
import {
  AppstoreAddOutlined,
  CheckOutlined,
  CloudDownloadOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ReadOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { templateLibraryApi, type TemplateWritePayload } from '../api/templateLibrary'
import { gzhThemesApi } from '../api/gzhThemes'
import { ApiError } from '../api/client'
import type { ChatSessionItem, GzhThemeItem, TemplateCategory, TemplateGeneration, TemplateItem, TemplateSourceType } from '../types'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW, SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW } from '../utils/frameLinks'
import { frameThemeDocument } from '../utils/themePreview'

type ResourceTab = 'templates' | 'themes'
type CategoryFilter = 'all' | 'uncategorized' | number

interface TemplateDraft {
  id?: number
  name: string
  categoryId: number | null
  html: string
  sourceType: TemplateSourceType
  mode: TemplateSourceType
}

interface TemplateLibraryPanelProps {
  modelId: number | null
  disabled?: boolean
  canInsertAtCaret: boolean
  attachedTemplateIds: number[]
  themeContext: ChatSessionItem['theme_context']
  onAppend: (template: TemplateItem) => void | Promise<void>
  onInsertAtCaret: (template: TemplateItem) => void | Promise<void>
  onToggleAttach: (template: TemplateItem) => void
  onClearThemeContext: () => void
  onOpenThemeGallery: (themeKey?: string) => void
  collection: { id: number; html: string } | null
  onCollectionHandled: () => void
}

const SOURCE_LABEL: Record<TemplateSourceType, string> = {
  rich_paste: '粘贴内容',
  source: '源码',
  ai: 'AI 生成',
}

const TEMPLATE_PAGE_SIZE = 6

function previewDocument(html: string): string {
  return frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><style>html,body{margin:0;padding:0;background:#fff;color:#252b36;font:14px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}body{padding:14px;box-sizing:border-box;overflow-wrap:anywhere}body>*{max-width:100%!important}img,video,svg,canvas{max-width:100%!important;height:auto!important}table{max-width:100%!important;border-collapse:collapse}a{color:inherit}</style></head><body>${html}</body></html>`)
}

function richEditorDocument(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><style>html,body{min-height:100%;margin:0;padding:0;background:#fff;color:#252b36;font:15px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}body{min-height:360px;padding:14px;box-sizing:border-box;outline:0;overflow-wrap:anywhere;cursor:text}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}a{color:inherit}</style></head><body contenteditable="true">${html}</body></html>`
}

function RichTemplateEditor({ html, onChange }: { html: string; onChange: (html: string) => void }) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const cleanupRef = useRef<() => void>(() => undefined)
  const sourceRef = useRef<string | null>(null)
  const renderedHtmlRef = useRef<string | null>(null)
  const htmlRef = useRef(html)
  const onChangeRef = useRef(onChange)

  htmlRef.current = html
  onChangeRef.current = onChange
  if (sourceRef.current === null) sourceRef.current = richEditorDocument(html)

  useEffect(() => {
    const body = iframeRef.current?.contentDocument?.body
    if (!body || renderedHtmlRef.current === html) return
    body.innerHTML = html
    renderedHtmlRef.current = html
  }, [html])

  useEffect(() => () => cleanupRef.current(), [])

  const handleLoad = useCallback(() => {
    cleanupRef.current()
    const document = iframeRef.current?.contentDocument
    const body = document?.body
    if (!document || !body) return
    body.innerHTML = htmlRef.current
    renderedHtmlRef.current = htmlRef.current
    const handleInput = () => {
      const nextHtml = body.innerHTML
      renderedHtmlRef.current = nextHtml
      onChangeRef.current(nextHtml)
    }
    const preventLinkNavigation = (event: Event) => {
      const target = event.target && (event.target as Node).nodeType === 1 ? event.target as HTMLElement : null
      if (target?.closest('a')) event.preventDefault()
    }
    body.addEventListener('input', handleInput)
    body.addEventListener('click', preventLinkNavigation, true)
    cleanupRef.current = () => {
      body.removeEventListener('input', handleInput)
      body.removeEventListener('click', preventLinkNavigation, true)
    }
  }, [])

  return <div className="template-rich-editor"><iframe ref={iframeRef} title="粘贴内容编辑" sandbox="allow-same-origin" srcDoc={sourceRef.current} onLoad={handleLoad} /></div>
}

function TemplatePreview({ html, title }: { html: string; title: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const cleanupRef = useRef<() => void>(() => undefined)
  const [height, setHeight] = useState(166)

  const syncHeight = useCallback(() => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    const nextHeight = Math.ceil(Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 166))
    setHeight((previous) => previous === nextHeight ? previous : nextHeight)
  }, [])

  const handleLoad = useCallback(() => {
    cleanupRef.current()
    const document = iframeRef.current?.contentDocument
    if (!document) return
    const images = Array.from(document.images)
    images.forEach((image) => image.addEventListener('load', syncHeight))
    images.forEach((image) => image.addEventListener('error', syncHeight))
    cleanupRef.current = () => {
      images.forEach((image) => image.removeEventListener('load', syncHeight))
      images.forEach((image) => image.removeEventListener('error', syncHeight))
    }
    window.requestAnimationFrame(syncHeight)
  }, [syncHeight])

  useEffect(() => () => cleanupRef.current(), [])

  return (
    <div className="template-library-preview" style={{ height }}>
      <iframe ref={iframeRef} title={title} sandbox={SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW} scrolling="no" srcDoc={previewDocument(html)} onLoad={handleLoad} style={{ height }} />
    </div>
  )
}

function asErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? String(error.detail) : fallback
}

function emptyDraft(): TemplateDraft {
  return { name: '', categoryId: null, html: '', sourceType: 'rich_paste', mode: 'rich_paste' }
}

export default function TemplateLibraryPanel({
  modelId,
  disabled = false,
  canInsertAtCaret,
  attachedTemplateIds,
  themeContext,
  onAppend,
  onInsertAtCaret,
  onToggleAttach,
  onClearThemeContext,
  onOpenThemeGallery,
  collection,
  onCollectionHandled,
}: TemplateLibraryPanelProps) {
  const [tab, setTab] = useState<ResourceTab>('templates')
  const [categories, setCategories] = useState<TemplateCategory[]>([])
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'updated' | 'name'>('updated')
  const [templatePage, setTemplatePage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<TemplateDraft | null>(null)
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [localizingTemplateImages, setLocalizingTemplateImages] = useState(false)
  const [categoryModal, setCategoryModal] = useState<{ id?: number; name: string } | null>(null)
  const [categoryManagerOpen, setCategoryManagerOpen] = useState(false)
  const [savingCategory, setSavingCategory] = useState(false)
  const [generation, setGeneration] = useState<TemplateGeneration | null>(null)
  const [generationPrompt, setGenerationPrompt] = useState('')
  const [generationSubmitting, setGenerationSubmitting] = useState(false)
  const [themeItems, setThemeItems] = useState<GzhThemeItem[]>([])
  const [themePreviews, setThemePreviews] = useState<Record<string, string>>({})
  const [themeLoading, setThemeLoading] = useState(false)
  const [themeError, setThemeError] = useState<string | null>(null)
  const templateContentRef = useRef<HTMLDivElement>(null)

  const loadTemplates = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const categoryId = typeof categoryFilter === 'number' ? categoryFilter : undefined
      const [nextCategories, nextTemplates] = await Promise.all([
        templateLibraryApi.listCategories(),
        templateLibraryApi.listTemplates({ categoryId, query, sort }),
      ])
      setCategories(nextCategories)
      setTemplates(categoryFilter === 'uncategorized'
        ? nextTemplates.filter((template) => template.category_id === null)
        : nextTemplates)
    } catch (err) {
      setError(asErrorMessage(err, '模板库加载失败'))
    } finally {
      setLoading(false)
    }
  }, [categoryFilter, query, sort])

  useEffect(() => {
    if (tab === 'templates') void loadTemplates()
  }, [loadTemplates, tab])

  useEffect(() => {
    if (!generation || !['pending', 'running'].includes(generation.status)) return
    const timer = window.setTimeout(() => {
      void templateLibraryApi.getGeneration(generation.id)
        .then(setGeneration)
        .catch((err) => {
          setGeneration((previous) => previous ? { ...previous, status: 'failed', error_message: asErrorMessage(err, '读取生成结果失败') } : previous)
        })
    }, 1200)
    return () => window.clearTimeout(timer)
  }, [generation])

  const loadThemes = useCallback(async () => {
    setThemeLoading(true)
    setThemeError(null)
    try {
      const items = await gzhThemesApi.list()
      setThemeItems(items)
      const previewPairs = await Promise.all(items.map(async (theme) => {
        try {
          const preview = await gzhThemesApi.preview(theme.key)
          return [theme.key, preview.html] as const
        } catch {
          return [theme.key, ''] as const
        }
      }))
      setThemePreviews(Object.fromEntries(previewPairs))
    } catch (err) {
      setThemeItems([])
      setThemePreviews({})
      setThemeError(asErrorMessage(err, '主题库加载失败'))
    } finally {
      setThemeLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab === 'themes') void loadThemes()
  }, [loadThemes, tab])

  useEffect(() => {
    if (!collection?.html.trim()) return
    setTab('templates')
    setGeneration(null)
    setGenerationPrompt('')
    setDraft({ ...emptyDraft(), html: collection.html, sourceType: 'source', mode: 'source' })
    onCollectionHandled()
  }, [collection, onCollectionHandled])

  const categoryOptions = useMemo(
    () => [{ label: '未分类', value: 0 }, ...categories.map((item) => ({ label: item.name, value: item.id }))],
    [categories],
  )

  const totalTemplatePages = Math.max(1, Math.ceil(templates.length / TEMPLATE_PAGE_SIZE))
  const currentTemplatePage = Math.min(templatePage, totalTemplatePages)
  const pagedTemplates = useMemo(() => {
    const start = (currentTemplatePage - 1) * TEMPLATE_PAGE_SIZE
    return templates.slice(start, start + TEMPLATE_PAGE_SIZE)
  }, [currentTemplatePage, templates])

  const resetTemplatePage = () => {
    setTemplatePage(1)
    if (templateContentRef.current) templateContentRef.current.scrollTop = 0
  }

  const changeTemplatePage = (nextPage: number) => {
    setTemplatePage(nextPage)
    if (templateContentRef.current) templateContentRef.current.scrollTop = 0
  }

  useEffect(() => {
    if (templatePage > totalTemplatePages) setTemplatePage(totalTemplatePages)
  }, [templatePage, totalTemplatePages])

  const updateDraft = (patch: Partial<TemplateDraft>) => setDraft((current) => current ? { ...current, ...patch } : current)

  const openCreate = () => {
    setGeneration(null)
    setGenerationPrompt('')
    setDraft(emptyDraft())
  }

  const openEdit = (template: TemplateItem) => {
    setGeneration(null)
    setGenerationPrompt('')
    setDraft({
      id: template.id,
      name: template.name,
      categoryId: template.category_id,
      html: template.html,
      sourceType: template.source_type,
      mode: template.source_type === 'rich_paste' ? 'rich_paste' : 'source',
    })
  }

  const saveDraft = async () => {
    if (!draft || savingTemplate) return
    if (!draft.name.trim()) {
      message.warning('请填写模板名称')
      return
    }
    if (!draft.html.trim()) {
      message.warning('请提供模板内容')
      return
    }
    setSavingTemplate(true)
    try {
      const payload: TemplateWritePayload = {
        name: draft.name.trim(),
        category_id: draft.categoryId,
        html: draft.html,
        source_type: draft.sourceType,
      }
      const result = draft.id
        ? await templateLibraryApi.updateTemplate(draft.id, payload)
        : await templateLibraryApi.createTemplate(payload)
      setDraft(null)
      resetTemplatePage()
      if (result.image_warnings.length) message.warning(`模板已保存，${result.image_warnings.length} 张图片未能转存`)
      else message.success('模板已保存')
      await loadTemplates()
    } catch (err) {
      message.error(asErrorMessage(err, '保存模板失败'))
    } finally {
      setSavingTemplate(false)
    }
  }

  const saveGeneratedTemplate = async () => {
    if (!draft || !generation || generation.status !== 'succeeded' || savingTemplate) return
    if (!draft.name.trim()) {
      message.warning('请填写模板名称')
      return
    }
    setSavingTemplate(true)
    try {
      const result = await templateLibraryApi.saveGeneration(generation.id, {
        name: draft.name.trim(),
        category_id: draft.categoryId,
      })
      setDraft(null)
      setGeneration(null)
      resetTemplatePage()
      message.success(`已保存「${result.name}」`)
      await loadTemplates()
    } catch (err) {
      message.error(asErrorMessage(err, '保存 AI 模板失败'))
    } finally {
      setSavingTemplate(false)
    }
  }

  const generateTemplate = async () => {
    if (!modelId) {
      message.warning('请先在 AI 对话中选择可用模型')
      return
    }
    if (generationSubmitting || generationPrompt.trim().length < 4) {
      message.warning('请至少输入 4 个字的组件需求')
      return
    }
    setGenerationSubmitting(true)
    try {
      const next = await templateLibraryApi.createGeneration({ model_id: modelId, prompt: generationPrompt.trim() })
      setGeneration(next)
    } catch (err) {
      message.error(asErrorMessage(err, '创建模板生成任务失败'))
    } finally {
      setGenerationSubmitting(false)
    }
  }

  const cancelGeneration = async () => {
    if (!generation || !['pending', 'running'].includes(generation.status)) return
    try {
      setGeneration(await templateLibraryApi.cancelGeneration(generation.id))
    } catch (err) {
      message.error(asErrorMessage(err, '取消生成失败'))
    }
  }

  const saveCategory = async () => {
    if (!categoryModal || savingCategory) return
    const name = categoryModal.name.trim()
    if (!name) {
      message.warning('请填写分类名称')
      return
    }
    setSavingCategory(true)
    try {
      if (categoryModal.id) await templateLibraryApi.updateCategory(categoryModal.id, { name })
      else await templateLibraryApi.createCategory({ name })
      setCategoryModal(null)
      await loadTemplates()
    } catch (err) {
      message.error(asErrorMessage(err, '保存分类失败'))
    } finally {
      setSavingCategory(false)
    }
  }

  const deleteCategory = async (category: TemplateCategory) => {
    try {
      await templateLibraryApi.deleteCategory(category.id)
      if (categoryFilter === category.id) setCategoryFilter('uncategorized')
      resetTemplatePage()
      await loadTemplates()
      message.success(`已删除「${category.name}」，其中模板已转为未分类`)
    } catch (err) {
      message.error(asErrorMessage(err, '删除分类失败'))
    }
  }

  const deleteTemplate = async (template: TemplateItem) => {
    try {
      await templateLibraryApi.deleteTemplate(template.id)
      resetTemplatePage()
      await loadTemplates()
      message.success('模板已删除')
    } catch (err) {
      message.error(asErrorMessage(err, '删除模板失败'))
    }
  }

  const localizeExternalTemplateImages = async () => {
    if (disabled || localizingTemplateImages) return
    setLocalizingTemplateImages(true)
    try {
      const result = await templateLibraryApi.localizeExternalImages()
      const summary = `已转存 ${result.updated_count} 个组件中的 ${result.localized_count} 张图片`
      if (result.failed_count) message.warning(`${summary}；${result.failed_count} 个组件未修改`)
      else message.success(summary)
      await loadTemplates()
    } catch (err) {
      message.error(asErrorMessage(err, '批量转存组件图片失败'))
    } finally {
      setLocalizingTemplateImages(false)
    }
  }

  const readClipboard = async () => {
    try {
      const clipboard = navigator.clipboard
      if (clipboard.read) {
        const items = await clipboard.read()
        for (const item of items) {
          if (item.types.includes('text/html')) {
            const blob = await item.getType('text/html')
            updateDraft({ html: await blob.text(), sourceType: 'rich_paste' })
            return
          }
        }
      }
      updateDraft({ html: await clipboard.readText(), sourceType: 'rich_paste' })
    } catch {
      message.warning('无法读取剪贴板，请在输入框中直接粘贴')
    }
  }

  const templateModalOpen = Boolean(draft)
  const generationIsActive = Boolean(generation && ['pending', 'running'].includes(generation.status))

  return (
    <aside className="resource-library" aria-label="资源库">
      <div className="resource-library-header">
        <Segmented
          size="small"
          block
          value={tab}
          onChange={(value) => setTab(value as ResourceTab)}
          options={[
            { label: '模板库', value: 'templates' },
            { label: '主题库', value: 'themes' },
          ]}
        />
      </div>

      {tab === 'templates' ? (
        <div className="template-library-content" ref={templateContentRef}>
          <div className="template-library-toolbar">
            <Input.Search
              allowClear
              placeholder="搜索模板"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                resetTemplatePage()
              }}
            />
            <Select
              aria-label="模板排序"
              value={sort}
              onChange={(value) => {
                setSort(value as 'updated' | 'name')
                resetTemplatePage()
              }}
              options={[{ label: '最近', value: 'updated' }, { label: '名称', value: 'name' }]}
            />
            <Tooltip title="批量转存组件外链图片">
              <span>
                <Popconfirm title="批量转存全部组件中的外链图片？" description="单个组件任一图片失败时，该组件将保持原样。" okText="开始转存" cancelText="取消" onConfirm={() => void localizeExternalTemplateImages()}>
                  <Button aria-label="批量转存组件外链图片" icon={<CloudDownloadOutlined />} disabled={disabled || localizingTemplateImages} loading={localizingTemplateImages} />
                </Popconfirm>
              </span>
            </Tooltip>
            <Button aria-label="新建模板" title="新建模板" type="primary" icon={<PlusOutlined />} disabled={disabled || localizingTemplateImages} onClick={openCreate} />
          </div>
          <div className="template-category-row">
            <button type="button" className={`template-category-chip${categoryFilter === 'all' ? ' is-active' : ''}`} onClick={() => { setCategoryFilter('all'); resetTemplatePage() }}>全部</button>
            <button type="button" className={`template-category-chip${categoryFilter === 'uncategorized' ? ' is-active' : ''}`} onClick={() => { setCategoryFilter('uncategorized'); resetTemplatePage() }}>未分类</button>
            {categories.map((category) => (
              <button type="button" className={`template-category-chip${categoryFilter === category.id ? ' is-active' : ''}`} key={category.id} onClick={() => { setCategoryFilter(category.id); resetTemplatePage() }}>{category.name}</button>
            ))}
            <Tooltip title="管理分类">
              <Button aria-label="管理分类" type="text" size="small" icon={<FolderOpenOutlined />} onClick={() => setCategoryManagerOpen(true)} />
            </Tooltip>
          </div>
          {error && <Alert type="error" showIcon message={error} action={<Button size="small" onClick={() => void loadTemplates()}>重试</Button>} />}
          {loading ? <div className="resource-library-loading"><Spin size="small" /></div> : templates.length ? (
            <>
              <Pagination
                className="template-library-pagination"
                size="small"
                current={currentTemplatePage}
                pageSize={TEMPLATE_PAGE_SIZE}
                total={templates.length}
                showLessItems
                showSizeChanger={false}
                hideOnSinglePage
                onChange={changeTemplatePage}
              />
              <div className="template-library-list">
                {pagedTemplates.map((template) => {
                  const attached = attachedTemplateIds.includes(template.id)
                  return (
                    <article className="template-library-card" key={template.id}>
                      <TemplatePreview html={template.html} title={`${template.name} 预览`} />
                      <div className="template-library-card-head">
                        <strong title={template.name}>{template.name}</strong>
                        <span>{SOURCE_LABEL[template.source_type]}</span>
                      </div>
                      <div className="template-library-actions">
                        <Tooltip title="添加到当前文章文末">
                          <Button aria-label={`添加 ${template.name} 到文末`} icon={<FileAddOutlined />} disabled={disabled || localizingTemplateImages} onClick={() => { void onAppend(template) }} />
                        </Tooltip>
                        <Tooltip title={canInsertAtCaret ? '插入当前直接编辑光标处' : '仅直接编辑模式且画布有真实光标时可用'}>
                          <Button aria-label={`插入 ${template.name} 到光标处`} icon={<AppstoreAddOutlined />} disabled={disabled || localizingTemplateImages || !canInsertAtCaret} onClick={() => { void onInsertAtCaret(template) }} />
                        </Tooltip>
                        <Tooltip title={attached ? '从 AI 对话移除' : attachedTemplateIds.length >= 6 ? '每次对话最多附加 6 个模板' : '附到 AI 对话'}>
                          <Button aria-label={`${attached ? '移除' : '附加'}模板 ${template.name}`} icon={attached ? <CheckOutlined /> : <PaperClipOutlined />} type={attached ? 'primary' : 'default'} disabled={disabled || (!attached && attachedTemplateIds.length >= 6)} onClick={() => onToggleAttach(template)} />
                        </Tooltip>
                        <Tooltip title="编辑模板"><Button aria-label={`编辑模板 ${template.name}`} type="text" icon={<EditOutlined />} disabled={disabled} onClick={() => openEdit(template)} /></Tooltip>
                        <Popconfirm title={`删除「${template.name}」？`} description="已转存的模板图片也会清理。" okText="删除" cancelText="取消" onConfirm={() => deleteTemplate(template)}>
                          <Button aria-label={`删除模板 ${template.name}`} type="text" danger icon={<DeleteOutlined />} disabled={disabled} />
                        </Popconfirm>
                      </div>
                    </article>
                  )
                })}
              </div>
            </>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? '没有匹配的模板' : '还没有模板'} />}
        </div>
      ) : (
        <div className="theme-library-content">
          <div className="theme-library-summary">
            <div className="theme-library-summary-copy">
              <FolderOpenOutlined />
              <div>
                <strong>主题库</strong>
                <span>完整套用与组件配方</span>
              </div>
            </div>
            <Button className="theme-library-open-button" type="primary" icon={<ReadOutlined />} disabled={disabled || !modelId} onClick={() => onOpenThemeGallery()}>打开主题库</Button>
          </div>
          {themeContext && (
            <div className="theme-library-active-context">
              <span title={themeContext.theme_name}>当前对话主题：{themeContext.theme_name}</span>
              <Tooltip title="清除当前对话的主题参考">
                <Button aria-label="清除当前对话主题参考" type="text" size="small" danger icon={<DeleteOutlined />} disabled={disabled} onClick={onClearThemeContext} />
              </Tooltip>
            </div>
          )}
          {themeError && <Alert type="error" showIcon message={themeError} action={<Button size="small" onClick={() => void loadThemes()}>重试</Button>} />}
          {themeLoading ? <div className="resource-library-loading"><Spin size="small" /></div> : themeItems.length ? (
            <div className="theme-library-preview-list">
              {themeItems.map((theme) => {
                const preview = themePreviews[theme.key]
                return (
                  <button type="button" className="theme-library-preview-card" key={theme.key} onClick={() => onOpenThemeGallery(theme.key)} disabled={disabled || !modelId}>
                    <span className="theme-library-preview-frame" style={{ borderTopColor: theme.accent_color }}>
                      {preview ? <iframe title={`${theme.name} 预览`} sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={frameThemeDocument(preview)} /> : <LoadingOutlined />}
                    </span>
                    <span className="theme-library-preview-meta"><strong>{theme.name}</strong><i style={{ background: theme.accent_color }} /></span>
                    <small>{theme.scenarios.slice(0, 3).join(' · ')}</small>
                  </button>
                )
              })}
            </div>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可用主题" />}
        </div>
      )}

      <Modal
        title={draft?.id ? '编辑模板' : '新建模板'}
        open={templateModalOpen}
        width={980}
        className="template-editor-modal"
        destroyOnHidden
        onCancel={() => { if (!generationIsActive) setDraft(null) }}
        footer={(
          <>
            <Button onClick={() => setDraft(null)} disabled={generationIsActive}>取消</Button>
            <Button type="primary" loading={savingTemplate} onClick={draft?.mode === 'ai' ? saveGeneratedTemplate : saveDraft} disabled={draft?.mode === 'ai' && generation?.status !== 'succeeded'}>
              {draft?.mode === 'ai' ? '确认保存到模板库' : '保存模板'}
            </Button>
          </>
        )}
      >
        {draft && (
          <div className="template-editor-layout">
            <section className="template-editor-form">
              <div className="template-editor-meta">
                <Input placeholder="模板名称" value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} />
                <Select value={draft.categoryId ?? 0} onChange={(value) => updateDraft({ categoryId: value || null })} options={categoryOptions} />
              </div>
              <Segmented
                block
                value={draft.mode}
                disabled={Boolean(draft.id)}
                onChange={(value) => {
                  const mode = value as TemplateSourceType
                  setGeneration(null)
                  updateDraft({ mode, sourceType: mode, html: mode === 'ai' ? '' : draft.html })
                }}
                options={[
                  { label: '粘贴内容', value: 'rich_paste', icon: <PaperClipOutlined /> },
                  { label: '源码', value: 'source', icon: <CodeOutlined /> },
                  { label: 'AI 生成', value: 'ai', icon: <SendOutlined /> },
                ]}
              />
              {draft.mode === 'rich_paste' && (
                <div className="template-editor-input">
                  <div className="template-editor-input-head"><span>从其他排版工具直接粘贴内容</span><Button size="small" onClick={() => void readClipboard()}>读取剪贴板</Button></div>
                  <RichTemplateEditor html={draft.html} onChange={(html) => updateDraft({ html, sourceType: 'rich_paste' })} />
                </div>
              )}
              {draft.mode === 'source' && (
                <div className="template-editor-input">
                  <div className="template-editor-input-head"><span>静态 HTML 片段</span></div>
                  <Input.TextArea rows={15} spellCheck={false} value={draft.html} placeholder={'<section style="...">...</section>'} onChange={(event) => updateDraft({ html: event.target.value, sourceType: 'source' })} />
                </div>
              )}
              {draft.mode === 'ai' && (
                <div className="template-ai-generation">
                  <Input.TextArea rows={6} value={generationPrompt} maxLength={6000} placeholder="描述需要的公众号静态组件，例如：科技发布会文章的蓝色数据卡片，包含标题、数字和说明。" disabled={generationIsActive} onChange={(event) => setGenerationPrompt(event.target.value)} />
                  <div className="template-ai-actions">
                    <Button type="primary" icon={generationIsActive ? <LoadingOutlined spin /> : <SendOutlined />} loading={generationSubmitting} disabled={generationIsActive || !modelId} onClick={() => void generateTemplate()}>生成组件</Button>
                    {generationIsActive && <Button onClick={() => void cancelGeneration()}>取消生成</Button>}
                  </div>
                  {generation && generation.status === 'failed' && <Alert type="error" showIcon message={generation.error_message || '模板生成失败'} />}
                  {generation && generation.status === 'cancelled' && <Alert type="info" showIcon message="已取消模板生成" />}
                  {generation && generation.status === 'succeeded' && <Alert type="success" showIcon message="生成完成，请确认名称、分类和右侧预览后保存。" />}
                  {generationIsActive && <div className="template-generation-status"><Spin size="small" /> 正在生成静态公众号组件…</div>}
                </div>
              )}
            </section>
            <section className="template-editor-preview">
              <span>沙箱预览</span>
              <iframe title="模板实时预览" sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={previewDocument(draft.mode === 'ai' ? generation?.output_html ?? '' : draft.html)} />
            </section>
          </div>
        )}
      </Modal>

      <Modal title={categoryModal?.id ? '编辑分类' : '新建分类'} open={Boolean(categoryModal)} okText="保存" cancelText="取消" confirmLoading={savingCategory} onCancel={() => setCategoryModal(null)} onOk={() => void saveCategory()}>
        <Input autoFocus value={categoryModal?.name ?? ''} maxLength={80} placeholder="分类名称" onChange={(event) => setCategoryModal((current) => current ? { ...current, name: event.target.value } : current)} onPressEnter={() => void saveCategory()} />
      </Modal>

      <Modal title="分类管理" open={categoryManagerOpen} footer={null} onCancel={() => setCategoryManagerOpen(false)}>
        <div className="template-category-manager">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCategoryModal({ name: '' })}>新建分类</Button>
          <div className="template-category-manager-list">
            {categories.length ? categories.map((category) => (
              <div className="template-category-manager-item" key={category.id}>
                <span title={category.name}>{category.name}</span>
                <div>
                  <Tooltip title="编辑分类"><Button aria-label={`编辑分类 ${category.name}`} type="text" size="small" icon={<EditOutlined />} onClick={() => setCategoryModal({ id: category.id, name: category.name })} /></Tooltip>
                  <Popconfirm title={`删除「${category.name}」？`} description="模板会保留并归入未分类。" okText="删除" cancelText="取消" onConfirm={() => void deleteCategory(category)}>
                    <Button aria-label={`删除分类 ${category.name}`} type="text" danger size="small" icon={<DeleteOutlined />} />
                  </Popconfirm>
                </div>
              </div>
            )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有分类" />}
          </div>
        </div>
      </Modal>
    </aside>
  )
}
