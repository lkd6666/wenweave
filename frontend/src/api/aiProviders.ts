import { api } from './client'
import type {
  AIImageModelItem,
  AIModelItem,
  AIProviderItem,
  AvailabilityTimeRange,
  ModelDiscoveryResult,
  ProviderPresetItem,
  ProviderType,
} from '../types'

export interface CreateProviderPayload {
  name: string
  provider_type: ProviderType
  base_url: string
  api_key: string
  is_enabled?: boolean
  availability_time_ranges?: AvailabilityTimeRange[]
}

export interface UpdateProviderPayload {
  name?: string
  provider_type?: ProviderType
  base_url?: string
  api_key?: string
  image_protocol?: '' | 'openai_images' | 'dashscope_images' | 'volcengine_ark_images'
  image_base_url?: string
  is_enabled?: boolean
  availability_time_ranges?: AvailabilityTimeRange[]
}

export interface CreateImageModelPayload {
  model_name: string
  display_name: string
  description?: string
  supported_aspect_ratios?: Array<'square' | 'portrait' | 'landscape'>
  supported_qualities?: string[]
  is_default?: boolean
  is_enabled?: boolean
  availability_time_ranges?: AvailabilityTimeRange[]
  access_mode?: 'all' | 'restricted'
  allowed_user_ids?: number[]
  allowed_group_ids?: number[]
}

export interface UpdateImageModelPayload extends Partial<Omit<CreateImageModelPayload, 'model_name'>> {
  access_mode?: 'all' | 'restricted'
  allowed_user_ids?: number[]
  allowed_group_ids?: number[]
}

export interface CreateModelPayload {
  model_name: string
  display_name: string
  description: string
  context_window_tokens: number
  context_compaction_threshold_tokens: number
  max_output_tokens: number
  tool_result_max_tokens: number
  is_default: boolean
  is_enabled: boolean
  availability_time_ranges?: AvailabilityTimeRange[]
  is_multimodal: boolean
  supports_disabled_thinking: boolean
  default_thinking_effort: 'auto' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  prompt_cache_enabled: boolean
  thinking_config?: Record<string, unknown>
}

export interface UpdateModelPayload {
  display_name?: string
  description?: string
  context_window_tokens?: number
  context_compaction_threshold_tokens?: number
  max_output_tokens?: number
  tool_result_max_tokens?: number
  is_default?: boolean
  is_enabled?: boolean
  availability_time_ranges?: AvailabilityTimeRange[]
  is_multimodal?: boolean
  supports_disabled_thinking?: boolean
  default_thinking_effort?: 'auto' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  prompt_cache_enabled?: boolean
  thinking_config?: Record<string, unknown>
  access_mode?: 'all' | 'restricted'
  allowed_user_ids?: number[]
  allowed_group_ids?: number[]
}

export interface InstallPresetPayload {
  api_key: string
  image_protocol?: '' | 'openai_images' | 'dashscope_images' | 'volcengine_ark_images'
  image_base_url?: string
  provider_type: ProviderType
  model_names: string[]
  model_capabilities?: Array<{
    model_name: string
    display_name: string
    description: string
    context_window_tokens: number
    context_compaction_threshold_tokens: number
    max_output_tokens: number
    tool_result_max_tokens: number
    is_multimodal: boolean
    supports_disabled_thinking: boolean
    thinking_config: Record<string, unknown>
    thinking_efforts: string[]
  }>
  name?: string
  set_as_default: boolean
}

export interface BulkModelPayload {
  models: Array<{
    model_name: string
    display_name: string
    description: string
    context_window_tokens: number
    context_compaction_threshold_tokens: number
    max_output_tokens: number
    tool_result_max_tokens: number
    is_enabled?: boolean
    availability_time_ranges?: AvailabilityTimeRange[]
    is_multimodal: boolean
    supports_disabled_thinking: boolean
    thinking_config: Record<string, unknown>
  }>
}

export interface BulkModelResult {
  created: AIModelItem[]
  skipped_model_names: string[]
}

export interface TestConnectionResult {
  success: boolean
  message: string
  latency_ms: number | null
}

export const aiProvidersApi = {
  list: () => api.get<AIProviderItem[]>('/ai-providers'),
  listPresets: () => api.get<ProviderPresetItem[]>('/ai-providers/presets'),
  discoverPresetModels: (presetId: string, apiKey: string, providerType: ProviderType) =>
    api.post<ModelDiscoveryResult>(`/ai-providers/presets/${presetId}/discover-models`, {
      api_key: apiKey,
      provider_type: providerType,
    }),
  installPreset: (presetId: string, payload: InstallPresetPayload) =>
    api.post<AIProviderItem>(`/ai-providers/presets/${presetId}/install`, payload),
  create: (payload: CreateProviderPayload) => api.post<AIProviderItem>('/ai-providers', payload),
  update: (id: number, payload: UpdateProviderPayload) => api.patch<AIProviderItem>(`/ai-providers/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/ai-providers/${id}`),
  testConnection: (id: number, modelName: string) =>
    api.post<TestConnectionResult>(`/ai-providers/${id}/test`, { model_name: modelName }),
  createModel: (providerId: number, payload: CreateModelPayload) =>
    api.post<AIModelItem>(`/ai-providers/${providerId}/models`, payload),
  discoverModels: (providerId: number) =>
    api.post<ModelDiscoveryResult>(`/ai-providers/${providerId}/discover-models`),
  createModelsBulk: (providerId: number, payload: BulkModelPayload) =>
    api.post<BulkModelResult>(`/ai-providers/${providerId}/models/bulk`, payload),
  updateModel: (modelId: number, payload: UpdateModelPayload) =>
    api.patch<AIModelItem>(`/ai-providers/models/${modelId}`, payload),
  removeModel: (modelId: number) => api.delete<void>(`/ai-providers/models/${modelId}`),
  createImageModel: (providerId: number, payload: CreateImageModelPayload) => api.post<AIImageModelItem>(`/ai-providers/${providerId}/image-models`, payload),
  updateImageModel: (modelId: number, payload: UpdateImageModelPayload) => api.patch<AIImageModelItem>(`/ai-providers/image-models/${modelId}`, payload),
  removeImageModel: (modelId: number) => api.delete<void>(`/ai-providers/image-models/${modelId}`),
}
