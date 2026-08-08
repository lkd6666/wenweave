import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs, { type Dayjs } from 'dayjs'
import { Button, DatePicker, Empty, List, Modal, Popconfirm, Space, Spin, Table, Tag, Typography, message } from 'antd'
import { CopyOutlined, EyeOutlined, LinkOutlined, StopOutlined } from '@ant-design/icons'
import { documentsApi } from '../api/documents'
import { ApiError } from '../api/client'
import type { DocumentShareRecord, DocumentShareVisit } from '../types'

type ExpiryPreset = '1d' | '7d' | '30d' | 'custom'

interface DocumentShareModalProps {
  open: boolean
  documentId: number
  documentTitle: string
  onClose: () => void
}

function expiryForPreset(preset: ExpiryPreset, customValue: Dayjs | null): string | null {
  if (preset === 'custom') {
    return customValue?.isValid() ? customValue.toISOString() : null
  }
  const days = preset === '1d' ? 1 : preset === '30d' ? 30 : 7
  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString()
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '无'
}

function formatReferer(value: string): string {
  return value.trim() || '直接访问或浏览器未提供来源'
}

async function copyShareUrl(token: string) {
  const url = `${window.location.origin}/share/${token}`
  try {
    await navigator.clipboard.writeText(url)
    message.success('分享链接已复制')
  } catch {
    window.prompt('复制分享链接', url)
  }
}

export default function DocumentShareModal({ open, documentId, documentTitle, onClose }: DocumentShareModalProps) {
  const [shares, setShares] = useState<DocumentShareRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [preset, setPreset] = useState<ExpiryPreset>('7d')
  const [customExpiry, setCustomExpiry] = useState<Dayjs | null>(() => dayjs().add(7, 'day'))
  const [editingShareId, setEditingShareId] = useState<number | null>(null)
  const [editingExpiry, setEditingExpiry] = useState<Dayjs | null>(null)
  const [savingExpiry, setSavingExpiry] = useState(false)
  const [visitShare, setVisitShare] = useState<DocumentShareRecord | null>(null)
  const [visits, setVisits] = useState<DocumentShareVisit[]>([])
  const [visitsTotal, setVisitsTotal] = useState(0)
  const [visitsLoading, setVisitsLoading] = useState(false)

  const loadShares = useCallback(async () => {
    setLoading(true)
    try {
      setShares(await documentsApi.listShares(documentId))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载分享链接失败')
    } finally {
      setLoading(false)
    }
  }, [documentId])

  useEffect(() => {
    if (!open) return
    void loadShares()
  }, [loadShares, open])

  const create = async () => {
    const expiresAt = expiryForPreset(preset, customExpiry)
    if (!expiresAt || Number.isNaN(new Date(expiresAt).getTime()) || new Date(expiresAt) <= new Date()) {
      message.error('请选择未来的有效期')
      return
    }
    setCreating(true)
    try {
      const share = await documentsApi.createShare(documentId, expiresAt)
      setShares((items) => [share, ...items])
      await copyShareUrl(share.token)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '创建分享链接失败')
    } finally {
      setCreating(false)
    }
  }

  const saveExpiry = async (share: DocumentShareRecord) => {
    const expiresAt = editingExpiry?.isValid() ? editingExpiry.toISOString() : ''
    if (!expiresAt || Number.isNaN(new Date(expiresAt).getTime()) || new Date(expiresAt) <= new Date()) {
      message.error('请选择未来的有效期')
      return
    }
    setSavingExpiry(true)
    try {
      const updated = await documentsApi.updateShare(documentId, share.id, expiresAt)
      setShares((items) => items.map((item) => item.id === updated.id ? updated : item))
      setEditingShareId(null)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '更新有效期失败')
    } finally {
      setSavingExpiry(false)
    }
  }

  const revoke = async (share: DocumentShareRecord) => {
    try {
      const updated = await documentsApi.revokeShare(documentId, share.id)
      setShares((items) => items.map((item) => item.id === updated.id ? updated : item))
      message.success('分享链接已停用')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '停用分享链接失败')
    }
  }

  const loadVisits = useCallback(async (share: DocumentShareRecord, page = 1) => {
    setVisitsLoading(true)
    try {
      const result = await documentsApi.listShareVisits(documentId, share.id, page)
      setVisits(result.items)
      setVisitsTotal(result.total)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载访客记录失败')
    } finally {
      setVisitsLoading(false)
    }
  }, [documentId])

  useEffect(() => {
    if (visitShare) void loadVisits(visitShare)
  }, [loadVisits, visitShare])

  const expiryOptions = useMemo(() => [
    ['1d', '1 天'],
    ['7d', '7 天'],
    ['30d', '30 天'],
    ['custom', '指定时间'],
  ] as const, [])

  return (
    <>
      <Modal
        title={`分享只读预览 - ${documentTitle}`}
        open={open}
        footer={null}
        width={760}
        className="document-share-modal"
        destroyOnHidden
        onCancel={onClose}
      >
        <div className="document-share-create-row">
          <Space wrap>
            {expiryOptions.map(([value, label]) => (
              <Button key={value} type={preset === value ? 'primary' : 'default'} onClick={() => setPreset(value)}>
                {label}
              </Button>
            ))}
            {preset === 'custom' && (
              <DatePicker
                aria-label="指定分享截止时间"
                showTime
                format="YYYY-MM-DD HH:mm"
                value={customExpiry}
                onChange={setCustomExpiry}
              />
            )}
            <Button type="primary" icon={<LinkOutlined />} loading={creating} onClick={() => void create()}>
              创建并复制链接
            </Button>
          </Space>
        </div>
        <Spin spinning={loading}>
          {shares.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无分享链接" />
          ) : (
            <List
              className="document-share-list"
              dataSource={shares}
              renderItem={(share) => (
                <List.Item
                  actions={[
                    <Button key="copy" type="text" icon={<CopyOutlined />} disabled={!share.token} onClick={() => void copyShareUrl(share.token)}>复制</Button>,
                    <Button key="visits" type="text" icon={<EyeOutlined />} onClick={() => setVisitShare(share)}>访客 {share.visit_count}</Button>,
                    ...(share.is_active ? [
                      <Button key="expiry" type="text" onClick={() => {
                        setEditingShareId(share.id)
                        setEditingExpiry(dayjs(share.expires_at))
                      }}>改有效期</Button>,
                      <Popconfirm key="revoke" title="停用后该链接将立即失效，且不能恢复。" okText="停用" cancelText="取消" onConfirm={() => void revoke(share)}>
                        <Button type="text" danger icon={<StopOutlined />}>停用</Button>
                      </Popconfirm>,
                    ] : []),
                  ]}
                >
                  <List.Item.Meta
                    title={(
                      <Space wrap>
                        <Typography.Text>{share.is_active ? '分享中' : share.revoked_at ? '已停用' : '已过期'}</Typography.Text>
                        <Tag color={share.is_active ? 'green' : 'default'}>{share.is_active ? '有效' : '失效'}</Tag>
                      </Space>
                    )}
                    description={(
                      <div className="document-share-meta">
                        <span>创建人：{share.created_by_display_name || share.created_by_username || '已删除用户'}</span>
                        <span>创建于：{formatDate(share.created_at)}</span>
                        {editingShareId === share.id ? (
                          <Space wrap>
                            <DatePicker
                              aria-label="新的分享截止时间"
                              showTime
                              format="YYYY-MM-DD HH:mm"
                              value={editingExpiry}
                              onChange={setEditingExpiry}
                            />
                            <Button size="small" type="primary" loading={savingExpiry} onClick={() => void saveExpiry(share)}>保存</Button>
                            <Button size="small" onClick={() => setEditingShareId(null)}>取消</Button>
                          </Space>
                        ) : (
                          <span>截止：{formatDate(share.expires_at)}</span>
                        )}
                      </div>
                    )}
                  />
                </List.Item>
              )}
            />
          )}
        </Spin>
      </Modal>
      <Modal
        title={`访客记录${visitShare ? ` - ${documentTitle}` : ''}`}
        open={Boolean(visitShare)}
        width={960}
        footer={null}
        onCancel={() => setVisitShare(null)}
      >
        <Table<DocumentShareVisit>
          rowKey="id"
          size="small"
          loading={visitsLoading}
          dataSource={visits}
          scroll={{ x: 860 }}
          pagination={{
            total: visitsTotal,
            pageSize: 30,
            onChange: (page) => visitShare && void loadVisits(visitShare, page),
          }}
          columns={[
            { title: '首次访问', dataIndex: 'first_seen_at', width: 175, render: formatDate },
            { title: '最近访问', dataIndex: 'last_seen_at', width: 175, render: formatDate },
            { title: 'IP', dataIndex: 'ip_address', width: 145 },
            { title: 'UA', dataIndex: 'user_agent', ellipsis: true },
            { title: '来源', dataIndex: 'referer', ellipsis: true, render: formatReferer },
          ]}
        />
      </Modal>
    </>
  )
}
