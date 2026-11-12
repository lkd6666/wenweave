import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Grid,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tabs,
  TimePicker,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CloudDownloadOutlined, DeleteOutlined, PlusOutlined, SafetyCertificateOutlined, SearchOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { aiProvidersApi } from '../../api/aiProviders'
import type { CreateImageModelPayload, UpdateProviderPayload } from '../../api/aiProviders'
import { ApiError } from '../../api/client'
import { userGroupsApi } from '../../api/userGroups'
import { usersApi } from '../../api/users'
import type { AIImageModelItem, AIModelItem, AIProviderItem, AvailabilityTimeRange, DiscoveredModelItem, ModelDiscoveryResult, ProviderPresetItem, ProviderType, User, UserGroup } from '../../types'
import { deriveModelTokenBudget, formatKTokens, tokensToWholeK } from '../../utils/modelTokenBudget'

const { Title, Text, Paragraph } = Typography

const PROVIDER_TYPE_OPTIONS = [
  { value: 'openai_compatible', label: 'OpenAI 兼容接口（DeepSeek/Qwen/Kimi/GLM/vLLM 等）' },
  { value: 'openai_responses', label: 'OpenAI Responses API' },
  { value: 'anthropic', label: 'Anthropic（Claude 系列）' },
  { value: 'gemini_native', label: 'Google Gemini 原生 API（generateContent）' },
]

function providerProtocolLabel(providerType: string): string {
  if (providerType === 'anthropic') return 'Anthropic Messages'
  if (providerType === 'openai_responses') return 'OpenAI Responses API'
  if (providerType === 'gemini_native') return 'Gemini 原生 GenerateContent'
  return 'OpenAI Chat Completions 兼容'
}

function providerProtocolColor(providerType: string): string {
  if (providerType === 'anthropic') return 'purple'
  if (providerType === 'openai_responses') return 'green'
  if (providerType === 'gemini_native') return 'gold'
  return 'geekblue'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function thinkingEfforts(config: Record<string, unknown> | undefined): string[] {
  const efforts = config?.efforts
  return isRecord(efforts) ? Object.keys(efforts) : []
}

function thinkingEffortsFromJson(value: unknown): string[] {
  if (typeof value !== 'string' || !value.trim()) return []
  try {
    const parsed: unknown = JSON.parse(value)
    return isRecord(parsed) ? thinkingEfforts(parsed) : []
  } catch {
    return []
  }
}

function availabilityTimeRangeFormValue(ranges: AvailabilityTimeRange[] | undefined) {
  return (ranges ?? []).map((item) => ({
    range: [dayjs(`2000-01-01T${item.start}:00`), dayjs(`2000-01-01T${item.end}:00`)],
  }))
}

function availabilityTimeRangesPayload(value: unknown): AvailabilityTimeRange[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const range = isRecord(item) ? item.range : undefined
    if (!Array.isArray(range) || range.length !== 2 || !dayjs.isDayjs(range[0]) || !dayjs.isDayjs(range[1])) {
      return []
    }
    return [{ start: range[0].format('HH:mm'), end: range[1].format('HH:mm') }]
  })
}

function availabilityTimeRangeSummary(ranges: AvailabilityTimeRange[] | undefined): string {
  return (ranges?.length ?? 0) > 0
    ? ranges!.map((item) => `${item.start}-${item.end}`).join(' / ')
    : '全天可用'
}

function AvailabilityTimeRangesFormItem() {
  return (
    <Form.Item label="可用时段（中国标准时间）" extra="留空即全天可用；支持跨午夜，例如 22:00-02:00。">
      <Form.List name="availability_time_ranges">
        {(fields, { add, remove }) => (
          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
            {fields.map((field) => (
              <Space key={field.key} align="center" wrap>
                <Form.Item name={[field.name, 'range']} noStyle rules={[{ required: true, message: '请选择开始和结束时间' }]}>
                  <TimePicker.RangePicker format="HH:mm" minuteStep={1} allowClear={false} inputReadOnly order={false} />
                </Form.Item>
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label="删除可用时段"
                  onClick={() => remove(field.name)}
                />
              </Space>
            ))}
            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({})}>添加时段</Button>
          </Space>
        )}
      </Form.List>
    </Form.Item>
  )
}

const THINKING_EFFORT_OPTIONS = [
  { label: '极简', value: 'minimal' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
  { label: '超高', value: 'xhigh' },
  { label: '最大（max）', value: 'max' },
]

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
  const [imageModelModalProviderId, setImageModelModalProviderId] = useState<number | null>(null)
  const [editingImageModel, setEditingImageModel] = useState<AIImageModelItem | null>(null)
  const [imageModelForm] = Form.useForm()
  const [savingImageModel, setSavingImageModel] = useState(false)
  const [providerTabs, setProviderTabs] = useState<Record<number, 'chat' | 'image'>>({})

  const [presetModalOpen, setPresetModalOpen] = useState(false)
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null)
  const [presetDiscovery, setPresetDiscovery] = useState<ModelDiscoveryResult | null>(null)
  const [presetForm] = Form.useForm()
  const [installingPreset, setInstallingPreset] = useState(false)
  const [discoveringPresetModels, setDiscoveringPresetModels] = useState(false)

  const [discoverModalProvider, setDiscoverModalProvider] = useState<AIProviderItem | null>(null)
  const [discovery, setDiscovery] = useState<ModelDiscoveryResult | null>(null)
  const [selectedDiscoveredModels, setSelectedDiscoveredModels] = useState<string[]>([])
  const [discoveredModelSearch, setDiscoveredModelSearch] = useState('')
  const [discoveringProviderId, setDiscoveringProviderId] = useState<number | null>(null)
  const [importingModels, setImportingModels] = useState(false)

  const [accessModalModel, setAccessModalModel] = useState<AIModelItem | null>(null)
  const [accessUsers, setAccessUsers] = useState<User[]>([])
  const [accessGroups, setAccessGroups] = useState<UserGroup[]>([])
  const [accessForm] = Form.useForm()
  const [loadingAccessTargets, setLoadingAccessTargets] = useState(false)
  const [savingAccess, setSavingAccess] = useState(false)

  const [testingKey, setTestingKey] = useState<string | null>(null)
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const inputLimitK = Form.useWatch('input_limit_k', modelForm)
  const outputLimitK = Form.useWatch('output_limit_k', modelForm)
  const selectedThinkingEfforts = (Form.useWatch('thinking_efforts', modelForm) ?? []) as string[]
  const thinkingConfigText = Form.useWatch('thinking_config_text', modelForm)
  const selectedPresetProviderType = Form.useWatch('provider_type', presetForm) as ProviderType | undefined
  const defaultThinkingEffortOptions = Array.from(new Set([
    ...selectedThinkingEfforts,
    ...thinkingEffortsFromJson(thinkingConfigText),
  ])).flatMap((effort) => {
    const option = THINKING_EFFORT_OPTIONS.find((item) => item.value === effort)
    return option ? [option] : []
  })
  const modelModalProvider = providers.find((provider) => provider.id === modelModalProviderId)
  const supportsPromptCache = modelModalProvider?.provider_type === 'openai_compatible'
    || modelModalProvider?.provider_type === 'openai_responses'
    || modelModalProvider?.provider_type === 'anthropic'
  const isAnthropicProvider = modelModalProvider?.provider_type === 'anthropic'
  const isGeminiNativeProvider = modelModalProvider?.provider_type === 'gemini_native'
  const automaticTokenBudget = deriveModelTokenBudget(inputLimitK, outputLimitK)
  const discoveredModelQuery = discoveredModelSearch.trim().toLocaleLowerCase()
  const filteredDiscoveredModels = (discovery?.models ?? []).filter((model) => (
    !discoveredModelQuery
    || model.display_name.toLocaleLowerCase().includes(discoveredModelQuery)
    || model.model_name.toLocaleLowerCase().includes(discoveredModelQuery)
  ))
  const existingDiscoveredModelNames = new Set(
    discoverModalProvider?.models.map((model) => model.model_name) ?? [],
  )
  const filteredSelectableModelNames = filteredDiscoveredModels
    .filter((model) => !existingDiscoveredModelNames.has(model.model_name))
    .map((model) => model.model_name)
  const selectableDiscoveredModelCount = (discovery?.models ?? []).filter(
    (model) => !existingDiscoveredModelNames.has(model.model_name),
  ).length
  const selectedDiscoveredModelNames = new Set(selectedDiscoveredModels)
  const allFilteredModelsSelected = filteredSelectableModelNames.length > 0
    && filteredSelectableModelNames.every((modelName) => selectedDiscoveredModelNames.has(modelName))
  const someFilteredModelsSelected = filteredSelectableModelNames.some(
    (modelName) => selectedDiscoveredModelNames.has(modelName),
  )

  const loadProviders = async () => {
    setLoading(true)
    try {
      const data = await aiProvidersApi.list()
      setProviders(data.map((provider) => ({ ...provider, image_models: provider.image_models ?? [] })))
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

  const loadAccessTargets = async () => {
    try {
      const [users, groups] = await Promise.all([usersApi.list(), userGroupsApi.list()])
      setAccessUsers(users)
      setAccessGroups(groups)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载授权对象失败')
    }
  }

  useEffect(() => {
    void loadProviders()
    void loadPresets()
    void loadAccessTargets()
  }, [])

  const openCreateProvider = () => {
    setEditingProvider(null)
    providerForm.resetFields()
    providerForm.setFieldsValue({ provider_type: 'openai_compatible', is_enabled: true, availability_time_ranges: [] })
    setProviderModalOpen(true)
  }

  const openEditProvider = (provider: AIProviderItem) => {
    setEditingProvider(provider)
    providerForm.setFieldsValue({
      name: provider.name,
      provider_type: provider.provider_type,
      base_url: provider.base_url,
      image_protocol: provider.image_protocol || '',
      image_base_url: provider.image_base_url || '',
      is_enabled: provider.is_enabled,
      availability_time_ranges: availabilityTimeRangeFormValue(provider.availability_time_ranges),
      api_key: '',
    })
    setProviderModalOpen(true)
  }

  const handleSaveProvider = async () => {
    try {
      const values = await providerForm.validateFields()
      setSavingProvider(true)
      if (editingProvider) {
        const payload: UpdateProviderPayload = {
          name: values.name,
          provider_type: values.provider_type,
          base_url: values.base_url,
          image_protocol: values.image_protocol || '',
          image_base_url: values.image_base_url || '',
          is_enabled: values.is_enabled,
          availability_time_ranges: availabilityTimeRangesPayload(values.availability_time_ranges),
        }
        if (values.api_key) payload.api_key = values.api_key
        await aiProvidersApi.update(editingProvider.id, payload)
        message.success('Provider 已更新')
      } else {
        await aiProvidersApi.create({
          ...values,
          is_enabled: values.is_enabled,
          availability_time_ranges: availabilityTimeRangesPayload(values.availability_time_ranges),
        })
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

  const handleProviderEnabledChange = async (provider: AIProviderItem, isEnabled: boolean) => {
    try {
      await aiProvidersApi.update(provider.id, { is_enabled: isEnabled })
      message.success(isEnabled ? 'Provider 已启用' : 'Provider 已停用')
      void loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '更新 Provider 状态失败')
    }
  }

  const openCreateModel = (providerId: number) => {
    setEditingModel(null)
    modelForm.resetFields()
    modelForm.setFieldsValue({
      is_default: false,
      is_enabled: true,
      is_multimodal: false,
      supports_disabled_thinking: true,
      input_limit_k: 24,
      output_limit_k: 8,
      thinking_config_text: '',
      thinking_efforts: [],
      default_thinking_effort: 'auto',
      prompt_cache_enabled: false,
      availability_time_ranges: [],
    })
    setModelModalProviderId(providerId)
  }

  const openCreateImageModel = (providerId: number) => {
    setEditingImageModel(null)
    imageModelForm.resetFields()
    imageModelForm.setFieldsValue({ supported_aspect_ratios: ['landscape', 'portrait', 'square'], supported_qualities: ['auto', 'medium'], is_default: false, is_enabled: true, availability_time_ranges: [], access_mode: 'all' })
    setImageModelModalProviderId(providerId)
  }

  const openEditImageModel = (model: AIImageModelItem) => {
    setEditingImageModel(model)
    imageModelForm.setFieldsValue({ ...model, availability_time_ranges: availabilityTimeRangeFormValue(model.availability_time_ranges), allowed_user_ids: model.allowed_user_ids ?? [], allowed_group_ids: model.allowed_group_ids ?? [] })
    setImageModelModalProviderId(model.provider_id)
  }

  const handleSaveImageModel = async () => {
    if (imageModelModalProviderId === null) return
    try {
      const values = await imageModelForm.validateFields()
      const parseIds = (value: unknown) => (Array.isArray(value) ? value : String(value ?? '').split(',')).map((item) => Number(String(item).trim())).filter((item) => Number.isInteger(item) && item > 0)
      const normalizedValues = {
        ...values,
        availability_time_ranges: availabilityTimeRangesPayload(values.availability_time_ranges),
        allowed_user_ids: parseIds(values.allowed_user_ids),
        allowed_group_ids: parseIds(values.allowed_group_ids),
      }
      setSavingImageModel(true)
      if (editingImageModel) {
        await aiProvidersApi.updateImageModel(editingImageModel.id, normalizedValues)
      } else {
        const payload: CreateImageModelPayload = normalizedValues
        await aiProvidersApi.createImageModel(imageModelModalProviderId, payload)
      }
      message.success('图片模型已保存')
      setImageModelModalProviderId(null)
      void loadProviders()
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSavingImageModel(false)
    }
  }

  const handleDeleteImageModel = async (model: AIImageModelItem) => {
    try {
      await aiProvidersApi.removeImageModel(model.id)
      message.success('图片模型已删除')
      void loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除图片模型失败')
    }
  }

  const handleImageModelEnabledChange = async (model: AIImageModelItem, isEnabled: boolean) => {
    try {
      await aiProvidersApi.updateImageModel(model.id, { is_enabled: isEnabled })
      message.success(isEnabled ? '图片模型已启用' : '图片模型已停用')
      void loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '更新图片模型状态失败')
    }
  }

  const imageModelList = (provider: AIProviderItem) => (
    <div className="responsive-card-list admin-model-card-list">
      {(() => {
        const imageModels = provider.image_models ?? []
        return imageModels.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无图片模型" /> : imageModels.map((model) => (
        <article className="responsive-data-card" key={model.id}>
          <div className="responsive-data-card-heading"><div><strong>{model.display_name}</strong><div className="responsive-data-card-secondary">{model.model_name}</div></div><Space size={4}>{model.is_default && <Tag color="blue">默认</Tag>}<Switch size="small" aria-label={`切换图片模型 ${model.display_name} 的启用状态`} checked={model.is_enabled} onChange={(isEnabled) => void handleImageModelEnabledChange(model, isEnabled)} /></Space></div>
          {model.description && <div className="responsive-data-card-description">{model.description}</div>}
          <div className="responsive-data-card-tags"><Tag>{model.supported_aspect_ratios.join(' / ')}</Tag><Tag>{model.supported_qualities.join(' / ')}</Tag><Tag color={(model.operations ?? []).includes('edit') ? 'green' : 'default'}>{(model.operations ?? []).includes('edit') ? '支持 AI 编辑' : '仅支持生成'}</Tag>{Array.isArray(model.adapter_config?.operations) && <Tag color="blue">能力已覆盖</Tag>}{model.access_mode === 'restricted' && <Tag color="orange">受限</Tag>}<Tag>{availabilityTimeRangeSummary(model.availability_time_ranges)}</Tag></div>
          <Space className="responsive-data-card-actions"><Button size="small" onClick={() => openEditImageModel(model)}>编辑</Button>{!model.is_default && <Button size="small" type="link" onClick={() => void aiProvidersApi.updateImageModel(model.id, { is_default: true }).then(loadProviders)}>设为默认</Button>}<Popconfirm title="确认删除该图片模型？" onConfirm={() => void handleDeleteImageModel(model)}><Button size="small" danger>删除</Button></Popconfirm></Space>
        </article>
        ))
      })()}
      <Button type="dashed" icon={<PlusOutlined />} onClick={() => openCreateImageModel(provider.id)}>添加图片模型</Button>
    </div>
  )

  const openEditModel = (model: AIModelItem) => {
    setEditingModel(model)
    modelForm.setFieldsValue({
      model_name: model.model_name,
      display_name: model.display_name,
      description: model.description,
      input_limit_k: tokensToWholeK(model.context_compaction_threshold_tokens),
      output_limit_k: tokensToWholeK(model.max_output_tokens),
      is_default: model.is_default,
      is_enabled: model.is_enabled,
      availability_time_ranges: availabilityTimeRangeFormValue(model.availability_time_ranges),
      is_multimodal: model.is_multimodal,
      supports_disabled_thinking: model.supports_disabled_thinking,
      thinking_config_text: Object.keys(model.thinking_config ?? {}).length ? JSON.stringify(model.thinking_config, null, 2) : '',
      thinking_efforts: thinkingEfforts(model.thinking_config),
      default_thinking_effort: model.default_thinking_effort,
      prompt_cache_enabled: model.prompt_cache_enabled,
    })
    setModelModalProviderId(model.provider_id)
  }

  const handleSaveModel = async () => {
    if (modelModalProviderId === null) return
    try {
      const values = await modelForm.validateFields()
      const tokenBudget = deriveModelTokenBudget(values.input_limit_k, values.output_limit_k)
      if (!tokenBudget) {
        modelForm.setFields([{
          name: 'input_limit_k',
          errors: ['输入和输出合计需在 8K 至 2,000K 之间，输出最多为 1,000K'],
        }])
        return
      }
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
          if (!isRecord(effortConfigs[effort])) {
            effortConfigs[effort] = isAnthropicProvider
              ? { thinking: { type: 'adaptive' }, effort }
              : isGeminiNativeProvider
                ? { thinkingConfig: values.model_name?.toString().toLowerCase().startsWith('gemini-3')
                    ? { includeThoughts: true, thinkingLevel: effort === 'low' ? 'low' : 'high' }
                    : { includeThoughts: true, thinkingBudget: effort === 'minimal' ? 512 : effort === 'low' ? 1024 : effort === 'medium' ? 4096 : effort === 'high' ? 8192 : -1 } }
                : { reasoning_effort: effort }
          }
        }
        thinkingConfig = {
          ...thinkingConfig,
          enabled: thinkingConfig.enabled ?? (
            isAnthropicProvider
              ? { thinking: { type: 'adaptive' }, effort: 'medium' }
              : isGeminiNativeProvider
                ? { thinkingConfig: values.model_name?.toString().toLowerCase().startsWith('gemini-3')
                    ? { includeThoughts: true, thinkingLevel: 'high' }
                    : { includeThoughts: true, thinkingBudget: -1 } }
                : { reasoning_effort: 'medium' }
          ),
          disabled: thinkingConfig.disabled ?? (
            isAnthropicProvider
              ? {}
              : isGeminiNativeProvider
                ? { thinkingConfig: values.model_name?.toString().toLowerCase().startsWith('gemini-3')
                    ? { includeThoughts: false, thinkingLevel: 'low' }
                    : { includeThoughts: false, thinkingBudget: 0 } }
                : { reasoning_effort: 'none' }
          ),
          efforts: effortConfigs,
        }
      }
      const defaultThinkingEffort = values.default_thinking_effort ?? 'auto'
      if (defaultThinkingEffort !== 'auto' && !thinkingEfforts(thinkingConfig).includes(defaultThinkingEffort)) {
        modelForm.setFields([{
          name: 'default_thinking_effort',
          errors: ['默认思考强度必须已在上方启用或高级 JSON 中配置'],
        }])
        return
      }
      setSavingModel(true)
      if (editingModel) {
        await aiProvidersApi.updateModel(editingModel.id, {
          display_name: values.display_name,
          description: values.description?.trim() ?? '',
          ...tokenBudget,
          is_default: values.is_default,
          is_enabled: values.is_enabled,
          availability_time_ranges: availabilityTimeRangesPayload(values.availability_time_ranges),
          is_multimodal: values.is_multimodal,
          supports_disabled_thinking: values.supports_disabled_thinking,
          default_thinking_effort: defaultThinkingEffort,
          prompt_cache_enabled: supportsPromptCache && Boolean(values.prompt_cache_enabled),
          thinking_config: thinkingConfig,
        })
        message.success('模型已更新')
      } else {
        await aiProvidersApi.createModel(modelModalProviderId, {
          model_name: values.model_name,
          display_name: values.display_name,
          description: values.description?.trim() ?? '',
          ...tokenBudget,
          is_default: values.is_default,
          is_enabled: values.is_enabled,
          availability_time_ranges: availabilityTimeRangesPayload(values.availability_time_ranges),
          is_multimodal: values.is_multimodal,
          supports_disabled_thinking: values.supports_disabled_thinking,
          default_thinking_effort: defaultThinkingEffort,
          prompt_cache_enabled: supportsPromptCache && Boolean(values.prompt_cache_enabled),
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

  const handleModelEnabledChange = async (model: AIModelItem, isEnabled: boolean) => {
    try {
      await aiProvidersApi.updateModel(model.id, { is_enabled: isEnabled })
      message.success(isEnabled ? '模型已启用' : '模型已停用')
      void loadProviders()
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '更新模型状态失败')
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
      provider_type: firstPreset.provider_type,
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
      provider_type: preset.provider_type,
      name: preset.name,
      model_names: [],
    })
  }

  const handleDiscoverPresetModels = async () => {
    if (!selectedPresetId) return
    try {
      const values = await presetForm.validateFields(['api_key', 'provider_type'])
      setDiscoveringPresetModels(true)
      const result = await aiProvidersApi.discoverPresetModels(selectedPresetId, values.api_key, values.provider_type)
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
        provider_type: values.provider_type,
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
      setDiscoveredModelSearch('')
      setSelectedDiscoveredModels(
        result.models.filter((model) => !existingNames.has(model.model_name)).map((model) => model.model_name),
      )
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '获取模型列表失败')
    } finally {
      setDiscoveringProviderId(null)
    }
  }

  const handleSelectFilteredDiscoveredModels = (selected: boolean) => {
    const filteredNames = new Set(filteredSelectableModelNames)
    setSelectedDiscoveredModels((current) => {
      if (!selected) return current.filter((modelName) => !filteredNames.has(modelName))

      const next = new Set([...current, ...filteredSelectableModelNames])
      return (discovery?.models ?? [])
        .map((model) => model.model_name)
        .filter((modelName) => next.has(modelName))
    })
  }

  const handleToggleDiscoveredModel = (modelName: string, selected: boolean) => {
    setSelectedDiscoveredModels((current) => {
      if (!selected) return current.filter((currentName) => currentName !== modelName)

      const next = new Set([...current, modelName])
      return (discovery?.models ?? [])
        .map((model) => model.model_name)
        .filter((currentName) => next.has(currentName))
    })
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

  const modelAccess = (model: AIModelItem) => model.access_mode === 'all' ? (
    <Tag color="green">所有用户</Tag>
  ) : (
    <Space size={4} wrap>
      <Tag color="orange">受限</Tag>
      {model.allowed_user_ids.length > 0 && <Tag>用户 {model.allowed_user_ids.length}</Tag>}
      {model.allowed_group_ids.length > 0 && <Tag>用户组 {model.allowed_group_ids.length}</Tag>}
      {model.allowed_user_ids.length === 0 && model.allowed_group_ids.length === 0 && <Text type="secondary">仅管理员</Text>}
    </Space>
  )

  const modelActions = (provider: AIProviderItem, model: AIModelItem) => (
    <Space size={8} wrap>
      <Button
        size="small"
        icon={<ThunderboltOutlined />}
        loading={testingKey === `${provider.id}-${model.id}`}
        onClick={() => handleTestConnection(provider, model)}
      >
        测试连接
      </Button>
      <Button size="small" onClick={() => openEditModel(model)}>编辑</Button>
      <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => void openModelAccess(model)}>权限</Button>
      <Popconfirm title="确认删除该模型？" onConfirm={() => handleDeleteModel(model)}>
        <Button size="small" danger>删除</Button>
      </Popconfirm>
    </Space>
  )

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
      title: '能力',
      key: 'capabilities',
      width: 170,
      render: (_, model) => (
        <Space size={4} wrap>
          {model.is_multimodal ? <Tag color="green">多模态</Tag> : <Text type="secondary">文本</Text>}
          {model.supports_disabled_thinking ? <Tag color="blue">可不思考</Tag> : <Tag>仅默认思考</Tag>}
          {model.prompt_cache_enabled && <Tag color="gold">提示缓存</Tag>}
        </Space>
      ),
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
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 118,
      render: (isEnabled: boolean, model) => (
        <Switch size="small" aria-label={`切换模型 ${model.display_name} 的启用状态`} checked={isEnabled} onChange={(next) => void handleModelEnabledChange(model, next)} />
      ),
    },
    {
      title: '可用时段',
      key: 'availability_time_ranges',
      width: 190,
      render: (_, model) => <Text type="secondary">{availabilityTimeRangeSummary(model.availability_time_ranges)}</Text>,
    },
    {
      title: '使用范围',
      key: 'access',
      width: 190,
      render: (_, model) => modelAccess(model),
    },
    {
      title: '操作',
      key: 'actions',
      width: 360,
      render: (_, model) => modelActions(provider, model),
    },
  ]

  const selectedPreset = presets.find((item) => item.id === selectedPresetId)
  const installableModels = presetDiscovery?.models ?? []

  return (
    <div className="admin-page admin-models-page">
      <div className="admin-page-header">
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

      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        {providers.map((provider) => (
          <Card
            key={provider.id}
            className="admin-model-provider-card"
            title={
              <Space>
                <Text strong>{provider.name}</Text>
                <Tag color={providerProtocolColor(provider.provider_type)}>
                  {providerProtocolLabel(provider.provider_type)}
                </Tag>
                {!provider.is_enabled && <Tag>已停用</Tag>}
                <Tag>{availabilityTimeRangeSummary(provider.availability_time_ranges)}</Tag>
              </Space>
            }
            extra={
              <Space wrap>
                <Switch
                  size="small"
                  aria-label={`切换 Provider ${provider.name} 的启用状态`}
                  checked={provider.is_enabled}
                  onChange={(isEnabled) => void handleProviderEnabledChange(provider, isEnabled)}
                />
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
            <Tabs activeKey={providerTabs[provider.id] ?? 'chat'} onChange={(key) => setProviderTabs((tabs) => ({ ...tabs, [provider.id]: key as 'chat' | 'image' }))} items={[{ key: 'chat', label: '对话模型' }, { key: 'image', label: `图片模型（${(provider.image_models ?? []).length}）` }]} />
            <div style={{ display: (providerTabs[provider.id] ?? 'chat') === 'chat' ? 'block' : 'none' }}>
            {isCompact ? (
              <div className="responsive-card-list admin-model-card-list" aria-label={`${provider.name} 模型列表`}>
                {provider.models.length === 0 ? (
                  <Empty description="暂无模型，点击下方按钮添加" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : provider.models.map((model) => (
                  <article className="responsive-data-card" key={model.id}>
                    <div className="responsive-data-card-heading">
                      <div>
                        <strong>{model.display_name}</strong>
                        <div className="responsive-data-card-secondary">{model.model_name}</div>
                      </div>
                      <Space size={4}>
                        {model.is_default ? <Tag color="blue">默认</Tag> : (
                          <Button size="small" type="link" onClick={() => handleSetDefault(model)}>设为默认</Button>
                        )}
                        <Switch size="small" aria-label={`切换模型 ${model.display_name} 的启用状态`} checked={model.is_enabled} onChange={(isEnabled) => void handleModelEnabledChange(model, isEnabled)} />
                      </Space>
                    </div>
                    {model.description && <div className="responsive-data-card-description">{model.description}</div>}
                    <div className="responsive-data-card-tags">
                      {Object.keys(model.thinking_config ?? {}).length ? <Tag color="cyan">推理已配置</Tag> : <Tag>自动推理</Tag>}
                       {thinkingEfforts(model.thinking_config).map((effort) => <Tag key={effort}>{effort}</Tag>)}
                       {model.prompt_cache_enabled && <Tag color="gold">提示缓存</Tag>}
                      {!model.is_enabled && <Tag>已停用</Tag>}
                      <Tag>{availabilityTimeRangeSummary(model.availability_time_ranges)}</Tag>
                      {modelAccess(model)}
                    </div>
                    <div className="responsive-data-card-actions">{modelActions(provider, model)}</div>
                  </article>
                ))}
              </div>
            ) : (
              <Table
                rowKey="id"
                size="small"
                columns={modelColumns(provider)}
                dataSource={provider.models}
                pagination={false}
                scroll={{ x: 1500 }}
                locale={{ emptyText: '暂无模型，点击下方按钮添加' }}
              />
            )}
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              style={{ marginTop: 12 }}
              onClick={() => openCreateModel(provider.id)}
            >
              添加模型
            </Button>
            </div>
            <div style={{ marginTop: 24 }}>
              <div style={{ display: (providerTabs[provider.id] ?? 'chat') === 'image' ? 'block' : 'none' }}>
              <Space style={{ marginBottom: 8 }}><Text strong>图片模型</Text><Tag color={provider.image_protocol ? 'green' : 'default'}>{provider.image_protocol || '未配置图片端点'}</Tag></Space>
              {imageModelList(provider)}
              </div>
            </div>
          </Card>
        ))}
      </Space>

      <Modal
        title={editingProvider ? `编辑 Provider：${editingProvider.name}` : '新增 Provider'}
        open={providerModalOpen}
        className="admin-model-modal"
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
            <Select options={PROVIDER_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[{ required: true, message: '请输入 Base URL' }]}
            extra="OpenAI Chat Completions / Responses API 都填到 /v1 级别，例如 https://api.openai.com/v1"
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
          <Form.Item name="image_protocol" label="图片协议（可选）">
            <Select allowClear options={[{ value: 'openai_images', label: 'OpenAI Images' }, { value: 'dashscope_images', label: '阿里百炼文生图' }, { value: 'volcengine_ark_images', label: '火山方舟图片' }]} />
          </Form.Item>
          <Form.Item name="image_base_url" label="图片 Base URL" extra="留空则不启用图片模型。OpenAI Images 可填 API 根地址、/v1、/v1/images 或完整 /v1/images/generations，系统会自动补全正确端点；百炼原生填 https://dashscope.aliyuncs.com/api/v1。">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="is_enabled" label="启用 Provider" valuePropName="checked">
            <Switch />
          </Form.Item>
          <AvailabilityTimeRangesFormItem />
        </Form>
      </Modal>

      <Modal
        title={editingImageModel ? `编辑图片模型：${editingImageModel.display_name}` : '添加图片模型'}
        open={imageModelModalProviderId !== null}
        onCancel={() => setImageModelModalProviderId(null)}
        onOk={handleSaveImageModel}
        confirmLoading={savingImageModel}
        destroyOnHidden
      >
        <Form form={imageModelForm} layout="vertical">
          <Form.Item name="model_name" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}><Input disabled={Boolean(editingImageModel)} placeholder="例如：gpt-image-1" /></Form.Item>
          <Form.Item name="display_name" label="展示名称" rules={[{ required: true, message: '请输入展示名称' }]}><Input placeholder="例如：高质量配图" /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="supported_aspect_ratios" label="支持比例"><Checkbox.Group options={[{ label: '方形', value: 'square' }, { label: '竖图', value: 'portrait' }, { label: '横图', value: 'landscape' }]} /></Form.Item>
          <Form.Item name="supported_qualities" label="质量选项"><Select mode="tags" options={['auto', 'low', 'medium', 'high'].map((value) => ({ label: value, value }))} /></Form.Item>
          <Form.Item name="is_default" valuePropName="checked"><Checkbox>设为默认图片模型</Checkbox></Form.Item>
          <Form.Item name="is_enabled" label="启用图片模型" valuePropName="checked"><Switch /></Form.Item>
          <AvailabilityTimeRangesFormItem />
          <Form.Item name="access_mode" label="使用范围"><Select options={[{ value: 'all', label: '所有有权限用户' }, { value: 'restricted', label: '仅管理员（可在权限中细分）' }]} /></Form.Item>
          <Form.Item name="allowed_user_ids" label="授权用户"><Select mode="multiple" allowClear loading={loadingAccessTargets} options={accessUsers.map((user) => ({ value: user.id, label: `${user.display_name}（${user.username}）` }))} placeholder="选择受限用户" /></Form.Item>
          <Form.Item name="allowed_group_ids" label="授权用户组"><Select mode="multiple" allowClear loading={loadingAccessTargets} options={accessGroups.map((group) => ({ value: group.id, label: `${group.name}（${group.members.length} 人）` }))} placeholder="选择受限用户组" /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="从模型预设添加"
        open={presetModalOpen}
        className="admin-model-modal"
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
            message="预设已包含官方 Base URL 和模型思考参数，可选择接口协议；只需填写 API Key。"
          />
          <Form.Item name="preset_id" label="供应商预设" rules={[{ required: true, message: '请选择供应商' }]}>
            <Select
              options={presets.map((preset) => ({ value: preset.id, label: preset.name }))}
              onChange={handlePresetChange}
            />
          </Form.Item>
          <Form.Item name="provider_type" label="接口协议类型" rules={[{ required: true, message: '请选择接口协议类型' }]}>
            <Select
              options={PROVIDER_TYPE_OPTIONS}
              onChange={() => {
                setPresetDiscovery(null)
                presetForm.setFieldValue('model_names', [])
              }}
            />
          </Form.Item>
          {selectedPreset && (
              <Alert
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
                message={`Base URL：${selectedPreset.base_url}`}
                description={`协议：${providerProtocolLabel(selectedPresetProviderType ?? selectedPreset.provider_type)}；填写 Key 后获取当前可用模型。`}
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
                <Space orientation="vertical" size={8} style={{ width: '100%', maxHeight: 300, overflowY: 'auto' }}>
                  {installableModels.map((model) => (
                    <Checkbox key={model.model_name} value={model.model_name}>
                      {model.display_name}
                      <Text type="secondary" style={{ marginLeft: 8 }}>{model.model_name}</Text>
                       {model.thinking_efforts.length > 0 && <Tag color="cyan" style={{ marginLeft: 8 }}>思考强度</Tag>}
                       {Boolean(model.thinking_config.enabled) && model.thinking_efforts.length === 0 ? <Tag color="cyan" style={{ marginLeft: 8 }}>可开关思考</Tag> : null}
                       <Tag color={model.context_window_source === '供应商接口' ? 'green' : 'gold'} style={{ marginLeft: 8 }}>
                         输入 {formatKTokens(model.context_compaction_threshold_tokens)} / 输出 {formatKTokens(model.max_output_tokens)}
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
        className="admin-model-modal"
        onCancel={() => {
          setDiscoverModalProvider(null)
          setDiscovery(null)
          setDiscoveredModelSearch('')
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
            <Space orientation="vertical" size={10} style={{ width: '100%', marginTop: 12 }}>
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜索模型名称"
                aria-label="搜索模型"
                value={discoveredModelSearch}
                onChange={(event) => setDiscoveredModelSearch(event.target.value)}
              />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <Space size={12}>
                  <Checkbox
                    checked={allFilteredModelsSelected}
                    indeterminate={!allFilteredModelsSelected && someFilteredModelsSelected}
                    disabled={filteredSelectableModelNames.length === 0}
                    onChange={(event) => handleSelectFilteredDiscoveredModels(event.target.checked)}
                  >
                    全选
                  </Checkbox>
                  <Button
                    type="link"
                    size="small"
                    disabled={!someFilteredModelsSelected}
                    onClick={() => handleSelectFilteredDiscoveredModels(false)}
                    style={{ paddingInline: 0 }}
                  >
                    全不选
                  </Button>
                </Space>
                <Text type="secondary">
                  已选 {selectedDiscoveredModels.length} / 可添加 {selectableDiscoveredModelCount}
                </Text>
              </div>
              <div style={{ maxHeight: 350, overflowY: 'auto' }}>
                {filteredDiscoveredModels.length > 0 ? (
                  <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                    {filteredDiscoveredModels.map((model: DiscoveredModelItem) => {
                      const exists = existingDiscoveredModelNames.has(model.model_name)
                      return (
                        <Checkbox
                          key={model.model_name}
                          checked={selectedDiscoveredModelNames.has(model.model_name)}
                          disabled={exists}
                          onChange={(event) => handleToggleDiscoveredModel(model.model_name, event.target.checked)}
                        >
                          {model.display_name}
                          <Text type="secondary" style={{ marginLeft: 8 }}>{model.model_name}</Text>
                          {exists && <Tag style={{ marginLeft: 8 }}>已添加</Tag>}
                          {model.thinking_efforts.length > 0 && <Tag color="cyan" style={{ marginLeft: 8 }}>{model.thinking_efforts.join(' / ')}</Tag>}
                          <Tag color={model.context_window_source === '供应商接口' ? 'green' : 'gold'} style={{ marginLeft: 8 }}>
                            输入 {formatKTokens(model.context_compaction_threshold_tokens)} / 输出 {formatKTokens(model.max_output_tokens)}
                          </Tag>
                        </Checkbox>
                      )
                    })}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的模型" />
                )}
              </div>
            </Space>
          </>
        )}
      </Modal>

      <Modal
        title={editingModel ? `编辑模型：${editingModel.display_name}` : '添加模型'}
        open={modelModalProviderId !== null}
        className="admin-model-modal admin-model-editor-modal"
        width={1120}
        onCancel={() => {
          setModelModalProviderId(null)
          setEditingModel(null)
        }}
        onOk={handleSaveModel}
        confirmLoading={savingModel}
        destroyOnHidden
      >
        <Form form={modelForm} layout="vertical" className="model-editor-form">
          <div className="model-editor-form-grid">
            <div>
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
              <div className="model-editor-token-grid">
                <Form.Item
                  name="input_limit_k"
                  label="最大输入（K tokens）"
                  rules={[{ required: true, message: '请输入最大输入' }]}
                >
                  <InputNumber min={1} max={1999} step={1} precision={0} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item
                  name="output_limit_k"
                  label="单次最大输出（K tokens）"
                  rules={[{ required: true, message: '请输入最大输出' }]}
                >
                  <InputNumber min={1} max={1000} step={1} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </div>
              {automaticTokenBudget && (
                <Space size={[8, 8]} wrap className="model-editor-automatic-budget" aria-label="自动配置">
                  <Text type="secondary">自动配置</Text>
                  <Tag>压缩阈值 {formatKTokens(automaticTokenBudget.context_compaction_threshold_tokens)}</Tag>
                  <Tag>触发后整理为精简任务记忆，按需读取历史</Tag>
                  <Tag>工具预览 {formatKTokens(automaticTokenBudget.tool_result_max_tokens)}</Tag>
                </Space>
              )}
            </div>
            <div>
              <div className="model-editor-switch-grid">
                <Form.Item name="is_default" label="设为默认模型" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item name="is_enabled" label="启用模型" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </div>
              <AvailabilityTimeRangesFormItem />
              <Form.Item
                name="is_multimodal"
                label="支持图片交互"
                valuePropName="checked"
                extra="开启后，用户可在聊天输入框选择或粘贴图片。请仅为确认支持视觉输入的模型开启。"
              >
                <Switch />
              </Form.Item>
              <Form.Item
                name="supports_disabled_thinking"
                label="支持不思考"
                valuePropName="checked"
                extra="关闭后，编辑器不会发送禁止思考参数，已保存的旧请求也会自动按默认思考设置执行。"
              >
                <Switch />
              </Form.Item>
            </div>
          </div>
          <Form.Item
            name="thinking_efforts"
            label="思考强度"
            extra={isAnthropicProvider
              ? 'Claude 通过 Anthropic adaptive thinking 与 output_config.effort 传递强度。'
              : isGeminiNativeProvider
                ? 'Gemini 2.5 使用 thinkingBudget；Gemini 3 使用 thinkingLevel。'
                : 'OpenAI 兼容协议通过 reasoning_effort 传递极简、低、中、高、超高或最大强度。'}
          >
            <Checkbox.Group
            options={isAnthropicProvider
              ? THINKING_EFFORT_OPTIONS.filter((option) => option.value !== 'minimal')
              : isGeminiNativeProvider
                ? THINKING_EFFORT_OPTIONS.filter((option) => ['minimal', 'low', 'medium', 'high', 'max'].includes(option.value))
              : THINKING_EFFORT_OPTIONS}
            />
          </Form.Item>
          <Form.Item
            name="default_thinking_effort"
            label="默认思考强度"
            extra="聊天设置选择“默认”时使用；自动会沿用高级 JSON 的 enabled 参数。"
          >
            <Select
              options={[
                { value: 'auto', label: '自动（使用 enabled 参数）' },
                ...defaultThinkingEffortOptions,
              ]}
            />
          </Form.Item>
          {supportsPromptCache && (
            <Form.Item
              name="prompt_cache_enabled"
              label="提示缓存优化"
              valuePropName="checked"
              extra="请在当前模型和网关验证后开启。按供应商协议启用稳定缓存键或原生缓存边界，分离固定规则与最新状态，并保留工具历史的稳定前缀；关闭后恢复原提示传递方式。缓存命中由上游服务决定，不会复用旧回答。"
            >
              <Switch />
            </Form.Item>
          )}
          <Form.Item
            name="thinking_config_text"
            label="高级思考参数 JSON（可选）"
            extra={isAnthropicProvider
              ? 'Claude 示例：{"enabled":{"thinking":{"type":"adaptive"},"effort":"medium"},"disabled":{},"efforts":{"xhigh":{"thinking":{"type":"adaptive"},"effort":"xhigh"}}}'
              : isGeminiNativeProvider
                ? 'Gemini 示例：{"enabled":{"thinkingConfig":{"includeThoughts":true,"thinkingBudget":-1}},"disabled":{"thinkingConfig":{"includeThoughts":false,"thinkingBudget":0}}}'
                : 'OpenAI 示例：{"enabled":{"reasoning_effort":"medium"},"disabled":{"reasoning_effort":"none"},"efforts":{"high":{"reasoning_effort":"high"}}}'}
          >
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 8 }}
            placeholder={isAnthropicProvider
              ? '例如：{"enabled":{"thinking":{"type":"adaptive"},"effort":"medium"}}'
              : isGeminiNativeProvider
                ? '例如：{"enabled":{"thinkingConfig":{"includeThoughts":true,"thinkingBudget":-1}}}'
                : '例如：{"enabled":{"reasoning_effort":"medium"},"disabled":{"reasoning_effort":"none"}}'}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={accessModalModel ? `模型权限：${accessModalModel.display_name}` : '模型权限'}
        open={Boolean(accessModalModel)}
        className="admin-model-modal"
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
