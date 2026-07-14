import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { ApiError } from '../../api/client'
import { userGroupsApi } from '../../api/userGroups'
import { usersApi } from '../../api/users'
import type { User, UserGroup } from '../../types'

const { Title, Text } = Typography

export default function AdminUserGroupsPage() {
  const [groups, setGroups] = useState<UserGroup[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)
  const [editingGroup, setEditingGroup] = useState<UserGroup | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const loadData = async () => {
    setLoading(true)
    try {
      const [groupData, userData] = await Promise.all([userGroupsApi.list(), usersApi.list()])
      setGroups(groupData)
      setUsers(userData)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载用户组失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const openCreate = () => {
    setEditingGroup(null)
    form.resetFields()
    form.setFieldsValue({ user_ids: [] })
    setModalOpen(true)
  }

  const openEdit = (group: UserGroup) => {
    setEditingGroup(group)
    form.setFieldsValue({ name: group.name, user_ids: group.members.map((member) => member.id) })
    setModalOpen(true)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingGroup) {
        await userGroupsApi.update(editingGroup.id, values)
        message.success('用户组已更新')
      } else {
        await userGroupsApi.create(values)
        message.success('用户组已创建')
      }
      setModalOpen(false)
      void loadData()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (group: UserGroup) => {
    try {
      await userGroupsApi.remove(group.id)
      message.success('用户组已删除')
      void loadData()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除用户组失败')
    }
  }

  const columns: ColumnsType<UserGroup> = [
    { title: '用户组', dataIndex: 'name', key: 'name', width: 240 },
    {
      title: '成员',
      dataIndex: 'members',
      key: 'members',
      render: (members: UserGroup['members']) => (
        <Space size={[4, 4]} wrap>
          {members.slice(0, 6).map((member) => (
            <Tag key={member.id} color={member.is_active ? 'blue' : 'default'}>
              {member.display_name || member.username}
            </Tag>
          ))}
          {members.length > 6 && <Tag>+{members.length - 6}</Tag>}
          {members.length === 0 && <Text type="secondary">暂无成员</Text>}
        </Space>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 190,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, group) => (
        <Space>
          <Button size="small" onClick={() => openEdit(group)}>编辑</Button>
          <Popconfirm title={`删除用户组“${group.name}”？`} onConfirm={() => void handleDelete(group)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>用户组</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户组</Button>
      </div>
      <Card>
        <Table rowKey="id" columns={columns} dataSource={groups} loading={loading} pagination={false} />
      </Card>

      <Modal
        title={editingGroup ? `编辑用户组：${editingGroup.name}` : '新建用户组'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="用户组名称" rules={[{ required: true, whitespace: true, message: '请输入用户组名称' }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="user_ids" label="成员">
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择用户"
              options={users.map((user) => ({
                value: user.id,
                label: `${user.display_name || user.username}（${user.username}）${user.is_active ? '' : ' - 已禁用'}`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
