import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, UIEvent } from 'react'
import { Alert, Button, Collapse, Dropdown, Image, Input, Modal, Popover, Select, Tag, Tooltip, Typography, message } from 'antd'
import {
  AppstoreOutlined,
  BulbOutlined,
  CheckCircleFilled,
  CodeOutlined,
  ClockCircleOutlined,
  DownOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  EyeOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FormatPainterOutlined,
  HistoryOutlined,
  LoadingOutlined,
  MoreOutlined,
  PaperClipOutlined,
  PlusOutlined,
  PictureOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  SendOutlined,
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
import { useAuthStore } from '../store/authStore'
import ModelSelector from './ModelSelector'
import type { AIModelItem } from '../types'
import MarkdownContent from './MarkdownContent'
import CodeBlock from './CodeBlock'
import PromptComposer from './PromptComposer'
import type { PromptComposerHandle } from './PromptComposer'
import ElementRenderPreview from './ElementRenderPreview'
import UserQuestionPanel from './UserQuestionPanel'
import type { UserQuestionAnswer } from './UserQuestionPanel'

const { Text } = Typography

export interface ChatRunNotice {
  kind: 'retrying' | 'error' | 'success'
  title: string
  detail: string
  attempt?: number
  maxAttempts?: number
}

export interface ReaskConflictNotice {
  kind: 'local_draft' | 'server'
}

export interface QueuedChatMessage {
  id: string
  content: string
}

const TOOL_LABELS: Record<string, string> = {
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
  validate_gzh_html: '主题严格检查',
}

const BOTTOM_FOLLOW_THRESHOLD = 48
const USER_SCROLL_INTENT_WINDOW_MS = 250
const MemoMarkdownContent = memo(MarkdownContent)
const CONTEXT_BREAKDOWN_LABELS: Record<string, string> = {
  system: '系统提示',
  document_map: '文档地图',
  memory: '压缩记忆',
  recent_history: '近期对话',
  tool_replay: '工具预览回放',
  tool_schema: '工具定义',
  current_request: '当前请求',
  image_inputs: '图片输入',
  selected_context: '选中元素',
  runtime_output: '本轮实时增量',
}
const CONTEXT_BREAKDOWN_COLORS: Record<string, string> = {
  system: '#a0a5af',
  document_map: '#b27ad8',
  memory: '#43ad78',
  recent_history: '#f0b45f',
  tool_replay: '#7fa0c2',
  tool_schema: '#7798a8',
  current_request: '#e34d80',
  image_inputs: '#4b9f9f',
  selected_context: '#ba9aaf',
  runtime_output: '#5d8c5a',
}
const TASK_PLAN_STATUS_LABELS: Record<TaskPlanItem['status'], string> = {
  pending: '待办',
  in_progress: '进行中',
  done: '已完成',
}

interface TaskPlan {
  items: TaskPlanItem[]
}

function isNearBottom(container: HTMLElement): boolean {
  return container.scrollHeight - container.scrollTop - container.clientHeight < BOTTOM_FOLLOW_THRESHOLD
}

// AssistantTurnTimeline.vue renders every live delta through its Markdown
// renderer. Keep that behavior so inline Markdown such as **bold** is never
// shown as literal source while the Agent is still streaming.
const StreamingMarkdownContent = memo(function StreamingMarkdownContent({ content }: { content: string }) {
  return <MemoMarkdownContent content={content} />
})

function formatTokenCount(value: number): string {
  if (value < 1_000) return value.toLocaleString()
  if (value < 10_000) return `${(value / 1_000).toFixed(1)}K`
  return `${Math.round(value / 1_000)}K`
}

function estimateRuntimeTokens(streamText: string, reasoningTrace: ReasoningTrace, toolActivities: ToolExecution[]): number {
  const content = [
    streamText,
    reasoningTrace.content,
    ...toolActivities.map((tool) => tool.result ?? ''),
  ].join('')
  return content ? Math.ceil(content.length / 2) : 0
}

export function contextUsageValues(stats: ChatContextStats, runtimeTokens = 0) {
  const runtimeProjectionTokens = Math.max(
    0,
    Math.round(runtimeTokens),
    stats.runtime_projected_tokens ?? 0,
  )
  return {
    compiledInputTokens: stats.compiled_input_tokens ?? stats.used_tokens,
    ledgerTokens: stats.ledger_tokens ?? stats.conversation_tokens ?? 0,
    runtimeProjectionTokens,
  }
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

function ContextUsage({
  stats,
  runtimeTokens = 0,
  onCompactContext,
}: {
  stats: ChatContextStats
  runtimeTokens?: number
  onCompactContext: (rebuild: boolean) => void | Promise<void>
}) {
  const [compacting, setCompacting] = useState(false)
  // The prepared-context budget remains authoritative for the next request.
  // While an Agent streams, add its visible output as a local projection so
  // the meter advances without waiting for the turn to be persisted.
  const { compiledInputTokens, ledgerTokens, runtimeProjectionTokens } = contextUsageValues(stats, runtimeTokens)
  const isLiveProjection = runtimeProjectionTokens > 0
  const stateLabel = isLiveProjection
    ? '本轮执行中'
    : stats.runtime_context_state === 'run_compacting' || stats.state === 'compacting'
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
            : '下次输入'
  const usedTokens = compiledInputTokens + runtimeProjectionTokens
  const usagePercent = Math.min(100, Math.round(usedTokens / Math.max(1, stats.usable_tokens) * 100))
  const breakdownItems = [
    ...Object.entries(stats.breakdown).filter(([, value]) => value > 0),
    ...(isLiveProjection ? [['runtime_output', runtimeProjectionTokens] as [string, number]] : []),
  ]
  const ringColor = usagePercent >= 85 ? '#e88b2d' : usagePercent >= 65 ? '#d6a33d' : '#3c84e8'
  const ringStyle = {
    background: `conic-gradient(${ringColor} ${usagePercent}%, var(--app-border) 0)`,
  } as CSSProperties
  const detail = (
    <div className="chat-context-popover">
      <div className="chat-context-popover-head">
        <strong>上下文使用</strong>
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
        <b>{usagePercent}% 已用</b>
        <span>{isLiveProjection ? '本轮预估约' : '下次输入约'} {formatTokenCount(usedTokens)} / {formatTokenCount(stats.usable_tokens)} tokens</span>
      </div>
      <div className="chat-context-bar" aria-label={`上下文已使用 ${usagePercent}%`}>
        {breakdownItems.map(([key, value]) => (
          <i key={key} style={{ width: `${Math.max(1, value / Math.max(1, usedTokens) * 100)}%`, background: CONTEXT_BREAKDOWN_COLORS[key] ?? '#98a2b3' }} />
        ))}
      </div>
      <div className="chat-context-breakdown">
        {breakdownItems.map(([key, value]) => (
          <span key={key}>
            <i><em style={{ background: CONTEXT_BREAKDOWN_COLORS[key] ?? '#98a2b3' }} />{CONTEXT_BREAKDOWN_LABELS[key] ?? key}</i>
            <b>{formatTokenCount(value)}</b>
          </span>
        ))}
      </div>
      <div className="chat-context-foot">
        原始账本约 {formatTokenCount(ledgerTokens)} tokens（{stats.event_count ?? stats.conversation_message_count ?? 0} 条事件）
        {stats.snapshot_covered_event_count ? `；快照覆盖 ${stats.snapshot_covered_event_count} 条事件` : ''}
        <br />完整事件 {stats.event_count ?? 0} 条，当前回放 {stats.replayed_event_count ?? 0} 条，已节省约 {stats.tokens_saved.toLocaleString()} tokens
        {stats.compaction_strategy ? `；压缩方式：${stats.compaction_strategy === 'agentic' ? '模型摘要' : stats.compaction_strategy}` : ''}
        {stats.is_estimate ? '，为估算值' : ''}
        {stats.runtime_input_tokens ? `；本轮最近调用约 ${formatTokenCount(stats.runtime_input_tokens)} tokens` : ''}
        {isLiveProjection ? `；本轮实时增量约 ${formatTokenCount(runtimeProjectionTokens)} tokens，尚未持久化` : ''}
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
      <button className={`chat-context-ring${usagePercent >= 85 ? ' is-warning' : ''}`} type="button" title={`上下文使用 ${usagePercent}%`} style={ringStyle}>
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
  queuedMessages: QueuedChatMessage[]
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
  onRemoveSelectedElement: (index: number) => void
  onDuplicateSelectedElement: (index: number) => void
  onMoveSelectedElement: (fromIndex: number, toIndex: number) => void
  onRemoveAttachedTemplate: (templateId: number) => void
  onRemoveComposerTemplate: (templateId: number) => void
  onRemoveQueuedMessage: (id: string) => void
  onEditRequest: (message: ChatMessageItem) => void
  onSend: (text: string, references: SelectedElementContext[], images: ChatImageAttachment[]) => void
  onAnswerUserQuestion: (answer: UserQuestionAnswer) => void
  onUserQuestionActivity: () => void
  onUserQuestionTimeoutElapsed: () => void
  onUploadImages: (files: File[]) => void
  onRemoveImage: (attachment: ChatImageAttachment) => void
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
  queuedMessages,
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
  onRemoveSelectedElement,
  onDuplicateSelectedElement,
  onMoveSelectedElement,
  onRemoveAttachedTemplate,
  onRemoveComposerTemplate,
  onRemoveQueuedMessage,
  onEditRequest,
  onSend,
  onAnswerUserQuestion,
  onUserQuestionActivity,
  onUserQuestionTimeoutElapsed,
  onUploadImages,
  onRemoveImage,
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
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameTitle, setRenameTitle] = useState('')
  const [hiddenHistoryOpen, setHiddenHistoryOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const listContentRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<PromptComposerHandle>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const followStreamRef = useRef(true)
  const lastScrollTopRef = useRef(0)
  const lastScrollHeightRef = useRef(0)
  const lastClientHeightRef = useRef(0)
  const userScrollIntentUntilRef = useRef(0)
  const scrollFrameRef = useRef<number | null>(null)
  const scrollSettleFrameRef = useRef<number | null>(null)
  const pendingVisibleScrollRef = useRef(false)
  const pendingVisibleForceScrollRef = useRef(false)
  const queuedForceScrollRef = useRef(false)
  const hasPositionedInitialHistoryRef = useRef(false)

  const forceScrollToLatest = useCallback(() => {
    const container = listRef.current
    if (!container) return
    container.scrollTop = Math.max(0, container.scrollHeight - container.clientHeight)
    followStreamRef.current = true
    lastScrollTopRef.current = container.scrollTop
    lastScrollHeightRef.current = container.scrollHeight
    lastClientHeightRef.current = container.clientHeight
  }, [])

  const scheduleFollowScroll = useCallback((force = false) => {
    if (document.hidden) {
      pendingVisibleScrollRef.current = true
      pendingVisibleForceScrollRef.current = pendingVisibleForceScrollRef.current || force
      return
    }
    queuedForceScrollRef.current = queuedForceScrollRef.current || force
    if (scrollFrameRef.current !== null) return
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      const shouldForce = queuedForceScrollRef.current
      queuedForceScrollRef.current = false
      const scrollToLatest = () => {
        const container = listRef.current
        if (!container) return false
        // User intent takes precedence over content growth. Once the user has
        // scrolled upward, only an explicit action or returning to the bottom
        // may restore following.
        if (!shouldForce && !followStreamRef.current) return false
        container.scrollTop = container.scrollHeight
        followStreamRef.current = true
        lastScrollTopRef.current = container.scrollTop
        lastScrollHeightRef.current = container.scrollHeight
        lastClientHeightRef.current = container.clientHeight
        return true
      }

      if (!scrollToLatest()) return
      // Markdown, code highlighting and collapsed panels can grow after the
      // first paint. Settle once more on the next frame so the visible latest
      // message is reliably at the bottom.
      if (scrollSettleFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollSettleFrameRef.current)
      }
      scrollSettleFrameRef.current = window.requestAnimationFrame(() => {
        scrollSettleFrameRef.current = null
        scrollToLatest()
      })
    })
  }, [])

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.hidden || !pendingVisibleScrollRef.current) return
      const force = pendingVisibleForceScrollRef.current
      pendingVisibleScrollRef.current = false
      pendingVisibleForceScrollRef.current = false
      scheduleFollowScroll(force)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [scheduleFollowScroll])

  useEffect(() => {
    const content = listContentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => scheduleFollowScroll())
    observer.observe(content)
    return () => observer.disconnect()
  }, [scheduleFollowScroll])

  useEffect(() => {
    const content = listContentRef.current
    if (!content || typeof MutationObserver === 'undefined') return
    const observer = new MutationObserver(() => scheduleFollowScroll())
    observer.observe(content, { childList: true, characterData: true, subtree: true })
    return () => observer.disconnect()
  }, [scheduleFollowScroll])

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current)
    if (scrollSettleFrameRef.current !== null) window.cancelAnimationFrame(scrollSettleFrameRef.current)
  }, [])

  const handleSend = () => {
    const payload = composerRef.current?.getPayload() ?? {
      message: composerDraft.trim(),
      references: selectedElements,
      templateIds: composerTemplates.map((template) => template.id),
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
    followStreamRef.current = true
    onSend(text, payload.references, imageAttachments)
    scheduleFollowScroll(true)
  }

  const handleInputChange = useCallback((value: string) => {
    onContextDraftChange(value)
  }, [onContextDraftChange])

  const handleEditRequest = useCallback((message: ChatMessageItem) => {
    onEditRequest(message)
    onContextDraftChange(message.content)
  }, [onContextDraftChange, onEditRequest])

  const handleMessageScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return
    const container = event.currentTarget
    const currentTop = container.scrollTop
    const nearBottom = isNearBottom(container)
    const layoutChanged = (
      container.scrollHeight !== lastScrollHeightRef.current
      || container.clientHeight !== lastClientHeightRef.current
    )
    const hasRecentUserScrollIntent = performance.now() < userScrollIntentUntilRef.current

    // Completing a tool can collapse its detail panel. The browser then clamps
    // scrollTop downward, which is not user intent and must not stop following.
    if (nearBottom) {
      followStreamRef.current = true
    } else if (
      currentTop < lastScrollTopRef.current - 10
      && (hasRecentUserScrollIntent || !layoutChanged)
    ) {
      followStreamRef.current = false
    }
    lastScrollTopRef.current = currentTop
    lastScrollHeightRef.current = container.scrollHeight
    lastClientHeightRef.current = container.clientHeight
  }, [])

  const markMessageListUserScrollIntent = useCallback(() => {
    userScrollIntentUntilRef.current = performance.now() + USER_SCROLL_INTENT_WINDOW_MS
  }, [])

  const selectedModel = models.find((model) => model.id === modelId)
  const isMultimodal = Boolean(selectedModel?.is_multimodal)
  const contextCannotFit = contextStats?.can_fit_after_compaction === false
  const conversationControlsDisabled = streaming || stopping || submitting || Boolean(pendingUserQuestion)
  const composerDisabled = stopping || submitting || Boolean(pendingUserQuestion)
  const canSend = Boolean(
    modelId
    && activeChatSession
    && !activeChatSession.is_archived
    && (!contextCannotFit || streaming)
    && !imageUploading
    && !submitting
    && (composerDraft.trim() || selectedElements.length > 0 || imageAttachments.length > 0 || composerTemplates.length > 0),
  )
  const effortConfig = selectedModel?.thinking_config?.efforts
  const effortOptions = effortConfig && typeof effortConfig === 'object' && !Array.isArray(effortConfig)
    ? Object.keys(effortConfig)
    : []
  const canDisableThinking = supportsDisabledThinkingOption(
    selectedModel,
    temporarilyUnsupportedThinkingModelIds,
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
  const runtimeTokens = streaming ? estimateRuntimeTokens(streamText, reasoningTrace, toolActivities) : 0
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
    if (!hasPositionedInitialHistoryRef.current && messages.length > 0) {
      hasPositionedInitialHistoryRef.current = true
      forceScrollToLatest()
      const frame = window.requestAnimationFrame(forceScrollToLatest)
      return () => {
        window.cancelAnimationFrame(frame)
      }
    }
    if (messages.length === 0) hasPositionedInitialHistoryRef.current = false
    scheduleFollowScroll()
  }, [conversationError, forceScrollToLatest, messages, pendingUserQuestion, queuedMessages, reasoningTrace, runtimeContextCompacting, scheduleFollowScroll, streamBlocks, streamNotice, streamText, streaming, toolActivities])

  return (
    <>
    <div className="chat-panel chat-panel-aichat">
      <div className="chat-panel-header">
        <div className="chat-panel-title-row">
          <div className="chat-panel-title-copy">
            <Text strong>排版助手</Text>
            <Text type="secondary">编辑当前推文</Text>
          </div>
          {streaming && (
            <span className={`chat-live-status${activeTool ? ' is-tool' : ''}`}>
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
                                disabled={conversationControlsDisabled || activeChatSession.is_archived}
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
        <div className="chat-panel-controls">
          <ModelSelector models={models} value={modelId} onChange={onModelChange} disabled={conversationControlsDisabled} />
          <Select
            className="thinking-effort-select"
            aria-label="思考强度"
            size="small"
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
              { value: 'auto', label: '思考强度：默认' },
              ...effortOptions.map((effort) => ({ value: effort, label: `思考强度：${effort}` })),
              ...(canDisableThinking ? [{ value: 'disabled', label: '不思考' }] : []),
            ]}
          />
        </div>
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
        {thinkingStatus && <Text className="chat-thinking-status" type="secondary">{thinkingStatus}</Text>}
      </div>

      {taskPlan && <TaskPlanPanel plan={taskPlan} live={streaming} />}

      <div
        className="chat-messages"
        ref={listRef}
        onScroll={handleMessageScroll}
        onWheelCapture={markMessageListUserScrollIntent}
        onTouchMoveCapture={markMessageListUserScrollIntent}
        onPointerDownCapture={markMessageListUserScrollIntent}
        onKeyDownCapture={markMessageListUserScrollIntent}
      >
        <div className="chat-messages-content" ref={listContentRef}>
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
                {streamNotice && <AgentRunNotice notice={streamNotice} />}
                <AssistantTurnTimeline
                  blocks={streamBlocks}
                  fallbackContent={streamText}
                  fallbackTrace={reasoningTrace}
                  fallbackTools={toolActivities}
                  streaming
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
              </div>
              <div className="chat-turn-meta"><span>排版助手</span></div>
            </div>
          </article>
        )}

        {queuedMessages.map((queuedMessage) => (
          <article className="chat-turn chat-turn-user chat-turn-queued" key={queuedMessage.id}>
            <div className="chat-turn-body">
              <div className="chat-turn-bubble">
                <div className="chat-turn-content">{queuedMessage.content}</div>
              </div>
              <div className="chat-turn-meta">
                <span>你 · 待处理</span>
                <Tooltip title="取消待处理要求">
                  <Button
                    className="chat-edit-request"
                    aria-label="取消待处理要求"
                    type="text"
                    size="small"
                    icon={<CloseOutlined />}
                    disabled={stopping}
                    onClick={() => onRemoveQueuedMessage(queuedMessage.id)}
                  />
                </Tooltip>
              </div>
            </div>
          </article>
        ))}
        </div>
      </div>

      <div className="chat-input-area">
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
          {imageAttachments.length > 0 && (
            <div className="chat-image-attachments" aria-label="待发送图片">
              {imageAttachments.map((attachment) => (
                <div className="chat-image-attachment" key={attachment.id}>
                  <img src={attachment.preview_url} alt={attachment.filename} />
                  <Tooltip title="移除图片">
                    <Button
                      aria-label={`移除图片 ${attachment.filename}`}
                      size="small"
                      type="text"
                      icon={<CloseOutlined />}
                      disabled={composerDisabled}
                      onClick={() => onRemoveImage(attachment)}
                    />
                  </Tooltip>
                </div>
              ))}
            </div>
          )}
          {imageUploading && (
            <div className="chat-image-uploading" role="status">
              <LoadingOutlined spin />
              <span>正在上传图片</span>
            </div>
          )}
          <PromptComposer
            ref={composerRef}
            value={composerDraft}
            references={selectedElements}
            templates={composerTemplates}
            onChange={handleInputChange}
            onSubmit={handleSend}
            disabled={composerDisabled}
            onRemoveReference={onRemoveSelectedElement}
            onDuplicateReference={onDuplicateSelectedElement}
            onMoveReference={onMoveSelectedElement}
            onRemoveTemplate={onRemoveComposerTemplate}
            acceptImages={isMultimodal}
            onPasteImages={onUploadImages}
          />
          <div className="chat-input-actions">
            <div className="chat-input-actions-start">
              <Tooltip title="模仿排版">
                <Button
                  aria-label="模仿排版"
                  icon={<FormatPainterOutlined />}
                  disabled={conversationControlsDisabled || !modelId || activeChatSession?.is_archived}
                  onClick={onOpenLayoutImitation}
                />
              </Tooltip>
              {isMultimodal && (
                <Tooltip title="添加图片">
                  <Button
                  aria-label="添加图片"
                  icon={<PaperClipOutlined />}
                  disabled={composerDisabled || imageUploading || activeChatSession?.is_archived || imageAttachments.length >= 5}
                    onClick={() => imageInputRef.current?.click()}
                  />
                </Tooltip>
              )}
              <Text type="secondary">Enter 发送，Shift+Enter 换行</Text>
            </div>
            <div className="chat-input-actions-submit">
              {contextStats && <ContextUsage stats={contextStats} runtimeTokens={runtimeTokens} onCompactContext={onCompactContext} />}
              {streaming && (
                <Tooltip title="停止生成">
                  <Button aria-label="停止生成" danger icon={<StopOutlined />} loading={stopping} disabled={stopping} onClick={onStop} />
                </Tooltip>
              )}
              <Tooltip title={streaming ? '加入待处理队列' : '发送'}>
                <Button aria-label={streaming ? '加入待处理队列' : '发送'} type="primary" icon={<SendOutlined />} disabled={!canSend} onClick={handleSend} />
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
    </>
  )
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

const ChatHistoryTurn = memo(function ChatHistoryTurn({
  messageItem,
  currentUserId,
  editingDisabled,
  onEditRequest,
}: {
  messageItem: ChatMessageItem
  currentUserId: number | undefined
  editingDisabled: boolean
  onEditRequest: (message: ChatMessageItem) => void
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
            />
          ) : (
            <div className="chat-turn-content">
              <UserMessageContent
                content={messageItem.content}
                elements={messageItem.selected_elements ?? []}
                templates={messageItem.template_refs ?? []}
                images={messageItem.image_attachments ?? []}
              />
            </div>
          )}
        </div>
        <div className="chat-turn-meta">
          <span>
            {messageAuthorLabel(messageItem, currentUserId)}
            {messageItem.role === 'assistant' && messageItem.model_usage && (
              <>
                {' · '}
                <Tooltip title={modelUsageDetail(messageItem.model_usage)}>
                  <span className="chat-turn-model-usage">{modelUsageLabel(messageItem.model_usage)}</span>
                </Tooltip>
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

export function modelUsageLabel(usage: NonNullable<ChatMessageItem['model_usage']>): string {
  const { modelNames, totalTokens, cacheHitRate, callCount } = modelUsageValues(usage)
  return usage.usage_reported
    ? `${modelNames} · 本轮 ${callCount} 次累计 ${formatTokenCount(totalTokens)} tokens · 缓存命中 ${cacheHitRate}%`
    : `${modelNames} · Token 未返回`
}

export function modelUsageDetail(usage: NonNullable<ChatMessageItem['model_usage']>): string {
  const { modelNames, inputTokens, outputTokens, totalTokens, cacheReadTokens, cacheHitRate, callCount } = modelUsageValues(usage)
  if (!usage.usage_reported) return `${modelNames} 未返回 token 用量`
  return `${modelNames}：本轮累计 ${callCount.toLocaleString()} 次模型调用；输入 ${inputTokens.toLocaleString()} tokens；缓存命中 ${cacheReadTokens.toLocaleString()} tokens（${cacheHitRate}%）；输出 ${outputTokens.toLocaleString()} tokens；合计 ${totalTokens.toLocaleString()} tokens`
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
  if (runningTool) return runningTool.preparing ? `正在准备${toolLabel(runningTool.name)}` : toolLabel(runningTool.name)
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
  if (tool.name !== 'update_task_plan' || tool.activity?.kind !== 'plan') return null
  const activity = tool.activity
  const structuredItems = taskPlanItemsFromDetails(activity.details?.tasks)
  const items = structuredItems.length > 0 ? structuredItems : taskPlanItemsFromTargets(activity.targets)
  return items.length > 0 ? { items } : null
}

function AgentRunNotice({ notice }: { notice: ChatRunNotice }) {
  const retryLabel = notice.kind === 'retrying' && notice.attempt && notice.maxAttempts
    ? `第 ${notice.attempt}/${notice.maxAttempts} 次`
    : ''

  return (
    <div className={`chat-run-notice is-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
      {notice.kind === 'retrying' ? <SyncOutlined spin /> : notice.kind === 'success' ? <CheckCircleFilled /> : <ExclamationCircleFilled />}
      <div className="chat-run-notice-copy">
        <div className="chat-run-notice-title">
          <strong>{notice.title}</strong>
          {retryLabel && <span>{retryLabel}</span>}
        </div>
        <div className="chat-run-notice-detail">{notice.detail}</div>
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
  const [expanded, setExpanded] = useState(false)
  const doneCount = plan.items.filter((item) => item.status === 'done').length
  const activeTask = plan.items.find((item) => item.status === 'in_progress')
  const nextTask = plan.items.find((item) => item.status === 'pending')
  const summary = activeTask
    ? `进行中：${activeTask.step}`
    : doneCount === plan.items.length
      ? '全部任务已完成'
      : nextTask
        ? `待办：${nextTask.step}`
        : '等待执行'

  return (
    <section className={`task-plan-panel${live ? ' is-live' : ''}`} aria-label="任务清单" aria-live={live ? 'polite' : 'off'}>
      <button
        className="task-plan-disclosure"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="task-plan-panel-title"><UnorderedListOutlined />任务清单</span>
        <span className={`task-plan-panel-summary${activeTask ? ' is-active' : ''}`} title={summary}>{summary}</span>
        <span className="task-plan-panel-progress">{doneCount}/{plan.items.length}</span>
        <span className="task-plan-expand-icon" aria-hidden="true">{expanded ? <UpOutlined /> : <DownOutlined />}</span>
      </button>
      {expanded && (
        <ol className="task-plan-list">
          {plan.items.map((item, index) => (
            <li
              key={`${item.status}-${item.step}-${index}`}
              className={`is-${item.status}`}
              aria-label={`${TASK_PLAN_STATUS_LABELS[item.status]}：${item.step}`}
            >
              <span className="task-plan-item-icon" aria-hidden="true">
                {item.status === 'done'
                  ? <CheckCircleFilled />
                  : item.status === 'in_progress'
                    ? <LoadingOutlined spin />
                    : <ClockCircleOutlined />}
              </span>
              <span className="task-plan-item-step">{item.step}</span>
              <span className="task-plan-item-status">{TASK_PLAN_STATUS_LABELS[item.status]}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
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
  const referencedTemplates = new Set<number>()
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
        if (!template) return <span key={`${part}-${index}`}>{part}</span>
        referencedTemplates.add(templateIndex)
        return <Tag key={`${part}-${index}`} className="chat-template-attachment">@组件{templateIndex + 1} &lt;{template.name}&gt;</Tag>
      })}
      {elements.map((element, index) => !referencedElements.has(index) && (
        <Tooltip key={`fallback-${index}`} title={<ElementRenderPreview html={element.html} />}>
          <Tag className="selected-element-tag">@元素{index + 1} &lt;{element.tag_name}&gt;</Tag>
        </Tooltip>
      ))}
      {templates.map((template, index) => !referencedTemplates.has(index) && (
        <Tag key={`template-fallback-${template.id}`} className="chat-template-attachment">@组件{index + 1} &lt;{template.name}&gt;</Tag>
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
}: {
  blocks: AssistantTurnBlock[]
  fallbackContent: string
  fallbackTrace: ReasoningTrace
  fallbackTools: ToolExecution[]
  streaming: boolean
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
  const timelineBlocks = rawTimelineBlocks.filter((block) => (
    block.type !== 'tool'
    || block.tool?.activity?.details?.reason !== 'user_question_timed_out'
  ))
  const displayBlocks = streaming ? timelineBlocks : settleHistoricalTimeline(timelineBlocks)
  const recoveredAfterRestart = !streaming && fallbackContent.includes('服务已重启，未完成的 Agent 已停止')
  const [archiveExpanded, setArchiveExpanded] = useState(recoveredAfterRestart)
  const timelineRef = useRef<HTMLDivElement>(null)
  const processResizeFrameRef = useRef<number | null>(null)
  const processFollowRef = useRef(new WeakMap<HTMLElement, boolean>())
  const processLastScrollTopRef = useRef(new WeakMap<HTMLElement, number>())
  const lastLiveProcessDetailsRef = useRef<HTMLElement[]>([])

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

  const getProcessDetailsToFollow = useCallback((): HTMLElement[] => {
    const activeDetails = Array.from(
      timelineRef.current?.querySelectorAll<HTMLElement>(
        '.thinking-trace-detail.is-live, .tool-trace-detail.is-live',
      ) ?? [],
    )
    if (activeDetails.length > 0) {
      lastLiveProcessDetailsRef.current = activeDetails
      return activeDetails
    }

    // A tool result is rendered in the same update that changes the tool from
    // running to completed, which removes .is-live. Follow that prior live
    // detail once so its freshly rendered result reaches the bottom, then clear
    // it to avoid moving historical panels for later assistant text deltas.
    const settledDetails = lastLiveProcessDetailsRef.current.filter((detail) => detail.isConnected)
    lastLiveProcessDetailsRef.current = []
    return settledDetails
  }, [])

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

  useEffect(() => {
    const timeline = timelineRef.current
    if (!timeline || !isStreamingProcess || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      if (processResizeFrameRef.current !== null) return
      processResizeFrameRef.current = window.requestAnimationFrame(() => {
        processResizeFrameRef.current = null
        scheduleProcessScroll()
      })
    })
    observer.observe(timeline)
    return () => observer.disconnect()
  }, [isStreamingProcess, scheduleProcessScroll])

  useEffect(() => () => {
    if (processResizeFrameRef.current !== null) window.cancelAnimationFrame(processResizeFrameRef.current)
  }, [])

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
          onChange={(keys) => setArchiveExpanded((Array.isArray(keys) ? keys : [keys]).includes('process'))}
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
                      />
                    ))}
                  </div>
                </div>
              ),
            },
          ]}
        />
      )}
      {finalContent && <div className="assistant-turn-final-content"><MemoMarkdownContent content={finalContent} /></div>}
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
  const editTools = tools.filter((tool) => ['apply_html_patch', 'replace_document'].includes(tool.name))
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
}: {
  block: AssistantTurnBlock
  archived?: boolean
  streaming?: boolean
  connectsToNext?: boolean
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
}) {
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
          <ToolTrace tool={block.tool} onProcessScroll={onProcessScroll} />
        </div>
      </div>
    )
  }

  return (
    <div className={`assistant-action-entry assistant-action-content${archived ? ' is-archived' : ''}`}>
      <div className="assistant-action-content-body">
        {streaming ? <StreamingMarkdownContent content={block.content} /> : <MemoMarkdownContent content={block.content} />}
      </div>
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
  if (['get_document_map', 'read_blocks', 'read_gzh_theme', 'read_current_gzh_theme', 'get_layout_reference_map', 'read_layout_reference_blocks'].includes(name)) return 'read'
  if (['search_html', 'search_layout_reference'].includes(name)) return 'search'
  if (['list_history_versions', 'search_history_versions', 'search_history_version', 'compare_history_version', 'read_history_blocks'].includes(name)) return 'history'
  if (['inspect_current_images', 'inspect_history_images'].includes(name)) return 'image'
  if (['apply_html_patch', 'replace_document'].includes(name)) return 'edit'
  if (name === 'check_compliance' || name === 'validate_gzh_html') return 'check'
  if (name === 'update_task_plan') return 'plan'
  if (name === 'apply_layout_reference') return 'reference'
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

function ToolTrace({
  tool,
  onProcessScroll,
}: {
  tool: ToolExecution
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
}) {
  const [expanded, setExpanded] = useState(tool.status === 'running')
  const previousStatus = useRef(tool.status)

  useEffect(() => {
    if (tool.status === 'running') {
      setExpanded(true)
    } else if (tool.status === 'error') {
      setExpanded(true)
    } else if (previousStatus.current === 'running' && tool.status === 'success') {
      const timer = window.setTimeout(() => setExpanded(false), 1200)
      previousStatus.current = tool.status
      return () => window.clearTimeout(timer)
    }
    previousStatus.current = tool.status
  }, [tool.status])

  const status = toolStatusSummary(tool)
  const isRunning = tool.status === 'running'
  const activity = tool.activity
  const detailResult = toolDetailResult(tool)
  const statusTone = status.tone
  const summary = isRunning
    ? tool.preparing ? '正在准备工具参数' : '正在执行操作'
    : toolActionTarget(tool)

  return (
    <Collapse
      className="assistant-action-row assistant-action-tool-row"
      size="small"
      expandIconPlacement="end"
      activeKey={expanded ? [tool.id] : []}
      onChange={(keys) => setExpanded((Array.isArray(keys) ? keys : [keys]).includes(tool.id))}
      items={[{
        key: tool.id,
        label: (
          <span className="tool-trace-label">
            <span className={`tool-trace-icon is-${toolVisualKind(tool.name)}`} aria-hidden="true"><ToolGlyph name={tool.name} /></span>
            <span className="tool-trace-copy">
              <span className={`tool-trace-title${isRunning ? ' is-running' : ''}`}>{toolLabel(tool.name)}</span>
              <span className="tool-trace-summary-text" title={summary}>{summary}</span>
              {tool.change_summary && !activity && <ChangeSummaryInline summary={tool.change_summary} />}
            </span>
            <span className={`tool-trace-status is-${statusTone}`}>{status.label}</span>
          </span>
        ),
        children: (
          <div className={`tool-trace-detail${isRunning ? ' is-live' : ''}`} onScroll={onProcessScroll}>
            {activity?.targets && activity.targets.length > 0 && (
              <div className="tool-activity-targets">
                {activity.targets.slice(0, activity.kind === 'plan' ? 12 : 4).map((target, index) => (
                  <span key={`${target.block_id ?? target.path ?? 'target'}-${index}`} title={target.path || target.text || ''}>
                    {target.text || target.path || target.tag || '排版块'}
                  </span>
                ))}
              </div>
            )}
            {activity?.html_validation?.valid === false && activity.html_validation.errors?.length ? (
              <div className="tool-trace-result">{activity.html_validation.errors.join('；')}</div>
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
            {!activity && Object.keys(tool.arguments).length > 0 && (
              <ToolCodeSection label="调用参数" language="json" code={JSON.stringify(tool.arguments, null, 2)} />
            )}
            {!activity && tool.change_summary?.diff_preview && (
              <ToolCodeSection
                label={tool.change_summary.diff_truncated ? '变更 diff（已截断）' : '变更 diff'}
                language="diff"
                code={tool.change_summary.diff_preview}
              />
            )}
            {detailResult && <div className="tool-trace-result">{detailResult}</div>}
          </div>
        ),
      }]}
    />
  )
}

function toolDetailResult(tool: ToolExecution): string {
  const result = tool.result?.trim()
  if (!result) return ''
  if (tool.status === 'error') return result
  const summary = tool.activity?.summary?.trim()
  if (!summary) return result

  const normalise = (value: string) => value.replace(/\s+/g, ' ').trim()
  const normalizedResult = normalise(result)
  const normalizedSummary = normalise(summary)
  // Successful activity summaries are already shown in the collapsed row.
  if (
    normalizedResult === normalizedSummary
    || normalizedResult === `错误：${normalizedSummary}`
    || normalizedResult === `错误: ${normalizedSummary}`
  ) {
    return ''
  }
  return result
}

function toolErrorMetadata(tool: ToolExecution): string {
  if (tool.status !== 'error') return ''
  const details = tool.activity?.details
  if (!details || typeof details !== 'object' || Array.isArray(details)) return ''
  const requested = Number(details.requested_block_count)
  const maximum = Number(details.max_read_blocks)
  if (Number.isFinite(requested) && Number.isFinite(maximum)) {
    return `本次请求读取 ${requested} 个排版块，上限为 ${maximum} 个。`
  }
  return ''
}

function toolStatusSummary(tool: ToolExecution): { label: string; tone: 'running' | 'error' | 'changed' | 'success' } {
  if (tool.status === 'running' && tool.preparing) return { label: '准备中', tone: 'running' }
  if (tool.status === 'running') return { label: '执行中', tone: 'running' }
  if (tool.status === 'error') return { label: '执行失败', tone: 'error' }
  if (tool.html_changed) return { label: '已更新', tone: 'changed' }
  return { label: '完成', tone: 'success' }
}

function toolActionTarget(tool: ToolExecution): string {
  if (tool.activity?.summary) return tool.activity.summary
  if (['get_document_map', 'search_html', 'read_blocks'].includes(tool.name)) return 'HTML'
  if (tool.name === 'check_compliance') return '兼容性'
  return toolLabel(tool.name)
}

function ChangeSummaryInline({ summary }: { summary: ChangeSummary }) {
  return (
    <span className="tool-change-inline">
      <span className="is-added">+{summary.added_lines}</span>
      <span className="is-removed">-{summary.removed_lines}</span>
    </span>
  )
}

function ChangeSummaryLine({ summary }: { summary: ChangeSummary }) {
  return (
    <div className="tool-change-summary">
      <span>新增 {summary.added_lines} 行</span>
      <span>删除 {summary.removed_lines} 行</span>
    </div>
  )
}

function ToolCodeSection({ label, language, code }: { label: string; language: string; code: string }) {
  return (
    <section className="tool-code-section">
      <div className="tool-code-section-title">{label}</div>
      <CodeBlock code={code} language={language} showLineNumbers={code.split('\n').length > 1} />
    </section>
  )
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
  const [expanded, setExpanded] = useState(isThinking)
  const liveDurationMs = useLiveThoughtDuration(isThinking, startedAtMs)

  useEffect(() => {
    setExpanded(isThinking)
  }, [isThinking])

  const label = isThinking ? '正在思考' : '思考过程'

  return (
    <Collapse
      className={`assistant-action-row assistant-action-thought-row is-${trace.status}`}
      size="small"
      expandIconPlacement="end"
      activeKey={expanded ? ['thinking'] : []}
      onChange={(keys) => {
        if (!isThinking) setExpanded((Array.isArray(keys) ? keys : [keys]).includes('thinking'))
      }}
      items={[
        {
          key: 'thinking',
          label: (
            <span className="thinking-action-label">
              <span className="thinking-action-icon" aria-hidden="true"><BulbOutlined /></span>
              <span>{label}</span>
              <span className={`thinking-action-status is-${trace.status}`}>{isThinking ? '分析中' : '已完成'}</span>
              {isThinking && liveDurationMs !== null && (
                <span className="thought-duration" aria-label={`已思考 ${formatThoughtDuration(liveDurationMs)}`}>
                  {formatThoughtDuration(liveDurationMs)}
                </span>
              )}
              {!isThinking && durationMs !== null && durationMs !== undefined && (
                <span className="thought-duration">{formatThoughtDuration(durationMs)}</span>
              )}
            </span>
          ),
          children: (
            <div className={`thinking-trace-detail${isThinking ? ' is-live' : ''}`} onScroll={onProcessScroll}>
              {trace.content
                ? trace.content
                : <span>{trace.detail || '模型正在生成推理内容…'}</span>}
            </div>
          ),
        },
      ]}
    />
  )
}

function useLiveThoughtDuration(isThinking: boolean, startedAtMs?: number): number | null {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!isThinking || !startedAtMs) return
    const update = () => setNow(Date.now())
    update()
    const timer = window.setInterval(update, 100)
    return () => window.clearInterval(timer)
  }, [isThinking, startedAtMs])

  return isThinking && startedAtMs ? Math.max(0, now - startedAtMs) : null
}

function formatThoughtDuration(durationMs: number): string {
  if (durationMs < 60_000) return `${Math.max(0.1, durationMs / 1000).toFixed(1)} 秒`
  const minutes = Math.floor(durationMs / 60_000)
  const seconds = Math.round((durationMs % 60_000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}
