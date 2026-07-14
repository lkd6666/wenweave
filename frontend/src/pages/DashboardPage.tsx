import { useEffect, useRef, useState } from 'react'
import { Button, Card, Dropdown, Empty, Input, List, Modal, Select, Space, Tag, Tooltip, Typography, message } from 'antd'
import type { MenuProps } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  LockOutlined,
  MoreOutlined,
  SafetyCertificateOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { documentGroupsApi } from '../api/documentGroups'
import { documentsApi } from '../api/documents'
import { ApiError } from '../api/client'
import ImportReviewModal from '../components/ImportReviewModal'
import VisibilitySettingsModal from '../components/VisibilitySettingsModal'
import { importDocumentDirectly } from '../imports/directImportUpload'
import type { DirectImportProgress } from '../imports/directImportUpload'
import { useAuthStore } from '../store/authStore'
import type { DocumentGroup, DocumentSourceType, DocumentSummary, UserReference, VisibilitySettings } from '../types'

const { Title, Text } = Typography

const SOURCE_TAG: Record<DocumentSourceType, { color: string; label: string }> = {
  blank: { color: 'default', label: '空白创建' },
  pdf: { color: 'red', label: 'PDF 导入' },
  word: { color: 'blue', label: 'Word 导入' },
}

const formatUser = (user: UserReference | null) => user?.display_name || user?.username || '未知用户'

const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

type VisibilityTarget =
  | { type: 'document'; resource: DocumentSummary }
  | { type: 'group'; resource: DocumentGroup }

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
  const [search, setSearch] = useState('')
  const [visibilityTarget, setVisibilityTarget] = useState<VisibilityTarget | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const importAbortRef = useRef<AbortController | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [documentList, groupList] = await Promise.all([documentsApi.list(), documentGroupsApi.list()])
      setDocuments(documentList)
      setGroups(groupList)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载推文列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

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
    if (ext !== 'pdf' && ext !== 'docx') {
      message.error('仅支持上传 PDF 或 Word(.docx) 文件')
      return
    }

    setImportFile(file)
    setImportProgress(null)
    setImportError('')
    setImportReviewOpen(true)
  }

  const handleImportConfirm = async () => {
    if (!importFile) return
    setImporting(true)
    const controller = new AbortController()
    importAbortRef.current = controller
    setImportError('')
    setImportProgress({ phase: 'parsing', percent: 0, detail: '正在准备前端直传…' })
    try {
      const doc = await importDocumentDirectly(importFile, setImportProgress, controller.signal)
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

  const renderDocuments = (items: DocumentSummary[]) => {
    if (items.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此分组暂无推文" />

    return (
      <List
        itemLayout="horizontal"
        dataSource={items}
        renderItem={(doc) => {
          const tag = SOURCE_TAG[doc.source_type]
          const icon =
            doc.source_type === 'pdf' ? (
              <FilePdfOutlined style={{ fontSize: 20, color: '#cf1322' }} />
            ) : doc.source_type === 'word' ? (
              <FileWordOutlined style={{ fontSize: 20, color: '#1d39c4' }} />
            ) : (
              <FileAddOutlined style={{ fontSize: 20 }} />
            )
          const groupMenu: MenuProps['items'] = [
            { key: 'ungrouped', label: '移至未分组', disabled: doc.group_id === null },
            ...groups.map((group) => ({ key: String(group.id), label: group.name, disabled: doc.group_id === group.id })),
          ]
          const canManageDocument = isAdmin || doc.created_by?.id === currentUserId
          const actions = [
            <Button key="open" type="link" onClick={() => navigate(`/editor/${doc.id}`)}>
              打开
            </Button>,
            ...(canManageDocument ? [
              <Dropdown
                key="group"
                menu={{
                  items: groupMenu,
                  onClick: ({ key }) => handleMoveToGroup(doc, key === 'ungrouped' ? null : Number(key)),
                }}
              >
                <Button type="link" icon={<FolderOpenOutlined />}>
                  移动
                </Button>
              </Dropdown>,
              <Button key="delete" type="link" danger onClick={() => handleDelete(doc)}>
                删除
              </Button>,
            ] : []),
            ...(canManageDocument ? [
              <Tooltip key="visibility" title="可见权限">
                <Button
                  aria-label={`设置推文 ${doc.title} 的可见权限`}
                  type="link"
                  icon={<SafetyCertificateOutlined />}
                  onClick={() => setVisibilityTarget({ type: 'document', resource: doc })}
                />
              </Tooltip>,
            ] : []),
          ]

          return (
            <List.Item
              actions={actions}
            >
              <List.Item.Meta
                avatar={icon}
                title={
                  <Space>
                    <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/editor/${doc.id}`)}>
                      {doc.title}
                    </Button>
                    <Tag color={tag.color}>{tag.label}</Tag>
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
        }}
      />
    )
  }

  const renderGroup = (group: DocumentGroup, groupItems: DocumentSummary[], isFirst: boolean) => {
    const canManageGroup = isAdmin || group.created_by?.id === currentUserId
    const groupMenu: MenuProps['items'] = canManageGroup
      ? [
          { key: 'rename', label: '修改名称', icon: <EditOutlined /> },
          { key: 'delete', label: '删除分组', icon: <DeleteOutlined />, danger: true },
        ]
      : []
    if (canManageGroup) groupMenu.unshift({ key: 'visibility', label: '可见权限', icon: <SafetyCertificateOutlined /> })

    return (
      <section key={group.id} style={{ paddingTop: isFirst ? 0 : 20, marginTop: isFirst ? 0 : 20, borderTop: isFirst ? undefined : '1px solid var(--app-border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
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
        {renderDocuments(groupItems)}
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
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          推文工作台
        </Title>
        <Input.Search
          allowClear
          aria-label="搜索推文或分组"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="搜索推文标题或分组名称"
          style={{ width: 280, maxWidth: '100%' }}
        />
        <Space wrap>
          <Button icon={<FolderAddOutlined />} onClick={handleCreateGroup}>
            新建分组
          </Button>
          <Button icon={<FileAddOutlined />} loading={creating} onClick={handleCreateBlank}>
            新建空白推文
          </Button>
          <Button type="primary" icon={<UploadOutlined />} loading={importing} onClick={handleImportClick}>
            导入 PDF / Word
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
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
                style={{
                  paddingTop: filteredGroups.length > 0 ? 20 : 0,
                  marginTop: filteredGroups.length > 0 ? 20 : 0,
                  borderTop: filteredGroups.length > 0 ? '1px solid var(--app-border)' : undefined,
                }}
              >
                <Text strong>未分组</Text>
                {renderDocuments(ungroupedDocuments)}
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
      {visibilityTarget && (
        <VisibilitySettingsModal
          open={visibilityTarget !== null}
          title={visibilityTarget?.type === 'group' ? '分组可见权限' : '推文可见权限'}
          value={visibilityTarget?.resource ?? null}
          onClose={() => setVisibilityTarget(null)}
          onSave={handleSaveVisibility}
        />
      )}
    </div>
  )
}
