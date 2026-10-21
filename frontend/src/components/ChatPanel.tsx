import { createContext, memo, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, UIEvent, WheelEvent } from 'react'
import { useStickToBottom } from 'use-stick-to-bottom'
import { Alert, Button, Collapse, Drawer, Dropdown, Grid, Image, Input, Modal, Popover, Select, Tag, Tooltip, Typography, message } from 'antd'
import {
  AppstoreOutlined,
  ArrowRightOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  BulbOutlined,
  CheckOutlined,
  CheckCircleFilled,
  CodeOutlined,
  DownOutlined,
  DragOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  EyeOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FormatPainterOutlined,
  HistoryOutlined,
  InfoCircleFilled,
  LoadingOutlined,
  MoreOutlined,
  PaperClipOutlined,
  PlusOutlined,
  PictureOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  SendOutlined,
  SettingOutlined,
  StopOutlined,
  SyncOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  CloseOutlined,
  ScissorOutlined,
  UndoOutlined,
  UnorderedListOutlined,
  UpOutlined,
} from '@ant-design/icons'
import type { AssistantTurnBlock, ChangeSummary, ChatContextStats, ChatImageAttachment, ChatMessageItem, ChatSessionItem, ChatUserQuestion, ReasoningTrace, SelectedElementContext, TaskPlanItem, TemplateItem, ToolExecution } from '../types'
import type { ThinkingEffort, ThinkingMode } from '../api/chat'
import { MAX_CHAT_IMAGES_PER_MESSAGE } from '../api/chat'
import { useAuthStore } from '../store/authStore'
import ModelSelector from './ModelSelector'
import type { AIModelItem } from '../types'
import MarkdownContent from './MarkdownContent'
import PromptComposer from './PromptComposer'
import { resolveOutgoingReferences } from './PromptComposer'
import type { PromptComposerHandle } from './PromptComposer'
import ElementRenderPreview from './ElementRenderPreview'
import ToolResultView from './ToolResultView'
import UserQuestionPanel from './UserQuestionPanel'
import ImageUploadProgress from './ImageUploadProgress'
import CollapsibleMessage from './CollapsibleMessage'
import type { ImageUploadProgress as UploadState } from '../utils/imageUpload'
import type { UserQuestionAnswer } from './UserQuestionPanel'
import {
  AiFileDiff,
  AiComparisonTable,
  AiInlineCitation,
  AiStreamingText,
  AiTextResponse,
  AiThinkingReasoning,
  AiTodoList,
  AiToolCall,
  AiWebSearch,
} from './AiOutput'
import { aiDiffRows } from './aiOutputDiff'

const { Text } = Typography

export interface ChatRunNotice {
  kind: 'retrying' | 'error' | 'success' | 'info'
  title: string
  detail: string
  attempt?: number
  maxAttempts?: number
  /** The retry wait window, anchored to the event's server-side timestamp. */
  retryDelaySeconds?: number
  retryStartedAtMs?: number
}

export interface ReaskConflictNotice {
  kind: 'local_draft' | 'server'
}

export interface QueuedChatMessage {
  id: string
  content: string
  images: ChatImageAttachment[]
}

const TOOL_LABELS: Record<string, string> = {
  list_files: '查看源码文件',
  read_file: '读取源码',
  search_files: '搜索源码',
  edit_file: '修改源码',
  apply_patch: '应用源码补丁',
  write_file: '写入源码文件',
  enable_tool_groups: '加载专用工具',
  preparing_tool: '准备工具调用',
  ask_user: '确认排版偏好',
  get_document_map: '读取文档地图',
  search_html: '查找排版块',
  read_blocks: '读取排版块',
  list_history_versions: '查看历史版本',
  search_history_versions: '搜索历史版本',
  search_history_version: '搜索指定历史版本',
  inspect_current_images: '盘点当前图片',
  inspect_history_images: '盘点历史图片',
  compare_history_version: '对比历史版本',
  read_history_blocks: '读取历史源码',
  apply_html_patch: '应用排版补丁',
  replace_document: '整体重写',
  read_wechat_compliance_spec: '读取微信合规规范',
  check_compliance: '合规检测',
  update_task_plan: '更新任务清单',
  apply_layout_reference: '应用参考排版',
  get_layout_reference_map: '读取参考模板地图',
  search_layout_reference: '搜索参考模板',
  read_layout_reference_blocks: '读取参考模板代码',
  list_gzh_themes: '浏览主题模板',
  apply_gzh_theme_proposal: '确认主题排版',
  read_gzh_theme_generator: '读取主题生成规范',
  create_gzh_theme_draft: '创建主题草稿',
  publish_gzh_theme: '发布主题',
  read_gzh_theme_recipe: '读取主题配方',
  read_gzh_theme_components: '读取已选主题组件',
  read_gzh_theme: '读取主题组件库',
  read_current_gzh_theme: '读取当前主题参考',
  read_attached_templates: '读取已附组件',
  read_tool_output: '读取完整工具结果',
  search_session_history: '检索会话历史',
  read_session_detail: '读取会话详情',
  validate_gzh_html: '主题严格检查',
  search_article_images: '搜索文章配图',
  view_article_images: '查看文章图片',
  view_chat_images_page: '分页查看附图',
  import_searched_image: '导入搜索图片',
  import_chat_image: '保存会话附图',
  apply_searched_cover: '设为搜索封面',
  generate_article_images: '生成文章配图',
  apply_generated_cover: '设为 AI 封面',
  edit_article_image: '编辑文章图片',
  apply_edited_image: '应用编辑图片',
  edit_article_cover: '编辑文章封面',
  apply_edited_cover: '应用编辑封面',
  transform_document_image: '裁切或旋转图片',
}

const EMPTY_IMAGE_PREVIEWS: ReadonlyMap<string, string> = new Map()
const ChatImagePreviewContext = createContext(EMPTY_IMAGE_PREVIEWS)

const MemoMarkdownContent = memo(MarkdownContent)
const CONTEXT_BREAKDOWN_LABELS: Record<string, string> = {
  system: '固定规则',
  runtime_state: '最新运行状态',
  document_map: '文档地图',
  memory: '压缩记忆',
  recent_history: '近期对话',
  tool_replay: '工具预览回放',
  tool_schema: '工具定义',
  current_request: '当前请求',
  image_inputs: '图片输入',
  selected_context: '选中元素',
  runtime_system: '固定规则',
  runtime_history: '用户与助手消息',
  runtime_tools: '工具结果',
  runtime_cache_boundaries: '工具轮分隔资料',
  runtime_images: '图片及附带文字',
  runtime_streaming: '正在生成',
}
const CONTEXT_BREAKDOWN_COLORS: Record<string, string> = {
  system: '#a0a5af',
  runtime_state: '#b27ad8',
  document_map: '#b27ad8',
  memory: '#43ad78',
  recent_history: '#f0b45f',
  tool_replay: '#7fa0c2',
  tool_schema: '#7798a8',
  current_request: '#e34d80',
  image_inputs: '#4b9f9f',
  selected_context: '#ba9aaf',
  runtime_system: '#a0a5af',
  runtime_history: '#f0b45f',
  runtime_tools: '#5d8c5a',
  runtime_cache_boundaries: '#7fa0c2',
  runtime_images: '#4b9f9f',
  runtime_streaming: '#d28a5b',
}
const THINKING_EFFORT_LABELS: Record<string, string> = {
  minimal: '极简',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '超高',
  max: '最大（max）',
}

function formatThinkingEffort(effort: string): string {
  return THINKING_EFFORT_LABELS[effort] ?? effort
}

interface TaskPlan {
  items: TaskPlanItem[]
}

// AssistantTurnTimeline.vue renders every live delta through its Markdown
// renderer. Keep that behavior so inline Markdown such as **bold** is never
// shown as literal source while the Agent is still streaming.
const StreamingMarkdownContent = memo(function StreamingMarkdownContent({ content }: { content: string }) {
  return <MemoMarkdownContent content={content} streaming />
})

function formatTokenCount(value: number): string {
  if (value < 1_000) return value.toLocaleString()
  if (value < 10_000) return `${(value / 1_000).toFixed(1)}K`
  return `${Math.round(value / 1_000)}K`
}

interface CompactionSummarySection {
  key: string
  label: string
  values: string[]
}

interface CompactionSummary {
  objective: string
  narrative: string
  sections: CompactionSummarySection[]
}

const COMPACTION_SUMMARY_FIELD_LABELS: Record<string, string> = {
  important_details: '重要信息',
  user_preferences: '用户偏好',
  completed_intents: '已完成',
  active_work: '正在处理',
  pending_tasks: '待处理',
  blocked: '阻塞项',
  next_move: '下一步',
  relevant_files: '相关文件',
  constraints: '约束条件',
  decisions: '已确认决策',
  completed: '已完成',
  blockers: '阻塞项',
  next_steps: '下一步',
  source_refs: '来源记录',
}

const COMPACTION_SUMMARY_FIELD_ORDER = [
  'active_work',
  'pending_tasks',
  'next_steps',
  'next_move',
  'constraints',
  'decisions',
  'user_preferences',
  'important_details',
  'completed',
  'completed_intents',
  'blockers',
  'blocked',
  'relevant_files',
  'source_refs',
]

function compactionSummaryValues(value: unknown): string[] {
  const values = Array.isArray(value) ? value : [value]
  return values.flatMap((item) => {
    if (typeof item === 'string') {
      const text = item.trim()
      return text ? [text] : []
    }
    if (typeof item === 'number' || typeof item === 'boolean') return [String(item)]
    return []
  })
}

function compactionSummaryFieldLabel(key: string): string {
  return COMPACTION_SUMMARY_FIELD_LABELS[key] ?? key.replace(/_/g, ' ')
}

/** Parse the compactors' two persisted JSON schemas without changing legacy text summaries. */
export function parseCompactionSummary(summary: string): CompactionSummary | null {
  const trimmed = summary.trim()
  const fenced = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(trimmed)
  const source = (fenced?.[1] ?? trimmed).trim()
  if (!source) return null

  let parsed: unknown
  try {
    parsed = JSON.parse(source)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null

  const record = parsed as Record<string, unknown>
  const objective = compactionSummaryValues(record.objective).join('；')
  const narrative = compactionSummaryValues(record.narrative).join('；')
  const knownKeys = new Set(['objective', 'narrative', ...COMPACTION_SUMMARY_FIELD_ORDER])
  const orderedKeys = [
    ...COMPACTION_SUMMARY_FIELD_ORDER.filter((key) => key in record),
    ...Object.keys(record).filter((key) => !knownKeys.has(key)),
  ]
  const sections = orderedKeys.flatMap((key) => {
    const values = compactionSummaryValues(record[key])
    return values.length ? [{ key, label: compactionSummaryFieldLabel(key), values }] : []
  })

  return objective || narrative || sections.length ? { objective, narrative, sections } : null
}

function wheelDeltaPixels(event: WheelEvent<HTMLElement>): number {
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) return event.deltaY * 16
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) return event.deltaY * event.currentTarget.clientHeight
  return event.deltaY
}

function scrollableWheelParent(element: HTMLElement, delta: number): HTMLElement | null {
  let parent = element.parentElement
  while (parent) {
    const overflowY = window.getComputedStyle(parent).overflowY
    const maximumScrollTop = parent.scrollHeight - parent.clientHeight
    const canScroll = maximumScrollTop > 1 && /auto|scroll|overlay/.test(overflowY)
    if (canScroll && (delta < 0 ? parent.scrollTop > 1 : parent.scrollTop < maximumScrollTop - 1)) return parent
    parent = parent.parentElement
  }
  return null
}

/** Hand the wheel event to the nearest scrollable parent as soon as a detail panel hits its edge. */
function forwardCompactionBoundaryWheel(event: WheelEvent<HTMLElement>) {
  const delta = wheelDeltaPixels(event)
  if (!delta) return
  const element = event.currentTarget
  const maximumScrollTop = element.scrollHeight - element.clientHeight
  const atBoundary = maximumScrollTop <= 1
    || (delta < 0 ? element.scrollTop <= 1 : element.scrollTop >= maximumScrollTop - 1)
  if (!atBoundary) return

  const parent = scrollableWheelParent(element, delta)
  if (!parent) return
  event.preventDefault()
  event.stopPropagation()
  parent.scrollTop = Math.max(0, Math.min(parent.scrollHeight - parent.clientHeight, parent.scrollTop + delta))
}

function hasRuntimeContextBudget(stats: ChatContextStats): boolean {
  return stats.runtime_context_tokens != null
    && (Boolean(stats.runtime_context_source) || stats.runtime_context_tokens > 0)
}

export function contextUsageValues(stats: ChatContextStats) {
  const runtimeContextTokens = Math.max(0, Math.round(stats.runtime_context_tokens ?? 0))
  return {
    compiledInputTokens: hasRuntimeContextBudget(stats)
      ? runtimeContextTokens
      : stats.compiled_input_tokens ?? stats.used_tokens,
    ledgerTokens: stats.ledger_tokens ?? stats.conversation_tokens ?? 0,
    runtimeContextTokens,
  }
}

export function contextInputWindowLabel(stats: ChatContextStats): string {
  const threshold = stats.active_context_threshold_tokens || stats.usable_tokens || stats.max_tokens
  const outputReserve = stats.max_output_tokens ?? 0
  const inputLimit = stats.input_limit_tokens || Math.max(0, stats.max_tokens - outputReserve)
  return `达到 ${formatTokenCount(threshold)} tokens 时自动压缩；模型总窗口 ${formatTokenCount(stats.max_tokens)}，输出预留 ${formatTokenCount(outputReserve)}，输入上限 ${formatTokenCount(inputLimit)} tokens`
}

export function isRuntimeContextCompacting(
  stats: ChatContextStats | null,
  streaming: boolean,
): boolean {
  return streaming && (
    stats?.runtime_context_state === 'run_compacting'
    || stats?.state === 'compacting'
    // The first SSE sample announces preparation before the compactor call.
    // If it is already known to be required, show the same dedicated state
    // instead of briefly rendering the ordinary "preparing" timeline.
    || (stats?.state === 'preparing' && stats.requires_compaction)
  )
}

export function supportsDisabledThinkingOption(
  model: AIModelItem | undefined,
  temporarilyUnsupportedThinkingModelIds: ReadonlySet<number>,
): boolean {
  return Boolean(
    model
    && model.supports_disabled_thinking !== false
    && !temporarilyUnsupportedThinkingModelIds.has(model.id),
  )
}

export function visibleTemplateReferenceIndexes(content: string, templateCount: number): Set<number> {
  const indexes = new Set<number>()
  for (const match of content.matchAll(/@组件(\d+)/g)) {
    const index = Number(match[1]) - 1
    if (index >= 0 && index < templateCount) indexes.add(index)
  }
  return indexes
}

export function contextCompactionNotice(content: string): ChatRunNotice {
  const successPrefix = '压缩上下文成功，'
  if (content.startsWith(successPrefix)) {
    return {
      kind: 'success',
      title: '上下文已压缩',
      detail: content.slice(successPrefix.length).trim(),
    }
  }

  const noOpPrefix = '上下文检查完成，'
  if (content.startsWith(noOpPrefix)) {
    return {
      kind: 'info',
      title: '无需压缩',
      detail: content.slice(noOpPrefix.length).trim(),
    }
  }

  return {
    kind: 'info',
    title: '上下文状态',
    detail: content,
  }
}

function ContextUsage({
  stats,
  onCompactContext,
}: {
  stats: ChatContextStats
  onCompactContext: (rebuild: boolean) => void | Promise<void>
}) {
  const [compacting, setCompacting] = useState(false)
  const { compiledInputTokens, ledgerTokens } = contextUsageValues(stats)
  const hasRuntimeContext = hasRuntimeContextBudget(stats)
  const sourceLabel = stats.runtime_context_source === 'provider_reported'
    ? '最近模型调用实报'
    : stats.runtime_context_source === 'server_recomputed_after_tool'
      ? '工具结果后重算'
      : '已构建上下文'
  const stateLabel = stats.runtime_context_state === 'run_compacting' || stats.state === 'compacting'
        ? '正在压缩'
      : stats.runtime_context_state === 'in_run_compacted'
        ? '运行中已压缩'
      : stats.runtime_context_state === 'run_compaction_failed'
        ? '压缩失败'
      : stats.state === 'compacted'
        ? '已压缩历史'
        : stats.state === 'requires_compaction'
          ? '发送时将压缩'
          : stats.state === 'context_overflow'
            ? '当前配置不足'
            : sourceLabel
  const usedTokens = compiledInputTokens
  const inputThreshold = stats.active_context_threshold_tokens || stats.usable_tokens
  const usagePercent = Math.min(100, Math.round(usedTokens / Math.max(1, inputThreshold) * 100))
  const activeBreakdown = hasRuntimeContext && Object.keys(stats.runtime_context_breakdown ?? {}).length
    ? stats.runtime_context_breakdown ?? {}
    : stats.breakdown
  const breakdownItems = Object.entries(activeBreakdown).filter(([, value]) => value > 0)
  const preparedBreakdownItems = hasRuntimeContext
    ? Object.entries(stats.breakdown).filter(([, value]) => value > 0)
    : []
  const preparedBreakdownTokens = preparedBreakdownItems.reduce((total, [, value]) => total + value, 0)
  const ringColor = usagePercent >= 85 ? '#e88b2d' : usagePercent >= 65 ? '#d6a33d' : '#3c84e8'
  const ringStyle = {
    background: `conic-gradient(${ringColor} ${usagePercent}%, var(--app-border) 0)`,
  } as CSSProperties
  const detail = (
    <div className="chat-context-popover">
      <div className="chat-context-popover-head">
        <strong>上下文预算</strong>
        <span>
          {stateLabel}
          <Tooltip title="立即压缩">
            <Button
              aria-label="立即压缩"
              type="text"
              size="small"
              icon={<SyncOutlined />}
              loading={compacting}
              disabled={compacting}
              onClick={() => {
                setCompacting(true)
                Promise.resolve(onCompactContext(false)).finally(() => setCompacting(false))
              }}
            />
          </Tooltip>
          <Tooltip title="从完整历史重建摘要">
            <Button
              aria-label="从完整历史重建摘要"
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              loading={compacting}
              disabled={compacting}
              onClick={() => {
                setCompacting(true)
                Promise.resolve(onCompactContext(true)).finally(() => setCompacting(false))
              }}
            />
          </Tooltip>
        </span>
      </div>
      <div className="chat-context-summary">
        <div className="chat-context-summary-main">
          <b>{usagePercent}% 预算占用</b>
          <span>约 {formatTokenCount(usedTokens)} / {formatTokenCount(inputThreshold)} tokens</span>
        </div>
        <div className="chat-context-summary-note">
          {contextInputWindowLabel(stats)}
        </div>
      </div>
      <div className="chat-context-bar" aria-label={`上下文已使用 ${usagePercent}%`}>
        {breakdownItems.map(([key, value]) => (
          <i key={key} style={{ width: `${Math.max(1, value / Math.max(1, usedTokens) * 100)}%`, background: CONTEXT_BREAKDOWN_COLORS[key] ?? '#98a2b3' }} />
        ))}
      </div>
      <div className="chat-context-breakdown">
        {hasRuntimeContext && <div className="chat-context-breakdown-heading">下一次请求预算</div>}
        {breakdownItems.map(([key, value]) => (
          <span key={key}>
            <i><em style={{ background: CONTEXT_BREAKDOWN_COLORS[key] ?? '#98a2b3' }} />{CONTEXT_BREAKDOWN_LABELS[key] ?? key}</i>
            <b>{formatTokenCount(value)}</b>
          </span>
        ))}
      </div>
      {preparedBreakdownItems.length > 0 && (
        <div className="chat-context-prepared-breakdown">
          <div className="chat-context-breakdown-heading">
            发送前细分 <small>约 {formatTokenCount(preparedBreakdownTokens)} tokens</small>
          </div>
          <div className="chat-context-breakdown">
            {preparedBreakdownItems.map(([key, value]) => (
              <span key={key}>
                <i><em style={{ background: CONTEXT_BREAKDOWN_COLORS[key] ?? '#98a2b3' }} />{CONTEXT_BREAKDOWN_LABELS[key] ?? key}</i>
                <b>{formatTokenCount(value)}</b>
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="chat-context-foot">
        原始账本约 {formatTokenCount(ledgerTokens)} tokens（{stats.event_count ?? stats.conversation_message_count ?? 0} 条事件）
        {stats.snapshot_covered_event_count ? `；快照覆盖 ${stats.snapshot_covered_event_count} 条事件` : ''}
        <br />完整事件 {stats.event_count ?? 0} 条，当前回放 {stats.replayed_event_count ?? 0} 条，已节省约 {stats.tokens_saved.toLocaleString()} tokens
        {stats.compaction_strategy ? `；压缩方式：${stats.compaction_strategy === 'agentic' ? '模型摘要' : stats.compaction_strategy}` : ''}
        {hasRuntimeContext ? (stats.runtime_context_is_estimate ? '；服务端预算估算' : '；提供方实报') : (stats.is_estimate ? '；服务端预算估算' : '')}
        {(stats.token_estimate_multiplier ?? 1) > 1 ? `；文本估算含 ${stats.token_estimate_multiplier} 倍安全余量` : ''}
        {stats.runtime_context_source === 'server_recomputed_after_tool' && stats.runtime_context_tool_name ? `；工具 ${stats.runtime_context_tool_name} 已完成` : ''}
        {stats.last_model_usage_reported || (stats.runtime_input_tokens ?? 0) > 0
          ? `；最近调用实报输入 ${formatTokenCount(stats.runtime_input_tokens ?? 0)} tokens（含缓存读取 ${formatTokenCount(stats.last_model_cached_input_tokens ?? 0)}）`
          : ''}
        {stats.runtime_context_state === 'streaming' ? '；已计入正在生成的正文和工具参数，工具完成后重算' : ''}
        <br />输出上限 {stats.max_output_tokens.toLocaleString()}，单次工具预览上限 {stats.tool_result_max_tokens.toLocaleString()} tokens
        {stats.effective_tool_preview_tokens && stats.effective_tool_preview_tokens !== stats.tool_result_max_tokens
          ? `（本轮动态上限 ${formatTokenCount(stats.effective_tool_preview_tokens)}）`
          : ''}
        {stats.stored_tool_output_count
          ? `；已暂存 ${stats.stored_tool_output_count} 份完整工具结果（${formatTokenCount(stats.stored_tool_output_tokens ?? 0)} tokens，${Math.ceil((stats.stored_tool_output_bytes ?? 0) / 1024).toLocaleString()} KiB，会话内保留，不计入下次输入）`
          : '；超过预览上限的完整工具结果会随会话保留，不计入下次输入'}
      </div>
    </div>
  )
  return (
    <Popover content={detail} trigger="click" placement="topRight">
      <button className={`chat-context-ring${usagePercent >= 85 ? ' is-warning' : ''}`} type="button" title={`上下文预算占用 ${usagePercent}%`} style={ringStyle}>
        <span>{usagePercent}%</span>
      </button>
    </Popover>
  )
}

interface ChatPanelProps {
  models: AIModelItem[]
  modelId: number | null
  onModelChange: (id: number) => void
  thinkingMode: ThinkingMode
  onThinkingModeChange: (mode: ThinkingMode) => void
  thinkingEffort: ThinkingEffort
  onThinkingEffortChange: (effort: ThinkingEffort) => void
  temporarilyUnsupportedThinkingModelIds: ReadonlySet<number>
  thinkingStatus: string | null
  contextStats: ChatContextStats | null
  chatSessions: ChatSessionItem[]
  activeChatSession: ChatSessionItem | null
  hiddenHistory: ChatMessageItem[]
  messages: ChatMessageItem[]
  hasOlderMessages: boolean
  olderMessagesLoading: boolean
  onLoadOlderMessages: () => Promise<boolean>
  queuedMessages: QueuedChatMessage[]
  queuePaused: boolean
  streaming: boolean
  stopping: boolean
  streamText: string
  toolActivities: ToolExecution[]
  reasoningTrace: ReasoningTrace
  streamBlocks: AssistantTurnBlock[]
  streamNotice: ChatRunNotice | null
  conversationError: string | null
  composerDraft: string
  submitting: boolean
  pendingUserQuestion: ChatUserQuestion | null
  questionSubmitting: boolean
  reaskConflict: ReaskConflictNotice | null
  resolvingReaskConflict: boolean
  selectedElements: SelectedElementContext[]
  attachedTemplates: TemplateItem[]
  composerTemplates: TemplateItem[]
  imageAttachments: ChatImageAttachment[]
  imageUploading: boolean
  imageUploadProgress?: UploadState | null
  onRemoveSelectedElement: (index: number) => void
  onDuplicateSelectedElement: (index: number) => void
  onMoveSelectedElement: (fromIndex: number, toIndex: number) => void
  onRemoveAttachedTemplate: (templateId: number) => void
  onRemoveComposerTemplate: (templateId: number) => void
  onRemoveQueuedMessage: (id: string) => void
  onUpdateQueuedMessage: (id: string, content: string) => void
  onMoveQueuedMessage: (fromIndex: number, toIndex: number) => void
  onResumeQueuedMessages: () => void
  onEditRequest: (message: ChatMessageItem) => void
  onSend: (text: string, references: SelectedElementContext[], images: ChatImageAttachment[]) => void
  onAnswerUserQuestion: (answer: UserQuestionAnswer) => void
  onUserQuestionActivity: () => void
  onUserQuestionTimeoutElapsed: () => void
  onUploadImages: (files: File[]) => void
  onRemoveImage: (attachment: ChatImageAttachment) => void
  onMoveImage: (fromIndex: number, toIndex: number) => void
  onContextDraftChange: (text: string) => void
  onDismissReaskConflict: () => void
  onDiscardReaskConflict: () => void
  onOpenLayoutImitation: () => void
  onStop: () => void
  onSessionChange: (sessionId: number) => void
  onCreateSession: () => void
  onRenameSession: (sessionId: number, title: string) => void | Promise<void>
  onArchiveSession: (sessionId: number) => void | Promise<void>
  onRestoreSession: (sessionId: number) => void | Promise<void>
  onTruncateContext: () => void | Promise<void>
  onRestoreContext: () => void | Promise<void>
  onCompactContext: (rebuild: boolean) => void | Promise<void>
  onViewHiddenHistory: () => void | Promise<void>
  onClearHiddenHistory: () => void
  onClearLayoutReference: () => void | Promise<void>
  onClearThemeContext: () => void | Promise<void>
}

export default function ChatPanel({
  models,
  modelId,
  onModelChange,
  thinkingMode,
  onThinkingModeChange,
  thinkingEffort,
  onThinkingEffortChange,
  temporarilyUnsupportedThinkingModelIds,
  thinkingStatus,
  contextStats,
  chatSessions,
  activeChatSession,
  hiddenHistory,
  messages,
  hasOlderMessages,
  olderMessagesLoading,
  onLoadOlderMessages,
  queuedMessages,
  queuePaused,
  streaming,
  stopping,
  streamText,
  toolActivities,
  reasoningTrace,
  streamBlocks,
  streamNotice,
  conversationError,
  composerDraft,
  submitting,
  pendingUserQuestion,
  questionSubmitting,
  reaskConflict,
  resolvingReaskConflict,
  selectedElements,
  attachedTemplates,
  composerTemplates,
  imageAttachments,
  imageUploading,
  imageUploadProgress,
  onRemoveSelectedElement,
  onDuplicateSelectedElement,
  onMoveSelectedElement,
  onRemoveAttachedTemplate,
  onRemoveComposerTemplate,
  onRemoveQueuedMessage,
  onUpdateQueuedMessage,
  onMoveQueuedMessage,
  onResumeQueuedMessages,
  onEditRequest,
  onSend,
  onAnswerUserQuestion,
  onUserQuestionActivity,
  onUserQuestionTimeoutElapsed,
  onUploadImages,
  onRemoveImage,
  onMoveImage,
  onContextDraftChange,
  onDismissReaskConflict,
  onDiscardReaskConflict,
  onOpenLayoutImitation,
  onStop,
  onSessionChange,
  onCreateSession,
  onRenameSession,
  onArchiveSession,
  onRestoreSession,
  onTruncateContext,
  onRestoreContext,
  onCompactContext,
  onViewHiddenHistory,
  onClearHiddenHistory,
  onClearLayoutReference,
  onClearThemeContext,
}: ChatPanelProps) {
  const currentUserId = useAuthStore((state) => state.user?.id)
  const chatImagePreviews = useMemo(() => new Map([
    ...messages.flatMap((item) => item.image_attachments ?? []),
    ...hiddenHistory.flatMap((item) => item.image_attachments ?? []),
    ...queuedMessages.flatMap((item) => item.images),
    ...imageAttachments,
  ].map((image) => [image.id, image.preview_url])), [messages, hiddenHistory, queuedMessages, imageAttachments])
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameTitle, setRenameTitle] = useState('')
  const [hiddenHistoryOpen, setHiddenHistoryOpen] = useState(false)
  const [settingsDrawerOpen, setSettingsDrawerOpen] = useState(false)
  const [editingQueuedMessageId, setEditingQueuedMessageId] = useState<string | null>(null)
  const [draggedQueuedMessageId, setDraggedQueuedMessageId] = useState<string | null>(null)
  const [queuedDropTargetId, setQueuedDropTargetId] = useState<string | null>(null)
  const composerRef = useRef<PromptComposerHandle>(null)
  const queuedEditPreviousDraftRef = useRef<string | null>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const messageListContentElementRef = useRef<HTMLDivElement | null>(null)
  const historyAnchorRef = useRef<{
    element: HTMLDivElement
    firstId: number
    sessionId: number
    scrollHeight: number
    scrollTop: number
    suspensionId: number
  } | null>(null)
  const autoFollowSuspensionsRef = useRef(new Set<number>())
  const autoFollowSuspensionIdRef = useRef(0)
  const {
    scrollRef: messageListRef,
    contentRef: messageListContentRef,
    scrollToBottom,
    stopScroll,
    isAtBottom,
    state: stickToBottomState,
  } = useStickToBottom({ initial: 'instant', resize: 'instant' })
  const setMessageListContentElement = useCallback((element: HTMLDivElement | null) => {
    messageListContentElementRef.current = element
    messageListContentRef(element)
  }, [messageListContentRef])
  const suspendChatAutoFollow = useCallback(() => {
    const suspensionId = ++autoFollowSuspensionIdRef.current
    autoFollowSuspensionsRef.current.add(suspensionId)
    stopScroll()
    stickToBottomState.resizeObserver?.disconnect()
    return suspensionId
  }, [stickToBottomState, stopScroll])
  const resumeChatAutoFollow = useCallback((suspensionId: number | null) => {
    if (suspensionId === null) return
    const removed = autoFollowSuspensionsRef.current.delete(suspensionId)
    if (removed && autoFollowSuspensionsRef.current.size === 0 && messageListContentElementRef.current) {
      messageListContentRef(messageListContentElementRef.current)
    }
  }, [messageListContentRef])
  const resumeAllChatAutoFollow = useCallback(() => {
    const hadSuspensions = autoFollowSuspensionsRef.current.size > 0
    autoFollowSuspensionsRef.current.clear()
    if (hadSuspensions && messageListContentElementRef.current) {
      messageListContentRef(messageListContentElementRef.current)
    }
  }, [messageListContentRef])
  const requestOlderMessages = useCallback((element: HTMLDivElement) => {
    if (!hasOlderMessages || olderMessagesLoading || historyAnchorRef.current || !messages.length || !activeChatSession) return
    const suspensionId = suspendChatAutoFollow()
    historyAnchorRef.current = {
      element,
      firstId: messages[0].id,
      sessionId: activeChatSession.id,
      scrollHeight: element.scrollHeight,
      scrollTop: element.scrollTop,
      suspensionId,
    }
    void onLoadOlderMessages().then((loaded) => {
      if (loaded) return
      const anchor = historyAnchorRef.current
      if (anchor?.suspensionId === suspensionId) {
        historyAnchorRef.current = null
        resumeChatAutoFollow(suspensionId)
      }
    })
  }, [activeChatSession, hasOlderMessages, messages, olderMessagesLoading, onLoadOlderMessages, resumeChatAutoFollow, suspendChatAutoFollow])
  useLayoutEffect(() => {
    const anchor = historyAnchorRef.current
    if (!anchor) return
    if (anchor.sessionId !== activeChatSession?.id) {
      historyAnchorRef.current = null
      resumeChatAutoFollow(anchor.suspensionId)
    } else if (messages[0]?.id !== anchor.firstId) {
      anchor.element.scrollTop = anchor.scrollTop + anchor.element.scrollHeight - anchor.scrollHeight
      historyAnchorRef.current = null
      resumeChatAutoFollow(anchor.suspensionId)
    }
  }, [activeChatSession?.id, messages, resumeChatAutoFollow])

  const handleSend = () => {
    if (imageUploading || submitting || stopping || pendingUserQuestion || !activeChatSession || activeChatSession.is_archived) return
    const composerPayload = composerRef.current?.getPayload() ?? {
      message: composerDraft.trim(),
      references: [],
      templateIds: composerTemplates.map((template) => template.id),
      imageIds: imageAttachments.map((image) => image.id),
    }
    const payload = {
      ...composerPayload,
      references: resolveOutgoingReferences(composerPayload.references, selectedElements),
    }
    if (editingQueuedMessageId) {
      saveQueuedMessageEdit()
      return
    }
    const text = payload.message || (payload.references.length > 0
      ? '请处理所附元素。'
      : imageAttachments.length > 0
        ? '请分析所附图片，并继续处理当前推文。'
        : payload.templateIds.length > 0
          ? '请依据已附组件库处理当前推文。'
          : '')
    if (!text) return
    if (!modelId) {
      message.warning('请先选择 AI 模型')
      return
    }
    if (!streaming && contextStats?.can_fit_after_compaction === false) {
      message.error('当前模型的压缩阈值不足以容纳此文档，请选择更大上下文模型或在模型管理中调整预算')
      return
    }
    const imageById = new Map(imageAttachments.map((image) => [image.id, image]))
    const orderedImages = payload.imageIds.flatMap((id) => {
      const image = imageById.get(id)
      imageById.delete(id)
      return image ? [image] : []
    })
    onSend(text, payload.references, [...orderedImages, ...imageById.values()])
    resumeAllChatAutoFollow()
    void scrollToBottom({ animation: 'instant', ignoreEscapes: true })
  }

  const handleInputChange = useCallback((value: string) => {
    onContextDraftChange(value)
  }, [onContextDraftChange])

  const handleEditRequest = useCallback((message: ChatMessageItem) => {
    onEditRequest(message)
    onContextDraftChange(message.content)
  }, [onContextDraftChange, onEditRequest])

  const beginQueuedMessageEdit = (queuedMessage: QueuedChatMessage) => {
    queuedEditPreviousDraftRef.current = composerDraft
    setEditingQueuedMessageId(queuedMessage.id)
    onContextDraftChange(queuedMessage.content)
    window.requestAnimationFrame(() => composerRef.current?.focus())
  }

  const finishQueuedMessageEdit = useCallback((restorePreviousDraft: boolean) => {
    const previousDraft = queuedEditPreviousDraftRef.current
    queuedEditPreviousDraftRef.current = null
    setEditingQueuedMessageId(null)
    if (restorePreviousDraft && previousDraft !== null) onContextDraftChange(previousDraft)
  }, [onContextDraftChange])

  const cancelQueuedMessageEdit = useCallback(() => {
    finishQueuedMessageEdit(true)
  }, [finishQueuedMessageEdit])

  const saveQueuedMessageEdit = () => {
    if (!editingQueuedMessageId) return
    const content = composerDraft.trim()
    if (!content) {
      message.warning('待处理内容不能为空')
      return
    }
    onUpdateQueuedMessage(editingQueuedMessageId, content)
    finishQueuedMessageEdit(true)
  }

  const moveQueuedMessage = (fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return
    onMoveQueuedMessage(fromIndex, toIndex)
  }

  const finishQueuedDrag = () => {
    setDraggedQueuedMessageId(null)
    setQueuedDropTargetId(null)
  }

  useEffect(() => {
    if (editingQueuedMessageId && !queuedMessages.some((item) => item.id === editingQueuedMessageId)) {
      cancelQueuedMessageEdit()
    }
  }, [cancelQueuedMessageEdit, editingQueuedMessageId, queuedMessages])

  const selectedModel = models.find((model) => model.id === modelId)
  const isMultimodal = Boolean(selectedModel?.is_multimodal)
  const contextCannotFit = contextStats?.can_fit_after_compaction === false
  const conversationControlsDisabled = streaming || stopping || submitting || Boolean(pendingUserQuestion)
  const composerDisabled = stopping || submitting || Boolean(pendingUserQuestion)
  const canSend = Boolean(
    activeChatSession
    && !activeChatSession.is_archived
    && !imageUploading
    && !submitting
    && (editingQueuedMessageId
      ? composerDraft.trim()
      : modelId
        && (!contextCannotFit || streaming)
        && (composerDraft.trim() || selectedElements.length > 0 || imageAttachments.length > 0 || composerTemplates.length > 0)),
  )
  const effortConfig = selectedModel?.thinking_config?.efforts
  const effortOptions = effortConfig && typeof effortConfig === 'object' && !Array.isArray(effortConfig)
    ? Object.keys(effortConfig)
    : []
  const modelDefaultThinkingEffort = selectedModel?.default_thinking_effort ?? 'auto'
  const canDisableThinking = supportsDisabledThinkingOption(
    selectedModel,
    temporarilyUnsupportedThinkingModelIds,
  )
  const chatSettingsContent = (
    <div className="chat-settings-panel">
      <label className="chat-settings-field">
        <span>AI 模型</span>
        <ModelSelector models={models} value={modelId} onChange={onModelChange} disabled={conversationControlsDisabled} />
      </label>
      <label className="chat-settings-field">
        <span>思考强度</span>
        <Select
          aria-label="思考强度"
          value={thinkingMode === 'disabled' ? 'disabled' : thinkingEffort}
          disabled={streaming || activeChatSession?.is_archived}
          onChange={(value) => {
            if (value === 'disabled') {
              onThinkingModeChange('disabled')
              return
            }
            onThinkingModeChange('enabled')
            onThinkingEffortChange(value as ThinkingEffort)
          }}
          options={[
            {
              value: 'auto',
              label: modelDefaultThinkingEffort === 'auto'
                ? '默认'
                : `默认（${formatThinkingEffort(modelDefaultThinkingEffort)}）`,
            },
            ...effortOptions.map((effort) => ({ value: effort, label: formatThinkingEffort(effort) })),
            ...(canDisableThinking ? [{ value: 'disabled', label: '不思考' }] : []),
          ]}
        />
      </label>
    </div>
  )
  const thinkingEffortLabel = thinkingMode === 'disabled'
    ? '不思考'
    : thinkingEffort === 'auto'
      ? modelDefaultThinkingEffort === 'auto'
        ? '默认'
        : formatThinkingEffort(modelDefaultThinkingEffort)
      : formatThinkingEffort(thinkingEffort)
  const modelSettingsLabel = selectedModel?.display_name ?? '选择模型'
  const chatSettingsTrigger = isCompact ? (
    <Tooltip title="会话设置">
      <Button
        aria-label={`会话设置：${modelSettingsLabel}，${thinkingEffortLabel}`}
        className="chat-settings-trigger"
        type="text"
        icon={<SettingOutlined />}
        onClick={() => setSettingsDrawerOpen(true)}
      >
        <span className="chat-settings-trigger-model">{modelSettingsLabel}</span>
        <span className="chat-settings-trigger-effort">{thinkingEffortLabel}</span>
      </Button>
    </Tooltip>
  ) : (
    <Popover title="会话设置" trigger="click" content={chatSettingsContent} overlayClassName="chat-settings-popover">
      <Button
        aria-label={`会话设置：${modelSettingsLabel}，${thinkingEffortLabel}`}
        className="chat-settings-trigger"
        type="text"
        icon={<SettingOutlined />}
      >
        <span className="chat-settings-trigger-model">{modelSettingsLabel}</span>
        <span className="chat-settings-trigger-effort">{thinkingEffortLabel}</span>
      </Button>
    </Popover>
  )
  const activeTool = getRunningTool(streamBlocks)
  const showActiveAssistantTurn = streaming || Boolean(pendingUserQuestion)
  const runtimeContextCompacting = isRuntimeContextCompacting(contextStats, streaming)
  const liveLabel = stopping
    ? '正在停止 Agent'
    : runtimeContextCompacting
      ? '正在压缩上下文'
    : thinkingStatus?.includes('工具参数')
      ? thinkingStatus
      : streamingLabel(streamBlocks, streamText)
  const taskPlan = streaming
    ? latestTaskPlanFromBlocks(streamBlocks, toolActivities)
    : latestTaskPlanFromMessages(messages)
  const layoutReferenceStrengthLabel = activeChatSession?.layout_reference?.imitation_strength === 'maximum'
    ? '最大还原'
    : activeChatSession?.layout_reference?.imitation_strength === 'style'
      ? '风格'
      : '结构'
  const layoutReference = activeChatSession?.layout_reference ?? null
  const themeContext = activeChatSession?.theme_context ?? null
  const themeApplyModeLabel = themeContext?.apply_mode === 'key_components'
    ? '关键组件'
    : themeContext?.apply_mode === 'restrained'
      ? '克制套用'
      : '全篇套用'
  const sessionResourceCount = Number(Boolean(layoutReference)) + Number(Boolean(themeContext)) + attachedTemplates.length
  const showStandaloneLayoutReference = Boolean(layoutReference) && !themeContext && attachedTemplates.length === 0
  const showSessionResources = sessionResourceCount > 0 && !showStandaloneLayoutReference

  const openRename = () => {
    if (!activeChatSession) return
    setRenameTitle(activeChatSession.title)
    setRenameOpen(true)
  }

  const confirmTruncate = () => {
    const count = activeChatSession?.visible_message_count ?? 0
    Modal.confirm({
      title: '截断当前对话上下文',
      content: `将隐藏当前对话的 ${count} 条消息，并使现有摘要失效。完整工具结果仍随该对话保留；当前文档内容不会改变。`,
      okText: '截断上下文',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => onTruncateContext(),
    })
  }

  const confirmArchive = () => {
    if (!activeChatSession) return
    Modal.confirm({
      title: '归档此对话',
      content: '归档后不会发送给模型，仍可在对话列表中恢复；当前文档内容不会改变。',
      okText: '归档',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => onArchiveSession(activeChatSession.id),
    })
  }

  const handleSessionMenu = (key: string) => {
    if (!activeChatSession) return
    if (key === 'rename') openRename()
    if (key === 'truncate') confirmTruncate()
    if (key === 'restore-context') void onRestoreContext()
    if (key === 'archive') confirmArchive()
    if (key === 'restore') void onRestoreSession(activeChatSession.id)
  }

  const sessionMenuItems = activeChatSession?.is_archived
    ? [{ key: 'restore', label: '恢复对话', icon: <UndoOutlined /> }]
    : [
        { key: 'rename', label: '重命名', icon: <EditOutlined /> },
        { key: 'truncate', label: '截断上下文', icon: <ScissorOutlined />, danger: true },
        ...(activeChatSession?.hidden_message_count ? [{ key: 'restore-context', label: '恢复隐藏历史到上下文', icon: <UndoOutlined /> }] : []),
        { type: 'divider' as const },
        { key: 'archive', label: '归档对话', icon: <HistoryOutlined />, danger: true },
      ]

  useLayoutEffect(() => {
    resumeAllChatAutoFollow()
    void scrollToBottom({ animation: 'instant', ignoreEscapes: true })
  }, [activeChatSession?.id, resumeAllChatAutoFollow, scrollToBottom])

  useLayoutEffect(() => {
    if (!streaming) return
    resumeAllChatAutoFollow()
    void scrollToBottom({ animation: 'instant', ignoreEscapes: true })
  }, [resumeAllChatAutoFollow, scrollToBottom, streaming])

  return (
    <ChatImagePreviewContext.Provider value={chatImagePreviews}>
    <div className="chat-panel chat-panel-aichat">
      <div className="chat-panel-header">
        <div className="chat-panel-title-row">
          <div className="chat-panel-title-copy">
            <Text strong>排版助手</Text>
            <Text type="secondary">编辑当前推文</Text>
          </div>
          {streaming && (
            <span className={`chat-live-status${activeTool ? ' is-tool' : ''}`} title={liveLabel}>
              <i /> <span className="chat-live-status-text">{liveLabel}</span>
            </span>
          )}
        </div>
        <div className="chat-session-bar">
          <Select
            aria-label="当前对话"
            size="small"
            value={activeChatSession?.id}
            disabled={conversationControlsDisabled}
            placeholder="选择对话"
            onChange={(value) => onSessionChange(Number(value))}
            options={chatSessions.map((session) => ({
              value: session.id,
              label: `${session.is_archived ? '已归档 · ' : ''}${session.title}`,
            }))}
          />
          <Tooltip title="新建对话">
            <Button aria-label="新建对话" size="small" icon={<PlusOutlined />} disabled={conversationControlsDisabled} onClick={onCreateSession} />
          </Tooltip>
          <Dropdown menu={{ items: sessionMenuItems, onClick: ({ key }) => handleSessionMenu(String(key)) }} trigger={['click']}>
            <Button aria-label="对话操作" size="small" icon={<MoreOutlined />} disabled={conversationControlsDisabled || !activeChatSession} />
          </Dropdown>
        </div>
        {showStandaloneLayoutReference && layoutReference && (
          <div className="chat-layout-reference-status">
            <Tooltip title={layoutReference.title}>
              <Tag className="chat-layout-reference-title" icon={<FormatPainterOutlined />}>{layoutReference.title}</Tag>
            </Tooltip>
            <Tag className="chat-layout-reference-strength">{layoutReferenceStrengthLabel}</Tag>
            <Tooltip title="清除参考模板">
              <Button
                aria-label="清除参考模板"
                type="text"
                size="small"
                icon={<CloseOutlined />}
                disabled={conversationControlsDisabled || activeChatSession?.is_archived}
                onClick={() => void onClearLayoutReference()}
              />
            </Tooltip>
          </div>
        )}
        {showSessionResources && activeChatSession && (
          <Collapse
            className="chat-session-resources"
            size="small"
            ghost
            expandIconPlacement="end"
            items={[{
              key: 'resources',
              label: (
                <span className="chat-session-resources-summary">
                  <FolderOpenOutlined aria-hidden="true" />
                  <span>会话资源</span>
                  <span className="chat-session-resources-count">{sessionResourceCount} 项</span>
                </span>
              ),
              children: (
                <div className="chat-session-resource-list">
                  {layoutReference && (
                    <div className="chat-session-resource-row">
                      <span className="chat-session-resource-kind"><FormatPainterOutlined aria-hidden="true" />排版模仿</span>
                      <div className="chat-session-resource-value">
                        <Text ellipsis={{ tooltip: layoutReference.title }}>{layoutReference.title}</Text>
                        <Tag>{layoutReferenceStrengthLabel}</Tag>
                      </div>
                      <Tooltip title="清除参考模板">
                        <Button
                          aria-label="清除参考模板"
                          type="text"
                          size="small"
                          icon={<CloseOutlined />}
                          disabled={conversationControlsDisabled || activeChatSession.is_archived}
                          onClick={() => void onClearLayoutReference()}
                        />
                      </Tooltip>
                    </div>
                  )}
                  {themeContext && (
                    <div className="chat-session-resource-row">
                      <span className="chat-session-resource-kind"><BulbOutlined aria-hidden="true" />主题</span>
                      <div className="chat-session-resource-value">
                        <Text ellipsis={{ tooltip: themeContext.theme_name }}>{themeContext.theme_name}</Text>
                        <Tag>{themeApplyModeLabel}</Tag>
                      </div>
                      <Tooltip title="清除主题参考">
                        <Button
                          aria-label="清除主题参考"
                          type="text"
                          size="small"
                          icon={<CloseOutlined />}
                          disabled={conversationControlsDisabled || activeChatSession.is_archived}
                          onClick={() => void onClearThemeContext()}
                        />
                      </Tooltip>
                    </div>
                  )}
                  {attachedTemplates.length > 0 && (
                    <div className="chat-session-resource-row is-templates">
                      <span className="chat-session-resource-kind"><AppstoreOutlined aria-hidden="true" />组件</span>
                      <div className="chat-session-resource-template-list">
                        {attachedTemplates.map((template) => (
                          <Tag key={template.id} className="chat-session-resource-template" title={template.name}>
                            <span>{template.name}</span>
                            <Tooltip title={`移除组件 ${template.name}`}>
                              <Button
                                aria-label={`移除组件 ${template.name}`}
                                type="text"
                                size="small"
                                icon={<CloseOutlined />}
                                disabled={composerDisabled || activeChatSession.is_archived}
                                onClick={() => onRemoveAttachedTemplate(template.id)}
                              />
                            </Tooltip>
                          </Tag>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ),
            }]}
          />
        )}
        {contextStats?.requires_compaction && !contextCannotFit && !streaming && (
          <Alert
            className="chat-context-notice"
            type="warning"
            showIcon
            message={`当前模型预算下，原始输入约 ${(contextStats.raw_input_tokens ?? contextStats.used_tokens).toLocaleString()} tokens，发送时将先压缩较早对话（完成后预计约 ${contextStats.projected_used_tokens.toLocaleString()} / ${contextStats.active_context_threshold_tokens.toLocaleString()} tokens）。`}
          />
        )}
        {activeChatSession?.is_archived && (
          <Alert
            className="chat-context-notice"
            type="warning"
            showIcon
            message="该对话已归档，不会再发送给模型。"
            action={<Button size="small" onClick={() => void onRestoreSession(activeChatSession.id)}>恢复</Button>}
          />
        )}
        {!activeChatSession?.is_archived && activeChatSession && activeChatSession.hidden_message_count > 0 && (
          <Alert
            className="chat-context-notice"
            type="info"
            showIcon
            message={`已从模型上下文中截断 ${activeChatSession.hidden_message_count} 条历史消息。`}
            action={(
              <Tooltip title="查看已隐藏历史">
                <Button
                  aria-label="查看已隐藏历史"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => {
                    setHiddenHistoryOpen(true)
                    void onViewHiddenHistory()
                  }}
                />
              </Tooltip>
            )}
          />
        )}
        {contextCannotFit && (
          <Alert
            className="chat-context-notice"
            type="error"
            showIcon
            message="当前模型的实际输入上下文不足，压缩后仍无法容纳文档工作区与近期对话。请提高压缩阈值或选择更大上下文模型。"
          />
        )}
        {thinkingStatus && (!streaming || thinkingStatus !== liveLabel) && (
          <Text className="chat-thinking-status" type="secondary">{thinkingStatus}</Text>
        )}
      </div>

      {taskPlan && <TaskPlanPanel plan={taskPlan} live={streaming} />}

      <div className="chat-messages-shell">
        <div className="chat-messages" ref={messageListRef} onScroll={(event) => {
          const element = event.currentTarget
          if (element.scrollTop <= 96 && element.scrollHeight > element.clientHeight + 20) requestOlderMessages(element)
        }}>
          <div className="chat-messages-content" ref={setMessageListContentElement}>
        {hasOlderMessages && (
          <div className="chat-history-loader">
            <Button
              type="text"
              size="small"
              icon={olderMessagesLoading ? <LoadingOutlined spin /> : <UpOutlined />}
              disabled={olderMessagesLoading}
              onClick={(event) => {
                const element = event.currentTarget.closest('.chat-messages')
                if (element instanceof HTMLDivElement) requestOlderMessages(element)
              }}
            >{olderMessagesLoading ? '正在加载' : '加载更早记录'}</Button>
          </div>
        )}
        {messages.length === 0 && !streaming && (
          <div className="chat-empty">
            <Text strong>开始排版对话</Text>
            <Text type="secondary">告诉我想如何调整这篇推文，我会直接修改预览内容。</Text>
            <div className="chat-quick-prompts">
              {['优化标题与开头层级', '统一正文段落和行距', '检查并修复公众号兼容性'].map((prompt) => (
                <button key={prompt} type="button" onClick={() => onContextDraftChange(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <ChatHistoryTurn
            key={msg.id}
            messageItem={msg}
            currentUserId={currentUserId}
            editingDisabled={streaming}
            onEditRequest={handleEditRequest}
            suspendChatAutoFollow={suspendChatAutoFollow}
            resumeChatAutoFollow={resumeChatAutoFollow}
          />
        ))}

        {conversationError && (
          <article className="chat-turn chat-turn-assistant chat-turn-error">
            <div className="chat-turn-body">
              <div className="chat-turn-bubble">
                <AgentRunNotice notice={{ kind: 'error', title: '对话请求未完成', detail: conversationError }} />
              </div>
              <div className="chat-turn-meta"><span>排版助手</span></div>
            </div>
          </article>
        )}

        {showActiveAssistantTurn && (
          <article className="chat-turn chat-turn-assistant chat-turn-streaming">
              <div className="chat-turn-body">
              <div className="chat-turn-bubble">
                {streaming && !runtimeContextCompacting && (
                  <div className={`chat-streaming-label${activeTool ? ' is-tool' : ''}`}>
                    <i /> <span className="chat-streaming-label-text">{liveLabel}</span>
                  </div>
                )}
                <AssistantTurnTimeline
                  blocks={streamBlocks}
                  fallbackContent={streamText}
                  fallbackTrace={reasoningTrace}
                  fallbackTools={toolActivities}
                  streaming
                  suspendChatAutoFollow={suspendChatAutoFollow}
                  resumeChatAutoFollow={resumeChatAutoFollow}
                  archiveScrollAnchorEnabled={false}
                />
                {streaming && runtimeContextCompacting ? (
                  <div className="chat-context-compacting" role="status" aria-live="polite">
                    <div className="chat-streaming-label">
                      <i /> <span className="chat-streaming-label-text">正在压缩上下文</span>
                    </div>
                    <div className="chat-context-compacting-detail">
                      {contextStats?.compaction_location === '新分支请求前'
                        ? '正在为新分支重建上下文，完成后继续执行…'
                        : '正在整理较早对话和工具结果，完成后继续执行…'}
                    </div>
                  </div>
                ) : streaming && streamBlocks.length === 0 && !streamText && reasoningTrace.status === 'idle' && toolActivities.length === 0 ? (
                  <div className="chat-streaming-placeholder">正在准备排版方案…</div>
                ) : null}
                {streamNotice && <AgentRunNotice notice={streamNotice} />}
              </div>
              <div className="chat-turn-meta"><span>排版助手</span></div>
            </div>
          </article>
        )}

        {queuedMessages.length > 0 && (
          <section className="chat-queue" aria-label="待处理队列">
            <div className="chat-queue-header">
              <span className="chat-queue-title"><UnorderedListOutlined aria-hidden="true" />待处理队列</span>
              <div className="chat-queue-header-actions">
                {queuePaused && <span role="status">已暂停</span>}
                <span className="chat-queue-count">{queuedMessages.length}</span>
                {queuePaused && (
                  <Button
                    size="small"
                    type="link"
                    icon={<SendOutlined />}
                    disabled={streaming || stopping || submitting || Boolean(pendingUserQuestion)}
                    onClick={onResumeQueuedMessages}
                  >
                    继续队列
                  </Button>
                )}
              </div>
            </div>
            <div className="chat-queue-list" role="list">
              {queuedMessages.map((queuedMessage, index) => {
                const isEditing = editingQueuedMessageId === queuedMessage.id
                const isDragging = draggedQueuedMessageId === queuedMessage.id
                const isDropTarget = queuedDropTargetId === queuedMessage.id && !isDragging
                return (
                  <article
                    className={`chat-queue-item${isDragging ? ' is-dragging' : ''}${isDropTarget ? ' is-drop-target' : ''}${isEditing ? ' is-editing' : ''}`}
                    key={queuedMessage.id}
                    role="listitem"
                    onDragOver={(event) => {
                      if (!draggedQueuedMessageId || isDragging) return
                      event.preventDefault()
                      event.dataTransfer.dropEffect = 'move'
                      setQueuedDropTargetId(queuedMessage.id)
                    }}
                    onDrop={(event) => {
                      event.preventDefault()
                      const fromIndex = queuedMessages.findIndex((item) => item.id === draggedQueuedMessageId)
                      finishQueuedDrag()
                      moveQueuedMessage(fromIndex, index)
                    }}
                  >
                    <div className="chat-queue-item-leading">
                      <span className="chat-queue-order" aria-label={index === 0 ? '下一项' : `第 ${index + 1} 项`}>
                        {index === 0 ? '下一项' : index + 1}
                      </span>
                      <span
                        className="chat-queue-drag-handle"
                        aria-hidden="true"
                        draggable={!isEditing}
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = 'move'
                          event.dataTransfer.setData('text/plain', queuedMessage.id)
                          setDraggedQueuedMessageId(queuedMessage.id)
                        }}
                        onDragEnd={finishQueuedDrag}
                      >
                        <DragOutlined />
                      </span>
                    </div>
                    <div className="chat-queue-content">
                      <div className="chat-queue-request">
                        {queuedMessage.images.length > 0 && (
                          <div className="chat-queue-images" aria-label="待处理图片">
                            <Image.PreviewGroup>
                              {queuedMessage.images.map((image) => (
                                <Image
                                  className="chat-queue-image"
                                  key={image.id}
                                  src={image.preview_url}
                                  alt={image.filename}
                                  preview={{ mask: <span className="chat-history-image-mask"><ZoomInOutlined />放大</span> }}
                                />
                              ))}
                            </Image.PreviewGroup>
                          </div>
                        )}
                        <div className="chat-queue-message">{queuedMessage.content}</div>
                      </div>
                    </div>
                    <div className="chat-queue-actions">
                      {isEditing ? (
                        <Tooltip title="取消编辑">
                          <Button aria-label="取消编辑" type="text" size="small" icon={<CloseOutlined />} onClick={cancelQueuedMessageEdit} />
                        </Tooltip>
                      ) : (
                        <>
                          {queuedMessages.length > 1 && (
                            <Tooltip title="上移任务">
                              <Button aria-label="上移任务" type="text" size="small" icon={<ArrowUpOutlined />} disabled={index === 0 || stopping} onClick={() => moveQueuedMessage(index, index - 1)} />
                            </Tooltip>
                          )}
                          {queuedMessages.length > 1 && (
                            <Tooltip title="下移任务">
                              <Button aria-label="下移任务" type="text" size="small" icon={<ArrowDownOutlined />} disabled={index === queuedMessages.length - 1 || stopping} onClick={() => moveQueuedMessage(index, index + 1)} />
                            </Tooltip>
                          )}
                          <Tooltip title="编辑待处理内容">
                            <Button aria-label="编辑待处理内容" type="text" size="small" icon={<EditOutlined />} disabled={stopping || Boolean(editingQueuedMessageId)} onClick={() => beginQueuedMessageEdit(queuedMessage)} />
                          </Tooltip>
                          <Tooltip title="取消待处理要求">
                            <Button aria-label="取消待处理要求" type="text" size="small" icon={<CloseOutlined />} disabled={stopping} onClick={() => onRemoveQueuedMessage(queuedMessage.id)} />
                          </Tooltip>
                        </>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        )}
          </div>
        </div>
        {!isAtBottom && (
          <Tooltip title="回到最新">
            <Button
              aria-label="回到最新"
              className="chat-scroll-to-latest"
              shape="circle"
              icon={<ArrowDownOutlined />}
              onClick={() => {
                resumeAllChatAutoFollow()
                void scrollToBottom({ animation: 'instant', ignoreEscapes: true })
              }}
            />
          </Tooltip>
        )}
      </div>

      <div className={`chat-input-area${pendingUserQuestion ? ' has-user-question' : ''}`}>
        <div className="chat-composer-shell">
          {pendingUserQuestion ? (
            <UserQuestionPanel
              key={pendingUserQuestion.id}
              question={pendingUserQuestion}
              submitting={questionSubmitting}
              onAnswer={onAnswerUserQuestion}
              onActivity={onUserQuestionActivity}
              onTimeoutElapsed={onUserQuestionTimeoutElapsed}
              onStop={onStop}
            />
          ) : (
            <>
          {imageUploadProgress ? <div className="chat-image-upload-progress"><ImageUploadProgress progress={imageUploadProgress} /></div> : imageUploading && (
            <div className="chat-image-uploading" role="status">
              <LoadingOutlined spin />
              <span>正在添加图片</span>
            </div>
          )}
          {editingQueuedMessageId && (
            <div className="chat-queue-composer-status">
              <span>正在编辑待处理任务</span>
              <Tooltip title="取消编辑">
                <Button aria-label="取消编辑" type="text" size="small" icon={<CloseOutlined />} onClick={cancelQueuedMessageEdit} />
              </Tooltip>
            </div>
          )}
          <PromptComposer
            key={editingQueuedMessageId ?? 'draft'}
            ref={composerRef}
            value={composerDraft}
            references={editingQueuedMessageId ? [] : selectedElements}
            templates={editingQueuedMessageId ? [] : composerTemplates}
            images={editingQueuedMessageId ? [] : imageAttachments}
            onChange={handleInputChange}
            onSubmit={handleSend}
            disabled={composerDisabled}
            onRemoveReference={onRemoveSelectedElement}
            onDuplicateReference={onDuplicateSelectedElement}
            onMoveReference={onMoveSelectedElement}
            onRemoveTemplate={onRemoveComposerTemplate}
            onRemoveImage={onRemoveImage}
            onMoveImage={onMoveImage}
            acceptImages={isMultimodal && !editingQueuedMessageId}
            onPasteImages={onUploadImages}
          />
          <div className="chat-input-actions">
            <div className="chat-input-actions-start">
              <Tooltip title="模仿排版">
                <Button
                  aria-label="模仿排版"
                  icon={<FormatPainterOutlined />}
                  disabled={composerDisabled || !modelId || activeChatSession?.is_archived}
                  onClick={onOpenLayoutImitation}
                />
              </Tooltip>
              {isMultimodal && (
                <Tooltip title="添加图片">
                  <Button
                  aria-label="添加图片"
                  icon={<PaperClipOutlined />}
                  disabled={composerDisabled || imageUploading || Boolean(editingQueuedMessageId) || activeChatSession?.is_archived || imageAttachments.length >= MAX_CHAT_IMAGES_PER_MESSAGE}
                    onClick={() => imageInputRef.current?.click()}
                  />
                </Tooltip>
              )}
              <Text type="secondary">{editingQueuedMessageId ? 'Enter 保存，Shift+Enter 换行' : 'Enter 发送，Shift+Enter 换行'}</Text>
            </div>
            <div className="chat-input-actions-submit">
              {chatSettingsTrigger}
              {contextStats && <ContextUsage stats={contextStats} onCompactContext={onCompactContext} />}
              {streaming && (
                <Tooltip title="停止生成">
                  <Button aria-label="停止生成" danger icon={<StopOutlined />} loading={stopping} disabled={stopping} onClick={onStop} />
                </Tooltip>
              )}
              <Tooltip title={editingQueuedMessageId ? '保存队列修改' : streaming ? '加入待处理队列' : '发送'}>
                <Button
                  aria-label={editingQueuedMessageId ? '保存队列修改' : streaming ? '加入待处理队列' : '发送'}
                  type="primary"
                  icon={editingQueuedMessageId ? <CheckOutlined /> : <SendOutlined />}
                  disabled={!canSend}
                  onClick={handleSend}
                />
              </Tooltip>
            </div>
          </div>
            </>
          )}
        </div>
        {isMultimodal && (
          <input
            ref={imageInputRef}
            className="chat-image-file-input"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            onChange={(event) => {
              const files = Array.from(event.target.files ?? [])
              event.target.value = ''
              if (files.length) onUploadImages(files)
            }}
          />
        )}
      </div>
    </div>
    <Drawer
      title="会话设置"
      placement="bottom"
      height={244}
      open={isCompact && settingsDrawerOpen}
      onClose={() => setSettingsDrawerOpen(false)}
      destroyOnHidden
      className="chat-settings-drawer"
    >
      {chatSettingsContent}
    </Drawer>
    <Modal
      title="重命名对话"
      open={renameOpen}
      okText="保存"
      cancelText="取消"
      onCancel={() => setRenameOpen(false)}
      onOk={() => {
        if (!activeChatSession || !renameTitle.trim()) return
        void Promise.resolve(onRenameSession(activeChatSession.id, renameTitle.trim())).then(() => setRenameOpen(false))
      }}
    >
      <Input value={renameTitle} maxLength={160} autoFocus onChange={(event) => setRenameTitle(event.target.value)} />
    </Modal>
    <Modal
      title="已隐藏历史"
      open={hiddenHistoryOpen}
      footer={<Button onClick={() => { setHiddenHistoryOpen(false); onClearHiddenHistory() }}>关闭</Button>}
      onCancel={() => { setHiddenHistoryOpen(false); onClearHiddenHistory() }}
    >
      <div className="chat-hidden-history">
        {hiddenHistory.length === 0 ? (
          <Text type="secondary">正在加载已隐藏的历史消息…</Text>
        ) : hiddenHistory.map((item) => (
          <article key={item.id} className={`chat-hidden-history-item is-${item.role}`}>
            <Text type="secondary">{messageAuthorLabel(item, currentUserId)}</Text>
            {item.role === 'assistant' ? <MemoMarkdownContent content={item.content} /> : <div>{item.content}</div>}
          </article>
        ))}
      </div>
    </Modal>
    <Modal
      title="无法从历史消息重新提问"
      open={reaskConflict !== null}
      closable={!resolvingReaskConflict}
      maskClosable={!resolvingReaskConflict}
      keyboard={!resolvingReaskConflict}
      onCancel={onDismissReaskConflict}
      footer={(
        <>
          <Button disabled={resolvingReaskConflict} onClick={onDismissReaskConflict}>继续编辑</Button>
          <Button danger type="primary" loading={resolvingReaskConflict} onClick={onDiscardReaskConflict}>舍弃修改并重新发送</Button>
        </>
      )}
    >
      <p>
        {reaskConflict?.kind === 'local_draft'
          ? '当前预览存在尚未保存的手动修改。'
          : '当前推文在所选历史要求之后已被手动或其他对话修改。'}
      </p>
      <p>舍弃修改会回退到该历史要求之前，并丢弃之后的当前稿改动；已保存内容仍可从版本历史恢复。</p>
    </Modal>
    </ChatImagePreviewContext.Provider>
  )
}

export function toolLabel(tool: ToolExecution): string {
  if (tool.name === 'view_article_images' || tool.name === 'view_chat_images_page') {
    const details = tool.activity?.kind === 'image_view' ? tool.activity.details : undefined
    const dimensionsOnly = tool.arguments.include_image === false
      || details?.include_image_requested === false
      || (details?.image_content_included === false && Array.isArray(details.items) && details.items.length > 0)
    if (dimensionsOnly) return tool.name === 'view_chat_images_page' ? '分页读取附图尺寸' : '读取图片尺寸'
  }
  return TOOL_LABELS[tool.name] ?? tool.name
}

const ChatHistoryTurn = memo(function ChatHistoryTurn({
  messageItem,
  currentUserId,
  editingDisabled,
  onEditRequest,
  suspendChatAutoFollow,
  resumeChatAutoFollow,
}: {
  messageItem: ChatMessageItem
  currentUserId: number | undefined
  editingDisabled: boolean
  onEditRequest: (message: ChatMessageItem) => void
  suspendChatAutoFollow: () => number
  resumeChatAutoFollow: (suspensionId: number | null) => void
}) {
  return (
    <article className={`chat-turn chat-turn-${messageItem.role}`}>
      <div className="chat-turn-body">
        <div className="chat-turn-bubble">
          {messageItem.role === 'assistant' ? (
            <AssistantTurnTimeline
              blocks={messageItem.turn_blocks}
              fallbackContent={messageItem.content}
              fallbackTrace={messageItem.reasoning_trace}
              fallbackTools={messageItem.tool_calls}
              streaming={false}
              suspendChatAutoFollow={suspendChatAutoFollow}
              resumeChatAutoFollow={resumeChatAutoFollow}
              archiveScrollAnchorEnabled={!editingDisabled}
            />
          ) : messageItem.role === 'tool' ? (
            messageItem.turn_blocks?.some((block) => block.type === 'context_compaction') ? (
              <AssistantTurnTimeline
                blocks={messageItem.turn_blocks}
                fallbackContent=""
                fallbackTrace={messageItem.reasoning_trace}
                fallbackTools={[]}
                streaming={false}
                suspendChatAutoFollow={suspendChatAutoFollow}
                resumeChatAutoFollow={resumeChatAutoFollow}
                archiveScrollAnchorEnabled={!editingDisabled}
              />
            ) : <ContextCompactionNotice content={messageItem.content} />
          ) : (
            <div className="chat-turn-content">
              <CollapsibleMessage><UserMessageContent
                content={messageItem.content}
                elements={messageItem.selected_elements ?? []}
                templates={messageItem.template_refs ?? []}
                images={messageItem.image_attachments ?? []}
              /></CollapsibleMessage>
            </div>
          )}
        </div>
        <div className="chat-turn-meta">
          <span>
            {messageAuthorLabel(messageItem, currentUserId)}
            {messageItem.role === 'assistant' && messageItem.model_usage && (
              <>
                {' · '}
                <Popover
                  content={<ModelUsageDetails usage={messageItem.model_usage} />}
                  classNames={{ root: 'chat-model-usage-popover', container: 'chat-model-usage-container' }}
                  color="var(--app-surface-raised)"
                  placement="top"
                  trigger={['hover', 'click']}
                >
                  <button type="button" className="chat-turn-model-usage" aria-label="查看本轮模型用量">
                    {modelUsageLabel(messageItem.model_usage)}
                  </button>
                </Popover>
              </>
            )}
            {' · '}{formatMessageTime(messageItem.created_at)}
          </span>
          {messageItem.role === 'user' && (
            <Tooltip title="从这条要求回退并重新提问">
              <Button
                className="chat-edit-request"
                aria-label="从这条要求重新提问"
                type="text"
                size="small"
                icon={<EditOutlined />}
                disabled={editingDisabled}
                onClick={() => onEditRequest(messageItem)}
              />
            </Tooltip>
          )}
        </div>
      </div>
    </article>
  )
})

function messageAuthorLabel(messageItem: ChatMessageItem, currentUserId: number | undefined): string {
  if (messageItem.role === 'tool') return '系统'
  if (messageItem.role !== 'user') return '排版助手'
  if (messageItem.created_by?.id === currentUserId) return '你'
  return messageItem.created_by?.display_name || messageItem.created_by?.username || '未知用户'
}

function modelUsageNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0
}

function modelUsageValues(usage: NonNullable<ChatMessageItem['model_usage']>) {
  const inputTokens = modelUsageNumber(usage.input_tokens)
  const cacheReadTokens = modelUsageNumber(usage.cache_read_tokens)
  const reportedCacheHitRate = typeof usage.cache_hit_rate === 'number' && Number.isFinite(usage.cache_hit_rate)
    ? Math.min(100, Math.max(0, Math.round(usage.cache_hit_rate)))
    : Math.round(cacheReadTokens / Math.max(1, inputTokens) * 100)

  return {
    modelNames: Array.isArray(usage.model_names)
      ? usage.model_names.filter((name): name is string => typeof name === 'string' && name.trim().length > 0).join(' / ') || '未知模型'
      : '未知模型',
    inputTokens,
    outputTokens: modelUsageNumber(usage.output_tokens),
    totalTokens: modelUsageNumber(usage.total_tokens),
    cacheReadTokens,
    cacheHitRate: reportedCacheHitRate,
    callCount: modelUsageNumber(usage.call_count),
  }
}

function formatModelUsageTokens(value: number): string {
  if (value >= 999_950) return `${Number((value / 1_000_000).toFixed(2))}M`
  if (value >= 1_000) return `${Number((value / 1_000).toFixed(1))}K`
  return value.toLocaleString()
}

export function modelUsageLabel(usage: NonNullable<ChatMessageItem['model_usage']>): string {
  const { modelNames, totalTokens, cacheHitRate, callCount } = modelUsageValues(usage)
  return usage.usage_reported
    ? `${modelNames} · 本轮 ${callCount} 次累计 ${formatModelUsageTokens(totalTokens)} tokens · 缓存命中 ${cacheHitRate}%`
    : `${modelNames} · Token 未返回`
}

export function modelUsageDetail(usage: NonNullable<ChatMessageItem['model_usage']>): string {
  const { modelNames, inputTokens, outputTokens, totalTokens, cacheReadTokens, cacheHitRate, callCount } = modelUsageValues(usage)
  if (!usage.usage_reported) return `${modelNames} 未返回 token 用量`
  return `${modelNames}：本轮累计 ${callCount.toLocaleString()} 次模型调用；输入 ${inputTokens.toLocaleString()} tokens；缓存命中 ${cacheReadTokens.toLocaleString()} tokens（${cacheHitRate}%）；输出 ${outputTokens.toLocaleString()} tokens；合计 ${totalTokens.toLocaleString()} tokens`
}

function ModelUsageDetails({ usage }: { usage: NonNullable<ChatMessageItem['model_usage']> }) {
  const { modelNames, inputTokens, outputTokens, totalTokens, cacheReadTokens, cacheHitRate, callCount } = modelUsageValues(usage)
  return (
    <div className="chat-model-usage-details">
      <div className="chat-model-usage-heading">
        <strong>本轮用量</strong>
        {usage.usage_reported && <span>{callCount.toLocaleString()} 次调用</span>}
      </div>
      <div className="chat-model-usage-models">{modelNames}</div>
      {usage.usage_reported ? (
        <>
          <div className="chat-model-usage-total">
            <span>Token 合计</span>
            <div><strong title={`${totalTokens.toLocaleString()} tokens`}>{formatModelUsageTokens(totalTokens)}</strong><span>tokens</span></div>
          </div>
          <dl className="chat-model-usage-breakdown">
            <div><dt>输入</dt><dd title={`${inputTokens.toLocaleString()} tokens`}>{formatModelUsageTokens(inputTokens)}</dd></div>
            <div><dt>输出</dt><dd title={`${outputTokens.toLocaleString()} tokens`}>{formatModelUsageTokens(outputTokens)}</dd></div>
          </dl>
          <div className="chat-model-usage-cache">
            <div className="chat-model-usage-cache-heading"><span>缓存命中率</span><strong>{cacheHitRate}%</strong></div>
            <div className="chat-model-usage-cache-track" aria-hidden="true">
              <div style={{ width: `${Math.min(100, Math.max(0, cacheHitRate))}%` }} />
            </div>
            <div className="chat-model-usage-cache-caption"><span>缓存读取（已计入输入）</span><span title={`${cacheReadTokens.toLocaleString()} tokens`}>{formatModelUsageTokens(cacheReadTokens)}</span></div>
          </div>
        </>
      ) : <p className="chat-model-usage-empty">模型未返回 Token 用量</p>}
    </div>
  )
}

export function formatMessageTime(value: string, now = new Date()): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  const dayDifference = Math.round((
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
    - Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())
  ) / 86_400_000)
  if (dayDifference === 0) return time
  if (dayDifference === 1) return `昨天 ${time}`
  if (dayDifference > 1 && dayDifference <= 7) return `${dayDifference}天前 ${time}`

  const dateLabel = [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((part, index) => index === 0 ? String(part) : String(part).padStart(2, '0'))
    .join('-')
  return `${dateLabel} ${time}`
}

function streamingLabel(blocks: AssistantTurnBlock[], streamText: string): string {
  const runningTool = getRunningTool(blocks)
  if (runningTool) return runningTool.preparing ? `正在准备${toolLabel(runningTool)}` : toolLabel(runningTool)
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.type === 'thought' && block.state === 'active') return 'Thinking'
    if (block.type === 'content' && block.state === 'active') return '正在生成回复'
  }
  return streamText ? '正在生成回复' : '正在处理中'
}

function getRunningTool(blocks: AssistantTurnBlock[]): ToolExecution | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const tool = blocks[index].type === 'tool' ? blocks[index].tool : null
    if (tool?.status === 'running') return tool
  }
  return null
}

function latestTaskPlanFromMessages(messages: ChatMessageItem[]): TaskPlan | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const messageItem = messages[index]
    if (messageItem.role !== 'assistant') continue
    return latestTaskPlanFromBlocks(messageItem.turn_blocks, messageItem.tool_calls)
  }
  return null
}

function latestTaskPlanFromBlocks(blocks: AssistantTurnBlock[], fallbackTools: ToolExecution[]): TaskPlan | null {
  const timelineTools = blocks.flatMap((block) => block.type === 'tool' && block.tool ? [block.tool] : [])
  return latestTaskPlanFromTools(timelineTools) ?? latestTaskPlanFromTools(fallbackTools)
}

function latestTaskPlanFromTools(tools: ToolExecution[]): TaskPlan | null {
  for (let index = tools.length - 1; index >= 0; index -= 1) {
    const plan = taskPlanFromTool(tools[index])
    if (plan) return plan
  }
  return null
}

function taskPlanFromTool(tool: ToolExecution): TaskPlan | null {
  if (!isTaskPlanTool(tool)) return null
  const activity = tool.activity
  if (!activity) return null
  const structuredItems = taskPlanItemsFromDetails(activity.details?.tasks)
  const items = structuredItems.length > 0 ? structuredItems : taskPlanItemsFromTargets(activity.targets)
  return items.length > 0 ? { items } : null
}

function isTaskPlanTool(tool: ToolExecution | null | undefined): tool is ToolExecution {
  return tool?.name === 'update_task_plan' && tool.activity?.kind === 'plan'
}

function AgentRunNotice({ notice }: { notice: ChatRunNotice }) {
  const [detailExpanded, setDetailExpanded] = useState(false)
  const [retryRemainingSeconds, setRetryRemainingSeconds] = useState<number | null>(null)
  const retryLabel = notice.kind === 'retrying' && notice.attempt && notice.maxAttempts
    ? `第 ${notice.attempt}/${notice.maxAttempts} 次`
    : ''
  const detail = notice.detail.trim()

  useEffect(() => {
    if (
      notice.kind !== 'retrying'
      || typeof notice.retryDelaySeconds !== 'number'
      || typeof notice.retryStartedAtMs !== 'number'
    ) {
      setRetryRemainingSeconds(null)
      return undefined
    }
    const deadline = notice.retryStartedAtMs + Math.max(0, notice.retryDelaySeconds) * 1000
    const update = () => {
      const remaining = Math.max(0, deadline - Date.now()) / 1000
      setRetryRemainingSeconds(Math.ceil(remaining * 100) / 100)
    }
    let timer: number | null = null
    const stopTimer = () => {
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    }
    const syncTimer = () => {
      stopTimer()
      update()
      if (document.visibilityState === 'visible') {
        timer = window.setInterval(update, 100)
      }
    }
    syncTimer()
    document.addEventListener('visibilitychange', syncTimer)
    window.addEventListener('focus', syncTimer)
    return () => {
      document.removeEventListener('visibilitychange', syncTimer)
      window.removeEventListener('focus', syncTimer)
      stopTimer()
    }
  }, [notice.kind, notice.retryDelaySeconds, notice.retryStartedAtMs])

  const formattedRetryRemaining = retryRemainingSeconds === null
    ? ''
    : `${retryRemainingSeconds.toFixed(2).replace(/\.?(0+)$/, '')} 秒后重试${notice.attempt && notice.maxAttempts ? `（剩余 ${Math.max(0, notice.maxAttempts - notice.attempt)} 次）` : ''}`
  const fullDetail = formattedRetryRemaining ? `${detail}；${formattedRetryRemaining}。` : detail
  const collapsible = fullDetail.length > 220
  const displayedDetail = collapsible && !detailExpanded
    ? `${fullDetail.slice(0, 220).trimEnd()}…`
    : fullDetail

  useEffect(() => {
    setDetailExpanded(false)
  }, [notice.detail])

  return (
    <div className={`chat-run-notice is-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
      {notice.kind === 'retrying'
        ? <SyncOutlined spin />
        : notice.kind === 'success'
          ? <CheckCircleFilled />
          : notice.kind === 'info'
            ? <InfoCircleFilled />
            : <ExclamationCircleFilled />}
      <div className="chat-run-notice-copy">
        <div className="chat-run-notice-title">
          <strong>{notice.title}</strong>
          {retryLabel && <span>{retryLabel}</span>}
        </div>
        <div className={`chat-run-notice-detail${collapsible ? ' is-collapsible' : ''}`}>
          <span>{displayedDetail}</span>
          {collapsible && (
            <Button
              type="text"
              size="small"
              className="chat-run-notice-detail-toggle"
              icon={detailExpanded ? <UpOutlined /> : <DownOutlined />}
              onClick={() => setDetailExpanded((expanded) => !expanded)}
            >
              {detailExpanded ? '收起完整信息' : '展开完整错误'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

interface ContextCompactionMetrics {
  savedTokens: string
  compressionRate: string
  beforeTokens: string
  afterTokens: string
}

function contextCompactionMetrics(detail: string): ContextCompactionMetrics | null {
  const match = detail.match(/^节省\s+([\d,]+)\s+tokens，压缩率\s+([\d.]+)%（([\d,]+)\s*→\s*([\d,]+)\s+tokens）[。.]?$/)
  if (!match) return null
  return {
    savedTokens: match[1],
    compressionRate: match[2],
    beforeTokens: match[3],
    afterTokens: match[4],
  }
}

function ContextCompactionNotice({ content }: { content: string }) {
  const notice = contextCompactionNotice(content)
  const metrics = notice.kind === 'success' ? contextCompactionMetrics(notice.detail) : null
  const isSuccess = notice.kind === 'success'

  return (
    <div className={`context-compaction-notice is-${notice.kind}`} role="status">
      <span className="context-compaction-notice-icon" aria-hidden="true">
        {isSuccess ? <CheckCircleFilled /> : <InfoCircleFilled />}
      </span>
      <div className="context-compaction-notice-copy">
        <div className="context-compaction-notice-heading">
          <strong>{notice.title}</strong>
          {isSuccess && <span className="context-compaction-notice-badge">已持久化</span>}
        </div>
        {metrics ? (
          <div className="context-compaction-notice-metrics" aria-label={notice.detail}>
            <div className="context-compaction-notice-token-flow">
              <span className="context-compaction-notice-token-value">
                <small>压缩前</small>
                <b>{metrics.beforeTokens}</b>
              </span>
              <ArrowRightOutlined />
              <span className="context-compaction-notice-token-value is-result">
                <small>压缩后</small>
                <b>{metrics.afterTokens}</b>
              </span>
              <em>tokens</em>
            </div>
            <div className="context-compaction-notice-savings">
              <small>本次节省</small>
              <b>{metrics.savedTokens}</b>
              <em>tokens</em>
              <span>压缩率 {metrics.compressionRate}%</span>
            </div>
          </div>
        ) : (
          <div className="context-compaction-notice-detail">{notice.detail}</div>
        )}
      </div>
    </div>
  )
}

function taskPlanItemsFromDetails(value: unknown): TaskPlanItem[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const { step, status } = item as Record<string, unknown>
    if (typeof step !== 'string' || !isTaskPlanStatus(status)) return []
    const normalisedStep = step.trim()
    return normalisedStep ? [{ step: normalisedStep, status }] : []
  })
}

function taskPlanItemsFromTargets(targets: NonNullable<ToolExecution['activity']>['targets'] | undefined): TaskPlanItem[] {
  if (!Array.isArray(targets)) return []
  const labelToStatus: Record<string, TaskPlanItem['status']> = {
    待办: 'pending',
    进行中: 'in_progress',
    已完成: 'done',
  }
  return targets.flatMap((target) => {
    const text = target.text?.trim() ?? ''
    const match = /^(待办|进行中|已完成)\s*[·.]\s*(.+)$/.exec(text)
    const status = match ? labelToStatus[match[1]] : undefined
    const step = match?.[2].trim()
    return status && step ? [{ step, status }] : []
  })
}

function isTaskPlanStatus(value: unknown): value is TaskPlanItem['status'] {
  return value === 'pending' || value === 'in_progress' || value === 'done'
}

function TaskPlanPanel({ plan, live }: { plan: TaskPlan; live: boolean }) {
  return <AiTodoList items={plan.items} live={live} />
}

function UserMessageContent({
  content,
  elements = [],
  templates = [],
  images = [],
}: {
  content: string
  elements?: SelectedElementContext[]
  templates?: Array<{ id: number; name: string }>
  images?: ChatImageAttachment[]
}) {
  const referencedElements = new Set<number>()
  const referencedTemplates = visibleTemplateReferenceIndexes(content, templates.length)
  const parts = content.split(/(@元素\d+|@组件\d+)/g)
  return (
    <>
      {parts.map((part, index) => {
        const elementMatch = /^@元素(\d+)$/.exec(part)
        if (elementMatch) {
          const referenceIndex = Number(elementMatch[1]) - 1
          const element = elements[referenceIndex]
          if (!element) return <span key={`${part}-${index}`}>{part}</span>
          referencedElements.add(referenceIndex)
          return (
            <Tooltip key={`${part}-${index}`} title={<ElementRenderPreview html={element.html} />}>
              <Tag className="selected-element-tag">@元素{referenceIndex + 1} &lt;{element.tag_name}&gt;</Tag>
            </Tooltip>
          )
        }

        const templateMatch = /^@组件(\d+)$/.exec(part)
        if (!templateMatch) return <span key={`${part}-${index}`}>{part}</span>
        const templateIndex = Number(templateMatch[1]) - 1
        const template = templates[templateIndex]
        if (!template || !referencedTemplates.has(templateIndex)) return <span key={`${part}-${index}`}>{part}</span>
        return <Tag key={`${part}-${index}`} className="chat-template-attachment">@组件{templateIndex + 1} &lt;{template.name}&gt;</Tag>
      })}
      {elements.map((element, index) => !referencedElements.has(index) && (
        <Tooltip key={`fallback-${index}`} title={<ElementRenderPreview html={element.html} />}>
          <Tag className="selected-element-tag">@元素{index + 1} &lt;{element.tag_name}&gt;</Tag>
        </Tooltip>
      ))}
      {images.length > 0 && (
        <span className="chat-history-images">
          <Image.PreviewGroup>
            {images.map((image) => (
              <Image
                className="chat-history-image"
                key={image.id}
                src={image.preview_url}
                alt={image.filename}
                preview={{ mask: <span className="chat-history-image-mask"><ZoomInOutlined />放大</span> }}
              />
            ))}
          </Image.PreviewGroup>
        </span>
      )}
    </>
  )
}

function AssistantTurnTimeline({
  blocks,
  fallbackContent,
  fallbackTrace,
  fallbackTools,
  streaming,
  suspendChatAutoFollow,
  resumeChatAutoFollow,
  archiveScrollAnchorEnabled,
}: {
  blocks: AssistantTurnBlock[]
  fallbackContent: string
  fallbackTrace: ReasoningTrace
  fallbackTools: ToolExecution[]
  streaming: boolean
  suspendChatAutoFollow: () => number
  resumeChatAutoFollow: (suspensionId: number | null) => void
  archiveScrollAnchorEnabled: boolean
}) {
  const normalisedBlocks = normaliseAssistantTurnBlocks(blocks)
  const hasStructuredContent = normalisedBlocks.some((block) => block.type === 'content' && block.content.trim())
  const rawTimelineBlocks = normalisedBlocks.length > 0
    ? (!hasStructuredContent && fallbackContent
        ? [...normalisedBlocks, { id: 'legacy-final-content', type: 'content' as const, state: 'done' as const, content: fallbackContent, duration_ms: null, tool: null }]
        : normalisedBlocks)
    : legacyTimelineBlocks(fallbackContent, fallbackTrace, fallbackTools)
  // The model may attempt a second ask_user call immediately after a timeout.
  // It receives a recoverable ToolMessage, but that rejected retry is not a
  // new user interaction and should not pollute the visible timeline.
  const timelineBlocks = visibleAssistantTurnBlocks(mergeFallbackThoughtBlocks(rawTimelineBlocks, fallbackTrace))
  const displayBlocks = streaming ? timelineBlocks : settleHistoricalTimeline(timelineBlocks)
  const recoveredAfterRestart = !streaming && fallbackContent.includes('服务已重启，未完成的 Agent 已停止')
  const [archiveExpanded, setArchiveExpanded] = useState(recoveredAfterRestart)
  const timelineRef = useRef<HTMLDivElement>(null)
  const archiveAnchorRef = useRef<{ scrollTop: number } | null>(null)
  const archiveAutoFollowSuspensionRef = useRef<number | null>(null)
  const processFollowRef = useRef(new WeakMap<HTMLElement, boolean>())
  const processLastScrollTopRef = useRef(new WeakMap<HTMLElement, number>())

  useEffect(() => () => {
    resumeChatAutoFollow(archiveAutoFollowSuspensionRef.current)
    archiveAutoFollowSuspensionRef.current = null
  }, [resumeChatAutoFollow])

  // History is always terminal. Older records may have been persisted before
  // their last tool-result event reached the server, but must never render as
  // a live Agent run after the user reopens the document.
  const isStreamingProcess = streaming
  const finalContentIndex = isStreamingProcess
    ? -1
    : findLastTimelineContentIndex(displayBlocks)
  const archiveBlocks = finalContentIndex >= 0
    ? displayBlocks.filter((_, index) => index !== finalContentIndex)
    : displayBlocks
  const finalContent = finalContentIndex >= 0
    ? displayBlocks[finalContentIndex].content
    : ''
  const timelineRevision = displayBlocks.map((block) => (
    `${block.id}:${block.state}:${block.content.length}:${block.tool?.status ?? ''}:${block.tool?.result?.length ?? 0}`
  )).join('|')

  const getProcessDetailsToFollow = useCallback(() => (
    Array.from(
      timelineRef.current?.querySelectorAll<HTMLElement>(
        '.aicss-thinking-reasoning-viewport.is-live, .tool-trace-detail.is-live',
      ) ?? [],
    )
  ), [])

  const scheduleProcessScroll = useCallback((force = false) => {
    if (!isStreamingProcess) return
    getProcessDetailsToFollow().forEach((container) => {
      const shouldFollow = processFollowRef.current.get(container) ?? true
      if (!force && !shouldFollow) return
      container.scrollTop = Math.max(0, container.scrollHeight - container.clientHeight)
      processFollowRef.current.set(container, true)
      processLastScrollTopRef.current.set(container, container.scrollTop)
    })
  }, [getProcessDetailsToFollow, isStreamingProcess])

  const handleProcessScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const container = event.currentTarget
    const currentTop = container.scrollTop
    const lastTop = processLastScrollTopRef.current.get(container) ?? currentTop
    const atBottom = container.scrollHeight - currentTop - container.clientHeight < 30

    // Match the main chat's intent model: an upward movement means the user is
    // reading earlier output, while reaching the bottom opts back into follow.
    if (currentTop < lastTop - 10) {
      processFollowRef.current.set(container, false)
    } else if (atBottom) {
      processFollowRef.current.set(container, true)
    }
    processLastScrollTopRef.current.set(container, currentTop)
  }, [])

  useLayoutEffect(() => {
    if (!isStreamingProcess) return
    scheduleProcessScroll()
    const frame = window.requestAnimationFrame(() => scheduleProcessScroll())
    return () => {
      window.cancelAnimationFrame(frame)
    }
  }, [isStreamingProcess, scheduleProcessScroll, timelineRevision])

  useEffect(() => {
    if (!isStreamingProcess) return
    scheduleProcessScroll()
  }, [isStreamingProcess, scheduleProcessScroll])

  const handleArchiveChange = useCallback((keys: string | string[]) => {
    const nextExpanded = (Array.isArray(keys) ? keys : [keys]).includes('process')
    const timeline = timelineRef.current
    const scrollContainer = timeline?.closest<HTMLElement>('.chat-messages')
    archiveAnchorRef.current = null
    if (archiveAutoFollowSuspensionRef.current !== null) {
      resumeChatAutoFollow(archiveAutoFollowSuspensionRef.current)
      archiveAutoFollowSuspensionRef.current = null
    }
    if (nextExpanded && archiveScrollAnchorEnabled && timeline && scrollContainer) {
      const distanceFromBottom = scrollContainer.scrollHeight
        - scrollContainer.scrollTop
        - scrollContainer.clientHeight
      // Historical disclosure layout changes must not be interpreted as live
      // output. Suspend the main content observer until this motion settles.
      archiveAutoFollowSuspensionRef.current = suspendChatAutoFollow()
      if (distanceFromBottom <= 4) {
        archiveAnchorRef.current = { scrollTop: scrollContainer.scrollTop }
      }
    }
    setArchiveExpanded(nextExpanded)
  }, [archiveScrollAnchorEnabled, resumeChatAutoFollow, suspendChatAutoFollow])

  useLayoutEffect(() => {
    if (!archiveExpanded || !archiveScrollAnchorEnabled) return
    const anchor = archiveAnchorRef.current
    const timeline = timelineRef.current
    const scrollContainer = timeline?.closest<HTMLElement>('.chat-messages')
    if (archiveAutoFollowSuspensionRef.current === null || !timeline || !scrollContainer) return

    let frame = 0
    let settleTimer = 0
    let active = true
    let observer: ResizeObserver | null = null
    const restore = () => {
      if (!active || !anchor) return
      const timeline = timelineRef.current
      const scrollContainer = timeline?.closest<HTMLElement>('.chat-messages')
      if (!timeline || !scrollContainer) return
      // Keep the viewport at the exact position it had before the historical
      // card opened. The stick-to-bottom observer otherwise follows the new
      // content height and makes the card appear to expand upward.
      const computedBehavior = window.getComputedStyle(scrollContainer).scrollBehavior
      if (computedBehavior !== 'auto') scrollContainer.style.scrollBehavior = 'auto'
      scrollContainer.scrollTop = anchor.scrollTop
      if (computedBehavior !== 'auto') scrollContainer.style.scrollBehavior = computedBehavior
    }
    const release = () => {
      if (!active) return
      active = false
      observer?.disconnect()
    }
    const keepAnchor = () => {
      restore()
      window.clearTimeout(settleTimer)
      // Ant Design animates the panel height. Wait until those layout changes
      // have settled before restoring normal automatic chat following.
      settleTimer = window.setTimeout(release, 420)
    }

    observer = new ResizeObserver(keepAnchor)
    observer.observe(timeline)
    scrollContainer.addEventListener('touchstart', release, { passive: true })
    scrollContainer.addEventListener('wheel', release, { passive: true })
    scrollContainer.addEventListener('pointerdown', release, { passive: true })
    frame = window.requestAnimationFrame(keepAnchor)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearTimeout(settleTimer)
      scrollContainer.removeEventListener('touchstart', release)
      scrollContainer.removeEventListener('wheel', release)
      scrollContainer.removeEventListener('pointerdown', release)
      release()
    }
  }, [archiveExpanded, archiveScrollAnchorEnabled])

  if (timelineBlocks.length === 0) return null

  if (isStreamingProcess) {
    return (
      <div className="assistant-action-list assistant-process-timeline is-live" ref={timelineRef}>
        {displayBlocks.map((block, index) => (
          <AssistantTimelineBlock
            key={block.id}
            block={block}
            streaming
            connectsToNext={hasFollowingProcessBlock(displayBlocks, index)}
            onProcessScroll={handleProcessScroll}
            suspendChatAutoFollow={suspendChatAutoFollow}
            resumeChatAutoFollow={resumeChatAutoFollow}
            autoFollowSuspensionEnabled={false}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="assistant-turn-complete" ref={timelineRef}>
      {archiveBlocks.length > 0 && (
        <Collapse
          className="assistant-action-summary"
          size="small"
          expandIconPlacement="end"
          activeKey={archiveExpanded ? ['process'] : []}
          onChange={handleArchiveChange}
          items={[
            {
              key: 'process',
              label: <ProcessArchiveLabel blocks={archiveBlocks} />,
              children: (
                <div className="assistant-action-summary-body">
                  <div className="assistant-action-list assistant-process-timeline">
                    {archiveBlocks.map((block, index) => (
                      <AssistantTimelineBlock
                        key={block.id}
                        block={block}
                        archived
                        connectsToNext={hasFollowingProcessBlock(archiveBlocks, index)}
                        onProcessScroll={handleProcessScroll}
                        suspendChatAutoFollow={suspendChatAutoFollow}
                        resumeChatAutoFollow={resumeChatAutoFollow}
                        autoFollowSuspensionEnabled={archiveScrollAnchorEnabled}
                      />
                    ))}
                  </div>
                </div>
              ),
            },
          ]}
        />
      )}
      {finalContent && <AiTextResponse><div className="assistant-turn-final-content"><MemoMarkdownContent content={finalContent} /></div></AiTextResponse>}
    </div>
  )
}

export function normaliseAssistantTurnBlocks(blocks: AssistantTurnBlock[]): AssistantTurnBlock[] {
  // Older persisted tool blocks omitted content. The API type supplies a
  // default today, but waiting-question timelines are served directly and
  // historical data must never be able to break the entire chat panel.
  return blocks.map((block) => {
    const content = typeof block.content === 'string'
      ? block.content
      : block.content == null
        ? ''
        : String(block.content)
    return content === block.content ? block : { ...block, content }
  })
}

export function visibleAssistantTurnBlocks(blocks: AssistantTurnBlock[]): AssistantTurnBlock[] {
  // A timed-out duplicate ask_user attempt is an internal retry detail. Task
  // plan updates are deliberate model actions and must stay visible alongside
  // the current plan panel above the conversation.
  return blocks.filter((block) => (
    block.type !== 'tool' || block.tool?.activity?.details?.reason !== 'user_question_timed_out'
  ))
}

export function mergeFallbackThoughtBlocks(
  blocks: AssistantTurnBlock[],
  fallbackTrace: ReasoningTrace,
): AssistantTurnBlock[] {
  const fallbackContent = fallbackTrace.content.trim()
  if (!fallbackContent || blocks.some((block) => block.type === 'thought' && block.content.trim())) return blocks

  const emptyThoughtIndex = blocks.findIndex((block) => block.type === 'thought' && !block.content.trim())
  if (emptyThoughtIndex >= 0) {
    return blocks.map((block, index) => index === emptyThoughtIndex
      ? { ...block, content: fallbackContent, state: fallbackTrace.status === 'thinking' ? 'active' : 'done' }
      : block,
    )
  }

  return [
    {
      id: 'legacy-reasoning-trace',
      type: 'thought',
      state: fallbackTrace.status === 'thinking' ? 'active' : 'done',
      content: fallbackContent,
      duration_ms: null,
      tool: null,
    },
    ...blocks,
  ]
}

function findLastTimelineContentIndex(blocks: AssistantTurnBlock[]): number {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (blocks[index].type === 'content' && blocks[index].content.trim()) return index
  }
  return -1
}

function hasFollowingProcessBlock(blocks: AssistantTurnBlock[], index: number): boolean {
  const nextBlock = blocks[index + 1]
  return nextBlock?.type === 'thought' || nextBlock?.type === 'tool'
}

function settleHistoricalTimeline(blocks: AssistantTurnBlock[]): AssistantTurnBlock[] {
  return blocks.map((block) => {
    const tool = block.tool?.status === 'running'
      ? {
          ...block.tool,
          status: 'error' as const,
          result: block.tool.result || '本轮 Agent 已结束，未收到该工具的执行结果。',
        }
      : block.tool
    return {
      ...block,
      state: block.state === 'active' ? 'done' : block.state,
      tool,
    }
  })
}

function ProcessArchiveLabel({ blocks }: { blocks: AssistantTurnBlock[] }) {
  const thoughtCount = blocks.filter((block) => block.type === 'thought').length
  const tools = blocks.flatMap((block) => block.type === 'tool' && block.tool ? [block.tool] : [])
  const toolCount = tools.length
  const editTools = tools.filter((tool) => ['apply_html_patch', 'replace_document', 'edit_file', 'apply_patch', 'write_file'].includes(tool.name))
  const latestFailedEdit = editTools.at(-1)?.status === 'error'
  const summary = toolCount > 0
    ? latestFailedEdit
      ? editTools.some((tool) => tool.status === 'success')
        ? '本轮排版部分完成，最后一项修改失败'
        : '本轮排版未完成，修改未写入文档'
      : `编辑了推文，执行了 ${toolCount} 项操作`
    : thoughtCount > 0
      ? `完成了 ${thoughtCount} 段思考`
      : '完成了本轮操作'

  return <span className="assistant-action-summary-label">{summary}</span>
}

const AssistantTimelineBlock = memo(function AssistantTimelineBlock({
  block,
  archived = false,
  streaming = false,
  connectsToNext = false,
  onProcessScroll,
  suspendChatAutoFollow,
  resumeChatAutoFollow,
  autoFollowSuspensionEnabled,
}: {
  block: AssistantTurnBlock
  archived?: boolean
  streaming?: boolean
  connectsToNext?: boolean
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
  suspendChatAutoFollow: () => number
  resumeChatAutoFollow: (suspensionId: number | null) => void
  autoFollowSuspensionEnabled: boolean
}) {
  if (block.type === 'context_compaction' && block.context_compaction) {
    const compaction = block.context_compaction
    const summary = parseCompactionSummary(compaction.summary)
    const sourceReferences = summary?.sections.find((section) => section.key === 'source_refs')
    const summarySections = summary?.sections.filter((section) => section.key !== 'source_refs') ?? []
    const savedTokens = Math.max(0, compaction.original_tokens - compaction.used_tokens)
    const rate = compaction.original_tokens > 0
      ? Math.round(savedTokens / compaction.original_tokens * 100)
      : 0
    return (
      <div className={`assistant-process-entry assistant-action-entry assistant-process-compaction${connectsToNext ? ' has-next-process' : ''}${archived ? ' is-archived' : ''}`}>
        <div className="assistant-process-rail" aria-hidden="true"><i className="assistant-process-dot" /></div>
        <div className="assistant-process-main">
          <div className="assistant-compaction-card">
            <div className="assistant-compaction-title">压缩上下文成功</div>
            <div className="assistant-compaction-stats">
              {savedTokens > 0 ? `节省 ${savedTokens.toLocaleString()} tokens（${rate}%）` : '已整理运行上下文'}
              {compaction.summarized_cycles > 0 ? ` · 摘要 ${compaction.summarized_cycles} 轮工具循环` : ''}
              {compaction.durable_snapshot ? ' · 已持久化' : ''}
            </div>
            {compaction.summary && (
              <details className="assistant-compaction-details">
                <summary>查看压缩摘要</summary>
                {summary ? (
                  <div className="assistant-compaction-summary" onWheel={forwardCompactionBoundaryWheel}>
                    {summary.objective && (
                      <section className="assistant-compaction-summary-objective">
                        <span>当前目标</span>
                        <p>{summary.objective}</p>
                      </section>
                    )}
                    {summary.narrative && (
                      <section className="assistant-compaction-summary-narrative">
                        <span>状态说明</span>
                        <p>{summary.narrative}</p>
                      </section>
                    )}
                    {summarySections.length > 0 && (
                      <div className="assistant-compaction-summary-grid">
                        {summarySections.map((section) => (
                          <section className="assistant-compaction-summary-section" key={section.key}>
                            <span>{section.label}</span>
                            <ul>
                              {section.values.map((value, index) => <li key={`${section.key}-${index}`}>{value}</li>)}
                            </ul>
                          </section>
                        ))}
                      </div>
                    )}
                    {sourceReferences && (
                      <details className="assistant-compaction-source-refs">
                        <summary>来源记录（{sourceReferences.values.length}）</summary>
                        <ul className="assistant-compaction-source-list" onWheel={forwardCompactionBoundaryWheel}>
                          {sourceReferences.values.map((value, index) => <li key={`source-ref-${index}`}><code>{value}</code></li>)}
                        </ul>
                      </details>
                    )}
                  </div>
                ) : (
                  <div className="assistant-compaction-summary-raw" onWheel={forwardCompactionBoundaryWheel}>{compaction.summary}</div>
                )}
              </details>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (block.type === 'thought') {
    const trace: ReasoningTrace = {
      status: block.state === 'active' ? 'thinking' : block.content ? 'complete' : 'unavailable',
      content: block.content,
      detail: block.content ? '' : '模型未返回可展示的思考内容',
    }
    return (
      <div className={`assistant-process-entry assistant-action-entry assistant-process-thinking is-${trace.status}${connectsToNext ? ' has-next-process' : ''}${archived ? ' is-archived' : ''}`}>
        <div className="assistant-process-rail" aria-hidden="true"><i className="assistant-process-dot" /></div>
        <div className="assistant-process-main">
          <ThinkingTrace
            trace={trace}
            durationMs={block.duration_ms}
            startedAtMs={block.started_at_ms}
            onProcessScroll={onProcessScroll}
          />
        </div>
      </div>
    )
  }

  if (block.type === 'tool' && block.tool) {
    return (
      <div className={`assistant-process-entry assistant-action-entry assistant-process-tool is-${block.tool.status}${connectsToNext ? ' has-next-process' : ''}${archived ? ' is-archived' : ''}`}>
        <div className="assistant-process-rail" aria-hidden="true"><i className="assistant-process-dot" /></div>
        <div className="assistant-process-main">
          <ToolTrace
            tool={block.tool}
            onProcessScroll={onProcessScroll}
            suspendChatAutoFollow={suspendChatAutoFollow}
            resumeChatAutoFollow={resumeChatAutoFollow}
            autoFollowSuspensionEnabled={autoFollowSuspensionEnabled}
          />
        </div>
      </div>
    )
  }

  return (
    <div className={`assistant-action-entry assistant-action-content${archived ? ' is-archived' : ''}`}>
      {streaming
        ? <AiStreamingText active showCaret={false}><div className="assistant-action-content-body"><StreamingMarkdownContent content={block.content} /></div></AiStreamingText>
        : <AiTextResponse><div className="assistant-action-content-body"><MemoMarkdownContent content={block.content} /></div></AiTextResponse>}
    </div>
  )
})

function legacyTimelineBlocks(
  content: string,
  trace: ReasoningTrace,
  tools: ToolExecution[],
): AssistantTurnBlock[] {
  const blocks: AssistantTurnBlock[] = []
  if (trace.status !== 'idle') {
    blocks.push({ id: 'legacy-thought', type: 'thought', state: trace.status === 'thinking' ? 'active' : 'done', content: trace.content, duration_ms: null, tool: null })
  }
  tools.forEach((tool, index) => {
    blocks.push({ id: `legacy-tool-${index}`, type: 'tool', state: 'done', content: '', duration_ms: null, tool })
  })
  if (content) {
    blocks.push({ id: 'legacy-content', type: 'content', state: 'done', content, duration_ms: null, tool: null })
  }
  return blocks
}

type ToolVisualKind = 'read' | 'search' | 'history' | 'image' | 'edit' | 'check' | 'plan' | 'reference' | 'other'

function toolVisualKind(name: string): ToolVisualKind {
  if (['list_files', 'read_file', 'enable_tool_groups'].includes(name)) return 'read'
  if (name === 'search_files') return 'search'
  if (['edit_file', 'apply_patch', 'write_file'].includes(name)) return 'edit'
  if (['get_document_map', 'read_blocks', 'read_gzh_theme', 'read_current_gzh_theme', 'get_layout_reference_map', 'read_layout_reference_blocks', 'read_wechat_compliance_spec', 'read_gzh_theme_generator', 'read_gzh_theme_recipe', 'read_gzh_theme_components', 'read_attached_templates', 'read_tool_output'].includes(name)) return 'read'
  if (['search_html', 'search_layout_reference'].includes(name)) return 'search'
  if (['list_history_versions', 'search_history_versions', 'search_history_version', 'compare_history_version', 'read_history_blocks', 'search_session_history', 'read_session_detail'].includes(name)) return 'history'
  if (['inspect_current_images', 'inspect_history_images', 'search_article_images', 'view_article_images', 'view_chat_images_page', 'import_chat_image', 'import_searched_image', 'apply_searched_cover', 'generate_article_images', 'apply_generated_cover', 'edit_article_image', 'apply_edited_image', 'edit_article_cover', 'apply_edited_cover', 'transform_document_image'].includes(name)) return 'image'
  if (['apply_html_patch', 'replace_document', 'create_gzh_theme_draft', 'publish_gzh_theme'].includes(name)) return 'edit'
  if (name === 'check_compliance' || name === 'validate_gzh_html') return 'check'
  if (name === 'update_task_plan') return 'plan'
  if (['apply_layout_reference', 'list_gzh_themes', 'apply_gzh_theme_proposal'].includes(name)) return 'reference'
  return 'other'
}

function ToolGlyph({ name }: { name: string }) {
  if (name === 'get_document_map') return <FileSearchOutlined />
  switch (toolVisualKind(name)) {
    case 'read': return <FileTextOutlined />
    case 'search': return <SearchOutlined />
    case 'history': return <HistoryOutlined />
    case 'image': return <PictureOutlined />
    case 'edit': return <EditOutlined />
    case 'check': return <SafetyCertificateOutlined />
    case 'plan': return <UnorderedListOutlined />
    case 'reference': return <FormatPainterOutlined />
    default: return <CodeOutlined />
  }
}

function ToolArgumentTokenCount({ value }: { value: number }) {
  const [displayValue, setDisplayValue] = useState(value)
  const displayedValueRef = useRef(value)

  useEffect(() => {
    const from = displayedValueRef.current
    if (value <= from) {
      displayedValueRef.current = value
      setDisplayValue(value)
      return
    }
    const startedAt = performance.now()
    const duration = Math.min(360, Math.max(120, (value - from) * 12))
    let frame = 0
    const render = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration)
      const nextValue = Math.round(from + (value - from) * progress)
      displayedValueRef.current = nextValue
      setDisplayValue(nextValue)
      if (progress < 1) frame = window.requestAnimationFrame(render)
    }
    frame = window.requestAnimationFrame(render)
    return () => window.cancelAnimationFrame(frame)
  }, [value])

  return (
    <span
      className="tool-argument-token-count"
      title="模型已输出的工具参数 token 估算，随流式参数持续更新"
    >
      {displayValue.toLocaleString()} tokens
    </span>
  )
}

function ToolTrace({
  tool,
  onProcessScroll,
  suspendChatAutoFollow,
  resumeChatAutoFollow,
  autoFollowSuspensionEnabled,
}: {
  tool: ToolExecution
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
  suspendChatAutoFollow: () => number
  resumeChatAutoFollow: (suspensionId: number | null) => void
  autoFollowSuspensionEnabled: boolean
}) {
  const chatImagePreviews = useContext(ChatImagePreviewContext)
  const [expanded, setExpanded] = useState(tool.status === 'running')
  const previousStatus = useRef(tool.status)
  const expansionSuspensionRef = useRef<number | null>(null)
  const expansionSuspensionTimerRef = useRef(0)

  const releaseExpansionSuspension = useCallback(() => {
    window.clearTimeout(expansionSuspensionTimerRef.current)
    resumeChatAutoFollow(expansionSuspensionRef.current)
    expansionSuspensionRef.current = null
  }, [resumeChatAutoFollow])

  useEffect(() => releaseExpansionSuspension, [releaseExpansionSuspension])

  useEffect(() => {
    if (tool.status === 'running') {
      setExpanded(true)
    } else if (tool.status === 'error') {
      setExpanded(true)
    } else if (
      tool.status === 'success'
      && ['running', 'waiting', 'error'].includes(previousStatus.current)
    ) {
      // A paused ask_user call is rendered as an error while the question
      // panel is waiting for its resumed stream. Its eventual success must
      // collapse just like an ordinary running tool, otherwise the answered
      // preference card remains expanded for the rest of the turn.
      const timer = window.setTimeout(() => setExpanded(false), 1200)
      previousStatus.current = tool.status
      return () => window.clearTimeout(timer)
    } else if (tool.status === 'interrupted' && previousStatus.current === 'running') {
      const timer = window.setTimeout(() => setExpanded(false), 600)
      previousStatus.current = tool.status
      return () => window.clearTimeout(timer)
    }
    previousStatus.current = tool.status
  }, [tool.status])

  const status = toolStatusSummary(tool)
  const isRunning = tool.status === 'running'
  const activity = tool.activity
  const htmlValidation = toolHtmlValidation(tool)
  const generatedImages = generatedImagePreviews(tool)
  const modelInputImages = modelImagePreviews(tool, chatImagePreviews)
  const statusTone = status.tone
  const argumentTokens = tool.status === 'running' && tool.preparing && typeof tool.argument_tokens === 'number' && tool.argument_tokens > 0
    ? tool.argument_tokens
    : null
  const summary = isRunning
    ? tool.preparing ? '正在准备工具参数' : '正在执行操作'
    : toolActionTarget(tool)

  const mappedStatus = tool.status === 'running' || tool.status === 'waiting'
    ? 'running'
    : tool.status === 'error'
      ? 'error'
      : tool.status === 'interrupted'
        ? 'cancelled'
        : 'success'
  const searchSources = generatedImages
    .filter((image) => image.kind === 'search')
    .map((image) => ({ label: image.title || image.label, href: image.sourcePageUrl || undefined }))
  const handleToggle = () => {
    const nextExpanded = !expanded
    releaseExpansionSuspension()
    if (nextExpanded && autoFollowSuspensionEnabled) {
      expansionSuspensionRef.current = suspendChatAutoFollow()
      expansionSuspensionTimerRef.current = window.setTimeout(releaseExpansionSuspension, 420)
    }
    setExpanded(nextExpanded)
  }

  return (
    <AiToolCall
      icon={<ToolGlyph name={tool.name} />}
      iconTone={toolVisualKind(tool.name)}
      title={toolLabel(tool)}
      summary={summary}
      status={mappedStatus}
      expanded={expanded}
      onToggle={handleToggle}
      statusDetail={<span className={`aicss-tool-call-status is-${statusTone}`}>{argumentTokens !== null ? <ToolArgumentTokenCount value={argumentTokens} /> : status.label}</span>}
    >
      <div className={`tool-trace-detail${isRunning ? ' is-live' : ''}`} onScroll={onProcessScroll}>
            {toolVisualKind(tool.name) === 'search' && <AiWebSearch query={String(activity?.query || summary)} running={isRunning} sources={searchSources} />}
            {generatedImages.length > 0 && <GeneratedImagePreviews images={generatedImages} />}
            {modelInputImages.length > 0 && <ModelImagePreviews images={modelInputImages} />}
            <ToolResultView tool={tool} hasImageGallery={generatedImages.length > 0 || modelInputImages.length > 0} />
            {htmlValidation?.valid === false && htmlValidation.errors?.length && !activity?.validation_warning ? (
              <div className="tool-trace-result">{htmlValidation.errors.join('；')}</div>
            ) : null}
            {activity?.validation_warning && htmlValidation?.errors?.length ? (
              <div className="tool-trace-summary">HTML 结构警告（修改已保留）：{htmlValidation.errors.join('；')}</div>
            ) : null}
            {htmlValidation?.warnings?.length ? (
              <div className="tool-trace-summary">HTML5 兼容提示：{htmlValidation.warnings.join('；')}</div>
            ) : null}
            {toolErrorMetadata(tool) && <div className="tool-trace-summary">{toolErrorMetadata(tool)}</div>}
            {tool.read_range && !activity && (
              <div className="tool-trace-summary">
                {tool.read_range.scope === 'whole'
                  ? `已读取完整文档，共 ${tool.read_range.total_lines} 行`
                  : `已读取第 ${tool.read_range.start_line}-${tool.read_range.end_line} 行，共 ${tool.read_range.total_lines} 行`}
              </div>
            )}
            {tool.change_summary && !activity && <ChangeSummaryLine summary={tool.change_summary} />}
            {!activity && tool.change_summary?.diff_preview && <AiFileDiff file={tool.change_summary.diff_truncated ? '变更 diff（已截断）' : '变更 diff'} rows={aiDiffRows(tool.change_summary.diff_preview)} />}
      </div>
    </AiToolCall>
  )
}

interface GeneratedImagePreview {
  id: string
  url: string
  label: string
  title: string
  engine: string
  width: number | null
  height: number | null
  sourcePageUrl: string
  kind: 'search' | 'generation' | 'applied'
}

export function generatedImagePreviews(tool: ToolExecution): GeneratedImagePreview[] {
  if (tool.activity?.kind === 'image_import' || tool.activity?.kind === 'image_application') {
    const details = tool.activity.details
    const url = typeof details?.url === 'string' ? details.url.trim() : ''
    if (!isSafeImagePreviewUrl(url)) return []
    return [{
      id: `applied-image-${String(details?.asset_id || url)}`,
      url,
      label: tool.activity.kind === 'image_import' ? '已导入图片' : '已应用图片',
      title: typeof details?.title === 'string' ? details.title : '',
      engine: tool.activity.kind === 'image_import' ? '搜索图片' : '当前图片',
      width: typeof details?.width === 'number' && details.width > 0 ? details.width : null,
      height: typeof details?.height === 'number' && details.height > 0 ? details.height : null,
      sourcePageUrl: typeof details?.source_page_url === 'string' ? details.source_page_url : '',
      kind: 'applied',
    }]
  }
  const isSearch = tool.activity?.kind === 'image_search'
  if (!isSearch && tool.activity?.kind !== 'image_generation') return []
  const details = tool.activity?.details
  const assets = isSearch ? details?.items : details?.assets
  if (!Array.isArray(assets)) return []
  return assets.flatMap((asset, index) => {
    if (!asset || typeof asset !== 'object' || Array.isArray(asset)) return []
    const value = asset as Record<string, unknown>
    const rawUrl = isSearch ? value.preview_url : value.url
    const url = typeof rawUrl === 'string' ? rawUrl.trim() : ''
    if (!isSafeImagePreviewUrl(url)) return []
    const width = typeof value.width === 'number' && value.width > 0 ? value.width : null
    const height = typeof value.height === 'number' && value.height > 0 ? value.height : null
    return [{
      id: typeof value.id === 'string' && value.id ? value.id : `tool-image-${index}`,
      url,
      label: isSearch ? `搜图候选 ${index + 1}` : `生成候选 ${index + 1}`,
      title: typeof value.title === 'string' ? value.title : (typeof value.revised_prompt === 'string' ? value.revised_prompt : ''),
      engine: typeof value.engine === 'string' ? value.engine : '',
      width,
      height,
      sourcePageUrl: typeof value.source_page_url === 'string' ? value.source_page_url : '',
      kind: isSearch ? 'search' : 'generation',
    }]
  })
}

function isSafeImagePreviewUrl(value: string): boolean {
  if (!value.trim()) return false
  try {
    const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin
    const url = new URL(value, origin)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

function GeneratedImagePreviews({ images }: { images: GeneratedImagePreview[] }) {
  const [expanded, setExpanded] = useState(false)
  const [failed, setFailed] = useState<Set<string>>(() => new Set())
  if (!images.length) return null
  return (
    <div className="tool-generated-image-gallery">
      <div className={`tool-generated-image-grid${expanded ? ' is-expanded' : ''}`}>
      {images.map((image) => (
        <figure className="tool-generated-image" key={image.id}>
          <div className="tool-generated-image-frame">
            {failed.has(image.id) ? (
              <div className="tool-generated-image-fallback"><PictureOutlined /><span>图片暂不可用</span></div>
            ) : (
              <Image
                alt={image.title || image.label}
                className="tool-generated-image-preview"
                preview={{ mask: <EyeOutlined /> }}
                src={image.url}
                onError={() => setFailed((current) => new Set(current).add(image.id))}
              />
            )}
          </div>
          <figcaption>
            <span className="tool-generated-image-label">{image.title || image.label}</span>
            <span className="tool-generated-image-meta">
              {image.engine || (image.kind === 'generation' ? 'AI 生图' : image.kind === 'applied' ? '已应用' : '搜图')}
              {image.width && image.height ? ` · ${image.width} × ${image.height}` : ' · 尺寸未知'}
            </span>
            {image.sourcePageUrl && <AiInlineCitation href={image.sourcePageUrl}>来源</AiInlineCitation>}
          </figcaption>
        </figure>
      ))}
      </div>
      {images.length > 8 && <Button type="link" size="small" className="tool-generated-image-expand tool-generated-image-expand-desktop" onClick={() => setExpanded((value) => !value)}>
        {expanded ? '收起候选' : `显示更多（${images.length} 张）`}
      </Button>}
      {images.length > 4 && <Button type="link" size="small" className="tool-generated-image-expand tool-generated-image-expand-narrow" onClick={() => setExpanded((value) => !value)}>
        {expanded ? '收起候选' : `显示更多（${images.length} 张）`}
      </Button>}
    </div>
  )
}

interface ModelImagePreview {
  id: string
  url: string
  label: string
  width: number | null
  height: number | null
}

export function modelImagePreviews(tool: ToolExecution, chatImagePreviews: ReadonlyMap<string, string> = EMPTY_IMAGE_PREVIEWS): ModelImagePreview[] {
  const details = tool.activity?.kind === 'image_view' ? tool.activity.details : undefined
  if (!details?.image_content_included || !Array.isArray(details.items)) return []
  return details.items.flatMap((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const value = item as Record<string, unknown>
    // Tool records keep unsigned references. Prefer the uploaded article asset,
    // then the freshly authorized preview from the loaded conversation.
    const url = [
      value.article_url,
      typeof value.attachment_id === 'string' ? chatImagePreviews.get(value.attachment_id) : undefined,
      value.preview_url,
    ].find((candidate): candidate is string => typeof candidate === 'string' && isSafeImagePreviewUrl(candidate))?.trim()
    if (!url) return []
    const number = typeof value.index === 'number' && value.index > 0 ? value.index : index + 1
    const width = typeof value.width === 'number' && value.width > 0 ? value.width : null
    const height = typeof value.height === 'number' && value.height > 0 ? value.height : null
    return [{
      id: `model-image-${number}-${url}`,
      url,
      label: typeof value.label === 'string' && value.label.trim() ? value.label.trim() : `图片 ${number}`,
      width,
      height,
    }]
  })
}

function ModelImagePreviews({ images }: { images: ModelImagePreview[] }) {
  const [failed, setFailed] = useState<Set<string>>(() => new Set())
  if (!images.length) return null
  return (
    <section className="tool-model-image-gallery" aria-label="本次提供给模型的图片">
      <div className="tool-model-image-heading"><EyeOutlined /> 本次提供给模型的图片</div>
      <div className="tool-generated-image-grid">
        {images.map((image) => (
          <figure className="tool-generated-image" key={image.id}>
            <div className="tool-generated-image-frame">
              {failed.has(image.id) ? (
                <div className="tool-generated-image-fallback"><PictureOutlined /><span>图片暂不可用</span></div>
              ) : (
                <Image
                  alt={image.label}
                  className="tool-generated-image-preview"
                  preview={{ mask: <EyeOutlined /> }}
                  src={image.url}
                  onError={() => setFailed((current) => new Set(current).add(image.id))}
                />
              )}
            </div>
            <figcaption>
              <span className="tool-generated-image-label">{image.label}</span>
              <span className="tool-generated-image-meta">
                多模态输入{image.width && image.height ? ` · ${image.width} × ${image.height}` : ''}
              </span>
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="tool-model-image-note">模型同时收到图片编号、名称和实际像素尺寸。</div>
    </section>
  )
}

function toolErrorMetadata(tool: ToolExecution): string {
  if (tool.status !== 'error') return ''
  const details = tool.activity?.details
  if (!details || typeof details !== 'object' || Array.isArray(details)) return ''
  if (details.reason === 'revision_not_current' || details.current_block) {
    return '目标内容已更新，Agent 将重新读取当前排版块后重试；本次未写入旧补丁。'
  }
  const requested = Number(details.requested_block_count)
  const maximum = Number(details.max_read_blocks)
  if (Number.isFinite(requested) && Number.isFinite(maximum)) {
    return `本次请求读取 ${requested} 个排版块，上限为 ${maximum} 个。`
  }
  return ''
}

function toolHtmlValidation(tool: ToolExecution): NonNullable<NonNullable<ToolExecution['activity']>['html_validation']> | undefined {
  if (tool.activity?.html_validation) return tool.activity.html_validation
  const nested = tool.activity?.details?.validation
  if (!nested || typeof nested !== 'object' || Array.isArray(nested)) return undefined
  const value = nested as Record<string, unknown>
  return {
    valid: typeof value.valid === 'boolean' ? value.valid : undefined,
    errors: Array.isArray(value.errors) ? value.errors.filter((item): item is string => typeof item === 'string') : undefined,
  }
}

function toolStatusSummary(tool: ToolExecution): { label: string; tone: 'running' | 'error' | 'changed' | 'success' } {
  if (tool.status === 'interrupted') return { label: '已重试', tone: 'changed' }
  if (tool.status === 'running' && tool.preparing) return { label: '准备中', tone: 'running' }
  if (tool.status === 'running') return { label: '执行中', tone: 'running' }
  if (tool.status === 'waiting') return { label: '等待回复', tone: 'running' }
  if (tool.status === 'error') return { label: '执行失败', tone: 'error' }
  if (tool.html_changed) return { label: '已更新', tone: 'changed' }
  return { label: '完成', tone: 'success' }
}

function toolActionTarget(tool: ToolExecution): string {
  if (tool.activity?.summary) return tool.activity.summary
  if (['get_document_map', 'search_html', 'read_blocks'].includes(tool.name)) return 'HTML'
  if (tool.name === 'check_compliance') return '兼容性'
  return toolLabel(tool)
}

function ChangeSummaryLine({ summary }: { summary: ChangeSummary }) {
  return <AiComparisonTable rows={[
    { label: '新增行', value: `+${summary.added_lines}`, tone: 'add' },
    { label: '删除行', value: `-${summary.removed_lines}`, tone: 'remove' },
  ]} />
}

function ThinkingTrace({
  trace,
  durationMs,
  startedAtMs,
  onProcessScroll,
}: {
  trace: ReasoningTrace
  durationMs?: number | null
  startedAtMs?: number
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
}) {
  const isThinking = trace.status === 'thinking'
  const liveDurationMs = useLiveThoughtDuration(isThinking, startedAtMs)

  const label = isThinking ? '正在思考' : '思考过程'

  const duration = isThinking && liveDurationMs !== null
    ? formatThoughtDuration(liveDurationMs)
    : durationMs !== null && durationMs !== undefined
      ? formatThoughtDuration(durationMs)
      : null
  return <AiThinkingReasoning thinking={isThinking} duration={duration} content={trace.content} fallback={trace.detail || label} onScroll={onProcessScroll} />
}

function useLiveThoughtDuration(isThinking: boolean, startedAtMs?: number): number | null {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!isThinking || !startedAtMs) return
    const update = () => setNow(Date.now())
    let timer: number | null = null
    const stopTimer = () => {
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    }
    const syncTimer = () => {
      stopTimer()
      update()
      if (document.visibilityState === 'visible') {
        timer = window.setInterval(update, 100)
      }
    }
    syncTimer()
    document.addEventListener('visibilitychange', syncTimer)
    window.addEventListener('focus', syncTimer)
    return () => {
      document.removeEventListener('visibilitychange', syncTimer)
      window.removeEventListener('focus', syncTimer)
      stopTimer()
    }
  }, [isThinking, startedAtMs])

  return isThinking && startedAtMs ? Math.max(0, now - startedAtMs) : null
}

function formatThoughtDuration(durationMs: number): string {
  if (durationMs < 60_000) return `${Math.max(0.1, durationMs / 1000).toFixed(1)} 秒`
  const minutes = Math.floor(durationMs / 60_000)
  const seconds = Math.round((durationMs % 60_000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}
