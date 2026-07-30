import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Drawer, Empty, Form, Grid, Input, List, Modal, Popconfirm, Radio, Select, Spin, Tag, Tooltip, Typography, message } from 'antd'
import { ArrowLeftOutlined, CopyOutlined, EyeOutlined, HistoryOutlined, RollbackOutlined, SwapOutlined } from '@ant-design/icons'
import { documentGroupsApi } from '../api/documentGroups'
import { documentsApi } from '../api/documents'
import type { DocumentVersionCopyPayload } from '../api/documents'
import { ApiError } from '../api/client'
import type { DocumentDetail, DocumentGroup, DocumentVersionDetail, DocumentVersionSource, DocumentVersionSummary, VisibilitySettings, VisibilityTargets } from '../types'
import { frameDocumentWithNewWindowLinks, SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

const { Text, Title } = Typography

interface VersionHistoryDrawerProps {
  documentId: number
  open: boolean
  refreshToken: number
  restoreDisabled?: boolean
  copyDisabled?: boolean
  copyDefaults: { group_id: number | null } & VisibilitySettings
  onClose: () => void
  onRestored: (document: DocumentDetail) => void | Promise<void>
  onCopied: (document: DocumentDetail) => void | Promise<void>
}

const sourceLabels: Record<DocumentVersionSource, string> = {
  initial: '初始版本',
  manual: '手动保存',
  ai: 'AI 编辑',
  restore: '恢复版本',
}

const sourceColors: Record<DocumentVersionSource, string> = {
  initial: 'blue',
  manual: 'green',
  ai: 'purple',
  restore: 'orange',
}

function formatTime(value: string) {
  const time = new Date(value)
  return Number.isNaN(time.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(time)
}

function versionPreviewDocument(html: string): string {
  const content = html.trim()
  if (!content) {
    return '<!doctype html><html><body><p style="color:#98a2b3;text-align:center;margin-top:48px;">此版本没有内容</p></body></html>'
  }
  if (/^\s*(?:<!doctype|<html[\s>])/i.test(content)) return frameDocumentWithNewWindowLinks(content)
  return frameDocumentWithNewWindowLinks(`<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:16px 12px 32px;background:#fff;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:2;word-break:break-word}img,table{max-width:100%;height:auto}</style>
</head><body>${content}</body></html>`)
}

function copyTitle(version: DocumentVersionSummary): string {
  const suffix = ` - v${version.version_number} 副本`
  return `${version.title.slice(0, Math.max(0, 256 - suffix.length))}${suffix}`
}

const VersionPreview = memo(function VersionPreview({
  versionId,
  versionNumber,
  html,
}: {
  versionId: number
  versionNumber: number
  html: string
}) {
  const srcDoc = useMemo(() => versionPreviewDocument(html), [html])
  return (
    <iframe
      key={versionId}
      className="version-html-preview-frame"
      title={`版本 v${versionNumber} 排版预览`}
      sandbox={SANDBOX_SAME_ORIGIN_ALLOW_NEW_WINDOW}
      srcDoc={srcDoc}
    />
  )
})

function versionOptionLabel(version: DocumentVersionSummary) {
  return `v${version.version_number} · ${version.title || sourceLabels[version.source]} · ${formatTime(version.created_at)}`
}

function VersionComparisonModal({
  open,
  versions,
  initialLeftId,
  initialRightId,
  onClose,
  loadVersion,
}: {
  open: boolean
  versions: DocumentVersionSummary[]
  initialLeftId: number | null
  initialRightId: number | null
  onClose: () => void
  loadVersion: (versionId: number) => Promise<DocumentVersionDetail>
}) {
  const [leftVersionId, setLeftVersionId] = useState<number | null>(null)
  const [rightVersionId, setRightVersionId] = useState<number | null>(null)
  const [leftVersion, setLeftVersion] = useState<DocumentVersionDetail | null>(null)
  const [rightVersion, setRightVersion] = useState<DocumentVersionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLeftVersionId(initialLeftId)
    setRightVersionId(initialRightId)
  }, [initialLeftId, initialRightId, open])

  useEffect(() => {
    if (!open || leftVersionId === null || rightVersionId === null || leftVersionId === rightVersionId) return
    let active = true
    setLoading(true)
    setError('')
    setLeftVersion(null)
    setRightVersion(null)
    void Promise.all([loadVersion(leftVersionId), loadVersion(rightVersionId)])
      .then(([left, right]) => {
        if (!active) return
        setLeftVersion(left)
        setRightVersion(right)
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? String(err.detail) : '加载比较版本失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [leftVersionId, loadVersion, open, rightVersionId])

  const options = versions.map((version) => ({ value: version.id, label: versionOptionLabel(version) }))
  const chooseLeft = (versionId: number) => {
    setLeftVersionId(versionId)
    if (versionId === rightVersionId) setRightVersionId(versions.find((version) => version.id !== versionId)?.id ?? null)
  }
  const chooseRight = (versionId: number) => {
    setRightVersionId(versionId)
    if (versionId === leftVersionId) setLeftVersionId(versions.find((version) => version.id !== versionId)?.id ?? null)
  }

  return (
    <Modal
      title="比较历史版本"
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(1440px, calc(100vw - 32px))"
      className="version-comparison-modal"
      destroyOnHidden
    >
      <div className="version-comparison-selectors">
        <label>
          <span>左侧版本</span>
          <Select value={leftVersionId ?? undefined} options={options.map((option) => ({ ...option, disabled: option.value === rightVersionId }))} onChange={chooseLeft} />
        </label>
        <label>
          <span>右侧版本</span>
          <Select value={rightVersionId ?? undefined} options={options.map((option) => ({ ...option, disabled: option.value === leftVersionId }))} onChange={chooseRight} />
        </label>
      </div>
      {loading ? (
        <div className="version-history-loading"><Spin description="正在加载比较版本…" /></div>
      ) : error ? (
        <Alert type="error" showIcon message={error} />
      ) : leftVersion && rightVersion ? (
        <div className="version-comparison-layout">
          <section className="version-comparison-pane" aria-label={`版本 v${leftVersion.version_number}`}>
            <div className="version-comparison-heading">
              <strong>v{leftVersion.version_number}</strong>
              <Text type="secondary">{leftVersion.title}</Text>
            </div>
            <div className="version-html-preview">
              <VersionPreview versionId={leftVersion.id} versionNumber={leftVersion.version_number} html={leftVersion.html} />
            </div>
          </section>
          <section className="version-comparison-pane" aria-label={`版本 v${rightVersion.version_number}`}>
            <div className="version-comparison-heading">
              <strong>v{rightVersion.version_number}</strong>
              <Text type="secondary">{rightVersion.title}</Text>
            </div>
            <div className="version-html-preview">
              <VersionPreview versionId={rightVersion.id} versionNumber={rightVersion.version_number} html={rightVersion.html} />
            </div>
          </section>
        </div>
      ) : null}
    </Modal>
  )
}

function VersionCopyModal({
  version,
  defaults,
  copying,
  onCancel,
  onCreate,
}: {
  version: DocumentVersionSummary | null
  defaults: { group_id: number | null } & VisibilitySettings
  copying: boolean
  onCancel: () => void
  onCreate: (payload: DocumentVersionCopyPayload) => Promise<void>
}) {
  const open = version !== null
  const [title, setTitle] = useState('')
  const [groupId, setGroupId] = useState<number | null>(null)
  const [visibilityMode, setVisibilityMode] = useState<VisibilitySettings['visibility_mode']>('all')
  const [allowedUserIds, setAllowedUserIds] = useState<number[]>([])
  const [allowedGroupIds, setAllowedGroupIds] = useState<number[]>([])
  const [groups, setGroups] = useState<DocumentGroup[]>([])
  const [visibilityTargets, setVisibilityTargets] = useState<VisibilityTargets>({ users: [], groups: [] })
  const [optionsLoading, setOptionsLoading] = useState(false)

  useEffect(() => {
    if (!open || !version) return
    setTitle(copyTitle(version))
    setGroupId(defaults.group_id)
    setVisibilityMode(defaults.visibility_mode)
    setAllowedUserIds(defaults.allowed_user_ids)
    setAllowedGroupIds(defaults.allowed_group_ids)
  }, [defaults, open, version])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setOptionsLoading(true)
    void Promise.all([documentGroupsApi.list(), documentsApi.visibilityTargets()])
      .then(([nextGroups, nextTargets]) => {
        if (cancelled) return
        setGroups(nextGroups)
        setVisibilityTargets(nextTargets)
        setGroupId((current) => current !== null && !nextGroups.some((group) => group.id === current) ? null : current)
      })
      .catch((err) => {
        if (!cancelled) message.error(err instanceof ApiError ? String(err.detail) : '加载目标文章设置失败')
      })
      .finally(() => {
        if (!cancelled) setOptionsLoading(false)
      })
    return () => { cancelled = true }
  }, [open])

  const create = async () => {
    const normalizedTitle = title.trim()
    if (!normalizedTitle) {
      message.error('请输入文章标题')
      return
    }
    await onCreate({
      title: normalizedTitle,
      group_id: groupId,
      visibility_mode: visibilityMode,
      allowed_user_ids: visibilityMode === 'restricted' ? allowedUserIds : [],
      allowed_group_ids: visibilityMode === 'restricted' ? allowedGroupIds : [],
    })
  }

  return (
    <Modal
      title={version ? `从 v${version.version_number} 复制新文章` : '复制新文章'}
      open={open}
      okText="创建并打开"
      cancelText="取消"
      confirmLoading={copying}
      okButtonProps={{ disabled: optionsLoading }}
      destroyOnHidden
      onCancel={onCancel}
      onOk={() => void create()}
    >
      <Form layout="vertical">
        <Form.Item label="文章标题" required>
          <Input value={title} maxLength={256} autoFocus onChange={(event) => setTitle(event.target.value)} />
        </Form.Item>
        <Spin spinning={optionsLoading}>
          <Form.Item label="目标分组">
            <Select
              allowClear
              placeholder="不加入分组"
              value={groupId ?? undefined}
              onChange={(value) => setGroupId(value ?? null)}
              options={groups.map((group) => ({ value: group.id, label: group.name }))}
            />
          </Form.Item>
          <Form.Item label="可见范围">
            <Radio.Group
              value={visibilityMode}
              onChange={(event) => setVisibilityMode(event.target.value as VisibilitySettings['visibility_mode'])}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: '全员可见', value: 'all' },
                { label: '指定对象', value: 'restricted' },
              ]}
            />
          </Form.Item>
          {visibilityMode === 'restricted' && (
            <>
              <Form.Item label="授权用户">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择可见用户"
                  value={allowedUserIds}
                  onChange={setAllowedUserIds}
                  options={visibilityTargets.users.map((user) => ({
                    value: user.id,
                    label: `${user.display_name || user.username} (${user.username})`,
                    disabled: !user.is_active,
                  }))}
                />
              </Form.Item>
              <Form.Item label="授权用户组" style={{ marginBottom: 0 }}>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择可见用户组"
                  value={allowedGroupIds}
                  onChange={setAllowedGroupIds}
                  options={visibilityTargets.groups.map((group) => ({ value: group.id, label: group.name }))}
                />
              </Form.Item>
            </>
          )}
        </Spin>
      </Form>
    </Modal>
  )
}

/** 文档快照独立于当前草稿，恢复始终会生成新的不可变版本。 */
export default function VersionHistoryDrawer({
  documentId,
  open,
  refreshToken,
  restoreDisabled = false,
  copyDisabled = false,
  copyDefaults,
  onClose,
  onRestored,
  onCopied,
}: VersionHistoryDrawerProps) {
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const [versions, setVersions] = useState<DocumentVersionSummary[]>([])
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersionDetail | null>(null)
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [restoringId, setRestoringId] = useState<number | null>(null)
  const [copyVersion, setCopyVersion] = useState<DocumentVersionSummary | null>(null)
  const [copyingId, setCopyingId] = useState<number | null>(null)
  const [comparisonOpen, setComparisonOpen] = useState(false)
  const [comparisonInitialIds, setComparisonInitialIds] = useState<{ left: number | null; right: number | null }>({ left: null, right: null })
  const versionCacheRef = useRef(new Map<number, DocumentVersionDetail>())

  const loadVersions = useCallback(async () => {
    if (!documentId) return
    setLoading(true)
    try {
      const result = await documentsApi.listVersions(documentId)
      setVersions(result)
      setSelectedVersion((current) => {
        if (current && result.some((item) => item.id === current.id)) return current
        return null
      })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载版本历史失败')
    } finally {
      setLoading(false)
    }
  }, [documentId])

  const loadVersionDetail = useCallback(async (versionId: number) => {
    if (!documentId) throw new Error('文档不存在')
    const cached = versionCacheRef.current.get(versionId)
    if (cached) return cached
    const detail = await documentsApi.getVersion(documentId, versionId)
    versionCacheRef.current.set(versionId, detail)
    return detail
  }, [documentId])

  const selectVersion = useCallback(async (versionId: number, openCompactDetail = false) => {
    if (selectedVersion?.id === versionId) {
      if (openCompactDetail) setMobileDetailOpen(true)
      return
    }
    setDetailLoading(true)
    try {
      const detail = await loadVersionDetail(versionId)
      if (detail) {
        setSelectedVersion(detail)
        if (openCompactDetail) setMobileDetailOpen(true)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载版本内容失败')
    } finally {
      setDetailLoading(false)
    }
  }, [loadVersionDetail, selectedVersion?.id])

  useEffect(() => {
    versionCacheRef.current.clear()
    setSelectedVersion(null)
    setMobileDetailOpen(false)
  }, [documentId])

  useEffect(() => {
    if (!open || !isCompact) setMobileDetailOpen(false)
  }, [isCompact, open])

  useEffect(() => {
    if (open) void loadVersions()
  }, [loadVersions, open, refreshToken])

  useEffect(() => {
    if (open && versions.length > 0 && !selectedVersion && !detailLoading) {
      void selectVersion(versions[0].id)
    }
  }, [detailLoading, open, selectedVersion, selectVersion, versions])

  const restoreVersion = async (version: DocumentVersionSummary) => {
    setRestoringId(version.id)
    try {
      const restored = await documentsApi.restoreVersion(documentId, version.id)
      await onRestored(restored)
      message.success(`已恢复到 v${version.version_number}，并创建新的恢复版本`)
      setSelectedVersion(null)
      await loadVersions()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '恢复版本失败')
    } finally {
      setRestoringId(null)
    }
  }

  const createCopy = async (payload: DocumentVersionCopyPayload) => {
    if (!copyVersion) return
    setCopyingId(copyVersion.id)
    try {
      const copied = await documentsApi.copyVersion(documentId, copyVersion.id, payload)
      message.success(`已从 v${copyVersion.version_number} 创建新文章`)
      setCopyVersion(null)
      await onCopied(copied)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '创建新文章失败')
    } finally {
      setCopyingId(null)
    }
  }

  const closeDrawer = () => {
    if (copyingId !== null) return
    setCopyVersion(null)
    onClose()
  }

  const openComparison = () => {
    if (versions.length < 2) {
      message.info('至少需要两个版本才能比较')
      return
    }
    const left = selectedVersion?.id ?? versions[0].id
    const right = versions.find((version) => version.id !== left)?.id ?? null
    setComparisonInitialIds({ left, right })
    setComparisonOpen(true)
  }

  return (
    <>
      <Drawer
        title={<span><HistoryOutlined /> 版本历史</span>}
        placement="right"
        size="min(960px, 100vw)"
        open={open}
        onClose={closeDrawer}
        className="version-history-drawer"
      >
        <div className={`version-history-layout${isCompact ? mobileDetailOpen ? ' version-history-layout-mobile-detail' : ' version-history-layout-mobile-list' : ''}`}>
        <section className="version-history-list-panel" aria-label="版本列表">
          <div className="version-history-panel-heading">
            <Text type="secondary">每次保存、AI 编辑和恢复都会保留快照</Text>
            <Tooltip title="并排比较任意两个版本">
              <Button size="small" icon={<SwapOutlined />} disabled={versions.length < 2} onClick={openComparison}>
                比较版本
              </Button>
            </Tooltip>
          </div>
          {loading ? (
            <div className="version-history-loading"><Spin /></div>
          ) : versions.length === 0 ? (
            <Empty description="暂无版本快照" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              className="version-history-list"
              dataSource={versions}
              renderItem={(version) => {
                const isSelected = selectedVersion?.id === version.id
                return (
                  <List.Item className={isSelected ? 'version-history-item version-history-item-selected' : 'version-history-item'}>
                    <button
                      type="button"
                      className="version-history-select"
                      onClick={() => void selectVersion(version.id, isCompact)}
                      aria-pressed={isSelected}
                    >
                      <span className="version-history-number">v{version.version_number}</span>
                      <span className="version-history-meta">
                        <span className="version-history-meta-head">
                          <span className="version-history-label">{version.label || sourceLabels[version.source]}</span>
                          <Tag color={sourceColors[version.source]}>{sourceLabels[version.source]}</Tag>
                        </span>
                        <time
                          className="version-history-time"
                          dateTime={version.created_at}
                          title={`编辑时间：${formatTime(version.created_at)}`}
                        >
                          {formatTime(version.created_at)}
                        </time>
                        <span className="version-history-author">{version.created_by?.display_name || '未知用户'}</span>
                      </span>
                    </button>
                    <span className="version-history-actions">
                      <Tooltip title="查看快照">
                        <Button
                          type={isSelected ? 'primary' : 'text'}
                          size="small"
                          aria-label={`查看版本 v${version.version_number}`}
                          icon={<EyeOutlined />}
                          onClick={() => void selectVersion(version.id, isCompact)}
                        />
                      </Tooltip>
                      <Tooltip title={copyDisabled ? '请先结束当前生成或保存手动草稿' : '复制为新文章'}>
                        <Button
                          size="small"
                          aria-label={`从版本 v${version.version_number} 复制新文章`}
                          icon={<CopyOutlined />}
                          loading={copyingId === version.id}
                          disabled={copyDisabled || restoringId !== null || copyingId !== null}
                          onClick={() => setCopyVersion(version)}
                        />
                      </Tooltip>
                      <Popconfirm
                        title={`恢复到 v${version.version_number}？`}
                        description="当前文档会被替换，系统会额外保存一份恢复后的新版本。"
                        okText="确认恢复"
                        cancelText="取消"
                        onConfirm={() => restoreVersion(version)}
                        disabled={restoreDisabled || restoringId !== null}
                      >
                        <Tooltip title={restoreDisabled ? '请先结束当前生成或保存手动草稿' : '恢复此版本'}>
                          <Button
                            danger
                            size="small"
                            aria-label={`恢复版本 v${version.version_number}`}
                            icon={<RollbackOutlined />}
                            loading={restoringId === version.id}
                            disabled={restoreDisabled || restoringId !== null}
                          />
                        </Tooltip>
                      </Popconfirm>
                    </span>
                  </List.Item>
                )
              }}
            />
          )}
        </section>
        <section className="version-history-detail-panel" aria-label="版本内容">
          {detailLoading ? (
            <div className="version-history-loading"><Spin description="加载版本内容…" /></div>
          ) : selectedVersion ? (
            <>
              <div className="version-history-detail-heading">
                <div className="version-history-detail-title">
                  {isCompact && (
                    <Button
                      type="text"
                      size="small"
                      className="version-history-back-button"
                      icon={<ArrowLeftOutlined />}
                      onClick={() => setMobileDetailOpen(false)}
                    >
                      返回列表
                    </Button>
                  )}
                  <div>
                  <Title level={5}>v{selectedVersion.version_number} 快照</Title>
                  <Text type="secondary">{selectedVersion.title}</Text>
                  </div>
                </div>
                <Tag color={sourceColors[selectedVersion.source]}>{sourceLabels[selectedVersion.source]}</Tag>
              </div>
              <div className="version-html-preview">
                <VersionPreview
                  versionId={selectedVersion.id}
                  versionNumber={selectedVersion.version_number}
                  html={selectedVersion.html}
                />
              </div>
            </>
          ) : (
            <Empty description="选择一个版本以查看 HTML 快照" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
        </div>
      </Drawer>
      <VersionCopyModal
        version={copyVersion}
        defaults={copyDefaults}
        copying={copyingId !== null}
        onCancel={() => !copyingId && setCopyVersion(null)}
        onCreate={createCopy}
      />
      <VersionComparisonModal
        open={comparisonOpen}
        versions={versions}
        initialLeftId={comparisonInitialIds.left}
        initialRightId={comparisonInitialIds.right}
        onClose={() => setComparisonOpen(false)}
        loadVersion={loadVersionDetail}
      />
    </>
  )
}
