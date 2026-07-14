import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
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
import { CloudDownloadOutlined, PlusOutlined, SafetyCertificateOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { aiProvidersApi } from '../../api/aiProviders'
import { ApiError } from '../../api/client'
import { userGroupsApi } from '../../api/userGroups'
import { usersApi } from '../../api/users'
import type { AIModelItem, AIProviderItem, DiscoveredModelItem, ModelDiscoveryResult, ProviderPresetItem, User, UserGroup } from '../../types'

const { Title, Text, Paragraph } = Typography

const PROVIDER_TYPE_OPTIONS = [
  { value: 'openai_compatible', label: 'OpenAI 兼容接口（DeepSeek/Qwen/Kimi/GLM/vLLM 等）' },
  { value: 'anthropic', label: 'Anthropic（Claude 系列）' },
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function thinkingEfforts(config: Record<string, unknown> | undefined): string[] {
  const efforts = config?.efforts
  return isRecord(efforts) ? Object.keys(efforts) : []
}

function asInteger(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

function recommendedTokenBudget(contextValue: unknown, outputValue: unknown) {
  const contextWindow = asInteger(contextValue)
  if (contextWindow === null || contextWindow < 8192) return null
  const configuredOutput = asInteger(outputValue)
  const defaultOutput = Math.min(8192, Math.max(128, Math.floor(contextWindow / 4)))
  const maxOutputTokens = configuredOutput !== null && configuredOutput >= 128 && configuredOutput < contextWindow
    ? configuredOutput
    : defaultOutput
  const contextCompactionThresholdTokens = contextWindow - maxOutputTokens
  return {
    context_window_tokens: contextWindow,
    context_compaction_threshold_tokens: contextCompactionThresholdTokens,
    max_output_tokens: maxOutputTokens,
    tool_result_max_tokens: Math.min(
      contextCompactionThresholdTokens,
      Math.max(4096, Math.floor(contextCompactionThresholdTokens / 16)),
    ),
  }
}

export default function AdminModelsPage() {
  const [providers, setProviders] = useState<AIProviderItem[]>([])
  const [presets, setPresets] = useState<ProviderPresetItem[]>([])
  const [loading, setLoading] = useState(false)

  const [providerModalOpen, setProviderModalOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<AIProviderItem | null>(null)
  const [providerForm] = Form.useForm()
  const [savingProvider, setSavingProvider] = useState(false)

  const [modelModalProviderId, setModelModalProviderId] = useState<number | null>(null)
  const [editingModel, setEditingModel] = useState<AIModelItem | null>(null)
  const [modelForm] = Form.useForm()
  const [savingModel, setSavingModel] = useState(false)

  const [presetModalOpen, setPresetModalOpen] = useState(false)
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null)
  const [presetDiscovery, setPresetDiscovery] = useState<ModelDiscoveryResult | null>(null)
  const [presetForm] = Form.useForm()
  const [installingPreset, setInstallingPreset] = useState(false)
  const [discoveringPresetModels, setDiscoveringPresetModels] = useState(false)

  const [discoverModalProvider, setDiscoverModalProvider] = useState<AIProviderItem | null>(null)
  const [discovery, setDiscovery] = useState<ModelDiscoveryResult | null>(null)
  const [selectedDiscoveredModels, setSelectedDiscoveredModels] = useState<string[]>([])
  const [discoveringProviderId, setDiscoveringProviderId] = useState<number | null>(null)
  const [importingModels, setImportingModels] = useState(false)

  const [accessModalModel, setAccessModalModel] = useState<AIModelItem | null>(null)
  const [accessUsers, setAccessUsers] = useState<User[]>([])
  const [accessGroups, setAccessGroups] = useState<UserGroup[]>([])
  const [accessForm] = Form.useForm()
  const [loadingAccessTargets, setLoadingAccessTargets] = useState(false)
  const [savingAccess, setSavingAccess] = useState(false)

  const [testingKey, setTestingKey] = useState<string | null>(null)

  const loadProviders = async () => {
    setLoading(true)
    try {
      const data = await aiProvidersApi.list()
      setProviders(data)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载模型列表失败')
    } finally {
      setLoading(false)
    }
  }

  const loadPresets = async () => {
    try {
      setPresets(await aiProvidersApi.listPresets())
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载模型预设失败')
    }
  }

  useEffect(() => {
    void loadProviders()
    void loadPresets()
  }, [])

  const openCreateProvider = () => {
    setEditingProvider(null)
    providerForm.resetFields()
    providerForm.setFieldsValue({ provider_type: 'openai_compatible' })
    setProviderModalOpen(true)
  }

  const openEditProvider = (provider: AIProviderItem) => {
    setEditingProvider(provider)
    providerForm.setFieldsValue({
      name: provider.name,
      provider_type: provider.provider_type,
      base_url: provider.base_url,
      api_key: '',
    })
    setProviderModalOpen(true)
  }

  const handleSaveProvider = async () => {
    try {
      const values = await providerForm.validateFields()
      setSavingProvider(true)
      if (editingProvider) {
        const payload: Record<string, unknown> = { name: values.name, base_url: values.base_url }
        if (values.api_key) payload.api_key = values.api_key
        await aiProvidersApi.update(editingProvider.id, payload)
        message.success('Provider 已更新')
      } else {
        await aiProvidersApi.create(values)
        message.success('Provider 创建成功')
      }
      setProviderModalOpen(false)
      loadProviders()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSavingProvider(false)
    }
  }

  const handleDeleteProvider = async (provider: AIProviderItem) => {
    try {
      await aiProvidersApi.remove(provider.id)
      message.success('Provider 已删除')
      loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除失败')
    }
  }

  const openCreateModel = (providerId: number) => {
    setEditingModel(null)
    modelForm.resetFields()
    modelForm.setFieldsValue({
      is_default: false,
      ...(recommendedTokenBudget(32768, 8192) ?? {}),
      thinking_config_text: '',
      thinking_efforts: [],
    })
    setModelModalProviderId(providerId)
  }

  const openEditModel = (model: AIModelItem) => {
    setEditingModel(model)
    const recommended = recommendedTokenBudget(
      model.context_window_tokens ?? 32768,
      model.max_output_tokens ?? 8192,
    ) ?? recommendedTokenBudget(32768, 8192)
    modelForm.setFieldsValue({
      model_name: model.model_name,
      display_name: model.display_name,
      description: model.description,
      context_window_tokens: recommended?.context_window_tokens,
      context_compaction_threshold_tokens: model.context_compaction_threshold_tokens ?? recommended?.context_compaction_threshold_tokens,
      max_output_tokens: recommended?.max_output_tokens,
      tool_result_max_tokens: model.tool_result_max_tokens ?? recommended?.tool_result_max_tokens,
      is_default: model.is_default,
      thinking_config_text: Object.keys(model.thinking_config ?? {}).length ? JSON.stringify(model.thinking_config, null, 2) : '',
      thinking_efforts: thinkingEfforts(model.thinking_config),
    })
    setModelModalProviderId(model.provider_id)
  }

  const handleModelBudgetBaseChange = (changedValues: Record<string, unknown>) => {
    if (!('context_window_tokens' in changedValues) && !('max_output_tokens' in changedValues)) return
    const recommended = recommendedTokenBudget(
      modelForm.getFieldValue('context_window_tokens'),
      modelForm.getFieldValue('max_output_tokens'),
    )
    if (!recommended) return
    modelForm.setFieldsValue(recommended)
  }

  const handleSaveModel = async () => {
    if (modelModalProviderId === null) return
    try {
      const values = await modelForm.validateFields()
      let thinkingConfig: Record<string, unknown> = {}
      if (values.thinking_config_text?.trim()) {
        try {
          const parsed = JSON.parse(values.thinking_config_text)
          if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('invalid')
          thinkingConfig = parsed
        } catch {
          modelForm.setFields([{ name: 'thinking_config_text', errors: ['请输入合法的 JSON 对象'] }])
          return
        }
      }
      const selectedEfforts = values.thinking_efforts ?? []
      if (selectedEfforts.length) {
        const existingEfforts = isRecord(thinkingConfig.efforts) ? thinkingConfig.efforts : {}
        const effortConfigs = { ...existingEfforts }
        for (const effort of selectedEfforts) {
          if (!isRecord(effortConfigs[effort])) effortConfigs[effort] = { reasoning_effort: effort }
        }
        thinkingConfig = {
          ...thinkingConfig,
          enabled: thinkingConfig.enabled ?? { reasoning_effort: 'medium' },
          disabled: thinkingConfig.disabled ?? { reasoning_effort: 'none' },
          efforts: effortConfigs,
        }
      }
      setSavingModel(true)
      if (editingModel) {
        await aiProvidersApi.updateModel(editingModel.id, {
          display_name: values.display_name,
          description: values.description?.trim() ?? '',
          context_window_tokens: values.context_window_tokens,
          context_compaction_threshold_tokens: values.context_compaction_threshold_tokens,
          max_output_tokens: values.max_output_tokens,
          tool_result_max_tokens: values.tool_result_max_tokens,
          is_default: values.is_default,
          thinking_config: thinkingConfig,
        })
        message.success('模型已更新')
      } else {
        await aiProvidersApi.createModel(modelModalProviderId, {
          model_name: values.model_name,
          display_name: values.display_name,
          description: values.description?.trim() ?? '',
          context_window_tokens: values.context_window_tokens,
          context_compaction_threshold_tokens: values.context_compaction_threshold_tokens,
          max_output_tokens: values.max_output_tokens,
          tool_result_max_tokens: values.tool_result_max_tokens,
          is_default: values.is_default,
          thinking_config: thinkingConfig,
        })
        message.success('模型已添加')
      }
      setModelModalProviderId(null)
      setEditingModel(null)
      loadProviders()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSavingModel(false)
    }
  }

  const handleSetDefault = async (model: AIModelItem) => {
    try {
      await aiProvidersApi.updateModel(model.id, { is_default: true })
      loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '设置失败')
    }
  }

  const handleDeleteModel = async (model: AIModelItem) => {
    try {
      await aiProvidersApi.removeModel(model.id)
      message.success('模型已删除')
      loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除失败')
    }
  }

  const openModelAccess = async (model: AIModelItem) => {
    setAccessModalModel(model)
    accessForm.setFieldsValue({
      access_mode: model.access_mode,
      allowed_user_ids: model.allowed_user_ids,
      allowed_group_ids: model.allowed_group_ids,
    })
    setLoadingAccessTargets(true)
    try {
      const [users, groups] = await Promise.all([usersApi.list(), userGroupsApi.list()])
      setAccessUsers(users)
      setAccessGroups(groups)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载授权对象失败')
    } finally {
      setLoadingAccessTargets(false)
    }
  }

  const handleSaveModelAccess = async () => {
    if (!accessModalModel) return
    try {
      const values = await accessForm.validateFields()
      setSavingAccess(true)
      const restricted = values.access_mode === 'restricted'
      await aiProvidersApi.updateModel(accessModalModel.id, {
        access_mode: values.access_mode,
        allowed_user_ids: restricted ? (values.allowed_user_ids ?? []) : [],
        allowed_group_ids: restricted ? (values.allowed_group_ids ?? []) : [],
      })
      message.success('模型使用范围已更新')
      setAccessModalModel(null)
      void loadProviders()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSavingAccess(false)
    }
  }

  const handleTestConnection = async (provider: AIProviderItem, model: AIModelItem) => {
    const key = `${provider.id}-${model.id}`
    setTestingKey(key)
    try {
      const result = await aiProvidersApi.testConnection(provider.id, model.model_name)
      if (result.success) {
        message.success(result.message)
      } else {
        Modal.error({ title: '连接测试失败', content: result.message })
      }
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '测试连接请求失败')
    } finally {
      setTestingKey(null)
    }
  }

  const openPresetInstall = () => {
    const firstPreset = presets[0]
    if (!firstPreset) {
      message.warning('模型预设仍在加载，请稍后重试')
      return
    }
    setSelectedPresetId(firstPreset.id)
    setPresetDiscovery(null)
    presetForm.resetFields()
    presetForm.setFieldsValue({
      preset_id: firstPreset.id,
      name: firstPreset.name,
      model_names: [],
      set_as_default: providers.length === 0,
    })
    setPresetModalOpen(true)
  }

  const handlePresetChange = (presetId: string) => {
    const preset = presets.find((item) => item.id === presetId)
    if (!preset) return
    setSelectedPresetId(presetId)
    setPresetDiscovery(null)
    presetForm.setFieldsValue({
      name: preset.name,
      model_names: [],
    })
  }

  const handleDiscoverPresetModels = async () => {
    if (!selectedPresetId) return
    try {
      const values = await presetForm.validateFields(['api_key'])
      setDiscoveringPresetModels(true)
      const result = await aiProvidersApi.discoverPresetModels(selectedPresetId, values.api_key)
      setPresetDiscovery(result)
      presetForm.setFieldValue('model_names', [])
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setDiscoveringPresetModels(false)
    }
  }

  const handlePresetApiKeyChange = () => {
    if (presetDiscovery) {
      setPresetDiscovery(null)
      presetForm.setFieldValue('model_names', [])
    }
  }

  const handleInstallPreset = async () => {
    if (!selectedPresetId) return
    try {
      if (!presetDiscovery) {
        message.warning('请先获取该 API Key 当前可用的模型')
        return
      }
      const values = await presetForm.validateFields()
      setInstallingPreset(true)
      await aiProvidersApi.installPreset(selectedPresetId, {
        api_key: values.api_key,
        model_names: values.model_names,
        model_capabilities: presetDiscovery.models.filter((model) => values.model_names.includes(model.model_name)),
        name: values.name,
        set_as_default: values.set_as_default,
      })
      message.success('模型预设已添加')
      setPresetModalOpen(false)
      void loadProviders()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setInstallingPreset(false)
    }
  }

  const handleDiscoverModels = async (provider: AIProviderItem) => {
    setDiscoveringProviderId(provider.id)
    try {
      const result = await aiProvidersApi.discoverModels(provider.id)
      const existingNames = new Set(provider.models.map((model) => model.model_name))
      setDiscoverModalProvider(provider)
      setDiscovery(result)
      setSelectedDiscoveredModels(
        result.models.filter((model) => !existingNames.has(model.model_name)).map((model) => model.model_name),
      )
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '获取模型列表失败')
    } finally {
      setDiscoveringProviderId(null)
    }
  }

  const handleImportDiscoveredModels = async () => {
    if (!discoverModalProvider || !discovery || selectedDiscoveredModels.length === 0) return
    const selected = new Set(selectedDiscoveredModels)
    const models = discovery.models.filter((model) => selected.has(model.model_name))
    try {
      setImportingModels(true)
      const result = await aiProvidersApi.createModelsBulk(discoverModalProvider.id, { models })
      const skipped = result.skipped_model_names.length
      message.success(`已添加 ${result.created.length} 个模型${skipped ? `，跳过 ${skipped} 个已存在模型` : ''}`)
      setDiscoverModalProvider(null)
      setDiscovery(null)
      void loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '批量添加模型失败')
    } finally {
      setImportingModels(false)
    }
  }

  const modelColumns = (provider: AIProviderItem): ColumnsType<AIModelItem> => [
    { title: '模型名称（调用用）', dataIndex: 'model_name', key: 'model_name', width: 220, ellipsis: true },
    { title: '展示名称', dataIndex: 'display_name', key: 'display_name', width: 180, ellipsis: true },
    {
      title: '模型描述',
      dataIndex: 'description',
      key: 'description',
      width: 260,
      ellipsis: true,
      render: (description: string) => description || <Text type="secondary">未填写</Text>,
    },
    {
      title: '推理参数',
      key: 'thinking',
      width: 160,
      render: (_, model) =>
        Object.keys(model.thinking_config ?? {}).length ? (
          <Space size={4} wrap>
            <Tag color="cyan">已配置</Tag>
            {thinkingEfforts(model.thinking_config).map((effort) => <Tag key={effort}>{effort}</Tag>)}
          </Space>
        ) : <Text type="secondary">自动识别</Text>,
    },
    {
      title: '默认模型',
      dataIndex: 'is_default',
      key: 'is_default',
      width: 130,
      render: (isDefault: boolean, model) =>
        isDefault ? (
          <Tag color="blue">默认</Tag>
        ) : (
          <Button size="small" type="link" onClick={() => handleSetDefault(model)}>
            设为默认
          </Button>
        ),
    },
    {
      title: '使用范围',
      key: 'access',
      width: 190,
      render: (_, model) => model.access_mode === 'all' ? (
        <Tag color="green">所有用户</Tag>
      ) : (
        <Space size={4} wrap>
          <Tag color="orange">受限</Tag>
          {model.allowed_user_ids.length > 0 && <Tag>用户 {model.allowed_user_ids.length}</Tag>}
          {model.allowed_group_ids.length > 0 && <Tag>用户组 {model.allowed_group_ids.length}</Tag>}
          {model.allowed_user_ids.length === 0 && model.allowed_group_ids.length === 0 && <Text type="secondary">仅管理员</Text>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 360,
      render: (_, model) => (
        <Space size={8} wrap={false}>
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testingKey === `${provider.id}-${model.id}`}
            onClick={() => handleTestConnection(provider, model)}
          >
            测试连接
          </Button>
          <Button size="small" onClick={() => openEditModel(model)}>
            编辑
          </Button>
          <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => void openModelAccess(model)}>
            权限
          </Button>
          <Popconfirm title="确认删除该模型？" onConfirm={() => handleDeleteModel(model)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const selectedPreset = presets.find((item) => item.id === selectedPresetId)
  const installableModels = presetDiscovery?.models ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          AI 模型与密钥管理
        </Title>
        <Space wrap>
          <Button onClick={openCreateProvider}>自定义 Provider</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openPresetInstall}>
            从预设添加
          </Button>
        </Space>
      </div>

      {providers.length === 0 && !loading && (
        <Card>
          <Empty description="还没有配置任何 AI Provider，点击右上角新增" />
        </Card>
      )}

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {providers.map((provider) => (
          <Card
            key={provider.id}
            title={
              <Space>
                <Text strong>{provider.name}</Text>
                <Tag color={provider.provider_type === 'anthropic' ? 'purple' : 'geekblue'}>
                  {provider.provider_type === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容'}
                </Tag>
              </Space>
            }
            extra={
              <Space wrap>
                <Button
                  size="small"
                  icon={<CloudDownloadOutlined />}
                  loading={discoveringProviderId === provider.id}
                  onClick={() => handleDiscoverModels(provider)}
                >
                  获取模型
                </Button>
                <Button size="small" onClick={() => openEditProvider(provider)}>
                  编辑
                </Button>
                <Popconfirm title="确认删除该 Provider 及其下所有模型？" onConfirm={() => handleDeleteProvider(provider)}>
                  <Button size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            }
          >
            <Paragraph type="secondary" style={{ marginBottom: 12 }}>
              Base URL：{provider.base_url} ｜ API Key：{provider.api_key_masked}
            </Paragraph>
            <Table
              rowKey="id"
              size="small"
              columns={modelColumns(provider)}
              dataSource={provider.models}
              pagination={false}
              scroll={{ x: 1500 }}
              locale={{ emptyText: '暂无模型，点击下方按钮添加' }}
            />
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              style={{ marginTop: 12 }}
              onClick={() => openCreateModel(provider.id)}
            >
              添加模型
            </Button>
          </Card>
        ))}
      </Space>

      <Modal
        title={editingProvider ? `编辑 Provider：${editingProvider.name}` : '新增 Provider'}
        open={providerModalOpen}
        onCancel={() => setProviderModalOpen(false)}
        onOk={handleSaveProvider}
        confirmLoading={savingProvider}
        destroyOnHidden
      >
        <Form form={providerForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：DeepSeek 官方 / 公司自建 vLLM" />
          </Form.Item>
          <Form.Item name="provider_type" label="接口协议类型" rules={[{ required: true }]}>
            <Select options={PROVIDER_TYPE_OPTIONS} disabled={!!editingProvider} />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[{ required: true, message: '请输入 Base URL' }]}
            extra="OpenAI 兼容接口填到 /v1 级别即可，例如 https://api.deepseek.com/v1"
          >
            <Input placeholder="https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={[{ required: !editingProvider, message: '请输入 API Key' }]}
            extra={editingProvider ? '留空表示不修改现有密钥' : undefined}
          >
            <Input.Password autoComplete="off" placeholder={editingProvider ? '留空则不修改' : 'sk-...'} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="从模型预设添加"
        open={presetModalOpen}
        onCancel={() => setPresetModalOpen(false)}
        onOk={handleInstallPreset}
        confirmLoading={installingPreset}
        okText="添加"
        destroyOnHidden
      >
        <Form form={presetForm} layout="vertical">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="预设已包含官方 Base URL、协议和模型思考参数，只需填写 API Key。"
          />
          <Form.Item name="preset_id" label="供应商预设" rules={[{ required: true, message: '请选择供应商' }]}>
            <Select
              options={presets.map((preset) => ({ value: preset.id, label: preset.name }))}
              onChange={handlePresetChange}
            />
          </Form.Item>
          {selectedPreset && (
              <Alert
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
                message={`Base URL：${selectedPreset.base_url}`}
                description={`协议：${selectedPreset.provider_type === 'anthropic' ? 'Anthropic Messages' : 'OpenAI 兼容'}；填写 Key 后获取当前可用模型。`}
              />
          )}
          <Form.Item name="name" label="Provider 名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password autoComplete="off" placeholder="仅加密保存于服务器" onChange={handlePresetApiKeyChange} />
          </Form.Item>
          <Button
            icon={<CloudDownloadOutlined />}
            loading={discoveringPresetModels}
            onClick={handleDiscoverPresetModels}
            style={{ marginBottom: 16 }}
          >
            获取当前可用模型
          </Button>
          {presetDiscovery?.warning && <Alert type="warning" showIcon message={presetDiscovery.warning} style={{ marginBottom: 16 }} />}
          {presetDiscovery && installableModels.length === 0 && (
            <Alert type="error" showIcon message="没有获取到可添加的模型，请确认 API Key 有模型列表权限后重试。" style={{ marginBottom: 16 }} />
          )}
          {presetDiscovery && installableModels.length > 0 && (
            <Form.Item name="model_names" label={`选择要添加的模型（${presetDiscovery.source}）`} rules={[{ required: true, message: '至少选择一个模型' }]}>
              <Checkbox.Group style={{ width: '100%' }}>
                <Space direction="vertical" size={8} style={{ width: '100%', maxHeight: 300, overflowY: 'auto' }}>
                  {installableModels.map((model) => (
                    <Checkbox key={model.model_name} value={model.model_name}>
                      {model.display_name}
                      <Text type="secondary" style={{ marginLeft: 8 }}>{model.model_name}</Text>
                       {model.thinking_efforts.length > 0 && <Tag color="cyan" style={{ marginLeft: 8 }}>思考强度</Tag>}
                       {Boolean(model.thinking_config.enabled) && model.thinking_efforts.length === 0 ? <Tag color="cyan" style={{ marginLeft: 8 }}>可开关思考</Tag> : null}
                       <Tag color={model.context_window_source === '供应商接口' ? 'green' : 'gold'} style={{ marginLeft: 8 }}>
                         上下文 {model.context_window_tokens.toLocaleString()} / 压缩 {model.context_compaction_threshold_tokens.toLocaleString()}
                       </Tag>
                    </Checkbox>
                  ))}
                </Space>
              </Checkbox.Group>
            </Form.Item>
          )}
          <Form.Item name="set_as_default" label="设首个模型为默认模型" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={discoverModalProvider ? `获取模型：${discoverModalProvider.name}` : '获取模型'}
        open={Boolean(discoverModalProvider)}
        onCancel={() => {
          setDiscoverModalProvider(null)
          setDiscovery(null)
        }}
        onOk={handleImportDiscoveredModels}
        okText="添加选中模型"
        okButtonProps={{ disabled: selectedDiscoveredModels.length === 0 }}
        confirmLoading={importingModels}
        width={680}
        destroyOnHidden
      >
        {discovery?.warning && <Alert type="warning" showIcon message={discovery.warning} style={{ marginBottom: 16 }} />}
        {discovery && (
          <>
            <Text type="secondary">模型来源：{discovery.source}</Text>
            <Checkbox.Group
              value={selectedDiscoveredModels}
              onChange={(values) => setSelectedDiscoveredModels(values as string[])}
              style={{ width: '100%', marginTop: 12, maxHeight: 420, overflowY: 'auto' }}
            >
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {discovery.models.map((model: DiscoveredModelItem) => {
                  const exists = discoverModalProvider?.models.some((item) => item.model_name === model.model_name)
                  return (
                    <Checkbox key={model.model_name} value={model.model_name} disabled={exists}>
                      {model.display_name}
                      <Text type="secondary" style={{ marginLeft: 8 }}>{model.model_name}</Text>
                       {exists && <Tag style={{ marginLeft: 8 }}>已添加</Tag>}
                       {model.thinking_efforts.length > 0 && <Tag color="cyan" style={{ marginLeft: 8 }}>{model.thinking_efforts.join(' / ')}</Tag>}
                       <Tag color={model.context_window_source === '供应商接口' ? 'green' : 'gold'} style={{ marginLeft: 8 }}>
                         上下文 {model.context_window_tokens.toLocaleString()} / 压缩 {model.context_compaction_threshold_tokens.toLocaleString()}
                       </Tag>
                    </Checkbox>
                  )
                })}
              </Space>
            </Checkbox.Group>
          </>
        )}
      </Modal>

      <Modal
        title={editingModel ? `编辑模型：${editingModel.display_name}` : '添加模型'}
        open={modelModalProviderId !== null}
        onCancel={() => {
          setModelModalProviderId(null)
          setEditingModel(null)
        }}
        onOk={handleSaveModel}
        confirmLoading={savingModel}
        destroyOnHidden
      >
        <Form form={modelForm} layout="vertical" onValuesChange={handleModelBudgetBaseChange}>
          <Form.Item
            name="model_name"
            label="模型名称（调用 API 时使用）"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input disabled={!!editingModel} placeholder="例如：deepseek-chat / claude-sonnet-4-5-20250929" />
          </Form.Item>
          <Form.Item name="display_name" label="展示名称" rules={[{ required: true, message: '请输入展示名称' }]}>
            <Input placeholder="用于前端模型选择器展示" />
          </Form.Item>
          <Form.Item name="description" label="模型描述" extra="在编辑器的模型下拉选择器中显示，便于区分模型的擅长场景与限制。">
            <Input.TextArea
              autoSize={{ minRows: 2, maxRows: 4 }}
              maxLength={1024}
              showCount
              placeholder="例如：适合长文改写与结构化排版，速度较快"
            />
          </Form.Item>
          <Form.Item
            name="context_window_tokens"
            label="模型最大上下文窗口（tokens）"
            rules={[{ required: true, message: '请输入模型上下文窗口' }]}
            extra="供应商声明的总请求上限。修改此项或最大输出时，会自动更新推荐的压缩阈值和工具返回上限。"
          >
            <InputNumber min={8192} max={2000000} step={1024} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="context_compaction_threshold_tokens"
            label="压缩阈值 / 实际输入上下文（tokens）"
            rules={[{ required: true, message: '请输入实际输入上下文窗口' }]}
            extra="达到此输入预算时会先压缩旧对话；切换到较小模型时也按此值重新评估。"
          >
            <InputNumber min={1024} max={2000000} step={1024} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="max_output_tokens"
            label="单次模型最大输出（tokens）"
            rules={[{ required: true, message: '请输入最大输出 token 数' }]}
            extra="同时传给模型接口，限制回答和工具调用参数的最大生成量。"
          >
            <InputNumber min={128} max={1000000} step={256} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="tool_result_max_tokens"
            label="单次工具返回上限（tokens）"
            rules={[{ required: true, message: '请输入工具返回上限' }]}
            extra="目录和搜索会按条目裁剪；精确 HTML 超限会拒绝返回，避免截断标签。"
          >
            <InputNumber min={128} max={1000000} step={256} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认模型" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="thinking_efforts"
            label="思考强度"
            extra="选择后会生成 OpenAI reasoning_effort 的低/中/高等参数；其他厂商使用下方高级 JSON 覆盖。"
          >
            <Checkbox.Group options={[
              { label: '极简', value: 'minimal' },
              { label: '低', value: 'low' },
              { label: '中', value: 'medium' },
              { label: '高', value: 'high' },
            ]} />
          </Form.Item>
          <Form.Item
            name="thinking_config_text"
            label="高级思考参数 JSON（可选）"
            extra={'预设已自动填写。手工模型示例：{"enabled":{"enable_thinking":true},"disabled":{"enable_thinking":false},"efforts":{"high":{"reasoning_effort":"high"}}}'}
          >
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 8 }}
              placeholder='例如：{"enabled":{"enable_thinking":true},"disabled":{"enable_thinking":false}}'
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={accessModalModel ? `模型权限：${accessModalModel.display_name}` : '模型权限'}
        open={Boolean(accessModalModel)}
        onCancel={() => setAccessModalModel(null)}
        onOk={handleSaveModelAccess}
        confirmLoading={savingAccess}
        destroyOnHidden
      >
        <Form form={accessForm} layout="vertical">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="管理员始终可以使用模型。受限模型会授权给所选用户或任一所选用户组的成员。"
          />
          <Form.Item name="access_mode" label="使用范围" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'all', label: '所有已启用用户' },
                { value: 'restricted', label: '仅指定用户和用户组' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(previous, current) => previous.access_mode !== current.access_mode}>
            {({ getFieldValue }) => getFieldValue('access_mode') === 'restricted' && (
              <>
                <Form.Item name="allowed_user_ids" label="允许使用的用户">
                  <Select
                    mode="multiple"
                    allowClear
                    loading={loadingAccessTargets}
                    optionFilterProp="label"
                    placeholder="选择用户"
                    options={accessUsers.map((user) => ({
                      value: user.id,
                      label: `${user.display_name || user.username}（${user.username}）${user.is_active ? '' : ' - 已禁用'}`,
                    }))}
                  />
                </Form.Item>
                <Form.Item name="allowed_group_ids" label="允许使用的用户组">
                  <Select
                    mode="multiple"
                    allowClear
                    loading={loadingAccessTargets}
                    optionFilterProp="label"
                    placeholder="选择用户组"
                    options={accessGroups.map((group) => ({ value: group.id, label: `${group.name}（${group.members.length} 人）` }))}
                  />
                </Form.Item>
              </>
            )}
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
