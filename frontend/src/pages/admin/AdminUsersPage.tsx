import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { usersApi } from '../../api/users'
import { ApiError } from '../../api/client'
import { useAuthStore } from '../../store/authStore'
import type { User } from '../../types'

const { Title } = Typography

export default function AdminUsersPage() {
  const currentUser = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [creating, setCreating] = useState(false)

  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const loadUsers = async () => {
    setLoading(true)
    try {
      const data = await usersApi.list()
      setUsers(data)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载用户列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields()
      setCreating(true)
      await usersApi.create(values)
      message.success('用户创建成功')
      setCreateOpen(false)
      createForm.resetFields()
      loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        message.error(String(err.detail))
      }
    } finally {
      setCreating(false)
    }
  }

  const openEdit = (user: User) => {
    setEditingUser(user)
    editForm.setFieldsValue({ display_name: user.display_name, role: user.role, is_active: user.is_active, password: '' })
  }

  const handleSaveEdit = async () => {
    if (!editingUser) return
    try {
      const values = await editForm.validateFields()
      setSaving(true)
      const payload: Record<string, unknown> = {
        display_name: values.display_name,
        role: values.role,
        is_active: values.is_active,
      }
      if (values.password) {
        payload.password = values.password
      }
      await usersApi.update(editingUser.id, payload)
      message.success('用户信息已更新')
      setEditingUser(null)
      loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        message.error(String(err.detail))
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (user: User) => {
    try {
      await usersApi.remove(user.id)
      message.success('用户已删除')
      loadUsers()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除失败')
    }
  }

  const columns: ColumnsType<User> = [
    { title: '账号', dataIndex: 'username', key: 'username' },
    { title: '用户名', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: User['role']) => (
        <Tag color={role === 'admin' ? 'blue' : 'default'}>{role === 'admin' ? '管理员' : '普通用户'}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => <Tag color={active ? 'green' : 'red'}>{active ? '启用' : '已禁用'}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, user) => (
        <Space>
          <Button size="small" onClick={() => openEdit(user)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该用户？"
            disabled={user.id === currentUser?.id}
            onConfirm={() => handleDelete(user)}
          >
            <Button size="small" danger disabled={user.id === currentUser?.id}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          用户管理
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建用户
        </Button>
      </div>

      <Card>
        <Table rowKey="id" columns={columns} dataSource={users} loading={loading} pagination={false} />
      </Card>

      <Modal
        title="新建用户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        confirmLoading={creating}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" initialValues={{ role: 'user' }}>
          <Form.Item name="username" label="账号" rules={[{ required: true, min: 3, message: '账号至少 3 个字符' }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="用户名" rules={[{ required: true, whitespace: true, message: '请输入用户名' }]}>
            <Input autoComplete="name" />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '密码至少 6 个字符' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'user', label: '普通用户' },
                { value: 'admin', label: '管理员' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑用户：${editingUser?.username ?? ''}`}
        open={!!editingUser}
        onCancel={() => setEditingUser(null)}
        onOk={handleSaveEdit}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="display_name" label="用户名" rules={[{ required: true, whitespace: true, message: '请输入用户名' }]}>
            <Input autoComplete="name" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select
              disabled={editingUser?.id === currentUser?.id}
              options={[
                { value: 'user', label: '普通用户' },
                { value: 'admin', label: '管理员' },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_active" label="账号状态" valuePropName="checked">
            <Switch
              disabled={editingUser?.id === currentUser?.id}
              checkedChildren="启用"
              unCheckedChildren="禁用"
            />
          </Form.Item>
          <Form.Item name="password" label="重置密码（留空则不修改）" rules={[{ min: 6, message: '密码至少 6 个字符' }]}>
            <Input.Password autoComplete="new-password" placeholder="留空表示不修改密码" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
