export type UserRole = 'admin' | 'user'

export interface User {
  id: number
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface UserGroup {
  id: number
  name: string
  members: Array<Pick<User, 'id' | 'username' | 'display_name' | 'is_active'>>
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export type ProviderType = 'openai_compatible' | 'anthropic'

export interface AIModelItem {
  id: number
  provider_id: number
  model_name: string
  display_name: string
  description: string
  context_window_tokens: number
  context_compaction_threshold_tokens: number
  max_output_tokens: number
  tool_result_max_tokens: number
  is_default: boolean
  access_mode: 'all' | 'restricted'
  allowed_user_ids: number[]
  allowed_group_ids: number[]
  thinking_config: Record<string, unknown>
}

export interface AIProviderItem {
  id: number
  name: string
  provider_type: ProviderType
  base_url: string
  api_key_masked: string
  models: AIModelItem[]
}

export interface ModelPresetItem {
  model_name: string
  display_name: string
  description: string
  context_window_tokens: number
  context_compaction_threshold_tokens: number
  max_output_tokens: number
  tool_result_max_tokens: number
  thinking_config: Record<string, unknown>
  thinking_efforts: string[]
}

export interface ProviderPresetItem {
  id: string
  name: string
  provider_type: ProviderType
  base_url: string
  api_key_hint: string
  models: ModelPresetItem[]
}

export interface DiscoveredModelItem extends ModelPresetItem {
  source: string
  context_window_source: string
}

export interface ModelDiscoveryResult {
  models: DiscoveredModelItem[]
  source: string
  warning: string | null
}

export interface StorageConfigItem {
  configured: boolean
  endpoint: string
  bucket: string
  access_key_id: string
  access_key_secret_masked: string
  custom_domain: string
}

export type DocumentSourceType = 'blank' | 'pdf' | 'word'
export type VisibilityMode = 'all' | 'restricted'

export interface VisibilitySettings {
  visibility_mode: VisibilityMode
  allowed_user_ids: number[]
  allowed_group_ids: number[]
}

export interface VisibilityTargets {
  users: Array<Pick<User, 'id' | 'username' | 'display_name' | 'is_active'>>
  groups: Array<Pick<UserGroup, 'id' | 'name'>>
}

export interface UserReference {
  id: number
  username: string
  display_name: string
}

export interface DocumentGroup extends VisibilitySettings {
  id: number
  name: string
  created_by: UserReference | null
  created_at: string
  updated_at: string
  last_modified_by: UserReference | null
}

export interface DocumentSummary extends VisibilitySettings {
  id: number
  title: string
  source_type: DocumentSourceType
  group_id: number | null
  created_by: UserReference | null
  last_modified_by: UserReference | null
  created_at: string
  updated_at: string
  has_source_file: boolean
}

export interface DocumentDetail extends DocumentSummary {
  current_html: string
  messages?: ChatMessageItem[]
}

export interface LayoutReferenceSummary {
  block_count: number
  image_slots: number
  extracted_from: string
}

export interface LayoutReferencePreview {
  reference_id: string
  canonical_url: string
  title: string
  site_name: string
  preview_html: string
  summary: LayoutReferenceSummary
  warning: string | null
}

export type DocumentVersionSource = 'initial' | 'manual' | 'ai' | 'restore'

export interface DocumentVersionSummary {
  id: number
  version_number: number
  title: string
  source: DocumentVersionSource
  label: string
  created_by: UserReference | null
  created_at: string
}

export interface DocumentVersionDetail extends DocumentVersionSummary {
  html: string
}

export type ChatRole = 'user' | 'assistant' | 'tool'

export type AgentRunStatus = 'pending' | 'running' | 'cancelling' | 'completed' | 'cancelled' | 'failed'

export type ToolExecutionStatus = 'running' | 'success' | 'error'

export type ReasoningStatus = 'idle' | 'thinking' | 'complete' | 'unavailable'

export interface ReasoningTrace {
  status: ReasoningStatus
  content: string
  detail: string
}

export interface ReadRange {
  scope: 'whole' | 'range'
  start_line: number
  end_line: number
  total_lines: number
}

export interface ChangeSummary {
  added_lines: number
  removed_lines: number
  changed_lines: number
  diff_preview: string
  diff_truncated: boolean
}

export interface ToolExecution {
  id: string
  name: string
  arguments: Record<string, unknown>
  status: ToolExecutionStatus
  preparing?: boolean
  result?: string | null
  html_changed: boolean
  activity?: ToolActivity | null
  read_range?: ReadRange | null
  change_summary?: ChangeSummary | null
}

export interface ToolActivityTarget {
  block_id?: string
  tag?: string
  path?: string
  text?: string
  before?: string
  after?: string
}

export interface ToolActivity {
  kind: 'map' | 'search' | 'read' | 'edit' | 'check' | 'reference' | 'error' | string
  summary: string
  query?: string
  revision?: string
  operation_count?: number
  character_delta?: number
  targets?: ToolActivityTarget[]
  details?: Record<string, unknown>
  html_validation?: { valid?: boolean; errors?: string[] }
}

export interface ChatContextStats {
  used_tokens: number
  max_tokens: number
  usable_tokens: number
  usage_percent: number
  is_estimate: boolean
  state: string
  breakdown: Record<string, number>
  tool_calls_count: number
  tool_summary_replayed_count: number
  tool_compact_replayed_count: number
  tool_full_replayed_count: number
  tokens_saved: number
  context_policy: string
  max_output_tokens: number
  tool_result_max_tokens: number
  active_context_threshold_tokens: number
  budget_multiplier: number
  requires_compaction: boolean
  can_fit_after_compaction: boolean
  overflow_tokens: number
  projected_used_tokens: number
}

export type AssistantTurnBlockType = 'thought' | 'tool' | 'content'

export interface AssistantTurnBlock {
  id: string
  type: AssistantTurnBlockType
  state: 'active' | 'done'
  content: string
  duration_ms?: number | null
  started_at_ms?: number
  tool: ToolExecution | null
}

export interface ChatMessageItem {
  id: number
  role: ChatRole
  content: string
  tool_calls: ToolExecution[]
  reasoning_trace: ReasoningTrace
  turn_blocks: AssistantTurnBlock[]
  selected_elements: SelectedElementContext[]
  can_revert: boolean
  created_at: string
}

export interface SelectedElementContext {
  selector: string
  tag_name: string
  html: string
  text: string
}

export interface ComplianceReport {
  removedClasses: string[]
  keptClasses: string[]
  removedIdAttributes: string[]
  riskStyleHints: string[]
  removedSvgBrs: number
  hasSvg: boolean
  oversizedSvgBlocks: number[]
  maxNestingDepth: number
  willFlattenNesting: boolean
  emptyNodeSuspects: string[]
  hasError: boolean
  hasWarning: boolean
}
