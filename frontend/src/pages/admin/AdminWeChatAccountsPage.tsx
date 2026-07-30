import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Grid,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ApiOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { ApiError } from '../../api/client'
import { wechatAccountsApi } from '../../api/wechatAccounts'
import { userGroupsApi } from '../../api/userGroups'
import { usersApi } from '../../api/users'
import type { User, UserGroup, WeChatAccount } from '../../types'

const { Title, Text } = Typography

export default function AdminWeChatAccountsPage() {
  const [accounts, setAccounts] = useState<WeChatAccount[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<UserGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<WeChatAccount | null>(null)
  const [form] = Form.useForm()
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg

  const load = async () => {
    setLoading(true)
    try {
      const [accountItems, userItems, groupItems] = await Promise.all([
        wechatAccountsApi.list(),
        usersApi.list(),
        userGroupsApi.list(),
      ])
      setAccounts(accountItems)
      setUsers(userItems.filter((user) => user.role === 'user'))
      setGroups(groupItems)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载公众号账号失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ allowed_user_ids: [], allowed_group_ids: [], is_active: true })
    setModalOpen(true)
  }

  const openEdit = (account: WeChatAccount) => {
    setEditing(account)
    form.setFieldsValue({
      name: account.name,
      app_id: account.app_id,
      app_secret: '',
      allowed_user_ids: account.allowed_user_ids,
      allowed_group_ids: account.allowed_group_ids,
      is_active: account.is_active,
    })
    setModalOpen(true)
  }

  const save = async () => {
    try {
      const values = await form.validateFields()
      if (!editing && !values.app_secret?.trim()) {
        form.setFields([{ name: 'app_secret', errors: ['请输入 AppSecret'] }])
        return
      }
      setSaving(true)
      const payload = {
        name: values.name.trim(),
        app_id: values.app_id.trim(),
        allowed_user_ids: values.allowed_user_ids ?? [],
        allowed_group_ids: values.allowed_group_ids ?? [],
        is_active: Boolean(values.is_active),
        ...(values.app_secret?.trim() ? { app_secret: values.app_secret.trim() } : {}),
      }
      if (editing) {
        await wechatAccountsApi.update(editing.id, payload)
        message.success('公众号账号已更新')
      } else {
        await wechatAccountsApi.create(payload as { name: string; app_id: string; app_secret: string; allowed_user_ids: number[]; allowed_group_ids: number[]; is_active: boolean })
        message.success('公众号账号已创建')
      }
      setModalOpen(false)
      await load()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSaving(false)
    }
  }

  const test = async (account: WeChatAccount) => {
    setTestingId(account.id)
    try {
      const result = await wechatAccountsApi.test(account.id)
      if (result.success) message.success(result.message)
      else Modal.error({ title: '连接测试失败', content: result.message })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '连接测试请求失败')
    } finally {
      setTestingId(null)
    }
  }

  const remove = async (account: WeChatAccount) => {
    try {
      await wechatAccountsApi.remove(account.id)
      message.success('公众号账号已删除')
      await load()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除公众号账号失败')
    }
  }

  const actions = (account: WeChatAccount) => (
    <Space size={4} wrap>
      <Tooltip title="编辑账号与授权范围"><Button size="small" icon={<EditOutlined />} onClick={() => openEdit(account)}>编辑</Button></Tooltip>
      <Tooltip title="测试 AppID、AppSecret 与 IP 白名单"><Button size="small" icon={<ThunderboltOutlined />} loading={testingId === account.id} onClick={() => void test(account)}>测试</Button></Tooltip>
      <Popconfirm title={`确认删除公众号账号“${account.name}”？`} onConfirm={() => void remove(account)}>
        <Tooltip title="已有草稿记录的账号只能停用"><Button size="small" danger icon={<DeleteOutlined />}>删除</Button></Tooltip>
      </Popconfirm>
    </Space>
  )

  const columns: ColumnsType<WeChatAccount> = [
    { title: '公众号', dataIndex: 'name', key: 'name', render: (name: string) => <Space><ApiOutlined /><strong>{name}</strong></Space> },
    { title: 'AppID', dataIndex: 'app_id', key: 'app_id' },
    {
      title: '授权范围',
      key: 'access',
      render: (_, account) => <Space size={[4, 4]} wrap><Tag>{account.allowed_user_ids.length} 人</Tag><Tag color="purple">{account.allowed_group_ids.length} 组</Tag></Space>,
    },
    { title: '状态', dataIndex: 'is_active', key: 'is_active', render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '已停用'}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', render: (value: string) => new Date(value).toLocaleString() },
    { title: '操作', key: 'actions', render: (_, account) => actions(account) },
  ]

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <Title level={4} style={{ margin: 0 }}>公众号账号</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增公众号</Button>
      </div>
      <Card loading={loading}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="凭据仅加密保存在服务器。请在公众号后台将部署服务器的公网出口 IP 加入 API IP 白名单；管理员始终可推送，普通用户可按用户或用户组授权。"
        />
        {isCompact ? (
          <div className="responsive-card-list" aria-label="公众号账号列表">
            {accounts.map((account) => (
              <article className="responsive-data-card" key={account.id}>
                <div className="responsive-data-card-heading"><strong>{account.name}</strong><Tag color={account.is_active ? 'green' : 'default'}>{account.is_active ? '启用' : '已停用'}</Tag></div>
                <div className="responsive-data-card-secondary">AppID：{account.app_id}</div>
                <Text type="secondary">授权范围：{account.allowed_user_ids.length} 人，{account.allowed_group_ids.length} 组</Text>
                <div className="responsive-data-card-actions">{actions(account)}</div>
              </article>
            ))}
          </div>
        ) : <Table rowKey="id" columns={columns} dataSource={accounts} pagination={false} />}
      </Card>
      <Modal
        title={editing ? `编辑公众号：${editing.name}` : '新增公众号'}
        open={modalOpen}
        className="admin-wechat-account-modal"
        onCancel={() => setModalOpen(false)}
        onOk={() => void save()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="公众号名称" rules={[{ required: true, whitespace: true, message: '请输入公众号名称' }]}><Input maxLength={128} /></Form.Item>
          <Form.Item name="app_id" label="AppID" rules={[{ required: true, whitespace: true, message: '请输入 AppID' }]}><Input maxLength={64} autoComplete="off" /></Form.Item>
          <Form.Item name="app_secret" label={editing ? 'AppSecret（留空不修改）' : 'AppSecret'} rules={editing ? [] : [{ required: true, whitespace: true, message: '请输入 AppSecret' }]}><Input.Password maxLength={512} autoComplete="new-password" /></Form.Item>
          <Form.Item name="allowed_user_ids" label="允许推送的普通用户" extra="管理员不需要单独配置，始终拥有推送权限。">
            <Select mode="multiple" allowClear showSearch optionFilterProp="label" placeholder="选择普通用户" options={users.map((user) => ({ value: user.id, label: `${user.display_name || user.username}（${user.username}）${user.is_active ? '' : ' - 已禁用'}`, disabled: !user.is_active }))} />
          </Form.Item>
          <Form.Item name="allowed_group_ids" label="允许推送的用户组" extra="用户属于任一已授权用户组时，即可向该公众号推送草稿。">
            <Select mode="multiple" allowClear showSearch optionFilterProp="label" placeholder="选择用户组" options={groups.map((group) => ({ value: group.id, label: `${group.name}（${group.members.length} 人）` }))} />
          </Form.Item>
          <Form.Item name="is_active" label="账号状态" valuePropName="checked" style={{ marginBottom: 0 }}><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
