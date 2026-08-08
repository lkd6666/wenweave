import { useEffect, useState } from 'react'
import { Button, Card, DatePicker, Descriptions, Drawer, Form, Grid, Input, Pagination, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { ApiError } from '../../api/client'
import { operationLogsApi, type OperationLogQuery } from '../../api/operationLogs'
import { usersApi } from '../../api/users'
import type { OperationLog, OperationLogStatus, User } from '../../types'

const { Title, Text } = Typography

const statusOptions: Array<{ value: OperationLogStatus; label: string }> = [
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const resourceOptions = [
  ['document', '文档'],
  ['document_import', '文档导入'],
  ['document_group', '文档分组'],
  ['chat_run', 'AI 对话'],
  ['chat_session', '对话会话'],
  ['wechat_draft', '公众号草稿'],
  ['wechat_account', '公众号账号'],
  ['user', '用户'],
  ['user_group', '用户组'],
  ['account', '账号安全'],
  ['ai_provider', 'AI 供应商'],
  ['ai_model', 'AI 模型'],
  ['storage', '存储'],
  ['theme', '主题'],
  ['theme_generation', '主题生成'],
  ['theme_reference_asset', '主题参考图'],
  ['theme_version', '主题版本'],
  ['template', '模板'],
  ['api_route', '系统接口'],
].map(([value, label]) => ({ value, label }))

const actionLabels: Record<string, string> = {
  'auth.login': '登录',
  'auth.refresh': '刷新登录会话',
  'account.password.change': '修改密码',
  'document.create': '创建文档',
  'document.update': '编辑文档信息',
  'document.content.update': '保存文档内容',
  'document.delete': '删除文档',
  'document.version.restore': '恢复文档版本',
  'document.version.copy': '复制文档版本',
  'document.ai.revert': '撤销 AI 修改',
  'document.message.restore': '恢复对话版本',
  'document.import.complete': '完成文档导入',
  'document.import.upload': '导入文件上传',
  'document.link_import.preview': '预览链接导入',
  'document.link_import.complete': '完成链接导入',
  'document.link_import.create': '创建链接导入',
  'document.link_import.delete': '删除链接导入',
  'document.image.upload': '上传文档图片',
  'document.wechat_cover.upload': '上传公众号封面',
  'chat.run': 'AI 对话执行',
  'chat.run.cancel_request': '请求停止 AI 对话',
  'chat.session.create': '创建对话',
  'chat.session.update': '编辑对话',
  'chat.session.archive': '归档对话',
  'chat.session.restore': '恢复对话',
  'chat.context.truncate': '截断对话上下文',
  'chat.context.restore': '恢复对话上下文',
  'chat.context.compact': '压缩对话上下文',
  'wechat.draft.push': '推送公众号草稿',
  'theme.reference_asset.upload': '上传主题参考图',
  'theme.generation.create': '创建主题生成任务',
  'theme.generation.cancel': '取消主题生成任务',
  'theme.generation.save': '保存主题生成结果',
  'theme.version.publish': '发布主题版本',
}

function actionLabel(action: string) {
  return actionLabels[action] ?? action
}

function resourceLabel(resourceType: string) {
  return resourceOptions.find((item) => item.value === resourceType)?.label ?? (resourceType || '系统')
}

function statusTag(status: OperationLogStatus) {
  const item = statusOptions.find((option) => option.value === status)
  return <Tag color={status === 'succeeded' ? 'green' : status === 'failed' ? 'red' : 'orange'}>{item?.label ?? status}</Tag>
}

function toIso(value: unknown): string | undefined {
  return value && typeof (value as { toISOString?: unknown }).toISOString === 'function'
    ? (value as { toISOString: () => string }).toISOString()
    : undefined
}

export default function AdminOperationLogsPage() {
  const [form] = Form.useForm()
  const [logs, setLogs] = useState<OperationLog[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [activeFilters, setActiveFilters] = useState<OperationLogQuery>({})
  const [selected, setSelected] = useState<OperationLog | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg

  const load = async (nextPage = page, filters = activeFilters, nextPageSize = pageSize) => {
    setLoading(true)
    try {
      const result = await operationLogsApi.list({ ...filters, page: nextPage, page_size: nextPageSize })
      setLogs(result.items)
      setTotal(result.total)
      setPage(result.page)
      setPageSize(result.page_size)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载操作日志失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(1, {}, 20)
    void usersApi.list().then(setUsers).catch(() => undefined)
  }, [])

  const submit = (values: Record<string, unknown>) => {
    const filters: OperationLogQuery = {
      actor_user_id: values.actor_user_id as number | undefined,
      action: values.action ? String(values.action).trim() : undefined,
      resource_type: values.resource_type ? String(values.resource_type) : undefined,
      status: values.status as OperationLogStatus | undefined,
      document_id: values.document_id ? Number(values.document_id) : undefined,
      client_ip: values.client_ip ? String(values.client_ip).trim() : undefined,
      keyword: values.keyword ? String(values.keyword).trim() : undefined,
      started_at: toIso(values.started_at),
      ended_at: toIso(values.ended_at),
    }
    setActiveFilters(filters)
    void load(1, filters)
  }

  const reset = () => {
    form.resetFields()
    setActiveFilters({})
    void load(1, {})
  }

  const openDetail = async (item: OperationLog) => {
    setSelected(item)
    setDetailLoading(true)
    try {
      setSelected(await operationLogsApi.get(item.id))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载日志详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const columns: ColumnsType<OperationLog> = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 176, render: (value: string) => new Date(value).toLocaleString() },
    { title: '操作者', key: 'actor', width: 150, render: (_, item) => item.actor_display_name || item.actor_username || '未知用户' },
    { title: '操作', dataIndex: 'action', key: 'action', width: 180, render: actionLabel },
    { title: '对象', key: 'resource', render: (_, item) => <span>{resourceLabel(item.resource_type)}{item.resource_name ? `：${item.resource_name}` : item.resource_id ? ` #${item.resource_id}` : ''}</span> },
    { title: '结果', dataIndex: 'status', key: 'status', width: 90, render: statusTag },
    { title: '客户端 IP', dataIndex: 'client_ip', key: 'client_ip', width: 140, render: (value: string) => value || '-' },
    { title: '摘要', dataIndex: 'summary', key: 'summary', ellipsis: true },
    { title: '详情', key: 'detail', width: 84, render: (_, item) => <Button type="link" size="small" onClick={() => void openDetail(item)}>查看</Button> },
  ]

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <Title level={4} style={{ margin: 0 }}>操作日志</Title>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
      </div>
      <Card>
        <Form form={form} layout="vertical" onFinish={submit} className="admin-log-filters">
          <div className="admin-log-filter-grid">
            <Form.Item name="keyword" label="关键词"><Input allowClear placeholder="操作者、对象或摘要" /></Form.Item>
            <Form.Item name="actor_user_id" label="操作者"><Select allowClear showSearch optionFilterProp="label" options={users.map((user) => ({ value: user.id, label: user.display_name || user.username }))} /></Form.Item>
            <Form.Item name="status" label="结果"><Select allowClear options={statusOptions} /></Form.Item>
            <Form.Item name="resource_type" label="对象类型"><Select allowClear options={resourceOptions} /></Form.Item>
            <Form.Item name="document_id" label="文档 ID"><Input inputMode="numeric" /></Form.Item>
            <Form.Item name="client_ip" label="客户端 IP"><Input allowClear placeholder="例如 203.0.113.8" /></Form.Item>
            <Form.Item name="action" label="动作代码"><Input allowClear placeholder="例如 document.content.update" /></Form.Item>
            <Form.Item name="started_at" label="开始时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="ended_at" label="结束时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} /></Form.Item>
          </div>
          <Space>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>查询</Button>
            <Button onClick={reset}>重置</Button>
          </Space>
        </Form>
      </Card>
      <Card>
        {isCompact ? (
          <div className="responsive-card-list" aria-label="操作日志列表">
            {logs.map((item) => (
              <article className="responsive-data-card" key={item.id}>
                <div className="responsive-data-card-heading"><strong>{actionLabel(item.action)}</strong>{statusTag(item.status)}</div>
                <div className="responsive-data-card-description">{item.summary || item.error_summary || '无摘要'}</div>
                <div className="responsive-data-card-meta"><span>{item.actor_display_name || item.actor_username || '未知用户'}</span><span>{new Date(item.created_at).toLocaleString()}</span></div>
                <div className="responsive-data-card-actions"><Button size="small" onClick={() => void openDetail(item)}>查看详情</Button></div>
              </article>
            ))}
          </div>
        ) : <Table rowKey="id" columns={columns} dataSource={logs} loading={loading} pagination={false} scroll={{ x: 940 }} />}
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger
          pageSizeOptions={[20, 50, 100]}
          showTotal={(count) => `共 ${count} 条`}
          onChange={(nextPage, nextPageSize) => void load(nextPageSize === pageSize ? nextPage : 1, activeFilters, nextPageSize)}
          style={{ marginTop: 16, textAlign: 'right' }}
        />
      </Card>
      <Drawer title="操作日志详情" size={isCompact ? '100%' : 560} open={!!selected} onClose={() => setSelected(null)} loading={detailLoading}>
        {selected && <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="时间">{new Date(selected.created_at).toLocaleString()}</Descriptions.Item>
          <Descriptions.Item label="操作者">{selected.actor_display_name || selected.actor_username || '未知用户'}</Descriptions.Item>
          <Descriptions.Item label="操作">{actionLabel(selected.action)} <Text type="secondary">{selected.action}</Text></Descriptions.Item>
          <Descriptions.Item label="对象">{resourceLabel(selected.resource_type)}{selected.resource_name ? `：${selected.resource_name}` : selected.resource_id ? ` #${selected.resource_id}` : ''}</Descriptions.Item>
          <Descriptions.Item label="结果">{statusTag(selected.status)}</Descriptions.Item>
          <Descriptions.Item label="摘要">{selected.summary || '-'}</Descriptions.Item>
          {selected.error_summary && <Descriptions.Item label="错误摘要">{selected.error_summary}</Descriptions.Item>}
          {selected.document_id && <Descriptions.Item label="文档 ID">{selected.document_id}</Descriptions.Item>}
          {selected.session_id && <Descriptions.Item label="会话 ID">{selected.session_id}</Descriptions.Item>}
          <Descriptions.Item label="客户端 IP">{selected.client_ip || '-'}</Descriptions.Item>
          <Descriptions.Item label="User-Agent"><span className="operation-log-user-agent">{selected.user_agent || '-'}</span></Descriptions.Item>
          <Descriptions.Item label="请求 ID">{selected.request_id || '-'}</Descriptions.Item>
          {Object.keys(selected.details).length > 0 && <Descriptions.Item label="附加信息"><pre className="operation-log-details">{JSON.stringify(selected.details, null, 2)}</pre></Descriptions.Item>}
        </Descriptions>}
      </Drawer>
    </div>
  )
}
