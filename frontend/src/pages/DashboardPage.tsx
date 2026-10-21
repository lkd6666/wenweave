import { useEffect, useRef, useState } from 'react'
import { Button, Card, Dropdown, Empty, Grid, Input, List, Modal, Pagination, Select, Space, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import type { MenuProps } from 'antd'
import {
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  FileAddOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  LockOutlined,
  LinkOutlined,
  MoreOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router'
import { documentGroupsApi } from '../api/documentGroups'
import { documentsApi, isWebArticleImportPreview } from '../api/documents'
import { workbenchApi } from '../api/workbench'
import type { Page, WorkbenchDocument, WorkbenchGroupedPage } from '../api/workbench'
import { wechatAccountsApi } from '../api/wechatAccounts'
import { ApiError } from '../api/client'
import ImportReviewModal from '../components/ImportReviewModal'
import LinkImportReviewModal from '../components/LinkImportReviewModal'
import VisibilitySettingsModal from '../components/VisibilitySettingsModal'
import WeChatDraftModal from '../components/WeChatDraftModal'
import { importDocumentDirectly } from '../imports/directImportUpload'
import type { DirectImportProgress } from '../imports/directImportUpload'
import type { ParsedImport } from '../imports/types'
import type { WebArticleImportPreview } from '../api/documents'
import { useAuthStore } from '../store/authStore'
import type { DocumentDetail, DocumentGroup, DocumentSourceType, DocumentSummary, UserReference, VisibilitySettings, WeChatAvailableAccount } from '../types'
import {
  LayoutCaptureBridge,
  getWechatVerificationDetail,
  resolveWechatCaptureUrl,
  type WechatVerificationDetail,
} from '../utils/layoutCaptureBridge'
import type { CaptureUiState } from '../components/WechatCaptureFallback'

const { Title, Text } = Typography

const SOURCE_TAG: Record<DocumentSourceType, { color: string; label: string }> = {
  blank: { color: 'default', label: '空白创建' },
  pdf: { color: 'red', label: 'PDF 导入' },
  word: { color: 'blue', label: 'Word 导入' },
  markdown: { color: 'gold', label: 'Markdown 导入' },
  web: { color: 'cyan', label: '链接导入' },
}

const formatUser = (user: UserReference | null) => user?.display_name || user?.username || '未知用户'

const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

type VisibilityTarget =
  | { type: 'document'; resource: DocumentSummary }
  | { type: 'group'; resource: DocumentGroup }

type WeChatDraftTarget = {
  document: DocumentDetail
  accounts: WeChatAvailableAccount[]
}

type DocumentPaginationState = {
  page: number
  pageSize: number
}

type WorkspaceView = 'grouped' | 'all'

const firstValidPage = (total: number, pageSize: number, requestedPage: number) =>
  Math.min(requestedPage, Math.max(1, Math.ceil(total / pageSize)))

const GROUP_DOCUMENT_PAGE_SIZE_OPTIONS = [5, 10, 20, 50, 100]

function replaceDocumentInPage<T extends DocumentSummary>(page: Page<T>, documentId: number, update: (document: T) => T): Page<T>
function replaceDocumentInPage<T extends DocumentSummary>(page: Page<T> | null, documentId: number, update: (document: T) => T): Page<T> | null
function replaceDocumentInPage<T extends DocumentSummary>(page: Page<T> | null, documentId: number, update: (document: T) => T) {
  if (!page) return page
  return {
    ...page,
    items: page.items.map((document) => document.id === documentId ? update(document) : document),
  }
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [modal, modalContextHolder] = Modal.useModal()
  const currentUserId = useAuthStore((state) => state.user?.id)
  const isAdmin = useAuthStore((state) => state.user?.role === 'admin')
  const [groupOptions, setGroupOptions] = useState<DocumentGroup[]>([])
  const [groupedWorkspace, setGroupedWorkspace] = useState<WorkbenchGroupedPage | null>(null)
  const [allDocuments, setAllDocuments] = useState<Page<WorkbenchDocument> | null>(null)
  const [searchResults, setSearchResults] = useState<Page<WorkbenchDocument> | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createBlankOpen, setCreateBlankOpen] = useState(false)
  const [createBlankTitle, setCreateBlankTitle] = useState('未命名推文')
  const [createBlankGroupId, setCreateBlankGroupId] = useState<number | null>(null)
  const [importing, setImporting] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importReviewOpen, setImportReviewOpen] = useState(false)
  const [importProgress, setImportProgress] = useState<DirectImportProgress | null>(null)
  const [importError, setImportError] = useState('')
  const [linkImportOpen, setLinkImportOpen] = useState(false)
  const [linkImportLoading, setLinkImportLoading] = useState(false)
  const [linkImporting, setLinkImporting] = useState(false)
  const [linkImportPreview, setLinkImportPreview] = useState<WebArticleImportPreview | null>(null)
  const [linkImportError, setLinkImportError] = useState('')
  const [linkImportWechatFallback, setLinkImportWechatFallback] = useState<WechatVerificationDetail | null>(null)
  const [linkImportCaptureState, setLinkImportCaptureState] = useState<CaptureUiState>('idle')
  const [linkImportCaptureError, setLinkImportCaptureError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [view, setView] = useState<WorkspaceView>('grouped')
  const [groupPagination, setGroupPagination] = useState<DocumentPaginationState>({ page: 1, pageSize: 10 })
  const [allPagination, setAllPagination] = useState<DocumentPaginationState>({ page: 1, pageSize: 20 })
  const [searchPagination, setSearchPagination] = useState<DocumentPaginationState>({ page: 1, pageSize: 20 })
  const [documentPagination, setDocumentPagination] = useState<Record<string, DocumentPaginationState>>({})
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [visibilityTarget, setVisibilityTarget] = useState<VisibilityTarget | null>(null)
  const [wechatAccounts, setWechatAccounts] = useState<WeChatAvailableAccount[]>([])
  const [wechatDraftTarget, setWechatDraftTarget] = useState<WeChatDraftTarget | null>(null)
  const [loadingWeChatDocumentId, setLoadingWeChatDocumentId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const importAbortRef = useRef<AbortController | null>(null)
  const linkImportBridgeRef = useRef<LayoutCaptureBridge<WebArticleImportPreview> | null>(null)
  const linkImportRequestVersionRef = useRef(0)
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const hasAiEditingDocument = Boolean(
    groupedWorkspace?.groups.items.some((item) => item.documents.items.some((document) => document.is_ai_editing))
    || groupedWorkspace?.ungrouped.items.some((document) => document.is_ai_editing)
    || allDocuments?.items.some((document) => document.is_ai_editing)
    || searchResults?.items.some((document) => document.is_ai_editing),
  )

  useEffect(() => {
    if (!linkImportOpen) return
    const bridge = new LayoutCaptureBridge<WebArticleImportPreview>((event) => {
      if (event.type === 'status') {
        setLinkImportCaptureState(event.status)
        setLinkImportCaptureError(null)
        return
      }
      if (event.type === 'error') {
        setLinkImportCaptureState('error')
        setLinkImportCaptureError(event.message)
        return
      }
      setLinkImportPreview(event.preview)
      setLinkImportWechatFallback(null)
      setLinkImportCaptureState('idle')
      setLinkImportCaptureError(null)
      setLinkImportError('')
    }, window, window.location.origin, undefined, isWebArticleImportPreview)
    linkImportBridgeRef.current = bridge
    return () => {
      linkImportRequestVersionRef.current += 1
      bridge.dispose()
      if (linkImportBridgeRef.current === bridge) linkImportBridgeRef.current = null
    }
  }, [linkImportOpen])
  const showInitialLoading = loading && !groupedWorkspace && !allDocuments && !searchResults

  const loadGroupOptions = async () => {
    setGroupOptions(await documentGroupsApi.list())
  }

  const loadGroupedWorkspace = async (
    requestedPage = groupPagination.page,
    requestedPageSize = groupPagination.pageSize,
    retainDocumentPages = true,
  ) => {
    setLoading(true)
    try {
      let workspace = await workbenchApi.groups(requestedPage, requestedPageSize, 5)
      const resolvedPage = firstValidPage(workspace.groups.total, requestedPageSize, requestedPage)
      if (workspace.groups.total > 0 && resolvedPage !== requestedPage) {
        workspace = await workbenchApi.groups(resolvedPage, requestedPageSize, 5)
      }

      if (retainDocumentPages) {
        const groupItems = await Promise.all(workspace.groups.items.map(async (item) => {
          const pagination = documentPagination[`group:${item.group.id}`]
          if (!pagination || (pagination.page === 1 && pagination.pageSize === 5)) return item
          let documents = await workbenchApi.groupDocuments(item.group.id, pagination.page, pagination.pageSize)
          const page = firstValidPage(documents.total, pagination.pageSize, pagination.page)
          if (documents.total > 0 && page !== pagination.page) {
            documents = await workbenchApi.groupDocuments(item.group.id, page, pagination.pageSize)
            setDocumentPagination((states) => ({ ...states, [`group:${item.group.id}`]: { page, pageSize: pagination.pageSize } }))
          }
          return { ...item, documents }
        }))
        const ungroupedPagination = documentPagination.ungrouped
        let ungrouped = workspace.ungrouped
        if (ungroupedPagination && (ungroupedPagination.page !== 1 || ungroupedPagination.pageSize !== 5)) {
          ungrouped = await workbenchApi.ungroupedDocuments(ungroupedPagination.page, ungroupedPagination.pageSize)
          const page = firstValidPage(ungrouped.total, ungroupedPagination.pageSize, ungroupedPagination.page)
          if (ungrouped.total > 0 && page !== ungroupedPagination.page) {
            ungrouped = await workbenchApi.ungroupedDocuments(page, ungroupedPagination.pageSize)
            setDocumentPagination((states) => ({ ...states, ungrouped: { page, pageSize: ungroupedPagination.pageSize } }))
          }
        }
        workspace = { ...workspace, groups: { ...workspace.groups, items: groupItems }, ungrouped }
      }
      setGroupedWorkspace(workspace)
      setGroupPagination({ page: workspace.groups.page, pageSize: workspace.groups.page_size })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载推文列表失败')
    } finally {
      setLoading(false)
    }
  }

  const loadFlatDocuments = async (
    requestedPage: number,
    requestedPageSize: number,
    query: string,
    target: 'all' | 'search',
  ) => {
    setLoading(true)
    try {
      let result = await workbenchApi.documents(requestedPage, requestedPageSize, query)
      const resolvedPage = firstValidPage(result.total, requestedPageSize, requestedPage)
      if (result.total > 0 && resolvedPage !== requestedPage) {
        result = await workbenchApi.documents(resolvedPage, requestedPageSize, query)
      }
      if (target === 'search') {
        setSearchResults(result)
        setSearchPagination({ page: result.page, pageSize: result.page_size })
      } else {
        setAllDocuments(result)
        setAllPagination({ page: result.page, pageSize: result.page_size })
      }
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载推文列表失败')
    } finally {
      setLoading(false)
    }
  }

  const load = async () => {
    try {
      await Promise.all([
        loadGroupOptions(),
        wechatAccountsApi.available().then(setWechatAccounts).catch(() => setWechatAccounts([])),
      ])
      if (searchQuery) {
        await loadFlatDocuments(searchPagination.page, searchPagination.pageSize, searchQuery, 'search')
      } else if (view === 'all') {
        await loadFlatDocuments(allPagination.page, allPagination.pageSize, '', 'all')
      } else {
        await loadGroupedWorkspace()
      }
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载工作台失败')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (!searchQuery) return
    void loadFlatDocuments(1, searchPagination.pageSize, searchQuery, 'search')
  }, [searchQuery])

  useEffect(() => {
    if (!hasAiEditingDocument) return
    let timer: number | null = null
    let refreshInFlight = false
    const refreshAiEditingStatus = async () => {
      if (refreshInFlight) return
      refreshInFlight = true
      try {
        const { active_document_ids: activeDocumentIds } = await documentsApi.aiEditingStatus()
        const activeIds = new Set(activeDocumentIds)
        const setAiEditing = <T extends DocumentSummary>(document: T): T => (
          document.is_ai_editing === activeIds.has(document.id)
            ? document
            : { ...document, is_ai_editing: activeIds.has(document.id) }
        )
        setGroupedWorkspace((workspace) => workspace && ({
          ...workspace,
          groups: {
            ...workspace.groups,
            items: workspace.groups.items.map((item) => ({
              ...item,
              documents: { ...item.documents, items: item.documents.items.map(setAiEditing) },
            })),
          },
          ungrouped: { ...workspace.ungrouped, items: workspace.ungrouped.items.map(setAiEditing) },
        }))
        setAllDocuments((page) => page && ({ ...page, items: page.items.map(setAiEditing) }))
        setSearchResults((page) => page && ({ ...page, items: page.items.map(setAiEditing) }))
      } catch {
        // The next polling cycle will retry without interrupting the workspace.
      } finally {
        refreshInFlight = false
      }
    }
    const stopPolling = () => {
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    }
    const syncPolling = () => {
      stopPolling()
      if (document.visibilityState !== 'visible') return
      void refreshAiEditingStatus()
      timer = window.setInterval(() => { void refreshAiEditingStatus() }, 3000)
    }
    syncPolling()
    document.addEventListener('visibilitychange', syncPolling)
    return () => {
      document.removeEventListener('visibilitychange', syncPolling)
      stopPolling()
    }
  }, [hasAiEditingDocument])

  const handleCreateGroup = () => {
    let name = ''
    modal.confirm({
      title: '新建推文分组',
      content: <Input autoFocus placeholder="例如：品牌活动" onChange={(event) => (name = event.target.value)} />,
      onOk: async () => {
        if (!name.trim()) {
          message.error('请输入分组名称')
          return Promise.reject()
        }
        await documentGroupsApi.create(name.trim())
        message.success('分组已创建')
        await load()
      },
    })
  }

  const handleRenameGroup = (group: DocumentGroup) => {
    let name = group.name
    modal.confirm({
      title: '修改分组名称',
      content: <Input autoFocus defaultValue={name} onChange={(event) => (name = event.target.value)} />,
      onOk: async () => {
        if (!name.trim()) {
          message.error('请输入分组名称')
          return Promise.reject()
        }
        await documentGroupsApi.update(group.id, name.trim())
        message.success('分组已更新')
        await load()
      },
    })
  }

  const handleDeleteGroup = (group: DocumentGroup) => {
    modal.confirm({
      title: `删除分组「${group.name}」？`,
      content: '该分组内的推文会移动到“未分组”，推文本身不会被删除。',
      okButtonProps: { danger: true },
      onOk: async () => {
        await documentGroupsApi.remove(group.id)
        message.success('分组已删除')
        await load()
      },
    })
  }

  const handleCreateBlank = (defaultGroupId: number | null = null) => {
    setCreateBlankTitle('未命名推文')
    setCreateBlankGroupId(defaultGroupId)
    setCreateBlankOpen(true)
  }

  const submitCreateBlank = async () => {
    setCreating(true)
    try {
      const doc = await documentsApi.create(createBlankTitle.trim() || '未命名推文', createBlankGroupId)
      setCreateBlankOpen(false)
      message.success('已创建')
      navigate(`/editor/${doc.id}`)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    const ext = file.name.split('.').pop()?.toLowerCase()
    if (ext !== 'pdf' && ext !== 'docx' && ext !== 'md') {
      message.error('仅支持上传 PDF、Word(.docx) 或 Markdown(.md) 文件')
      return
    }

    setImportFile(file)
    setImportProgress(null)
    setImportError('')
    setImportReviewOpen(true)
  }

  const handleImportConfirm = async (preparedImport: ParsedImport | null) => {
    if (!importFile) return
    setImporting(true)
    const controller = new AbortController()
    importAbortRef.current = controller
    setImportError('')
    setImportProgress({ phase: 'parsing', percent: 0, detail: '正在准备上传…' })
    try {
      const doc = await importDocumentDirectly(importFile, setImportProgress, controller.signal, preparedImport ?? undefined)
      message.success('导入成功，可在列表中移动到所需分组')
      setImportReviewOpen(false)
      setImportFile(null)
      navigate(`/editor/${doc.id}`)
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '导入失败'
        const visibleError = `导入未完成：${detail || '浏览器未返回具体错误，请刷新后重试'}`
        setImportError(visibleError)
        message.error(visibleError)
      }
    } finally {
      importAbortRef.current = null
      setImporting(false)
    }
  }

  const releaseLinkImportPreview = (preview = linkImportPreview) => {
    if (preview) void documentsApi.cancelWebArticleImport(preview.id).catch(() => undefined)
  }

  const handleLinkImportPreview = async (url: string) => {
    if (!url) {
      setLinkImportError('请输入公开 HTTPS 文章链接')
      return
    }
    const requestVersion = linkImportRequestVersionRef.current + 1
    linkImportRequestVersionRef.current = requestVersion
    linkImportBridgeRef.current?.cancel()
    releaseLinkImportPreview()
    setLinkImportPreview(null)
    setLinkImportLoading(true)
    setLinkImportError('')
    setLinkImportWechatFallback(null)
    setLinkImportCaptureState('idle')
    setLinkImportCaptureError(null)
    try {
      const preview = await documentsApi.previewWebArticleImport(url)
      if (linkImportRequestVersionRef.current !== requestVersion) return
      setLinkImportPreview(preview)
    } catch (err) {
      if (linkImportRequestVersionRef.current !== requestVersion) return
      const verification = getWechatVerificationDetail(err)
      if (verification) {
        const captureUrl = resolveWechatCaptureUrl(verification.url, url) || verification.url
        setLinkImportWechatFallback({ ...verification, url: captureUrl })
        setLinkImportCaptureState('checking')
        const connection = await linkImportBridgeRef.current?.connect('web_article_import') ?? 'missing'
        if (linkImportRequestVersionRef.current === requestVersion) {
          setLinkImportCaptureState(connection === 'available' ? 'ready' : connection)
        }
      } else {
        const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '文章链接解析失败'
        setLinkImportError(detail)
      }
    } finally {
      if (linkImportRequestVersionRef.current === requestVersion) setLinkImportLoading(false)
    }
  }

  const detectLinkImportExtension = async () => {
    setLinkImportCaptureState('checking')
    setLinkImportCaptureError(null)
    const connection = await linkImportBridgeRef.current?.connect('web_article_import') ?? 'missing'
    setLinkImportCaptureState(connection === 'available' ? 'ready' : connection)
  }

  const startLinkImportCapture = async () => {
    if (!linkImportWechatFallback || !linkImportBridgeRef.current) return
    setLinkImportCaptureState('opening')
    setLinkImportCaptureError(null)
    try {
      const session = await documentsApi.createWebArticleCaptureSession(linkImportWechatFallback.url)
      linkImportBridgeRef.current.startSession(session)
    } catch (err) {
      setLinkImportCaptureState('error')
      setLinkImportCaptureError(err instanceof ApiError ? String(err.detail) : '创建浏览器采集会话失败，请重试')
    }
  }

  const resetLinkImportCapture = () => {
    linkImportRequestVersionRef.current += 1
    linkImportBridgeRef.current?.cancel()
    releaseLinkImportPreview()
    setLinkImportPreview(null)
    setLinkImportError('')
    setLinkImportWechatFallback(null)
    setLinkImportCaptureState('idle')
    setLinkImportCaptureError(null)
    setLinkImportLoading(false)
  }

  const handleLinkImportConfirm = async () => {
    if (!linkImportPreview) return
    setLinkImporting(true)
    setLinkImportError('')
    try {
      const doc = await documentsApi.completeWebArticleImport(linkImportPreview.id)
      setLinkImportOpen(false)
      setLinkImportPreview(null)
      message.success('文章已导入，可继续编辑')
      navigate(`/editor/${doc.id}`)
    } catch (err) {
      const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '文章导入失败'
      setLinkImportError(detail)
    } finally {
      setLinkImporting(false)
    }
  }

  const handleLinkImportClose = () => {
    resetLinkImportCapture()
    setLinkImportOpen(false)
  }

  const handleDelete = (doc: DocumentSummary) => {
    modal.confirm({
      title: `确认删除「${doc.title}」？`,
      content: '删除后无法恢复。',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await documentsApi.remove(doc.id)
          message.success('已删除')
          await load()
        } catch (err) {
          message.error(err instanceof ApiError ? String(err.detail) : '删除失败')
        }
      },
    })
  }

  const handleMoveToGroup = async (doc: DocumentSummary, groupId: number | null) => {
    if (doc.group_id === groupId) return
    try {
      await documentsApi.update(doc.id, { group_id: groupId })
      message.success(groupId === null ? '已移至未分组' : '已移动到分组')
      await load()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '移动分组失败')
    }
  }

  const handleSaveVisibility = async (settings: VisibilitySettings) => {
    if (!visibilityTarget) return
    try {
      if (visibilityTarget.type === 'document') {
        await documentsApi.update(visibilityTarget.resource.id, settings)
      } else {
        await documentGroupsApi.update(visibilityTarget.resource.id, settings)
      }
      message.success('可见权限已保存')
      await load()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '保存可见权限失败')
      throw err
    }
  }

  const handleOpenWeChatDraft = async (doc: DocumentSummary) => {
    if (doc.is_ai_editing) {
      message.warning('当前推文正在由 AI 编辑，完成或停止后才能同步公众号草稿')
      return
    }
    setLoadingWeChatDocumentId(doc.id)
    try {
      const [detail, availableAccounts] = await Promise.all([
        documentsApi.get(doc.id),
        wechatAccountsApi.available(),
      ])
      if (detail.is_ai_editing) {
        message.warning('当前推文正在由 AI 编辑，完成或停止后才能同步公众号草稿')
        return
      }
      setWechatAccounts(availableAccounts)
      setWechatDraftTarget({ document: detail, accounts: availableAccounts })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载公众号草稿信息失败')
    } finally {
      setLoadingWeChatDocumentId(null)
    }
  }

  const handleWeChatMetadataSaved = (metadata: DocumentDetail['wechat_metadata'], title: string) => {
    if (!wechatDraftTarget) return
    const documentId = wechatDraftTarget.document.id
    setWechatDraftTarget({
      ...wechatDraftTarget,
      document: { ...wechatDraftTarget.document, title, wechat_metadata: metadata },
    })
    const updateDocument = <T extends DocumentSummary>(document: T): T => (
      document.id === documentId ? { ...document, title, wechat_cover_url: metadata.cover_url } : document
    )
    setGroupedWorkspace((workspace) => workspace && ({
      ...workspace,
      groups: {
        ...workspace.groups,
        items: workspace.groups.items.map((item) => ({
          ...item,
          documents: replaceDocumentInPage(item.documents, documentId, updateDocument),
        })),
      },
      ungrouped: replaceDocumentInPage(workspace.ungrouped, documentId, updateDocument),
    }))
    setAllDocuments((page) => replaceDocumentInPage(page, documentId, updateDocument))
    setSearchResults((page) => replaceDocumentInPage(page, documentId, updateDocument))
  }

  const loadGroupedDocumentPage = async (groupId: number, requestedPage: number, requestedPageSize: number) => {
    setLoading(true)
    try {
      let documents = await workbenchApi.groupDocuments(groupId, requestedPage, requestedPageSize)
      const page = firstValidPage(documents.total, requestedPageSize, requestedPage)
      if (documents.total > 0 && page !== requestedPage) {
        documents = await workbenchApi.groupDocuments(groupId, page, requestedPageSize)
      }
      setDocumentPagination((states) => ({ ...states, [`group:${groupId}`]: { page: documents.page, pageSize: documents.page_size } }))
      setGroupedWorkspace((workspace) => workspace && ({
        ...workspace,
        groups: {
          ...workspace.groups,
          items: workspace.groups.items.map((item) => item.group.id === groupId ? { ...item, documents } : item),
        },
      }))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载分组推文失败')
    } finally {
      setLoading(false)
    }
  }

  const loadUngroupedDocumentPage = async (requestedPage: number, requestedPageSize: number) => {
    setLoading(true)
    try {
      let documents = await workbenchApi.ungroupedDocuments(requestedPage, requestedPageSize)
      const page = firstValidPage(documents.total, requestedPageSize, requestedPage)
      if (documents.total > 0 && page !== requestedPage) {
        documents = await workbenchApi.ungroupedDocuments(page, requestedPageSize)
      }
      setDocumentPagination((states) => ({ ...states, ungrouped: { page: documents.page, pageSize: documents.page_size } }))
      setGroupedWorkspace((workspace) => workspace && ({ ...workspace, ungrouped: documents }))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载未分组推文失败')
    } finally {
      setLoading(false)
    }
  }

  const renderDocuments = (
    pageData: Page<DocumentSummary>,
    onPageChange: (page: number, pageSize: number) => void,
    showGroupName = false,
    pageSizeOptions = [20, 50, 100],
  ) => {
    if (pageData.total === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此分组暂无推文" />

    const renderDocument = (doc: DocumentSummary) => {
          const tag = SOURCE_TAG[doc.source_type]
          const icon =
            doc.source_type === 'pdf' ? (
              <FilePdfOutlined style={{ fontSize: 20, color: '#cf1322' }} />
            ) : doc.source_type === 'word' ? (
              <FileWordOutlined style={{ fontSize: 20, color: '#1d39c4' }} />
            ) : doc.source_type === 'markdown' ? (
              <FileTextOutlined style={{ fontSize: 20, color: '#ad6800' }} />
            ) : doc.source_type === 'web' ? (
              <LinkOutlined style={{ fontSize: 20, color: '#08979c' }} />
            ) : (
              <FileAddOutlined style={{ fontSize: 20 }} />
            )
          const groupMenu: MenuProps['items'] = [
            { key: 'ungrouped', label: '移至未分组', disabled: doc.group_id === null },
            ...groupOptions.map((group) => ({ key: String(group.id), label: group.name, disabled: doc.group_id === group.id })),
          ]
          const compactMoveMenu: MenuProps['items'] = [
            { key: 'move-ungrouped', label: '移至未分组', disabled: doc.group_id === null },
            ...groupOptions.map((group) => ({ key: `move-${group.id}`, label: group.name, disabled: doc.group_id === group.id })),
          ]
          const canConfigureDocumentVisibility = isAdmin || doc.created_by?.id === currentUserId
          const canOpenWeChatDraft = isAdmin || wechatAccounts.length > 0
          const wechatActionTooltip = doc.is_ai_editing
            ? '当前推文正在由 AI 编辑，完成或停止后才能同步公众号草稿'
            : wechatAccounts.length
              ? '处理封面并推送公众号草稿'
              : '请先在后台配置并启用公众号账号'
          const wechatAction = (
            <Tooltip key="wechat" title={wechatActionTooltip}>
              <span>
                <Button
                  aria-label={`处理推文 ${doc.title} 的公众号封面与草稿`}
                  className="dashboard-document-action"
                  type="text"
                  icon={<SendOutlined />}
                  loading={loadingWeChatDocumentId === doc.id}
                  disabled={doc.is_ai_editing || wechatAccounts.length === 0}
                  onClick={() => void handleOpenWeChatDraft(doc)}
                />
              </span>
            </Tooltip>
          )
          const documentAvatar = doc.wechat_cover_url ? (
            <Tooltip title={doc.is_ai_editing ? 'AI 编辑完成后才能处理公众号封面和草稿' : '查看或编辑公众号封面'}>
              <span>
                <Button
                  aria-label={`查看或编辑推文 ${doc.title} 的公众号封面`}
                  className="dashboard-wechat-cover"
                  type="text"
                  disabled={doc.is_ai_editing || !canOpenWeChatDraft || wechatAccounts.length === 0}
                  onClick={() => void handleOpenWeChatDraft(doc)}
                >
                  <img src={doc.wechat_cover_url} alt={`${doc.title} 封面`} />
                </Button>
              </span>
            </Tooltip>
          ) : (
            <span className="dashboard-document-avatar">{icon}</span>
          )
          const compactMenu: MenuProps['items'] = [
            { key: 'open', label: '打开推文' },
            ...(canOpenWeChatDraft ? [{ key: 'wechat', label: doc.is_ai_editing ? '公众号草稿（AI 编辑中）' : '公众号草稿', icon: <SendOutlined />, disabled: doc.is_ai_editing }] : []),
            ...(canConfigureDocumentVisibility ? [
              { key: 'visibility', label: '可见权限' },
            ] : []),
            {
              key: 'move',
              label: '移动到分组',
              children: compactMoveMenu,
            },
            { type: 'divider' as const },
            { key: 'delete', label: '删除推文', danger: true },
          ]
          const desktopMenu: MenuProps['items'] = [
            { key: 'move', label: '移动到分组', icon: <FolderOpenOutlined />, children: groupMenu },
            ...(canConfigureDocumentVisibility ? [{ key: 'visibility', label: '可见权限', icon: <SafetyCertificateOutlined /> }] : []),
            { type: 'divider' as const },
            { key: 'delete', label: '删除推文', icon: <DeleteOutlined />, danger: true },
          ]
          const handleDesktopMenuAction: MenuProps['onClick'] = ({ key }) => {
            const action = String(key)
            if (action === 'visibility') setVisibilityTarget({ type: 'document', resource: doc })
            else if (action === 'delete') handleDelete(doc)
            else handleMoveToGroup(doc, action === 'ungrouped' ? null : Number(action))
          }
          const handleCompactAction: MenuProps['onClick'] = ({ key }) => {
            const action = String(key)
            if (action === 'open') navigate(`/editor/${doc.id}`)
            else if (action === 'wechat') void handleOpenWeChatDraft(doc)
            else if (action === 'visibility') setVisibilityTarget({ type: 'document', resource: doc })
            else if (action === 'delete') handleDelete(doc)
            else if (action.startsWith('move-')) {
              const target = action.slice('move-'.length)
              handleMoveToGroup(doc, target === 'ungrouped' ? null : Number(target))
            }
          }
          const compactAction = (
            <Dropdown menu={{ items: compactMenu, onClick: handleCompactAction }} trigger={['click']}>
              <Button aria-label={`操作推文 ${doc.title}`} type="text" icon={<MoreOutlined />} />
            </Dropdown>
          )

          if (isCompact) {
            return (
              <article className="dashboard-document-card" key={doc.id}>
                <div className="dashboard-document-card-heading">
                  {documentAvatar}
                  <div className="dashboard-document-card-title">
                    <Button type="link" onClick={() => navigate(`/editor/${doc.id}`)}>{doc.title}</Button>
                    <div className="dashboard-document-card-tags">
                      <Tag color={tag.color}>{tag.label}</Tag>
                      {showGroupName && <Tag>{(doc as WorkbenchDocument).group_name || '未分组'}</Tag>}
                      {doc.is_ai_editing && <Tag color="processing">AI 编辑中</Tag>}
                      {doc.visibility_mode === 'restricted' && <Tag color="gold" icon={<LockOutlined />}>受限可见</Tag>}
                    </div>
                  </div>
                  <Space className="dashboard-document-card-actions" size={0}>
                    {canOpenWeChatDraft && wechatAction}
                    {compactAction}
                  </Space>
                </div>
                <div className="dashboard-document-card-meta">
                  <span>创建人：{formatUser(doc.created_by)}</span>
                  <span>最后修改：{formatUser(doc.last_modified_by)} · {formatDate(doc.updated_at)}</span>
                </div>
              </article>
            )
          }

          return (
            <List.Item className="dashboard-document-item">
              <List.Item.Meta
                avatar={documentAvatar}
                title={
                  <Space className="dashboard-document-title" size={[8, 4]} wrap>
                    <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/editor/${doc.id}`)}>
                      {doc.title}
                    </Button>
                    <Tag color={tag.color}>{tag.label}</Tag>
                    {showGroupName && <Tag>{(doc as WorkbenchDocument).group_name || '未分组'}</Tag>}
                    {doc.is_ai_editing && <Tag color="processing">AI 编辑中</Tag>}
                    {doc.visibility_mode === 'restricted' && (
                      <Tooltip title="仅指定用户或用户组可见">
                        <Tag color="gold" icon={<LockOutlined />}>受限可见</Tag>
                      </Tooltip>
                    )}
                  </Space>
                }
                description={
                  <Space size={[12, 4]} wrap>
                    <Text type="secondary">创建人：{formatUser(doc.created_by)}</Text>
                    <Text type="secondary">
                      最后修改：{formatUser(doc.last_modified_by)} · {formatDate(doc.updated_at)}
                    </Text>
                  </Space>
                }
              />
              <div className="dashboard-document-item-actions">
                <Tooltip title="打开推文">
                  <Button
                    aria-label={`打开推文 ${doc.title}`}
                    type="link"
                    icon={<EditOutlined />}
                    onClick={() => navigate(`/editor/${doc.id}`)}
                  >
                    编辑
                  </Button>
                </Tooltip>
                {canOpenWeChatDraft && (
                  <Tooltip title={wechatActionTooltip}>
                    <span>
                      <Button
                        aria-label={`同步推文 ${doc.title} 到公众号草稿`}
                        type="text"
                        icon={<SendOutlined />}
                        loading={loadingWeChatDocumentId === doc.id}
                        disabled={doc.is_ai_editing || wechatAccounts.length === 0}
                        onClick={() => void handleOpenWeChatDraft(doc)}
                      >
                        同步
                      </Button>
                    </span>
                  </Tooltip>
                )}
                <Dropdown menu={{ items: desktopMenu, onClick: handleDesktopMenuAction }} trigger={['click']}>
                  <Tooltip title="更多操作">
                    <Button aria-label={`更多推文 ${doc.title} 操作`} type="text" icon={<MoreOutlined />} />
                  </Tooltip>
                </Dropdown>
              </div>
            </List.Item>
          )
    }

    if (isCompact) {
      return (
        <>
          <div className="dashboard-document-card-list">{pageData.items.map(renderDocument)}</div>
          {pageData.total > pageData.page_size && (
            <div className="dashboard-group-pagination">
              <Pagination
                size="small"
                current={pageData.page}
                pageSize={pageData.page_size}
                total={pageData.total}
                showSizeChanger
                pageSizeOptions={pageSizeOptions}
                showTotal={(total) => `共 ${total} 篇`}
                onChange={onPageChange}
              />
            </div>
          )}
        </>
      )
    }

    return (
      <>
        <List itemLayout="horizontal" dataSource={pageData.items} renderItem={renderDocument} />
        {pageData.total > pageData.page_size && (
          <div className="dashboard-group-pagination">
            <Pagination
              current={pageData.page}
              pageSize={pageData.page_size}
              total={pageData.total}
              showSizeChanger
              pageSizeOptions={pageSizeOptions}
              showTotal={(total) => `共 ${total} 篇`}
              onChange={onPageChange}
            />
          </div>
        )}
      </>
    )
  }

  const toggleGroup = (groupKey: string) => {
    setCollapsedGroups((groups) => ({ ...groups, [groupKey]: !groups[groupKey] }))
  }

  const handleGroupHeadingKeyDown = (event: React.KeyboardEvent<HTMLElement>, groupKey: string) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    toggleGroup(groupKey)
  }

  const renderGroup = (item: WorkbenchGroupedPage['groups']['items'][number]) => {
    const { group } = item
    const groupKey = `group:${group.id}`
    const collapsed = Boolean(collapsedGroups[groupKey])
    const canConfigureGroupVisibility = isAdmin || group.created_by?.id === currentUserId
    const groupMenu: MenuProps['items'] = [
      { key: 'rename', label: '修改名称', icon: <EditOutlined /> },
      { key: 'delete', label: '删除分组', icon: <DeleteOutlined />, danger: true },
    ]
    if (canConfigureGroupVisibility) groupMenu.unshift({ key: 'visibility', label: '可见权限', icon: <SafetyCertificateOutlined /> })

    return (
      <section className={`dashboard-group${collapsed ? ' is-collapsed' : ''}`} key={group.id}>
        <div
          className="dashboard-group-heading"
          role="button"
          tabIndex={0}
          aria-label={`${collapsed ? '展开' : '收起'}分组 ${group.name}`}
          aria-expanded={!collapsed}
          onClick={() => toggleGroup(groupKey)}
          onKeyDown={(event) => handleGroupHeadingKeyDown(event, groupKey)}
        >
          <div className="dashboard-group-title">
            <Tooltip title={collapsed ? '展开分组' : '收起分组'}>
              <Button
                aria-label={`${collapsed ? '展开' : '收起'}分组 ${group.name}`}
                aria-expanded={!collapsed}
                className={`dashboard-group-toggle${collapsed ? ' is-collapsed' : ''}`}
                type="text"
                icon={<DownOutlined className="dashboard-group-toggle-icon" />}
                onClick={(event) => {
                  event.stopPropagation()
                  toggleGroup(groupKey)
                }}
                onKeyDown={(event) => event.stopPropagation()}
              />
            </Tooltip>
            <span className="dashboard-group-icon"><FolderOpenOutlined /></span>
            <div>
              <div className="dashboard-group-name">
                <Text strong>{group.name}</Text>
                <Tag bordered={false} className="dashboard-group-count">{item.document_total} 篇</Tag>
                {group.visibility_mode === 'restricted' && (
                  <Tooltip title="仅指定用户或用户组可见">
                    <Tag color="gold" icon={<LockOutlined />}>受限可见</Tag>
                  </Tooltip>
                )}
              </div>
              <div className="dashboard-group-meta">
                <span>最后修改：{formatUser(group.last_modified_by)} · {formatDate(group.updated_at)}</span>
              </div>
            </div>
          </div>
          <Space className="dashboard-group-actions" size={2} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
            <Tooltip title={`在「${group.name}」中新建推文`}>
              <Button aria-label={`在分组 ${group.name} 中新建推文`} type="text" icon={<FileAddOutlined />} onClick={() => handleCreateBlank(group.id)}>
                <span className="dashboard-group-create-label">新建推文</span>
              </Button>
            </Tooltip>
            {groupMenu.length > 0 && (
              <Dropdown
                menu={{
                  items: groupMenu,
                  onClick: ({ key }) => {
                    if (key === 'visibility') setVisibilityTarget({ type: 'group', resource: group })
                    else if (key === 'rename') handleRenameGroup(group)
                    else handleDeleteGroup(group)
                  },
                }}
              >
                <Tooltip title="分组操作">
                  <Button aria-label={`操作分组 ${group.name}`} type="text" icon={<MoreOutlined />} />
                </Tooltip>
              </Dropdown>
            )}
          </Space>
        </div>
        <div className={`dashboard-group-collapse${collapsed ? ' is-collapsed' : ''}`} aria-hidden={collapsed}>
          <div className="dashboard-group-collapse-inner" inert={collapsed}>
            <div className="dashboard-group-content">
              {renderDocuments(item.documents, (page, pageSize) => {
                void loadGroupedDocumentPage(group.id, pageSize === item.documents.page_size ? page : 1, pageSize)
              }, false, GROUP_DOCUMENT_PAGE_SIZE_OPTIONS)}
            </div>
          </div>
        </div>
      </section>
    )
  }

  const handleViewChange = (nextView: string) => {
    const value = nextView as WorkspaceView
    setView(value)
    if (value === 'all' && !allDocuments) {
      void loadFlatDocuments(allPagination.page, allPagination.pageSize, '', 'all')
    }
    if (value === 'grouped' && !groupedWorkspace) {
      void loadGroupedWorkspace()
    }
  }

  const renderFlatDocuments = (pageData: Page<WorkbenchDocument> | null, target: 'all' | 'search') => {
    if (!pageData) return null
    if (pageData.total === 0) return <Empty description={target === 'search' ? '没有找到匹配的推文或分组' : '还没有任何推文，点击右上角新建或导入'} />
    return renderDocuments(pageData, (page, pageSize) => {
      const current = target === 'search' ? searchPagination : allPagination
      void loadFlatDocuments(pageSize === current.pageSize ? page : 1, pageSize, target === 'search' ? searchQuery : '', target)
    }, true)
  }

  return (
    <div className="dashboard-page">
      {modalContextHolder}
      <div className="dashboard-page-header">
        <Title level={4} style={{ margin: 0 }}>
          推文工作台
        </Title>
        <Input.Search
          allowClear
          aria-label="搜索推文或分组"
          value={search}
          onChange={(event) => {
            const value = event.target.value
            setSearch(value)
            if (!value.trim()) setSearchQuery('')
          }}
          placeholder="搜索推文标题或分组名称"
          className="dashboard-search"
        />
        <Space className="dashboard-actions" wrap>
          <Button icon={<FolderAddOutlined />} onClick={handleCreateGroup}>
            新建分组
          </Button>
          <Button icon={<FileAddOutlined />} loading={creating} onClick={() => handleCreateBlank()}>
            新建空白推文
          </Button>
          <Button type="primary" icon={<UploadOutlined />} loading={importing} onClick={handleImportClick}>
            从文件导入
          </Button>
          <Button icon={<LinkOutlined />} loading={linkImportLoading || linkImporting} onClick={() => setLinkImportOpen(true)}>
            导入文章链接
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.md,text/markdown,text/plain"
            style={{ display: 'none' }}
            onChange={handleFileSelected}
          />
        </Space>
      </div>

      <Card className="dashboard-workspace-card" loading={showInitialLoading}>
        {searchQuery ? (
          <section className="dashboard-flat-results" aria-label="搜索结果">
            <Text strong>搜索结果</Text>
            {renderFlatDocuments(searchResults, 'search')}
          </section>
        ) : (
          <>
            <Tabs
              activeKey={view}
              onChange={handleViewChange}
              className="dashboard-view-tabs"
              items={[
                { key: 'grouped', label: '分组浏览' },
                { key: 'all', label: '全部推文' },
              ]}
            />
            {view === 'all' ? renderFlatDocuments(allDocuments, 'all') : (
              !groupedWorkspace ? null : groupedWorkspace.groups.total === 0 && groupedWorkspace.ungrouped.total === 0 ? (
                <Empty description="还没有任何推文，点击右上角新建、导入或创建分组" />
              ) : (
                <>
                  {groupedWorkspace.groups.items.map(renderGroup)}
                  {groupedWorkspace.ungrouped.total > 0 && (
                    <section className={`dashboard-group dashboard-ungrouped${collapsedGroups.ungrouped ? ' is-collapsed' : ''}`}>
                      <div
                        className="dashboard-group-heading"
                        role="button"
                        tabIndex={0}
                        aria-label={`${collapsedGroups.ungrouped ? '展开' : '收起'}未分组推文`}
                        aria-expanded={!collapsedGroups.ungrouped}
                        onClick={() => toggleGroup('ungrouped')}
                        onKeyDown={(event) => handleGroupHeadingKeyDown(event, 'ungrouped')}
                      >
                        <div className="dashboard-group-title">
                          <Tooltip title={collapsedGroups.ungrouped ? '展开未分组推文' : '收起未分组推文'}>
                            <Button
                              aria-label={`${collapsedGroups.ungrouped ? '展开' : '收起'}未分组推文`}
                              aria-expanded={!collapsedGroups.ungrouped}
                              className={`dashboard-group-toggle${collapsedGroups.ungrouped ? ' is-collapsed' : ''}`}
                              type="text"
                              icon={<DownOutlined className="dashboard-group-toggle-icon" />}
                              onClick={(event) => {
                                event.stopPropagation()
                                toggleGroup('ungrouped')
                              }}
                              onKeyDown={(event) => event.stopPropagation()}
                            />
                          </Tooltip>
                          <span className="dashboard-group-icon"><FolderOpenOutlined /></span>
                          <div>
                            <div className="dashboard-group-name"><Text strong>未分组</Text><Tag bordered={false} className="dashboard-group-count">{groupedWorkspace.ungrouped.total} 篇</Tag></div>
                            <div className="dashboard-group-meta"><span>尚未归类的推文</span></div>
                          </div>
                        </div>
                        <Space className="dashboard-group-actions" size={2} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                          <Tooltip title="新建未分组推文">
                            <Button aria-label="新建未分组推文" type="text" icon={<FileAddOutlined />} onClick={() => handleCreateBlank()}>
                              <span className="dashboard-group-create-label">新建推文</span>
                            </Button>
                          </Tooltip>
                        </Space>
                      </div>
                      <div className={`dashboard-group-collapse${collapsedGroups.ungrouped ? ' is-collapsed' : ''}`} aria-hidden={Boolean(collapsedGroups.ungrouped)}>
                        <div className="dashboard-group-collapse-inner" inert={Boolean(collapsedGroups.ungrouped)}>
                          <div className="dashboard-group-content">
                            {renderDocuments(groupedWorkspace.ungrouped, (page, pageSize) => {
                              void loadUngroupedDocumentPage(pageSize === groupedWorkspace.ungrouped.page_size ? page : 1, pageSize)
                            }, false, GROUP_DOCUMENT_PAGE_SIZE_OPTIONS)}
                          </div>
                        </div>
                      </div>
                    </section>
                  )}
                  {groupedWorkspace.groups.total > groupedWorkspace.groups.page_size && (
                    <div className="dashboard-workspace-pagination">
                      <Pagination
                        current={groupedWorkspace.groups.page}
                        pageSize={groupedWorkspace.groups.page_size}
                        total={groupedWorkspace.groups.total}
                        showSizeChanger
                        pageSizeOptions={[10, 20, 50]}
                        showTotal={(total) => `共 ${total} 个分组`}
                        onChange={(page, pageSize) => {
                          void loadGroupedWorkspace(pageSize === groupedWorkspace.groups.page_size ? page : 1, pageSize)
                        }}
                      />
                    </div>
                  )}
                </>
              )
            )}
          </>
        )}
      </Card>
      <Modal
        className="create-blank-document-modal"
        title="新建空白推文"
        open={createBlankOpen}
        okText="确定"
        cancelText="取消"
        confirmLoading={creating}
        onCancel={() => {
          if (!creating) setCreateBlankOpen(false)
        }}
        onOk={() => void submitCreateBlank()}
      >
        <div className="create-blank-document-fields">
          <Input
            autoFocus
            value={createBlankTitle}
            placeholder="请输入标题"
            onChange={(event) => setCreateBlankTitle(event.target.value)}
            onPressEnter={() => void submitCreateBlank()}
          />
          <Select
            allowClear
            value={createBlankGroupId ?? undefined}
            placeholder="选择分组（可选）"
            options={groupOptions.map((group) => ({ value: group.id, label: group.name }))}
            onChange={(value) => setCreateBlankGroupId(value ?? null)}
            popupMatchSelectWidth={false}
          />
        </div>
      </Modal>
      <ImportReviewModal
        file={importFile}
        open={importReviewOpen}
        importing={importing}
        progress={importProgress}
        importError={importError}
        onCancel={() => {
          if (importing) {
            importAbortRef.current?.abort()
            setImportReviewOpen(false)
            setImportFile(null)
            setImportProgress(null)
            setImportError('')
            return
          }
          setImportReviewOpen(false)
          setImportFile(null)
          setImportProgress(null)
          setImportError('')
        }}
        onConfirm={handleImportConfirm}
      />
      <LinkImportReviewModal
        open={linkImportOpen}
        loading={linkImportLoading}
        importing={linkImporting}
        preview={linkImportPreview}
        error={linkImportError}
        wechatFallback={linkImportWechatFallback}
        captureState={linkImportCaptureState}
        captureError={linkImportCaptureError}
        onClose={handleLinkImportClose}
        onPreview={(url) => void handleLinkImportPreview(url)}
        onUrlChange={resetLinkImportCapture}
        onDetectExtension={() => { void detectLinkImportExtension() }}
        onStartCapture={() => { void startLinkImportCapture() }}
        onConfirm={() => void handleLinkImportConfirm()}
      />
      {visibilityTarget && (
        <VisibilitySettingsModal
          open={visibilityTarget !== null}
          title={visibilityTarget?.type === 'group' ? '分组可见权限' : '推文可见权限'}
          value={visibilityTarget?.resource ?? null}
          onClose={() => setVisibilityTarget(null)}
          onSave={handleSaveVisibility}
        />
      )}
      {wechatDraftTarget && (
        <WeChatDraftModal
          open={wechatDraftTarget !== null}
          documentId={wechatDraftTarget.document.id}
          disabled={false}
          onClose={() => setWechatDraftTarget(null)}
          onMetadataSaved={handleWeChatMetadataSaved}
          onDocumentRefreshed={(document) => {
            handleWeChatMetadataSaved(document.wechat_metadata, document.title)
          }}
        />
      )}
    </div>
  )
}
