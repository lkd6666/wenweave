export type UserRole = 'admin' | 'user'

export type OperationLogStatus = 'succeeded' | 'failed' | 'cancelled'

export interface OperationLog {
  id: number
  actor_user_id: number | null
  actor_username: string
  actor_display_name: string
  action: string
  resource_type: string
  resource_id: string
  resource_name: string
  document_id: number | null
  session_id: number | null
  status: OperationLogStatus
  summary: string
  error_summary: string
  details: Record<string, unknown>
  request_id: string
  client_ip: string
  user_agent: string
  created_at: string
}

export interface OperationLogListResult {
  items: OperationLog[]
  total: number
  page: number
  page_size: number
}

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

export interface AppBranding {
  system_name: string
  logo_url: string | null
  logo_content_type: string
  favicon_url: string | null
  favicon_content_type: string
  updated_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export type ProviderType = 'openai_compatible' | 'openai_responses' | 'anthropic'

export interface AvailabilityTimeRange {
  start: string
  end: string
}

export interface ArticleTypographySettings {
  horizontal_padding_px: number
  paragraph_spacing_px: number
  font_size_px: number
  line_height_em: number
  letter_spacing_px: number
  text_indent_em: number
  text_color: string
  updated_at: string | null
}

export interface AIModelItem {
  id: number
  provider_id: number
  provider_name: string
  model_name: string
  display_name: string
  description: string
  context_window_tokens: number
  context_compaction_threshold_tokens: number
  max_output_tokens: number
  tool_result_max_tokens: number
  is_default: boolean
  is_enabled: boolean
  availability_time_ranges: AvailabilityTimeRange[]
  is_multimodal: boolean
  supports_disabled_thinking: boolean
  default_thinking_effort: 'auto' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  prompt_cache_enabled: boolean
  access_mode: 'all' | 'restricted'
  allowed_user_ids: number[]
  allowed_group_ids: number[]
  thinking_config: Record<string, unknown>
}

export type WorkboardPeriod = 'today' | '7d' | '30d' | 'month'

export interface WorkboardTokenStats {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cache_hit_rate: number | null
  usage_unreported_calls: number
}

export interface WorkboardModelRank extends WorkboardTokenStats {
  model_id: number
  display_name: string
  call_count: number
}

export interface WorkboardUserRank extends WorkboardTokenStats {
  user_id: number | null
  display_name: string
  username: string
  call_count: number
}

export interface WorkboardTweetActivity {
  total_documents: number
  created_documents: number
  active_creators: number
  ai_versions: number
  manual_versions: number
}

export interface WorkboardOverview extends WorkboardTokenStats {
  model_call_count: number
  active_users: number
}

export interface WorkboardData {
  period: WorkboardPeriod
  start_at: string
  end_at: string
  overview: WorkboardOverview
  model_ranking: WorkboardModelRank[]
  user_ranking: WorkboardUserRank[]
  tweet_activity: WorkboardTweetActivity
}

export interface AIProviderItem {
  id: number
  name: string
  provider_type: ProviderType
  base_url: string
  image_protocol: '' | 'openai_images' | 'dashscope_images' | 'volcengine_ark_images'
  image_base_url: string
  is_enabled: boolean
  availability_time_ranges: AvailabilityTimeRange[]
  api_key_masked: string
  models: AIModelItem[]
  image_models: AIImageModelItem[]
}

export interface AIImageModelItem {
  id: number
  provider_id: number
  model_name: string
  display_name: string
  description: string
  supported_aspect_ratios: Array<'square' | 'portrait' | 'landscape'>
  supported_qualities: string[]
  is_default: boolean
  is_enabled: boolean
  availability_time_ranges: AvailabilityTimeRange[]
  access_mode: 'all' | 'restricted'
  allowed_user_ids: number[]
  allowed_group_ids: number[]
  operations: Array<'generate' | 'edit'>
  adapter_config?: Record<string, unknown>
}

export interface ModelPresetItem {
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
  provider: 'aliyun_oss' | 'tencent_cos' | 'huawei_obs' | 'volcengine_tos' | 'qiniu_kodo'
  endpoint: string
  bucket: string
  access_key_id: string
  access_key_secret_masked: string
  region_or_zone: string
  upload_endpoint: string
  custom_domain: string
}

export type DocumentSourceType = 'blank' | 'pdf' | 'word' | 'markdown' | 'web'
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
  wechat_cover_url: string
  is_ai_editing: boolean
  created_by: UserReference | null
  last_modified_by: UserReference | null
  created_at: string
  updated_at: string
  has_source_file: boolean
}

export interface DocumentDetail extends DocumentSummary {
  current_html: string
  wechat_metadata: WeChatArticleMetadata
  messages?: ChatMessageItem[]
}

export interface DocumentShareRecord {
  id: number
  document_id: number | null
  document_title: string
  token: string
  created_by_id: number | null
  created_by_username: string
  created_by_display_name: string
  expires_at: string
  revoked_at: string | null
  revoked_by_id: number | null
  revoked_by_username: string
  revoked_by_display_name: string
  created_at: string
  is_active: boolean
  visit_count: number
  last_visited_at: string | null
}

export interface DocumentShareVisit {
  id: number
  ip_address: string
  user_agent: string
  referer: string
  first_seen_at: string
  last_seen_at: string
}

export interface DocumentShareVisitList {
  items: DocumentShareVisit[]
  total: number
  page: number
  page_size: number
}

export interface WeChatArticleMetadata {
  title: string
  author: string
  digest: string
  content_source_url: string
  cover_url: string
  pic_crop_235_1: string
  pic_crop_1_1: string
  need_open_comment: boolean
  only_fans_can_comment: boolean
}

export interface WeChatAccount {
  id: number
  name: string
  app_id: string
  app_secret_masked: string
  allowed_user_ids: number[]
  allowed_group_ids: number[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface WeChatAvailableAccount {
  id: number
  name: string
}

export interface WeChatDraftRecord {
  id: number
  account_id: number
  account_name: string
  status: 'succeeded' | 'failed'
  media_id: string | null
  sync_mode: 'create' | 'update'
  article_title: string
  error_code: number | null
  error_message: string
  created_by_name: string | null
  created_at: string
}

export interface WeChatDraftTarget {
  media_id: string
  title: string
  update_time: number | null
  article_count: number
}

export interface LayoutReferenceSummary {
  block_count: number
  image_slots: number
  image_assets: number
  extracted_from: string
}

export interface LayoutReferenceAssetPreview {
  asset_id: string
  preview_url: string
  content_type: string
  width: number
  height: number
  usage_count: number
  role: string
  default_selected: boolean
}

export interface LayoutReferencePreview {
  reference_id: string
  canonical_url: string
  title: string
  site_name: string
  preview_html: string
  assets: LayoutReferenceAssetPreview[]
  summary: LayoutReferenceSummary
  requires_asset_reuse_confirmation: boolean
  warning: string | null
}

export interface LayoutCaptureSession {
  id: string
  token: string
  canonical_url: string
  expires_at: string
  purpose: 'layout_reference' | 'web_article_import'
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

export type AgentRunStatus = 'pending' | 'running' | 'waiting_for_input' | 'cancelling' | 'completed' | 'cancelled' | 'failed'

export type ToolExecutionStatus = 'running' | 'waiting' | 'success' | 'error' | 'interrupted'

export interface ChatUserQuestionOption {
  id: string
  label: string
  description: string
  style_html: string | null
}

export interface ChatUserQuestion {
  id: string
  run_id: string
  question: string
  options: ChatUserQuestionOption[]
  allow_multiple: boolean
  include_style: boolean
  timeout_at?: string | null
  inactivity_seconds?: number
  timeline?: {
    tool_calls?: ToolExecution[]
    turn_blocks?: AssistantTurnBlock[]
    reasoning?: ReasoningTrace
  }
  event_sequence?: number
}

export interface PendingChatUserQuestion {
  document_id: number
  document_title: string
  session_id: number
  created_at: string
  question: ChatUserQuestion
}

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
  argument_tokens?: number
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

export interface TaskPlanItem {
  step: string
  status: 'pending' | 'in_progress' | 'done'
}

export interface HtmlValidationIssue {
  code: string
  message: string
  line?: number | null
  column?: number | null
  tag?: string
  severity?: 'error' | 'warning'
}

export interface HtmlValidationReport {
  valid?: boolean
  errors?: string[]
  warnings?: string[]
  issues?: HtmlValidationIssue[]
}

export interface ToolActivity {
  kind: 'map' | 'search' | 'read' | 'edit' | 'check' | 'plan' | 'reference' | 'error' | string
  summary: string
  query?: string
  revision?: string
  operation_count?: number
  character_delta?: number
  targets?: ToolActivityTarget[]
  details?: Record<string, unknown>
  html_validation?: HtmlValidationReport
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
  event_count?: number
  replayed_event_count?: number
  compaction_strategy?: string
  compaction_target_tokens?: number
  tokens_saved: number
  context_policy: string
  max_output_tokens: number
  tool_result_max_tokens: number
  effective_tool_preview_tokens?: number
  stored_tool_output_count?: number
  stored_tool_output_bytes?: number
  stored_tool_output_tokens?: number
  tool_output_retention_days?: number
  active_context_threshold_tokens: number
  budget_multiplier: number
  requires_compaction: boolean
  can_fit_after_compaction: boolean
  overflow_tokens: number
  projected_used_tokens: number
  conversation_tokens?: number
  conversation_message_count?: number
  compacted_history_tokens?: number
  compacted_history_message_count?: number
  runtime_context_state?: string
  runtime_input_tokens?: number
  runtime_original_tokens?: number
  runtime_digested_cycles?: number
  runtime_dropped_cycles?: number
  runtime_projected_tokens?: number
  runtime_visible_output_tokens?: number
  runtime_reasoning_tokens?: number
  runtime_tool_argument_tokens?: number
  last_model_output_tokens?: number
  last_model_cached_input_tokens?: number
  ledger_tokens?: number
  raw_input_tokens?: number
  compiled_input_tokens?: number
  raw_breakdown?: Record<string, number>
  snapshot_id?: number
  snapshot_covered_event_count?: number
  hot_event_count?: number
  cold_event_count?: number
  tool_output_retention_mode?: 'session' | 'ttl' | string
  run_summarized_cycles?: number
  runtime_summary_tokens?: number
  snapshot_source_event_count?: number
  snapshot_prefix_valid?: boolean
  archived_branch_count?: number
  compaction_location?: string
  thinking_capability_fallback?: {
    model_id: number
    reason: string
    fallback_mode: 'auto'
    message: string
  } | null
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
  created_by: UserReference | null
  model_usage: ChatMessageModelUsage | null
  image_attachments: ChatImageAttachment[]
  tool_calls: ToolExecution[]
  reasoning_trace: ReasoningTrace
  turn_blocks: AssistantTurnBlock[]
  selected_elements: SelectedElementContext[]
  template_refs: Array<{ id: number; name: string }>
  can_revert: boolean
  created_at: string
}

export interface ChatMessageModelUsage {
  model_names: string[]
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  cache_hit_rate?: number
  call_count?: number
  usage_reported: boolean
}

export interface ChatHistoryArchive {
  id: number
  source_message_id: number
  reason: string
  message_count: number
  created_at: string
}

export interface ChatImageAttachment {
  id: string
  filename: string
  content_type: string
  size: number
  preview_url: string
}

export type LayoutReferenceImitationStrength = 'style' | 'structure' | 'maximum'

export interface ChatSessionItem {
  id: number
  title: string
  is_archived: boolean
  context_start_message_id: number
  visible_message_count: number
  hidden_message_count: number
  layout_reference: {
    title: string
    site_name: string
    extracted_from: string
    block_count: number
    image_assets: number
    imitation_strength: LayoutReferenceImitationStrength
  } | null
  attached_templates: TemplateItem[]
  theme_context: {
    proposal_id: string
    theme_key: string
    theme_name: string
    apply_mode: GzhApplyMode
    status: string
  } | null
  image_model_id: number | null
  created_at: string
  updated_at: string
}

export type ImageGenerationStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type ImageGenerationPurpose = 'cover' | 'body'
export type ImageGenerationOperation = 'generate' | 'edit'

export interface PreviewImageTarget {
  sourceUrl: string
  imageIndex: number
  alt: string
}

export interface GeneratedImageAsset {
  id: string
  generation_id: string
  url: string
  content_type: string
  size: number
  width: number
  height: number
  revised_prompt: string
  library_asset_id: string
  library_url: string
  is_applied: boolean
  is_currently_applied: boolean
  applied_at: string | null
  created_at: string
}

export interface ImageGenerationItem {
  id: string
  document_id: number
  session_id: number | null
  model_id: number
  source: 'editor' | 'agent'
  purpose: ImageGenerationPurpose
  operation: ImageGenerationOperation
  prompt: string
  quantity: number
  aspect_ratio: 'square' | 'portrait' | 'landscape'
  quality: string
  timeout_seconds: number
  anchor_block_id: string
  source_image_url: string
  source_image_hash: string
  target_image_index: number
  direct_insert: boolean
  status: ImageGenerationStatus
  error_message: string
  usage: Record<string, unknown>
  created_at: string
  updated_at: string
  finished_at: string | null
  assets: GeneratedImageAsset[]
}

export type ImageSearchOrientation = 'any' | 'landscape' | 'portrait' | 'square'

export interface ImageSearchCandidate {
  id: string
  token: string
  preview_url: string
  title: string
  source_page_url: string
  engine: string
  width: number | null
  height: number | null
  format: string
}

export interface ImageSearchResult {
  query: string
  page: number
  next_page: number | null
  notice: string
  items: ImageSearchCandidate[]
}

export type ImageLibraryMode = 'personal' | 'shared'
export type ImageLibrarySource = 'upload' | 'ai' | 'search'

export interface ImageLibraryAsset {
  id: string
  owner_id: number
  owner_name: string
  document_id: number | null
  generation_id: string
  generated_asset_id: string
  name: string
  source: ImageLibrarySource
  url: string
  content_type: string
  size: number
  width: number
  height: number
  is_shared: boolean
  can_manage: boolean
  created_at: string
  updated_at: string
}

export interface ImageLibraryListResult {
  items: ImageLibraryAsset[]
  total: number
  page: number
  page_size: number
  mode: ImageLibraryMode
}

export interface SelectedElementFingerprint {
  tag_name: string
  stable_attributes: Record<string, string>
  text: string
}

export interface SelectedElementLocator {
  path: string
  parent_path: string
  sibling_index: number
  fingerprint: SelectedElementFingerprint
}

export interface SelectedElementContext {
  selector: string
  tag_name: string
  html: string
  text: string
  locator?: SelectedElementLocator
}

export interface ComplianceReport {
  removedClasses: string[]
  keptClasses: string[]
  removedIdAttributes: string[]
  riskStyleHints: string[]
  bannedTags: string[]
  consecutiveBrRuns: number[]
  svgIdAttributes: string[]
  imageIssues: string[]
  removedSvgBrs: number
  hasSvg: boolean
  oversizedSvgBlocks: number[]
  maxNestingDepth: number
  willFlattenNesting: boolean
  emptyNodeSuspects: string[]
  diagnostics: ComplianceDiagnostic[]
  hasError: boolean
  hasWarning: boolean
  gzhStrict?: GzhStrictReport | null
}

export interface GzhStrictReport {
  hasError: boolean
  hasWarning: boolean
  errors: string[]
  warnings: string[]
  leafCount: number
}

export type GzhApplyMode = 'full' | 'restrained' | 'key_components'
export type GzhThemeStatus = 'draft' | 'published' | 'archived'

export interface GzhThemeItem {
  id: number | null
  key: string
  name: string
  description: string
  scenarios: string[]
  accent_color: string
  is_builtin: boolean
  status: GzhThemeStatus
  preview_available: boolean
  active_version_id?: number | null
  active_version?: number | null
}

export interface GzhThemeComponent {
  id: string
  name: string
  category: string
  source: 'theme' | 'common'
}

export interface GzhThemeRecipe {
  id: string
  article_type: string
  core_component_ids: string[]
  decorative_component_ids: string[]
}

export interface GzhThemeManifest {
  schema_version: number
  source_checksum: string
  design_tokens: Array<{ name: string; value: string }>
  components: GzhThemeComponent[]
  recipes: GzhThemeRecipe[]
  structural_component_ids: string[]
  recommended_recipe_id: string
}

export interface GzhThemeCreatePayload {
  slug: string
  name: string
  description: string
  scenarios: string[]
  accent_color: string
  source_markdown: string
  preview_html: string
}

export interface GzhThemeVersion {
  id: number
  theme_id: number
  version: number
  status: GzhThemeStatus
  generation_brief: string
  validation: Array<{ level: string; message: string }>
  component_count: number
  recipe_count: number
  created_at: string
  published_at: string | null
}

export interface GzhThemeManagerItem extends GzhThemeItem {
  id: number
  versions: GzhThemeVersion[]
}

export interface GzhThemeReferenceAsset {
  id: string
  filename: string
  content_type: string
  size: number
  expires_at: string
}

export interface GzhThemeGeneration {
  id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'saved'
  theme_id: number | null
  name_hint: string
  slug_hint: string
  brief: string
  validation: Array<{ level: string; message: string }>
  error_message: string
  preview_html: string
  component_count: number
  recipe_count: number
  progress: {
    stage: string
    current: number
    total: number
    message: string
  }
  created_at: string
  finished_at: string | null
}

export interface GzhThemeProposal {
  id: string
  theme_key: string
  theme_name: string
  apply_mode: GzhApplyMode
  user_instructions: string
  article_type: string
  recipe_id: string
  selected_component_ids: string[]
  status: string
  expires_at: string
}

export type TemplateSourceType = 'rich_paste' | 'source' | 'ai'
export type TemplateGenerationStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'saved'

export interface TemplateCategory {
  id: number
  name: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface TemplateImageWarning {
  source: string
  message: string
}

export interface TemplateItem {
  id: number
  name: string
  category_id: number | null
  html: string
  source_type: TemplateSourceType
  image_warnings: TemplateImageWarning[]
  created_at: string
  updated_at: string
}

export interface TemplateImageLocalizationItem {
  template_id: number
  name: string
  status: 'updated' | 'unchanged' | 'failed'
  localized_count: number
  message: string
}

export interface TemplateImageLocalizationResult {
  items: TemplateImageLocalizationItem[]
  updated_count: number
  failed_count: number
  localized_count: number
}

export interface TemplateGeneration {
  id: string
  status: TemplateGenerationStatus
  prompt: string
  output_html: string
  error_message: string
  created_at: string
  finished_at: string | null
}

export interface ComplianceDiagnostic {
  code: string
  severity: 'error' | 'warning' | 'info'
  path: string
  line: number
  column: number
  snippet: string
  message: string
  consequence: string
  suggestion: string
}
