import { useEffect, useRef, useState } from 'react'
import { Button, Card, Dropdown, Empty, Grid, Input, List, Modal, Pagination, Select, Space, Tag, Tooltip, Typography, message } from 'antd'
import type { MenuProps } from 'antd'
import {
  DeleteOutlined,
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
import { documentsApi } from '../api/documents'
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

export default function DashboardPage() {
  const navigate = useNavigate()
  const currentUserId = useAuthStore((state) => state.user?.id)
  const isAdmin = useAuthStore((state) => state.user?.role === 'admin')
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [groups, setGroups] = useState<DocumentGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
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
  const [search, setSearch] = useState('')
  const [documentPagination, setDocumentPagination] = useState<Record<string, DocumentPaginationState>>({})
  const [visibilityTarget, setVisibilityTarget] = useState<VisibilityTarget | null>(null)
  const [wechatAccounts, setWechatAccounts] = useState<WeChatAvailableAccount[]>([])
  const [wechatDraftTarget, setWechatDraftTarget] = useState<WeChatDraftTarget | null>(null)
  const [loadingWeChatDocumentId, setLoadingWeChatDocumentId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const importAbortRef = useRef<AbortController | null>(null)
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const hasAiEditingDocument = documents.some((document) => document.is_ai_editing)

  const load = async () => {
    setLoading(true)
    try {
      const [documentList, groupList, availableWeChatAccounts] = await Promise.all([
        documentsApi.list(),
        documentGroupsApi.list(),
        wechatAccountsApi.available().catch(() => []),
      ])
      setDocuments(documentList)
      setGroups(groupList)
      setWechatAccounts(availableWeChatAccounts)
      setDocumentPagination({})
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载推文列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (!hasAiEditingDocument) return
    const refreshAiEditingStatus = async () => {
      try {
        const { active_document_ids: activeDocumentIds } = await documentsApi.aiEditingStatus()
        const activeIds = new Set(activeDocumentIds)
        setDocuments((items) => items.map((item) => {
          const isAiEditing = activeIds.has(item.id)
          return item.is_ai_editing === isAiEditing ? item : { ...item, is_ai_editing: isAiEditing }
        }))
      } catch {
        // The next polling cycle will retry without interrupting the workspace.
      }
    }
    void refreshAiEditingStatus()
    const timer = window.setInterval(() => { void refreshAiEditingStatus() }, 3000)
    return () => window.clearInterval(timer)
  }, [hasAiEditingDocument])

  const handleCreateGroup = () => {
    let name = ''
    Modal.confirm({
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
    Modal.confirm({
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
    Modal.confirm({
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

  const handleCreateBlank = () => {
    let title = '未命名推文'
    let groupId: number | null = null
    Modal.confirm({
      title: '新建空白推文',
      content: (
        <Space direction="vertical" style={{ display: 'flex' }}>
          <Input defaultValue={title} placeholder="请输入标题" onChange={(event) => (title = event.target.value)} />
          <Select
            allowClear
            placeholder="选择分组（可选）"
            options={groups.map((group) => ({ value: group.id, label: group.name }))}
            onChange={(value) => (groupId = value ?? null)}
          />
        </Space>
      ),
      onOk: async () => {
        setCreating(true)
        try {
          const doc = await documentsApi.create(title.trim() || '未命名推文', groupId)
          message.success('已创建')
          navigate(`/editor/${doc.id}`)
        } catch (err) {
          message.error(err instanceof ApiError ? String(err.detail) : '创建失败')
          return Promise.reject(err)
        } finally {
          setCreating(false)
        }
      },
    })
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
    releaseLinkImportPreview()
    setLinkImportPreview(null)
    setLinkImportLoading(true)
    setLinkImportError('')
    try {
      const preview = await documentsApi.previewWebArticleImport(url)
      setLinkImportPreview(preview)
    } catch (err) {
      const detail = err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '文章链接解析失败'
      setLinkImportError(detail)
    } finally {
      setLinkImportLoading(false)
    }
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
    releaseLinkImportPreview()
    setLinkImportOpen(false)
    setLinkImportPreview(null)
    setLinkImportError('')
  }

  const handleDelete = (doc: DocumentSummary) => {
    Modal.confirm({
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
    setDocuments((items) => items.map((item) => (
      item.id === documentId ? { ...item, title, wechat_cover_url: metadata.cover_url } : item
    )))
  }

  const renderDocuments = (items: DocumentSummary[], sectionKey: string) => {
    if (items.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此分组暂无推文" />

    const pagination = documentPagination[sectionKey] ?? { page: 1, pageSize: 20 }
    const pageCount = Math.ceil(items.length / pagination.pageSize)
    const currentPage = Math.min(pagination.page, pageCount)
    const pagedItems = items.slice((currentPage - 1) * pagination.pageSize, currentPage * pagination.pageSize)
    const changePage = (nextPage: number, nextPageSize: number) => {
      setDocumentPagination((states) => ({
        ...states,
        [sectionKey]: {
          page: nextPageSize === pagination.pageSize ? nextPage : 1,
          pageSize: nextPageSize,
        },
      }))
    }

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
            ...groups.map((group) => ({ key: String(group.id), label: group.name, disabled: doc.group_id === group.id })),
          ]
          const compactMoveMenu: MenuProps['items'] = [
            { key: 'move-ungrouped', label: '移至未分组', disabled: doc.group_id === null },
            ...groups.map((group) => ({ key: `move-${group.id}`, label: group.name, disabled: doc.group_id === group.id })),
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
          const actions = [
            <Tooltip key="open" title="打开推文">
              <Button
                aria-label={`打开推文 ${doc.title}`}
                className="dashboard-document-action"
                type="text"
                icon={<EditOutlined />}
                onClick={() => navigate(`/editor/${doc.id}`)}
              />
            </Tooltip>,
            ...(canOpenWeChatDraft ? [wechatAction] : []),
            <Dropdown
              key="group"
              menu={{
                items: groupMenu,
                onClick: ({ key }) => handleMoveToGroup(doc, key === 'ungrouped' ? null : Number(key)),
              }}
            >
              <Tooltip title="移动到分组">
                <Button aria-label={`移动推文 ${doc.title} 到分组`} className="dashboard-document-action" type="text" icon={<FolderOpenOutlined />} />
              </Tooltip>
            </Dropdown>,
            <Tooltip key="delete" title="删除推文">
              <Button aria-label={`删除推文 ${doc.title}`} className="dashboard-document-action" type="text" danger icon={<DeleteOutlined />} onClick={() => handleDelete(doc)} />
            </Tooltip>,
            ...(canConfigureDocumentVisibility ? [
              <Tooltip key="visibility" title="可见权限">
                <Button
                  aria-label={`设置推文 ${doc.title} 的可见权限`}
                  className="dashboard-document-action"
                  type="text"
                  icon={<SafetyCertificateOutlined />}
                  onClick={() => setVisibilityTarget({ type: 'document', resource: doc })}
                />
              </Tooltip>,
            ] : []),
          ]
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
            <List.Item
              className="dashboard-document-item"
              actions={actions}
            >
              <List.Item.Meta
                avatar={documentAvatar}
                title={
                  <Space>
                    <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/editor/${doc.id}`)}>
                      {doc.title}
                    </Button>
                    <Tag color={tag.color}>{tag.label}</Tag>
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
            </List.Item>
          )
    }

    if (isCompact) {
      return (
        <>
          <div className="dashboard-document-card-list">{pagedItems.map(renderDocument)}</div>
          {items.length > 20 && (
            <div className="dashboard-group-pagination">
              <Pagination
                size="small"
                current={currentPage}
                pageSize={pagination.pageSize}
                total={items.length}
                showSizeChanger
                pageSizeOptions={[20, 50, 100]}
                showTotal={(total) => `共 ${total} 篇`}
                onChange={changePage}
              />
            </div>
          )}
        </>
      )
    }

    return (
      <>
        <List itemLayout="horizontal" dataSource={pagedItems} renderItem={renderDocument} />
        {items.length > 20 && (
          <div className="dashboard-group-pagination">
            <Pagination
              current={currentPage}
              pageSize={pagination.pageSize}
              total={items.length}
              showSizeChanger
              pageSizeOptions={[20, 50, 100]}
              showTotal={(total) => `共 ${total} 篇`}
              onChange={changePage}
            />
          </div>
        )}
      </>
    )
  }

  const renderGroup = (group: DocumentGroup, groupItems: DocumentSummary[], isFirst: boolean) => {
    const canConfigureGroupVisibility = isAdmin || group.created_by?.id === currentUserId
    const groupMenu: MenuProps['items'] = [
      { key: 'rename', label: '修改名称', icon: <EditOutlined /> },
      { key: 'delete', label: '删除分组', icon: <DeleteOutlined />, danger: true },
    ]
    if (canConfigureGroupVisibility) groupMenu.unshift({ key: 'visibility', label: '可见权限', icon: <SafetyCertificateOutlined /> })

    return (
      <section className="dashboard-group" key={group.id} style={{ paddingTop: isFirst ? 0 : 20, marginTop: isFirst ? 0 : 20, borderTop: isFirst ? undefined : '1px solid var(--app-border)' }}>
        <div className="dashboard-group-heading">
          <Space size={10} wrap>
            <FolderOpenOutlined style={{ color: '#1677ff' }} />
            <Text strong>{group.name}</Text>
            {group.visibility_mode === 'restricted' && (
              <Tooltip title="仅指定用户或用户组可见">
                <Tag color="gold" icon={<LockOutlined />}>受限可见</Tag>
              </Tooltip>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              最后修改：{formatUser(group.last_modified_by)} · {formatDate(group.updated_at)}
            </Text>
          </Space>
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
        </div>
        {renderDocuments(groupItems, `group:${group.id}`)}
      </section>
    )
  }

  const normalizedSearch = search.trim().toLocaleLowerCase()
  const matchesDocument = (doc: DocumentSummary) =>
    !normalizedSearch || doc.title.toLocaleLowerCase().includes(normalizedSearch)
  const filteredGroups = groups
    .map((group) => {
      const groupDocuments = documents.filter((doc) => doc.group_id === group.id)
      const groupMatches = group.name.toLocaleLowerCase().includes(normalizedSearch)
      return {
        group,
        documents: groupMatches ? groupDocuments : groupDocuments.filter(matchesDocument),
        visible: groupMatches || groupDocuments.some(matchesDocument),
      }
    })
    .filter(({ visible }) => visible)
  const ungroupedDocuments = documents.filter((doc) => doc.group_id === null && matchesDocument(doc))
  const hasContent = groups.length > 0 || documents.length > 0
  const hasSearchResults = filteredGroups.length > 0 || ungroupedDocuments.length > 0

  return (
    <div className="dashboard-page">
      <div className="dashboard-page-header">
        <Title level={4} style={{ margin: 0 }}>
          推文工作台
        </Title>
        <Input.Search
          allowClear
          aria-label="搜索推文或分组"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setDocumentPagination({})
          }}
          placeholder="搜索推文标题或分组名称"
          className="dashboard-search"
        />
        <Space className="dashboard-actions" wrap>
          <Button icon={<FolderAddOutlined />} onClick={handleCreateGroup}>
            新建分组
          </Button>
          <Button icon={<FileAddOutlined />} loading={creating} onClick={handleCreateBlank}>
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

      <Card loading={loading}>
        {!hasContent ? (
          <Empty description="还没有任何推文，点击右上角新建、导入或创建分组" />
        ) : !hasSearchResults ? (
          <Empty description="没有找到匹配的推文或分组" />
        ) : (
          <>
            {filteredGroups.map(({ group, documents: groupDocuments }, index) =>
              renderGroup(group, groupDocuments, index === 0),
            )}
            {ungroupedDocuments.length > 0 && (
              <section
                className="dashboard-group dashboard-ungrouped"
                style={{
                  paddingTop: filteredGroups.length > 0 ? 20 : 0,
                  marginTop: filteredGroups.length > 0 ? 20 : 0,
                  borderTop: filteredGroups.length > 0 ? '1px solid var(--app-border)' : undefined,
                }}
              >
                <Text strong>未分组</Text>
                {renderDocuments(ungroupedDocuments, 'ungrouped')}
              </section>
            )}
          </>
        )}
      </Card>
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
        onClose={handleLinkImportClose}
        onPreview={(url) => void handleLinkImportPreview(url)}
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
          documentTitle={wechatDraftTarget.document.title}
          metadata={wechatDraftTarget.document.wechat_metadata}
          accounts={wechatDraftTarget.accounts}
          disabled={false}
          onClose={() => setWechatDraftTarget(null)}
          onMetadataSaved={handleWeChatMetadataSaved}
        />
      )}
    </div>
  )
}
