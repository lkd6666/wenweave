import { useEffect, useState } from 'react'
import { Alert, Form, Modal, Radio, Select, Spin, message } from 'antd'
import { documentsApi } from '../api/documents'
import { ApiError } from '../api/client'
import type { VisibilityMode, VisibilitySettings, VisibilityTargets } from '../types'

interface VisibilitySettingsModalProps {
  open: boolean
  title: string
  value: VisibilitySettings | null
  onClose: () => void
  onSave: (settings: VisibilitySettings) => Promise<void>
}

export default function VisibilitySettingsModal({
  open,
  title,
  value,
  onClose,
  onSave,
}: VisibilitySettingsModalProps) {
  const [visibilityMode, setVisibilityMode] = useState<VisibilityMode>('all')
  const [userIds, setUserIds] = useState<number[]>([])
  const [groupIds, setGroupIds] = useState<number[]>([])
  const [targets, setTargets] = useState<VisibilityTargets>({ users: [], groups: [] })
  const [loadingOptions, setLoadingOptions] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !value) return
    setVisibilityMode(value.visibility_mode)
    setUserIds(value.allowed_user_ids)
    setGroupIds(value.allowed_group_ids)
  }, [open, value])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadingOptions(true)
    void documentsApi.visibilityTargets()
      .then((nextTargets) => {
        if (cancelled) return
        setTargets(nextTargets)
      })
      .catch((err) => {
        if (!cancelled) message.error(err instanceof ApiError ? String(err.detail) : '加载授权对象失败')
      })
      .finally(() => {
        if (!cancelled) setLoadingOptions(false)
      })
    return () => { cancelled = true }
  }, [open])

  const save = async () => {
    setSaving(true)
    try {
      await onSave({
        visibility_mode: visibilityMode,
        allowed_user_ids: visibilityMode === 'restricted' ? userIds : [],
        allowed_group_ids: visibilityMode === 'restricted' ? groupIds : [],
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={title}
      open={open}
      okText="保存权限"
      cancelText="取消"
      confirmLoading={saving}
      destroyOnHidden
      onCancel={onClose}
      onOk={() => void save()}
    >
      <Form layout="vertical">
        <Form.Item label="可见范围">
          <Radio.Group
            value={visibilityMode}
            onChange={(event) => setVisibilityMode(event.target.value as VisibilityMode)}
            optionType="button"
            buttonStyle="solid"
            options={[
              { label: '全员可见', value: 'all' },
              { label: '指定对象', value: 'restricted' },
            ]}
          />
        </Form.Item>
        {visibilityMode === 'restricted' && (
          <Spin spinning={loadingOptions}>
            <Alert
              type="info"
              showIcon
              message="仅被授权的用户或用户组成员可见；未选择对象时仅管理员可见。"
              style={{ marginBottom: 16 }}
            />
            <Form.Item label="授权用户">
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择可见用户"
                value={userIds}
                onChange={setUserIds}
                options={targets.users.map((user) => ({
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
                value={groupIds}
                onChange={setGroupIds}
                options={targets.groups.map((group) => ({ value: group.id, label: group.name }))}
              />
            </Form.Item>
          </Spin>
        )}
      </Form>
    </Modal>
  )
}
