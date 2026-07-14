import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Drawer, Empty, List, Popconfirm, Spin, Tag, Tooltip, Typography, message } from 'antd'
import { EyeOutlined, HistoryOutlined, RollbackOutlined } from '@ant-design/icons'
import { documentsApi } from '../api/documents'
import { ApiError } from '../api/client'
import type { DocumentDetail, DocumentVersionDetail, DocumentVersionSource, DocumentVersionSummary } from '../types'

const { Text, Title } = Typography

interface VersionHistoryDrawerProps {
  documentId: number
  open: boolean
  refreshToken: number
  restoreDisabled?: boolean
  onClose: () => void
  onRestored: (document: DocumentDetail) => void | Promise<void>
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
  if (/^\s*(?:<!doctype|<html[\s>])/i.test(content)) return content
  return `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:16px 12px 32px;background:#fff;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:2;word-break:break-word}img,table{max-width:100%;height:auto}</style>
</head><body>${content}</body></html>`
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
      sandbox="allow-same-origin"
      srcDoc={srcDoc}
    />
  )
})

/** 文档快照独立于当前草稿，恢复始终会生成新的不可变版本。 */
export default function VersionHistoryDrawer({
  documentId,
  open,
  refreshToken,
  restoreDisabled = false,
  onClose,
  onRestored,
}: VersionHistoryDrawerProps) {
  const [versions, setVersions] = useState<DocumentVersionSummary[]>([])
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [restoringId, setRestoringId] = useState<number | null>(null)
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

  const selectVersion = useCallback(async (versionId: number) => {
    if (!documentId) return
    if (selectedVersion?.id === versionId) return
    const cached = versionCacheRef.current.get(versionId)
    if (cached) {
      setSelectedVersion(cached)
      return
    }
    setDetailLoading(true)
    try {
      const detail = await documentsApi.getVersion(documentId, versionId)
      versionCacheRef.current.set(versionId, detail)
      setSelectedVersion(detail)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载版本内容失败')
    } finally {
      setDetailLoading(false)
    }
  }, [documentId, selectedVersion?.id])

  useEffect(() => {
    versionCacheRef.current.clear()
    setSelectedVersion(null)
  }, [documentId])

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

  return (
    <Drawer
      title={<span><HistoryOutlined /> 版本历史</span>}
      placement="right"
      width={620}
      open={open}
      onClose={onClose}
      className="version-history-drawer"
    >
      <div className="version-history-layout">
        <section className="version-history-list-panel" aria-label="版本列表">
          <div className="version-history-panel-heading">
            <Text type="secondary">每次保存、AI 编辑和恢复都会保留快照</Text>
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
                      onClick={() => void selectVersion(version.id)}
                      aria-pressed={isSelected}
                    >
                      <span className="version-history-number">v{version.version_number}</span>
                      <span className="version-history-meta">
                        <span className="version-history-label">{version.label || sourceLabels[version.source]}</span>
                        <span className="version-history-subtitle">
                          {version.created_by?.display_name || '未知用户'} · {formatTime(version.created_at)}
                        </span>
                      </span>
                    </button>
                    <span className="version-history-actions">
                      <Tag color={sourceColors[version.source]}>{sourceLabels[version.source]}</Tag>
                      <Tooltip title="查看快照">
                        <Button
                          type={isSelected ? 'primary' : 'text'}
                          size="small"
                          aria-label={`查看版本 v${version.version_number}`}
                          icon={<EyeOutlined />}
                          onClick={() => void selectVersion(version.id)}
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
                <div>
                  <Title level={5}>v{selectedVersion.version_number} 快照</Title>
                  <Text type="secondary">{selectedVersion.title}</Text>
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
  )
}
