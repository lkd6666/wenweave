import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { Button, Drawer, Grid, Input, Modal, Popconfirm, Popover, Progress, Segmented, Slider, Space, Switch, Tooltip, message } from 'antd'
import { AppstoreOutlined, ArrowLeftOutlined, BulbOutlined, CloudDownloadOutlined, CopyOutlined, EditOutlined, FileSearchOutlined, HistoryOutlined, LinkOutlined, MoonOutlined, MoreOutlined, RedoOutlined, ReloadOutlined, SafetyCertificateOutlined, SaveOutlined, SelectOutlined, SendOutlined, UndoOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router'
import ChatPanel, { type ChatRunNotice, type QueuedChatMessage, type ReaskConflictNotice } from '../components/ChatPanel'
import type { UserQuestionAnswer } from '../components/UserQuestionPanel'
import PreviewFrame from '../components/PreviewFrame'
import type { PreviewFrameHandle, PreviewMode } from '../components/PreviewFrame'
import type { HtmlValidationReport } from '../types'
import CompliancePanel from '../components/CompliancePanel'
import VersionHistoryDrawer from '../components/VersionHistoryDrawer'
import TemplateLibraryPanel, { type ResourceTab } from '../components/TemplateLibraryPanel'
import ImageLibraryPanel from '../components/ImageLibraryPanel'
import { documentsApi } from '../api/documents'
import { imageLibraryApi } from '../api/imageLibrary'
import { complianceApi } from '../api/compliance'
import { modelsApi } from '../api/models'
import { aiProvidersApi } from '../api/aiProviders'
import { wechatAccountsApi } from '../api/wechatAccounts'
import { MAX_CHAT_IMAGES_PER_MESSAGE, cancelChatRun, chatApi, reaskDocumentConflictFromError, reaskSourceUnavailableFromError, startChatRun, streamChatRunEvents } from '../api/chat'
import type { AgentRunTimeline, ReaskConflictResolution, ThinkingEffort, ThinkingMode } from '../api/chat'
import { ApiError } from '../api/client'
import { abortableDelay, isRetryable, retryDelayMs } from '../utils/retry'
import { retryNotice } from '../utils/retryNotice'
import type { UploadProgress } from '../api/client'
import { runImageUploads } from '../utils/imageUpload'
import useImageUploadProgress from '../hooks/useImageUploadProgress'
import { useChatTextAttachments } from '../hooks/useChatTextAttachments'
import type { ChatTextAttachment } from '../types'
import type { AIModelItem, AssistantTurnBlock, ChatContextStats, ChatImageAttachment, ChatMessageItem, ChatSessionItem, ChatUserQuestion, ComplianceReport, GzhThemeProposal, LayoutReferenceImitationStrength, LayoutReferencePreview, PreviewImageTarget, ReasoningTrace, SelectedElementContext, TemplateItem, ToolActivity, ToolExecution, VisibilitySettings, WeChatAvailableAccount } from '../types'
import { sanitizeSelectedElement, sanitizeSelectedElements } from '../utils/selectedElements'
import { prepareWeChatBodyImage } from '../utils/wechatBodyImage'
import { clearChatComposerDraft, clearChatComposerDraftForRequest, readChatComposerDraft, writeChatComposerDraft } from '../utils/chatComposerDraft'
import { orderMessageTemplates, restoreComposerTemplates } from '../utils/templateReferences'
import { canAdvanceQueuedChat, moveQueuedChatItem, updateQueuedChatContent } from '../utils/chatQueue'
import { createChatRunConnection, detachChatRunConnection, ownsChatRunConnection, requestChatRunStop, retireChatRunConnection } from '../utils/chatRunConnection'
import type { ChatRunConnection } from '../utils/chatRunConnection'
import { resolveThinkingPreference, saveThinkingPreference } from '../utils/thinkingPreference'
import { requestChatQuestionNotificationPermissionOnce } from '../utils/chatQuestionNotifications'
import { useAuthStore } from '../store/authStore'

const CodeViewer = lazy(() => import('../components/CodeViewer'))
const LayoutImitationModal = lazy(() => import('../components/LayoutImitationModal'))
const SourceDocumentModal = lazy(() => import('../components/SourceDocumentModal'))
const ThemeGalleryModal = lazy(() => import('../components/ThemeGalleryModal'))
const WeChatDraftModal = lazy(() => import('../components/WeChatDraftModal'))
const DocumentShareModal = lazy(() => import('../components/DocumentShareModal'))

type CenterView = 'preview' | 'code'
type MobileWorkspace = 'chat' | CenterView
type WorkspaceLoadStep = 'document' | 'sessions' | 'models' | 'resources' | 'messages' | 'draft' | 'editor'
type WorkspaceLoadStepStatus = 'pending' | 'loading' | 'completed'
interface WorkspaceResourceProgress {
  loaded: number
  total: number
}
const STREAM_RENDER_INTERVAL_MS = 48
const CHAT_HISTORY_PAGE_SIZE = 30
const MAX_STREAM_RECONNECT_ATTEMPTS = 12
const MIN_CHAT_PANE_WIDTH = 300
const MIN_CENTER_PANE_WIDTH = 440
const MIN_TOUCH_CENTER_PANE_WIDTH = 320
const MIN_RESOURCE_PANE_WIDTH = 260
const COLUMN_RESIZER_WIDTH = 8
const AUTO_SAVE_DELAY_MS = 5000
const USER_QUESTION_ACTIVITY_THROTTLE_MS = 10_000
const LAST_SELECTED_MODEL_STORAGE_KEY_PREFIX = 'yibanpaiban-last-selected-model'
const PREVIEW_RESOURCE_TIMEOUT_MS = 12_000

const WORKSPACE_LOAD_STEPS: Array<{ key: WorkspaceLoadStep; label: string }> = [
  { key: 'document', label: '文章内容' },
  { key: 'sessions', label: '对话列表' },
  { key: 'models', label: '可用模型' },
  { key: 'resources', label: '预览前端资源' },
  { key: 'messages', label: '当前对话记录' },
  { key: 'draft', label: '未发送内容' },
  { key: 'editor', label: '编辑器初始化' },
]

function initialWorkspaceLoadSteps(): Record<WorkspaceLoadStep, WorkspaceLoadStepStatus> {
  return {
    document: 'loading',
    sessions: 'loading',
    models: 'loading',
    resources: 'pending',
    messages: 'pending',
    draft: 'pending',
    editor: 'pending',
  }
}

function extractPreviewResourceUrls(html: string): string[] {
  const document = new DOMParser().parseFromString(html, 'text/html')
  return [...new Set(
    Array.from(document.querySelectorAll<HTMLImageElement>('img[src]'))
      .map((image) => image.getAttribute('src')?.trim() ?? '')
      .filter((source) => source && !source.startsWith('data:')),
  )]
}

function preloadPreviewResources(
  html: string,
  onProgress: (progress: WorkspaceResourceProgress) => void,
): Promise<void> {
  const resources = extractPreviewResourceUrls(html)
  const total = resources.length
  onProgress({ loaded: 0, total })
  if (total === 0) return Promise.resolve()

  let loaded = 0
  const settleResource = () => {
    loaded += 1
    onProgress({ loaded, total })
  }
  return Promise.all(resources.map((source) => new Promise<void>((resolve) => {
    let settled = false
    const settle = () => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      settleResource()
      resolve()
    }
    const image = new Image()
    const timeout = window.setTimeout(settle, PREVIEW_RESOURCE_TIMEOUT_MS)
    image.referrerPolicy = 'no-referrer'
    image.onload = settle
    image.onerror = settle
    image.src = source
    if (image.complete) queueMicrotask(settle)
  }))).then(() => undefined)
}

type ComplianceButtonStatus = 'unknown' | 'checking' | 'success' | 'warning' | 'error'

type ReaskConflictState = ReaskConflictNotice & { currentChecksum?: string }

interface QueuedChatRequest extends QueuedChatMessage {
  sessionId: number
  references: SelectedElementContext[]
  images: ChatImageAttachment[]
  texts: ChatTextAttachment[]
  templates: TemplateItem[]
  referencedTemplates: TemplateItem[]
  modelId: number
  thinkingMode: ThinkingMode
  thinkingEffort: ThinkingEffort
}

interface ChatRunOptions {
  modelId: number
  thinkingMode: ThinkingMode
  thinkingEffort: ThinkingEffort
  templates?: TemplateItem[]
  referencedTemplates?: TemplateItem[]
  textAttachments?: ChatTextAttachment[]
}

export function getComplianceButtonStatus(
  report: ComplianceReport | null,
  loading = false,
): ComplianceButtonStatus {
  if (loading) return 'checking'
  if (!report) return 'unknown'
  if (!report.engine.available || report.isValid === null) return 'warning'
  if (report.isValid === false || report.violations.length > 0 || report.gzhStrict?.hasError) return 'error'
  if (report.gzhStrict?.hasWarning) return 'warning'
  return 'success'
}

export function complianceReportFromToolActivity(
  activity: ToolActivity | null | undefined,
): ComplianceReport | null {
  const report = activity?.compliance as unknown
  if (!report || typeof report !== 'object' || Array.isArray(report)) return null
  const candidate = report as Partial<ComplianceReport>
  if (!candidate.engine || typeof candidate.engine !== 'object') return null
  if (!Array.isArray(candidate.violations) || !Array.isArray(candidate.warnMsgs)) return null
  if (candidate.isValid !== true && candidate.isValid !== false && candidate.isValid !== null) return null
  return candidate as ComplianceReport
}

export function latestComplianceReportFromTools(
  tools: ToolExecution[] | null | undefined,
): ComplianceReport | null {
  if (!Array.isArray(tools)) return null
  for (const tool of [...tools].reverse()) {
    if (tool.name !== 'check_compliance') continue
    const report = complianceReportFromToolActivity(tool.activity)
    if (report) return report
  }
  return null
}

function getComplianceButtonLabel(status: ComplianceButtonStatus): string {
  switch (status) {
    case 'checking':
      return '正在检测合规性'
    case 'success':
      return '官方合规检测通过'
    case 'warning':
      return '官方合规检测未验证或存在警告'
    case 'error':
      return '存在官方合规违规'
    default:
      return '尚未运行官方合规检测'
  }
}

function formatModelRetryReason(reason: string): string {
  const status = /^upstream_(\d{3})$/.exec(reason)
  if (status) return `模型服务 ${status[1]}`
  if (reason === 'stream_first_progress_timeout') return '等待模型首个输出超时'
  if (reason === 'stream_progress_idle_timeout') return '模型输出中断超时'
  if (reason === 'connection_interrupted') return '模型连接中断'
  return '模型服务暂时不可用'
}

function selectedModelStorageKey(userId: number | null | undefined): string | null {
  return userId && userId > 0 ? `${LAST_SELECTED_MODEL_STORAGE_KEY_PREFIX}:${userId}` : null
}

function getLastSelectedModelId(userId: number | null | undefined): number | null {
  const key = selectedModelStorageKey(userId)
  if (!key) return null
  try {
    const value = Number(window.localStorage.getItem(key))
    return Number.isSafeInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

function saveLastSelectedModelId(userId: number | null | undefined, modelId: number): void {
  const key = selectedModelStorageKey(userId)
  if (!key) return
  try {
    window.localStorage.setItem(key, String(modelId))
  } catch {
    // Keep the selection for the current page if storage is unavailable.
  }
}

function clearLastSelectedModelId(userId: number | null | undefined): void {
  const key = selectedModelStorageKey(userId)
  if (!key) return
  try {
    window.localStorage.removeItem(key)
  } catch {
    // The fallback model still remains usable for the current page.
  }
}

function finishActiveTextBlock(blocks: AssistantTurnBlock[], endedAtMs = Date.now()): AssistantTurnBlock[] {
  const last = blocks.at(-1)
  if (!last || (last.type !== 'thought' && last.type !== 'content') || last.state === 'done') return blocks
  const duration_ms = last.type === 'thought' && last.started_at_ms
    ? Math.max(0, endedAtMs - last.started_at_ms)
    : last.duration_ms
  return [...blocks.slice(0, -1), { ...last, state: 'done', duration_ms }]
}

function appendStreamTextBlock(
  blocks: AssistantTurnBlock[],
  type: Extract<AssistantTurnBlock['type'], 'thought' | 'content'>,
  text: string,
  occurredAtMs = Date.now(),
): AssistantTurnBlock[] {
  if (!text) return blocks
  const last = blocks.at(-1)
  if (last?.type === type && last.state === 'active') {
    return [...blocks.slice(0, -1), { ...last, content: last.content + text }]
  }
  return [
    ...finishActiveTextBlock(blocks, occurredAtMs),
    {
      id: `${type}-${blocks.length + 1}`,
      type,
      state: 'active',
      content: text,
      duration_ms: null,
      ...(type === 'thought' ? { started_at_ms: occurredAtMs } : {}),
      tool: null,
    },
  ]
}

function timelineContent(blocks: AssistantTurnBlock[]): string {
  return blocks
    .filter((block) => block.type === 'content')
    .map((block) => block.content)
    .join('')
}

export function mergeContextStats(current: ChatContextStats | null, incoming: ChatContextStats): ChatContextStats {
  if (!current) return incoming
  if ((current.model_id && incoming.model_id && current.model_id !== incoming.model_id)
    || (current.session_id && incoming.session_id && current.session_id !== incoming.session_id)) return incoming
  if (incoming.runtime_context_source) return incoming
  const keepRuntimeContext = ['provider_reported', 'server_recomputed_after_tool', 'server_request_budget'].includes(
    current.runtime_context_source ?? '',
  )
    && ['streaming', 'tool_result_context', 'tool_outputs_stored', 'run_compacting', 'in_run_compacted', 'run_compaction_failed'].includes(
      incoming.runtime_context_state ?? incoming.state,
    )
  if (!keepRuntimeContext) return incoming
  // A retained estimate must keep the threshold and model configuration that
  // priced it. Polling persisted history does not describe the live projection.
  const budget = Object.fromEntries([
    'used_tokens', 'compiled_input_tokens', 'usage_percent', 'active_context_threshold_tokens',
    'usable_tokens', 'input_limit_tokens', 'max_tokens', 'max_output_tokens', 'token_estimate_multiplier',
  ].filter((key) => current[key as keyof ChatContextStats] != null)
    .map((key) => [key, current[key as keyof ChatContextStats]]))
  return {
    ...incoming,
    ...budget,
    runtime_context_tokens: current.runtime_context_tokens,
    runtime_context_breakdown: current.runtime_context_breakdown,
    runtime_context_source: current.runtime_context_source,
    runtime_context_is_estimate: current.runtime_context_is_estimate,
    runtime_context_tool_call_id: current.runtime_context_tool_call_id,
    runtime_context_tool_name: current.runtime_context_tool_name,
  }
}

function preserveRetriedToolPreviews(
  checkpoint: {
    tools: ToolExecution[]
    blocks: AssistantTurnBlock[]
  },
  currentTools: ToolExecution[],
  currentBlocks: AssistantTurnBlock[],
  retryAttempt: number,
): { tools: ToolExecution[]; blocks: AssistantTurnBlock[] } {
  const checkpointToolIds = new Set(checkpoint.tools.map((tool) => tool.id))
  const retrySuffix = `:retry-${Math.max(1, retryAttempt)}`
  const interruptedBySourceId = new Map<string, ToolExecution>()

  currentTools.forEach((tool) => {
    if (checkpointToolIds.has(tool.id) || tool.status !== 'running' || !tool.preparing) return
    interruptedBySourceId.set(tool.id, {
      ...tool,
      id: `${tool.id}${retrySuffix}`,
      status: 'interrupted',
      preparing: false,
      result: '本次工具参数生成被模型重试中断，尚未执行任何修改。',
      activity: {
        kind: 'retry',
        summary: '参数生成中断，正在重新请求模型',
      },
    })
  })

  if (interruptedBySourceId.size === 0) return checkpoint

  const interruptedBlocks = currentBlocks.flatMap((block) => {
    const sourceId = block.type === 'tool' ? block.tool?.id : null
    const interrupted = sourceId ? interruptedBySourceId.get(sourceId) : undefined
    return interrupted
      ? [{ ...block, id: `${block.id}${retrySuffix}`, tool: interrupted }]
      : []
  })
  const blockedSourceIds = new Set(interruptedBlocks.map((block) => block.tool?.id))
  const missingBlocks = [...interruptedBySourceId.entries()]
    .filter(([, tool]) => !blockedSourceIds.has(tool.id))
    .map(([sourceId, tool]) => ({
      id: `block-${sourceId}${retrySuffix}`,
      type: 'tool' as const,
      state: 'done' as const,
      content: '',
      duration_ms: null,
      tool,
    }))

  return {
    tools: [...checkpoint.tools, ...interruptedBySourceId.values()],
    blocks: [...checkpoint.blocks, ...interruptedBlocks, ...missingBlocks],
  }
}

function createClientRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `run-${Date.now()}-${Math.random().toString(36).slice(2)}`
}


function codePointWidth(value: string, index: number): number {
  return (value.codePointAt(index) ?? 0) > 0xffff ? 2 : 1
}

function previousCodePointIndex(value: string, index: number): number {
  const previous = value.charCodeAt(index - 1)
  return previous >= 0xdc00 && previous <= 0xdfff && index > 1 ? index - 2 : index - 1
}

function buildHtmlSplice(baseHtml: string, nextHtml: string): Omit<import('../api/documents').DocumentHtmlPatch, 'base_checksum'> {
  let baseStart = 0
  let nextStart = 0
  let prefixLength = 0
  while (
    baseStart < baseHtml.length
    && nextStart < nextHtml.length
    && baseHtml.codePointAt(baseStart) === nextHtml.codePointAt(nextStart)
  ) {
    baseStart += codePointWidth(baseHtml, baseStart)
    nextStart += codePointWidth(nextHtml, nextStart)
    prefixLength += 1
  }

  let baseEnd = baseHtml.length
  let nextEnd = nextHtml.length
  let suffixLength = 0
  while (baseEnd > baseStart && nextEnd > nextStart) {
    const basePrevious = previousCodePointIndex(baseHtml, baseEnd)
    const nextPrevious = previousCodePointIndex(nextHtml, nextEnd)
    if (baseHtml.codePointAt(basePrevious) !== nextHtml.codePointAt(nextPrevious)) break
    baseEnd = basePrevious
    nextEnd = nextPrevious
    suffixLength += 1
  }

  return {
    prefix_length: prefixLength,
    suffix_length: suffixLength,
    replacement: nextHtml.slice(nextStart, nextEnd),
  }
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export default function EditorPage() {
  const { documentId } = useParams()
  const navigate = useNavigate()
  const docId = Number(documentId)
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const currentUser = useAuthStore((state) => state.user)

  const [title, setTitle] = useState('')
  const [html, setHtml] = useState('')
  const [draftHtml, setDraftHtml] = useState('')
  const [previewRevision, setPreviewRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [workspaceLoadSteps, setWorkspaceLoadSteps] = useState<Record<WorkspaceLoadStep, WorkspaceLoadStepStatus>>(initialWorkspaceLoadSteps)
  const [workspaceResourceProgress, setWorkspaceResourceProgress] = useState<WorkspaceResourceProgress>({ loaded: 0, total: 0 })
  const [hasSourceFile, setHasSourceFile] = useState(false)
  const [documentGroupId, setDocumentGroupId] = useState<number | null>(null)
  const [documentVisibility, setDocumentVisibility] = useState<VisibilitySettings>({
    visibility_mode: 'all',
    allowed_user_ids: [],
    allowed_group_ids: [],
  })
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false)
  const [themeGalleryOpen, setThemeGalleryOpen] = useState(false)
  const [themeGalleryInitialKey, setThemeGalleryInitialKey] = useState<string | null>(null)
  const [wechatDraftOpen, setWechatDraftOpen] = useState(false)
  const [documentShareOpen, setDocumentShareOpen] = useState(false)
  const [wechatAccounts, setWechatAccounts] = useState<WeChatAvailableAccount[]>([])
  const [saving, setSaving] = useState(false)
  const [materializingTemplateImages, setMaterializingTemplateImages] = useState(false)
  const [localizingArticleImages, setLocalizingArticleImages] = useState(false)
  const [chatPaneWidth, setChatPaneWidth] = useState<number | null>(null)
  const [resizingChatPane, setResizingChatPane] = useState(false)
  const [resourcePaneWidth, setResourcePaneWidth] = useState<number | null>(null)
  const [resizingResourcePane, setResizingResourcePane] = useState(false)
  const [resourceCollapsed, setResourceCollapsed] = useState(false)
  const [resourceDrawerOpen, setResourceDrawerOpen] = useState(false)
  const [mobileActionsDrawerOpen, setMobileActionsDrawerOpen] = useState(false)
  const [activeResourceTab, setActiveResourceTab] = useState<ResourceTab>('templates')
  const [imageLibraryCommand, setImageLibraryCommand] = useState<{ id: number; tab: 'library' | 'search' | 'generate'; editCurrentImage?: boolean } | null>(null)
  const [imageApplicationTarget, setImageApplicationTarget] = useState<'image' | 'block' | 'caret' | null>(null)
  const [activeCanvasImage, setActiveCanvasImage] = useState<PreviewImageTarget | null>(null)

  const [models, setModels] = useState<AIModelItem[]>([])
  const [modelId, setModelId] = useState<number | null>(null)
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>('enabled')
  const [thinkingEffort, setThinkingEffort] = useState<ThinkingEffort>('auto')
  const [temporarilyUnsupportedThinkingModelIds, setTemporarilyUnsupportedThinkingModelIds] = useState<Set<number>>(new Set())
  const [thinkingStatus, setThinkingStatus] = useState<string | null>(null)
  const [contextStats, setContextStats] = useState<ChatContextStats | null>(null)
  const [contextDraft, setContextDraft] = useState('')
  const [composerTemplates, setComposerTemplates] = useState<TemplateItem[]>([])
  const [chatImages, setChatImages] = useState<ChatImageAttachment[]>([])
  const [chatImageUploading, setChatImageUploading] = useState(false)
  const [chatImageUploadProgress, setChatImageUploadProgress] = useImageUploadProgress()
  const [reasoningTrace, setReasoningTrace] = useState<ReasoningTrace>({ status: 'idle', content: '', detail: '' })

  const [messages, setMessages] = useState<ChatMessageItem[]>([])
  const [hasOlderMessages, setHasOlderMessages] = useState(false)
  const [olderMessagesLoading, setOlderMessagesLoading] = useState(false)
  const [chatSessions, setChatSessions] = useState<ChatSessionItem[]>([])
  const [activeChatSessionId, setActiveChatSessionId] = useState<number | null>(null)
  const olderMessagesLoadingRef = useRef(false)
  const activeHistorySessionRef = useRef(activeChatSessionId)
  const messagesRef = useRef(messages)
  activeHistorySessionRef.current = activeChatSessionId
  messagesRef.current = messages
  const setRecentMessages = useCallback((items: ChatMessageItem[]) => {
    setHasOlderMessages(items.length > CHAT_HISTORY_PAGE_SIZE)
    setMessages(items.slice(-CHAT_HISTORY_PAGE_SIZE))
  }, [])
  const loadRecentMessages = useCallback((documentId: number, sessionId: number) => (
    chatApi.listRecentMessages(documentId, sessionId, CHAT_HISTORY_PAGE_SIZE + 1)
  ), [])
  const loadOlderMessages = useCallback(async (): Promise<boolean> => {
    const sessionId = activeChatSessionId
    const firstId = messagesRef.current[0]?.id
    if (!docId || !sessionId || !firstId || !hasOlderMessages || olderMessagesLoadingRef.current) return false
    olderMessagesLoadingRef.current = true
    setOlderMessagesLoading(true)
    try {
      const page = await chatApi.listRecentMessages(docId, sessionId, CHAT_HISTORY_PAGE_SIZE + 1, firstId)
      if (activeHistorySessionRef.current !== sessionId || messagesRef.current[0]?.id !== firstId) return false
      setHasOlderMessages(page.length > CHAT_HISTORY_PAGE_SIZE)
      const older = page.slice(-CHAT_HISTORY_PAGE_SIZE)
      if (older.length === 0) return false
      setMessages((current) => current[0]?.id === firstId ? [...older, ...current] : current)
      return true
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载更早对话失败')
      return false
    } finally {
      olderMessagesLoadingRef.current = false
      setOlderMessagesLoading(false)
    }
  }, [activeChatSessionId, docId, hasOlderMessages])
  const [hiddenHistory, setHiddenHistory] = useState<ChatMessageItem[]>([])
  const [streaming, setStreaming] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [toolActivities, setToolActivities] = useState<ToolExecution[]>([])
  const [streamBlocks, setStreamBlocks] = useState<AssistantTurnBlock[]>([])
  const compactionControllerRef = useRef<AbortController | null>(null)
  const [streamNotice, setStreamNotice] = useState<ChatRunNotice | null>(null)
  const [recoveryNotice, setRecoveryNotice] = useState<ChatRunNotice | null>(null)
  const [recoveryCheck, setRecoveryCheck] = useState(0)
  const recoveredCheckRef = useRef(0)
  const [conversationError, setConversationError] = useState<string | null>(null)
  const chatTexts = useChatTextAttachments(docId || undefined, activeChatSessionId)
  const { restore: restoreChatTexts, detach: detachChatTexts } = chatTexts
  const [chatSubmitting, setChatSubmitting] = useState(false)
  const [queuedChatRequests, setQueuedChatRequests] = useState<QueuedChatRequest[]>([])
  const [chatQueuePaused, setChatQueuePaused] = useState(false)
  const [pendingUserQuestion, setPendingUserQuestion] = useState<ChatUserQuestion | null>(null)
  const [questionSubmitting, setQuestionSubmitting] = useState(false)
  const documentEditingLocked = streaming || Boolean(pendingUserQuestion) || questionSubmitting
  const [reaskConflict, setReaskConflict] = useState<ReaskConflictState | null>(null)
  const [resolvingReaskConflict, setResolvingReaskConflict] = useState(false)

  const [centerView, setCenterView] = useState<CenterView>('preview')
  const [codeViewMounted, setCodeViewMounted] = useState(false)
  const [mobileWorkspace, setMobileWorkspace] = useState<MobileWorkspace>('preview')
  const [previewMode, setPreviewMode] = useState<PreviewMode>('browse')
  const [previewBrightness, setPreviewBrightness] = useState(100)
  const [previewDarkMode, setPreviewDarkMode] = useState(false)
  const effectivePreviewMode = previewMode === 'edit' && (documentEditingLocked || localizingArticleImages) ? 'select' : previewMode
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState === 'visible')
  const [editHistoryState, setEditHistoryState] = useState({ canUndo: false, canRedo: false })
  const [selectedElements, setSelectedElements] = useState<SelectedElementContext[]>([])
  const [, setActiveCaretTarget] = useState<SelectedElementContext | null>(null)
  const [attachedTemplates, setAttachedTemplates] = useState<TemplateItem[]>([])
  const [templateAttachmentsUpdating, setTemplateAttachmentsUpdating] = useState(false)
  const templateAttachmentUpdateRef = useRef(false)
  const [templateCollection, setTemplateCollection] = useState<{ id: number; html: string } | null>(null)
  const [hasPreviewCaret, setHasPreviewCaret] = useState(false)
  const [pendingReaskMessageId, setPendingReaskMessageId] = useState<number | null>(null)
  const [complianceDrawerOpen, setComplianceDrawerOpen] = useState(false)
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false)
  const [layoutImitationOpen, setLayoutImitationOpen] = useState(false)
  const [versionRefreshToken, setVersionRefreshToken] = useState(0)
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null)
  const [complianceLoading, setComplianceLoading] = useState(false)

  useEffect(() => {
    setPreviewDarkMode(false)
  }, [docId])

  useEffect(() => {
    const update = () => setPageVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])

  const chatRunConnectionRef = useRef<ChatRunConnection | null>(null)
  const documentLoadVersionRef = useRef(0)
  const attachedEditorDocumentRef = useRef<number | null>(null)
  const activeRunRef = useRef<string | null>(null)
  const resumedRunRef = useRef<string | null>(null)
  const resumeHandlerRef = useRef<((
    runId: string,
    sessionId?: number,
    streamAfter?: number,
    timeline?: AgentRunTimeline | null,
  ) => Promise<void>) | null>(null)
  const questionAnswerRequestRef = useRef<{
    questionId: string
    answerKey: string
    clientRequestId: string
  } | null>(null)
  const questionActivityRef = useRef<{ questionId: string; lastSentAt: number } | null>(null)
  const questionTimeoutRecoveryRef = useRef<string | null>(null)
  const pendingUserQuestionRef = useRef(pendingUserQuestion)
  pendingUserQuestionRef.current = pendingUserQuestion
  const documentEditingLockedRef = useRef(documentEditingLocked)
  const documentMutationEpochRef = useRef(0)
  if (documentEditingLockedRef.current !== documentEditingLocked) documentMutationEpochRef.current += 1
  documentEditingLockedRef.current = documentEditingLocked
  const columnsRef = useRef<HTMLDivElement>(null)
  const resizeCleanupRef = useRef<(() => void) | null>(null)
  const htmlRef = useRef('')
  const draftHtmlRef = useRef('')
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRequestRef = useRef<Promise<string | null> | null>(null)
  const savedHtmlValidationRef = useRef<{ html: string; report: HtmlValidationReport | null } | null>(null)
  const previewFrameRef = useRef<PreviewFrameHandle>(null)
  const codeViewerHtmlRef = useRef('')
  const creatingChatSessionRef = useRef(false)
  const modelIdRef = useRef<number | null>(null)
  const modelsRef = useRef<AIModelItem[]>([])
  const documentIdRef = useRef<number | null>(null)
  const chatImageDocumentIdRef = useRef<number | null>(null)
  const chatImagesRef = useRef<ChatImageAttachment[]>([])
  const observedDocumentIdRef = useRef<number | null>(docId || null)
  const selectedElementsDocumentIdRef = useRef<number | null>(docId || null)
  const chatImageDraftEpochRef = useRef(0)
  const chatImageUploadInProgressRef = useRef(false)
  const chatStartInProgressRef = useRef(false)
  const promptedUnsupportedThinkingModelIdsRef = useRef<Set<number>>(new Set())
  const queuedChatRequestsRef = useRef<QueuedChatRequest[]>([])
  const queuedRequestStarterRef = useRef<((request: QueuedChatRequest) => void) | null>(null)

  htmlRef.current = html
  draftHtmlRef.current = draftHtml
  modelIdRef.current = modelId
  modelsRef.current = models
  documentIdRef.current = docId ?? null
  chatImagesRef.current = chatImages
  queuedChatRequestsRef.current = queuedChatRequests
  const activeChatSession = chatSessions.find((item) => item.id === activeChatSessionId) ?? null
  useEffect(() => {
    if (!docId || !activeChatSessionId) return
    const saved = readChatComposerDraft(docId, activeChatSessionId)
    if (saved?.textAttachments && ['editing', 'retry'].includes(saved.phase)) restoreChatTexts(saved.textAttachments)
    // The attachment hook owns the current session lifetime.
  }, [docId, activeChatSessionId, restoreChatTexts])

  const versionCopyDefaults = useMemo(() => ({ group_id: documentGroupId, ...documentVisibility }), [documentGroupId, documentVisibility])

  useEffect(() => () => resizeCleanupRef.current?.(), [])
  useEffect(() => () => {
    compactionControllerRef.current?.abort()
    compactionControllerRef.current = null
  }, [docId, activeChatSessionId])

  const cancelAutoSave = useCallback(() => {
    if (!autoSaveTimerRef.current) return
    clearTimeout(autoSaveTimerRef.current)
    autoSaveTimerRef.current = null
  }, [])

  useEffect(() => {
    if (documentEditingLocked) cancelAutoSave()
  }, [cancelAutoSave, documentEditingLocked])

  const applyExternalHtml = useCallback((nextHtml: string) => {
    // AI、加载和版本恢复已由各自服务端流程持久化，不应进入手动自动保存队列。
    cancelAutoSave()
    htmlRef.current = nextHtml
    draftHtmlRef.current = nextHtml
    setHtml(nextHtml)
    setDraftHtml(nextHtml)
  }, [cancelAutoSave])

  const resolveStoredComposerDraft = useCallback(async (documentId: number, sessionId: number) => {
    const saved = readChatComposerDraft(documentId, sessionId)
    if (!saved) return null
    if (saved.phase === 'editing' || saved.phase === 'retry') return saved

    try {
      const run = saved.runId
        ? await chatApi.getRun(documentId, saved.runId)
        : saved.clientRequestId
          ? await chatApi.getRunByClientRequest(documentId, saved.clientRequestId)
          : null
      if (run && ['pending', 'running', 'cancelling'].includes(run.status)) {
        writeChatComposerDraft(documentId, sessionId, { ...saved, phase: 'running', runId: run.run_id })
        return null
      }
      if (run?.status === 'completed' || run?.status === 'cancelled') {
        clearChatComposerDraft(documentId, sessionId)
        return null
      }
      if (run?.status === 'failed') {
        // A failed run is terminal, so retrying it needs a fresh idempotency
        // key instead of replaying the same failed request.
        const retry = {
          message: saved.message,
          textAttachments: saved.textAttachments,
          templateRefs: saved.templateRefs,
          reaskFromMessageId: saved.reaskFromMessageId,
          phase: 'retry' as const,
        }
        writeChatComposerDraft(documentId, sessionId, retry)
        return retry
      }
    } catch {
      // A disconnected backend is precisely when the original instruction
      // must remain available for retry.
    }

    const retry = { ...saved, phase: 'retry' as const }
    writeChatComposerDraft(documentId, sessionId, retry)
    return retry
  }, [])

  useEffect(() => {
    if (!docId || !activeChatSessionId || loading || chatSubmitting) return
    const saved = readChatComposerDraft(docId, activeChatSessionId)
    const readyTexts = chatTexts.items.filter(item => item.status !== 'uploading' && item.status !== 'error')
    if (!contextDraft.trim() && !readyTexts.length && !composerTemplates.length) {
      if (saved?.phase === 'editing' || saved?.phase === 'retry') clearChatComposerDraft(docId, activeChatSessionId)
      return
    }
    const retainRetryIdentity = saved?.phase === 'retry'
      && saved.message === contextDraft
      && saved.reaskFromMessageId === pendingReaskMessageId
      && JSON.stringify((saved.textAttachments ?? []).map(item => item.id)) === JSON.stringify(readyTexts.map(item => item.id))
      && JSON.stringify((saved.templateRefs ?? []).map(item => item.id)) === JSON.stringify(composerTemplates.map(item => item.id))
    writeChatComposerDraft(docId, activeChatSessionId, {
      message: contextDraft,
      textAttachments: readyTexts,
      templateRefs: composerTemplates.map(({ id, name }) => ({ id, name })),
      reaskFromMessageId: pendingReaskMessageId,
      phase: retainRetryIdentity ? 'retry' : 'editing',
      ...(retainRetryIdentity && saved.clientRequestId ? { clientRequestId: saved.clientRequestId } : {}),
    })
  }, [activeChatSessionId, chatSubmitting, chatTexts.items, composerTemplates, contextDraft, docId, loading, pendingReaskMessageId])

  const handleChatPaneResizeStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0) || window.matchMedia('(max-width: 720px)').matches) return
    const columns = columnsRef.current
    if (!columns) return
    const bounds = columns.getBoundingClientRect()
    const minimumCenterWidth = window.matchMedia('(pointer: coarse)').matches
      ? MIN_TOUCH_CENTER_PANE_WIDTH
      : MIN_CENTER_PANE_WIDTH
    const resourceWidth = columns.querySelector<HTMLElement>('.editor-col-resource')?.getBoundingClientRect().width ?? 0
    const resizerWidth = columns.querySelectorAll<HTMLElement>('.editor-col-resizer').length * COLUMN_RESIZER_WIDTH
    const maximumWidth = bounds.width - resourceWidth - minimumCenterWidth - resizerWidth
    if (maximumWidth < MIN_CHAT_PANE_WIDTH) return

    event.preventDefault()
    const resizer = event.currentTarget
    try {
      resizer.setPointerCapture(event.pointerId)
    } catch {
      // Some older touch browsers do not implement pointer capture.
    }
    resizeCleanupRef.current?.()
    setResizingChatPane(true)
    const previousUserSelect = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    const updateWidth = (clientX: number) => {
      const nextWidth = Math.max(MIN_CHAT_PANE_WIDTH, Math.min(maximumWidth, clientX - bounds.left))
      setChatPaneWidth(Math.round(nextWidth))
    }
    const handleMove = (moveEvent: PointerEvent) => updateWidth(moveEvent.clientX)
    const finish = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      document.body.style.userSelect = previousUserSelect
      if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId)
      resizeCleanupRef.current = null
      setResizingChatPane(false)
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }, [])

  const handleResourcePaneResizeStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0) || resourceCollapsed || window.matchMedia('(max-width: 991px)').matches) return
    const columns = columnsRef.current
    if (!columns) return
    const bounds = columns.getBoundingClientRect()
    const minimumCenterWidth = window.matchMedia('(pointer: coarse)').matches
      ? MIN_TOUCH_CENTER_PANE_WIDTH
      : MIN_CENTER_PANE_WIDTH
    const chatWidth = columns.querySelector<HTMLElement>('.editor-col-chat')?.getBoundingClientRect().width ?? MIN_CHAT_PANE_WIDTH
    const resizerWidth = columns.querySelectorAll<HTMLElement>('.editor-col-resizer').length * COLUMN_RESIZER_WIDTH
    const maximumWidth = bounds.width - chatWidth - minimumCenterWidth - resizerWidth
    if (maximumWidth < MIN_RESOURCE_PANE_WIDTH) return

    event.preventDefault()
    const resizer = event.currentTarget
    try {
      resizer.setPointerCapture(event.pointerId)
    } catch {
      // Some older touch browsers do not implement pointer capture.
    }
    resizeCleanupRef.current?.()
    setResizingResourcePane(true)
    const previousUserSelect = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    const updateWidth = (clientX: number) => {
      const nextWidth = Math.max(MIN_RESOURCE_PANE_WIDTH, Math.min(maximumWidth, bounds.right - clientX))
      setResourcePaneWidth(Math.round(nextWidth))
    }
    const handleMove = (moveEvent: PointerEvent) => updateWidth(moveEvent.clientX)
    const finish = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      document.body.style.userSelect = previousUserSelect
      if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId)
      resizeCleanupRef.current = null
      setResizingResourcePane(false)
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }, [resourceCollapsed])

  // Only a completed official checker result is authoritative. Any local edit
  // invalidates that snapshot, but never starts an HTTP compliance check.
  const invalidateCompliance = useCallback(() => {
    setCompliance(null)
  }, [])

  const handleManualComplianceCheck = useCallback(async () => {
    if (complianceLoading) return
    const snapshot = draftHtmlRef.current
    const sourceDocumentId = documentIdRef.current
    setComplianceLoading(true)
    try {
      const report = await complianceApi.check(snapshot)
      if (draftHtmlRef.current !== snapshot || documentIdRef.current !== sourceDocumentId) {
        message.info('内容已变化，本次检测结果已失效')
        return
      }
      setCompliance(report)
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '合规检测失败，请稍后重试')
    } finally {
      setComplianceLoading(false)
    }
  }, [complianceLoading])

  const loadDocument = useCallback(async () => {
    if (!docId || Number.isNaN(docId)) return
    const loadVersion = ++documentLoadVersionRef.current
    const ownsLoad = () => loadVersion === documentLoadVersionRef.current
      && documentIdRef.current === docId && attachedEditorDocumentRef.current === docId
    setLoading(true)
    setWorkspaceLoadSteps(initialWorkspaceLoadSteps())
    setWorkspaceResourceProgress({ loaded: 0, total: 0 })
    try {
      const markLoadStepCompleted = (step: WorkspaceLoadStep) => {
        if (!ownsLoad()) return
        setWorkspaceLoadSteps((current) => ({ ...current, [step]: 'completed' }))
      }
      const [doc, sessions, modelList] = await Promise.all([
        documentsApi.get(docId).then((document) => {
          markLoadStepCompleted('document')
          return document
        }),
        chatApi.listSessions(docId).then((items) => {
          markLoadStepCompleted('sessions')
          return items
        }),
        modelsApi.list().then((items) => {
          markLoadStepCompleted('models')
          return items
        }),
      ])
      if (!ownsLoad()) return
      const activeSession = sessions.find((item) => !item.is_archived) ?? sessions[0]
      if (activeSession) {
        setWorkspaceLoadSteps((current) => ({
          ...current,
          messages: 'loading',
          draft: 'loading',
        }))
      } else {
        markLoadStepCompleted('messages')
        markLoadStepCompleted('draft')
      }
      const [msgs, restoredComposerDraft] = activeSession
        ? await Promise.all([
          loadRecentMessages(docId, activeSession.id).then((items) => {
            markLoadStepCompleted('messages')
            return items
          }),
          resolveStoredComposerDraft(docId, activeSession.id).then((draft) => {
            markLoadStepCompleted('draft')
            return draft
          }),
        ])
        : [[], null]
      if (!ownsLoad()) return
      setWorkspaceLoadSteps((current) => ({ ...current, resources: 'loading', editor: 'loading' }))
      await preloadPreviewResources(doc.current_html, (progress) => {
        if (ownsLoad()) setWorkspaceResourceProgress(progress)
      })
      if (!ownsLoad()) return
      markLoadStepCompleted('resources')
      setTitle(doc.title)
      setHasSourceFile(doc.has_source_file)
      setDocumentGroupId(doc.group_id)
      setDocumentVisibility({
        visibility_mode: doc.visibility_mode,
        allowed_user_ids: doc.allowed_user_ids,
        allowed_group_ids: doc.allowed_group_ids,
      })
      applyExternalHtml(doc.current_html)
      setPreviewRevision((value) => value + 1)
      setActiveCaretTarget(null)
      // A refresh rehydrates the same article, not the user's selection
      // intent. Keep its anchor so the next turn resolves it against this
      // latest HTML; only discard anchors when navigating to another article.
      const selectionBelongsToAnotherDocument = (
        selectedElementsDocumentIdRef.current !== null
        && selectedElementsDocumentIdRef.current !== docId
      )
      selectedElementsDocumentIdRef.current = docId
      setSelectedElements((items) => (selectionBelongsToAnotherDocument ? [] : items))
      setVersionRefreshToken((value) => value + 1)
      setRecentMessages(msgs)
      setChatSessions(sessions)
      setActiveChatSessionId(activeSession?.id ?? null)
      setAttachedTemplates(activeSession?.attached_templates ?? [])
      setComposerTemplates(restoreComposerTemplates(restoredComposerDraft?.templateRefs))
      setTemplateAttachmentsUpdating(false)
      templateAttachmentUpdateRef.current = false
      setContextDraft(restoredComposerDraft?.message ?? '')
      setPendingReaskMessageId(restoredComposerDraft?.reaskFromMessageId ?? null)
      setHiddenHistory([])
      setModels(modelList)
      const lastSelectedModelId = getLastSelectedModelId(currentUser?.id)
      const lastSelectedModel = modelList.find((model) => model.id === lastSelectedModelId)
      const defaultModel = modelList.find((m) => m.is_default) ?? modelList[0]
      const selectedModel = lastSelectedModel ?? defaultModel
      if (!lastSelectedModel && lastSelectedModelId !== null) {
        clearLastSelectedModelId(currentUser?.id)
      }
      setModelId(selectedModel?.id ?? null)
      const restoredThinkingPreference = resolveThinkingPreference(currentUser?.id, selectedModel)
      setThinkingMode(restoredThinkingPreference.mode)
      setThinkingEffort(restoredThinkingPreference.effort)
      invalidateCompliance()
      markLoadStepCompleted('editor')
    } catch (err) {
      if (!ownsLoad()) return
      message.error(err instanceof ApiError ? String(err.detail) : '加载文档失败')
      navigate('/')
    } finally {
      if (ownsLoad()) setLoading(false)
    }
  }, [applyExternalHtml, currentUser?.id, docId, invalidateCompliance, loadRecentMessages, navigate, resolveStoredComposerDraft, setRecentMessages])

  const openImageLibrary = useCallback((tab: 'library' | 'search' | 'generate' = 'library', editCurrentImage = false) => {
    setCenterView('preview')
    setMobileWorkspace('preview')
    setPreviewMode('edit')
    setResourceCollapsed(false)
    if (isCompact) setResourceDrawerOpen(true)
    setActiveResourceTab('images')
    setImageLibraryCommand({ id: Date.now(), tab, editCurrentImage })
  }, [isCompact])

  const handleThinkingCapabilityFallback = useCallback((fallback: {
    model_id: number
    message: string
    reason: string
    fallback_mode: 'auto'
  }) => {
    if (!fallback.model_id) return
    setTemporarilyUnsupportedThinkingModelIds((current) => {
      if (current.has(fallback.model_id)) return current
      return new Set(current).add(fallback.model_id)
    })
    if (modelId === fallback.model_id) {
      setThinkingMode('auto')
      setThinkingEffort('auto')
    }
    setThinkingStatus(fallback.message)
    message.warning(fallback.message)
    if (currentUser?.role !== 'admin' || promptedUnsupportedThinkingModelIdsRef.current.has(fallback.model_id)) return

    promptedUnsupportedThinkingModelIdsRef.current.add(fallback.model_id)
    Modal.confirm({
      title: '将模型标记为不支持不思考？',
      content: '该模型已拒绝禁止思考参数。本次页面将不再提供“不思考”；确认后会为所有用户永久关闭该模型的此选项。',
      okText: '永久关闭',
      cancelText: '仅本页隐藏',
      onOk: async () => {
        try {
          await aiProvidersApi.updateModel(fallback.model_id, { supports_disabled_thinking: false })
          setModels(await modelsApi.list())
          message.success('已永久关闭该模型的不思考选项')
        } catch (error) {
          message.error(error instanceof ApiError ? String(error.detail) : '更新模型能力失败')
        }
      },
    })
  }, [currentUser?.role, modelId])

  useEffect(() => {
    let active = true
    void wechatAccountsApi.available()
      .then((accounts) => { if (active) setWechatAccounts(accounts) })
      .catch(() => { if (active) setWechatAccounts([]) })
    return () => { active = false }
  }, [docId])

  useEffect(() => {
    attachedEditorDocumentRef.current = docId ?? null
    chatStartInProgressRef.current = false
    saveRequestRef.current = null
    savedHtmlValidationRef.current = null
    activeRunRef.current = null
    resumedRunRef.current = null
    setChatSubmitting(false)
    setStreaming(false)
    setStopping(false)
    setSaving(false)
    setMaterializingTemplateImages(false)
    setLocalizingArticleImages(false)
    setStreamText('')
    setToolActivities([])
    setStreamBlocks([])
    setStreamNotice(null)
    setRecoveryNotice(null)
    setThinkingStatus(null)
    setPendingUserQuestion(null)
    setQuestionSubmitting(false)
    questionAnswerRequestRef.current = null
    questionTimeoutRecoveryRef.current = null
    loadDocument()
    return () => {
      documentLoadVersionRef.current += 1
      if (attachedEditorDocumentRef.current === (docId ?? null)) attachedEditorDocumentRef.current = null
      detachChatRunConnection(chatRunConnectionRef.current)
      cancelAutoSave()
    }
  }, [cancelAutoSave, docId, loadDocument])

  useEffect(() => {
    if (!docId || Number.isNaN(docId) || !modelId || !activeChatSessionId || activeChatSession?.is_archived) {
      setContextStats(null)
      return
    }
    if (streaming || compactionControllerRef.current || !pageVisible) return
    let active = true
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void chatApi.previewContext(
        docId,
        modelId,
        activeChatSessionId,
        contextDraft,
        selectedElements,
        chatImages.map((item) => item.id),
        attachedTemplates.map((item) => item.id),
        controller.signal,
        chatTexts.items.filter(item => item.status !== 'uploading' && item.status !== 'error').map(item => item.id),
      )
        .then((stats) => {
          if (active && !compactionControllerRef.current) setContextStats(stats)
        })
        .catch((error) => {
          if (error instanceof DOMException && error.name === 'AbortError') return
          if (active && !compactionControllerRef.current) setContextStats(null)
        })
    }, contextDraft || selectedElements.length > 0 || chatImages.length > 0 || attachedTemplates.length > 0 ? 300 : 0)
    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [activeChatSession, activeChatSessionId, attachedTemplates, chatImages, chatTexts.items, contextDraft, docId, messages.length, modelId, pageVisible, selectedElements, streaming])

  const handleImageUpload = useCallback(async (file: File): Promise<string> => {
    if (!docId) throw new Error('文档不存在')
    try {
      const prepared = await prepareWeChatBodyImage(file)
      const [asset] = await imageLibraryApi.upload(docId, [prepared.file])
      if (!asset) throw new Error('图片未保存到图库')
      return asset.url
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '图片上传失败')
      throw err
    }
  }, [docId])

  const persistDraftHtml = useCallback(async (showSuccess = false, saveLatest = true): Promise<string | null> => {
    if (!docId) return null
    const loadVersion = documentLoadVersionRef.current
    const ownsDocument = () => loadVersion === documentLoadVersionRef.current
      && documentIdRef.current === docId && attachedEditorDocumentRef.current === docId
    if (!ownsDocument() || documentEditingLockedRef.current) return null
    cancelAutoSave()
    const validationMessageKey = `document-html-validation-${docId}`
    const warnAboutStructure = (report: HtmlValidationReport) => {
      message.warning({
        key: validationMessageKey,
        content: `修改已保存，但正文 HTML 结构有误，同步前需要修复：${report.errors?.[0] || '请检查正文标签的嵌套与闭合。'}`,
        duration: 8,
      })
    }

    // 同一文档同一时刻仅保存一笔。显式保存和发送前保存会继续写入最新草稿；
    // 自动保存只落当前快照，后续输入交给新的空闲计时器处理。
    while (true) {
      if (!ownsDocument() || documentEditingLockedRef.current) return null
      const inFlight = saveRequestRef.current
      if (inFlight) {
        const saved = await inFlight
        if (saved === null) return null
        if (!saveLatest) return saved
        continue
      }

      const snapshot = draftHtmlRef.current
      const baseHtml = htmlRef.current
      if (snapshot === htmlRef.current) {
        if (showSuccess) {
          const validation = savedHtmlValidationRef.current
          if (validation?.html === snapshot && validation.report?.valid === false) warnAboutStructure(validation.report)
          else message.success('预览修改已保存')
        }
        return htmlRef.current
      }

      const request = (async (): Promise<string | null> => {
        setSaving(true)
        try {
          const patch = {
            ...buildHtmlSplice(baseHtml, snapshot),
            base_checksum: await sha256(baseHtml),
          }
          if (!ownsDocument() || documentEditingLockedRef.current) return null
          const result = await documentsApi.patchContent(docId, patch)
          const savedHtml = result.html
          if (!ownsDocument()) return null
          const previousValidation = savedHtmlValidationRef.current
          savedHtmlValidationRef.current = { html: savedHtml, report: result.html_validation ?? null }
          if (result.html_validation?.valid === false) {
            if (!showSuccess) warnAboutStructure(result.html_validation)
          } else if (previousValidation?.report?.valid === false) {
            message.destroy(validationMessageKey)
          }
          htmlRef.current = savedHtml
          setHtml(savedHtml)

          // 用户在请求中继续编辑时保留新草稿，下一轮循环会自动保存它。
          if (draftHtmlRef.current === snapshot) {
            draftHtmlRef.current = savedHtml
            setDraftHtml(savedHtml)
            invalidateCompliance()
          }
          setPreviewRevision((value) => value + 1)
          setVersionRefreshToken((value) => value + 1)
          return savedHtml
        } catch (err) {
          if (ownsDocument()) message.error(err instanceof ApiError ? String(err.detail) : '保存失败')
          return null
        } finally {
          if (ownsDocument()) setSaving(false)
        }
      })()

      saveRequestRef.current = request
      const saved = await request
      if (saveRequestRef.current === request) saveRequestRef.current = null
      if (saved === null) return null
      if (!saveLatest) return saved
    }
  }, [cancelAutoSave, docId, invalidateCompliance])

  const scheduleAutoSave = useCallback(() => {
    cancelAutoSave()
    if (documentEditingLockedRef.current) return
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      void persistDraftHtml(false, false)
    }, AUTO_SAVE_DELAY_MS)
  }, [cancelAutoSave, persistDraftHtml])

  const renderedDocumentEpoch = documentLoadVersionRef.current
  const renderedMutationEpoch = documentMutationEpochRef.current
  const ownsRenderedDocument = useCallback(() => documentIdRef.current === docId
    && attachedEditorDocumentRef.current === docId
    && documentLoadVersionRef.current === renderedDocumentEpoch, [docId, renderedDocumentEpoch])
  const ownsRenderedMutation = useCallback(() => ownsRenderedDocument()
    && documentMutationEpochRef.current === renderedMutationEpoch, [ownsRenderedDocument, renderedMutationEpoch])

  const handleHtmlChange = useCallback((next: string) => {
    // Delayed editor/iframe callbacks can retain props from before the pause.
    if (!ownsRenderedMutation() || documentEditingLockedRef.current || localizingArticleImages || next === draftHtmlRef.current) return
    draftHtmlRef.current = next
    setDraftHtml(next)
    invalidateCompliance()
    scheduleAutoSave()
  }, [invalidateCompliance, localizingArticleImages, ownsRenderedMutation, scheduleAutoSave])

  const handleInsertTemplateAtBoundary = useCallback(async (template: TemplateItem, placement: 'prepend' | 'append') => {
    if (!docId || !ownsRenderedMutation() || documentEditingLockedRef.current || saving || materializingTemplateImages || localizingArticleImages) return
    setMaterializingTemplateImages(true)
    try {
      const result = await documentsApi.materializeTemplateImages(docId, template.id)
      if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
      const inserted = previewFrameRef.current?.insertTemplateHtml(result.html, placement)
      if (!inserted) {
        message.error('画布尚未准备好，无法添加模板')
        return
      }
      const position = placement === 'prepend' ? '文首' : '文末'
      message.success(result.localized_count
        ? `已转存 ${result.localized_count} 张图片并将「${template.name}」添加到${position}`
        : `已将「${template.name}」添加到${position}`)
    } catch (err) {
      if (!ownsRenderedDocument()) return
      message.error(err instanceof ApiError ? String(err.detail) : '组件图片转存失败，未插入文章')
    } finally {
      if (ownsRenderedDocument()) setMaterializingTemplateImages(false)
    }
  }, [docId, localizingArticleImages, materializingTemplateImages, ownsRenderedDocument, ownsRenderedMutation, saving])

  const handleInsertTemplateAtCaret = useCallback(async (template: TemplateItem) => {
    if (!docId || !ownsRenderedMutation() || documentEditingLockedRef.current || saving || materializingTemplateImages || localizingArticleImages) return
    setMaterializingTemplateImages(true)
    try {
      const result = await documentsApi.materializeTemplateImages(docId, template.id)
      if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
      const inserted = previewFrameRef.current?.insertTemplateHtml(result.html, 'caret')
      if (!inserted) {
        setHasPreviewCaret(false)
        message.warning('请在直接编辑模式中将真实文本光标放到画布内，再插入模板')
        return
      }
      message.success(result.localized_count ? `已转存 ${result.localized_count} 张图片并插入「${template.name}」` : `已将「${template.name}」插入光标处`)
    } catch (err) {
      if (!ownsRenderedDocument()) return
      message.error(err instanceof ApiError ? String(err.detail) : '组件图片转存失败，未插入文章')
    } finally {
      if (ownsRenderedDocument()) setMaterializingTemplateImages(false)
    }
  }, [docId, localizingArticleImages, materializingTemplateImages, ownsRenderedDocument, ownsRenderedMutation, saving])

  const handleLocalizeArticleImages = useCallback(async () => {
    if (!docId || !ownsRenderedMutation() || documentEditingLockedRef.current || saving || materializingTemplateImages || localizingArticleImages) return
    setLocalizingArticleImages(true)
    const progressMessageKey = `editor-localize-external-images-${docId}-${renderedDocumentEpoch}`
    const externalImageCount = (draftHtmlRef.current.match(/<img\b[^>]*https?:\/\//gi) ?? []).length
    message.loading({ key: progressMessageKey, content: '正在保存文章并转存外链图片…', duration: 0 })
    try {
      previewFrameRef.current?.flushPendingChange()
      if (await persistDraftHtml(false) === null || !ownsRenderedMutation() || documentEditingLockedRef.current) {
        message.destroy(progressMessageKey)
        return
      }
      message.loading({
        key: progressMessageKey,
        content: externalImageCount > 0
          ? `正在转存外链图片（${externalImageCount} 张），请稍候…`
          : '正在转存外链图片，请稍候…',
        duration: 0,
      })
      const result = await documentsApi.localizeExternalImages(docId)
      if (!ownsRenderedMutation() || documentEditingLockedRef.current) {
        message.destroy(progressMessageKey)
        return
      }
      applyExternalHtml(result.html)
      setPreviewRevision((value) => value + 1)
      setVersionRefreshToken((value) => value + 1)
      invalidateCompliance()
      message.success({
        key: progressMessageKey,
        content: result.localized_count ? `已转存 ${result.localized_count} 张外链图片` : '未发现需要转存的外链图片',
        duration: 3,
      })
    } catch (err) {
      if (!ownsRenderedDocument()) {
        message.destroy(progressMessageKey)
        return
      }
      message.error({
        key: progressMessageKey,
        content: err instanceof ApiError ? String(err.detail) : '文章图片转存失败，正文未修改',
        duration: 4,
      })
    } finally {
      if (ownsRenderedDocument()) setLocalizingArticleImages(false)
    }
  }, [applyExternalHtml, docId, invalidateCompliance, localizingArticleImages, materializingTemplateImages, ownsRenderedDocument, ownsRenderedMutation, persistDraftHtml, renderedDocumentEpoch, saving])

  const handleExternalImagesPasted = useCallback(() => {
    // Wait for the iframe's native paste/input event to update draftHtmlRef.
    window.setTimeout(() => { void handleLocalizeArticleImages() }, 0)
  }, [handleLocalizeArticleImages])

  const handleCopyPreviewArticle = useCallback(async () => {
    const result = await previewFrameRef.current?.copyArticle()
    if (result === 'copied') {
      message.success('文章已复制，可直接粘贴到公众号编辑器')
      return
    }
    if (result === 'empty') {
      message.info('暂无文章内容可复制')
      return
    }
    message.error('复制失败，请检查浏览器剪贴板权限后重试')
  }, [])

  useEffect(() => {
    const handleCanvasHistoryShortcut = (event: KeyboardEvent) => {
      if (
        centerView !== 'preview'
        || documentEditingLockedRef.current
        || saving
        || (!event.ctrlKey && !event.metaKey)
        || event.altKey
      ) return

      const key = event.key.toLowerCase()
      const direction = key === 'y' || (key === 'z' && event.shiftKey)
        ? 'redo'
        : key === 'z'
          ? 'undo'
          : null
      if (!direction) return

      const target = event.target
      if (
        target instanceof HTMLElement
        && target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')
      ) return

      const completed = direction === 'undo'
        ? previewFrameRef.current?.undo()
        : previewFrameRef.current?.redo()
      if (!completed) return
      event.preventDefault()
      event.stopPropagation()
    }

    window.addEventListener('keydown', handleCanvasHistoryShortcut, true)
    return () => window.removeEventListener('keydown', handleCanvasHistoryShortcut, true)
  }, [centerView, saving])

  const applySessionResourceContext = useCallback((updated: ChatSessionItem) => {
    setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
    if (updated.id === activeChatSessionId) {
      // Attached templates change the next-request preview. Invalidate the
      // retained post-run meter so the context effect recomputes it once.
      if (!streaming) setContextStats(null)
      const nextTemplates = updated.attached_templates ?? []
      setAttachedTemplates(nextTemplates)
      setComposerTemplates((items) => {
        const availableIds = new Set(nextTemplates.map((item) => item.id))
        return items.filter((item) => availableIds.has(item.id))
      })
    }
  }, [activeChatSessionId, streaming])

  const attachTemplateToChat = useCallback(async (template: TemplateItem) => {
    if (!docId || !activeChatSessionId || activeChatSession?.is_archived || templateAttachmentUpdateRef.current) return
    const attached = attachedTemplates.find((item) => item.id === template.id)
    if (attached) {
      setComposerTemplates((items) => items.some((item) => item.id === attached.id) ? items : [...items, attached])
      return
    }
    const next = [...attachedTemplates, template]
    if (next.length > 6) {
      message.warning('每个对话最多附加 6 个模板')
      return
    }
    const loadVersion = documentLoadVersionRef.current
    templateAttachmentUpdateRef.current = true
    setTemplateAttachmentsUpdating(true)
    try {
      const updated = await chatApi.replaceTemplateAttachments(docId, activeChatSessionId, next.map((item) => item.id))
      if (loadVersion !== documentLoadVersionRef.current) return
      applySessionResourceContext(updated)
      setComposerTemplates((items) => items.some((item) => item.id === template.id) ? items : [...items, template])
    } catch (err) {
      if (loadVersion === documentLoadVersionRef.current) message.error(err instanceof ApiError ? String(err.detail) : '更新对话组件失败')
    } finally {
      if (loadVersion === documentLoadVersionRef.current) {
        templateAttachmentUpdateRef.current = false
        setTemplateAttachmentsUpdating(false)
      }
    }
  }, [activeChatSession?.is_archived, activeChatSessionId, applySessionResourceContext, attachedTemplates, docId])

  const removeAttachedTemplate = useCallback(async (templateId: number) => {
    if (!docId || !activeChatSessionId || activeChatSession?.is_archived || templateAttachmentUpdateRef.current) return
    const loadVersion = documentLoadVersionRef.current
    templateAttachmentUpdateRef.current = true
    setTemplateAttachmentsUpdating(true)
    try {
      const updated = await chatApi.removeTemplateAttachment(docId, activeChatSessionId, templateId)
      if (loadVersion !== documentLoadVersionRef.current) return
      applySessionResourceContext(updated)
      setComposerTemplates((items) => items.filter((item) => item.id !== templateId))
    } catch (err) {
      if (loadVersion !== documentLoadVersionRef.current) return
      setAttachedTemplates((items) => [...items])
      message.error(err instanceof ApiError ? String(err.detail) : '移除对话组件失败')
    } finally {
      if (loadVersion === documentLoadVersionRef.current) {
        templateAttachmentUpdateRef.current = false
        setTemplateAttachmentsUpdating(false)
      }
    }
  }, [activeChatSession?.is_archived, activeChatSessionId, applySessionResourceContext, docId])

  const clearSessionThemeContext = useCallback(async () => {
    if (!docId || !activeChatSessionId || activeChatSession?.is_archived) return
    try {
      const updated = await chatApi.clearThemeContext(docId, activeChatSessionId)
      applySessionResourceContext(updated)
      message.success('已清除当前对话的主题参考')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '清除主题参考失败')
    }
  }, [activeChatSession?.is_archived, activeChatSessionId, applySessionResourceContext, docId])

  const collectTemplateHtml = useCallback((templateHtml: string) => {
    if (streaming || saving || !templateHtml.trim()) return
    setTemplateCollection({ id: Date.now(), html: templateHtml })
    if (isCompact) setResourceDrawerOpen(true)
    else setResourceCollapsed(false)
    message.success('已带入组件库，请填写名称和分类后保存')
  }, [isCompact, saving, streaming])

  const handleTemplateCollection = useCallback(() => setTemplateCollection(null), [])

  const handleSaveHtml = async () => {
    if (documentEditingLockedRef.current) return
    previewFrameRef.current?.flushPendingChange()
    await persistDraftHtml(true)
  }

  const handleSaveTitle = async () => {
    if (!docId || !ownsRenderedDocument() || documentEditingLockedRef.current) return
    try {
      await documentsApi.update(docId, { title })
      if (!ownsRenderedDocument()) return
      setVersionRefreshToken((value) => value + 1)
    } catch (err) {
      if (!ownsRenderedDocument()) return
      message.error(err instanceof ApiError ? String(err.detail) : '标题保存失败')
    }
  }

  const addChatImages = useCallback(async (
    count: number,
    requests: (limit: number) => Array<(onProgress?: (progress: UploadProgress) => void) => Promise<ChatImageAttachment | ChatImageAttachment[]>>,
    uploadFiles: File[] = [],
  ): Promise<boolean> => {
    if (!docId || chatImageUploadInProgressRef.current) return false
    const selectedModel = modelsRef.current.find((item) => item.id === modelIdRef.current)
    if (!selectedModel?.is_multimodal) {
      message.warning('当前模型未启用图片交互')
      return false
    }
    const remaining = Math.max(0, MAX_CHAT_IMAGES_PER_MESSAGE - chatImagesRef.current.length)
    if (count > remaining) message.warning(`每条消息最多附加 ${MAX_CHAT_IMAGES_PER_MESSAGE} 张图片`)
    const candidates = remaining > 0 ? requests(Math.min(count, remaining)) : []
    if (!candidates.length) return false
    const draftEpoch = chatImageDraftEpochRef.current
    chatImageUploadInProgressRef.current = true
    setChatImageUploadProgress(null)
    setChatImageUploading(true)
    const uploadDocumentId = docId
    try {
      const results = uploadFiles.length
        ? await runImageUploads(candidates.map((request, index) => ({
          size: uploadFiles[index]!.size,
          run: (onProgress: (progress: UploadProgress) => void) => request(onProgress),
        })), (progress) => {
          if (draftEpoch === chatImageDraftEpochRef.current && documentIdRef.current === uploadDocumentId) setChatImageUploadProgress(progress)
        })
        : await Promise.allSettled(candidates.map((request) => request()))
      const attachments = results
        .filter((result): result is PromiseFulfilledResult<ChatImageAttachment | ChatImageAttachment[]> => result.status === 'fulfilled')
        .flatMap((result) => result.value)
      const failure = results.find((result) => result.status === 'rejected')
      if (failure) message.error(failure.reason instanceof ApiError ? String(failure.reason.detail) : '部分聊天图片添加失败')
      if (!attachments.length) return false
      const currentModel = modelsRef.current.find((item) => item.id === modelIdRef.current)
      if (
        draftEpoch !== chatImageDraftEpochRef.current
        || documentIdRef.current !== uploadDocumentId
        || !currentModel?.is_multimodal
      ) {
        void Promise.allSettled(attachments.filter((attachment) => !attachment.message_id).map((attachment) => chatApi.deleteImage(uploadDocumentId, attachment.id)))
        return false
      }
      chatImageDocumentIdRef.current = uploadDocumentId
      setChatImages((items) => [...items, ...attachments].slice(0, MAX_CHAT_IMAGES_PER_MESSAGE))
      return true
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '聊天图片添加失败')
      return false
    } finally {
      chatImageUploadInProgressRef.current = false
      setChatImageUploading(false)
    }
  }, [docId, setChatImageUploadProgress])

  const handleChatImageUpload = useCallback((files: File[]) => {
    const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
    const validCandidates = files.filter((file) => {
      if (!allowedTypes.has(file.type)) {
        message.warning(`${file.name || '图片'} 仅支持 PNG、JPG/JPEG、WEBP 或 GIF`)
        return false
      }
      if (file.size > 10 * 1024 * 1024) {
        message.warning(`${file.name || '图片'} 不能超过 10MB`)
        return false
      }
      return true
    })
    if (validCandidates.length) void addChatImages(validCandidates.length, (limit) => validCandidates.slice(0, limit).map((file) => (onProgress) => chatApi.uploadImage(docId, file, { onProgress })), validCandidates)
  }, [addChatImages, docId])

  const handleReferenceLibraryImage = useCallback(async (assetIds: string[]) => {
    const added = await addChatImages(assetIds.length, (limit) => [() => imageLibraryApi.referenceChatMany(assetIds.slice(0, limit), docId)])
    if (added) {
      setResourceDrawerOpen(false)
      setMobileWorkspace('chat')
    }
    return added
  }, [addChatImages, docId])

  const handleRemoveChatImage = useCallback((attachment: ChatImageAttachment) => {
    setChatImages((items) => items.filter((item) => item.id !== attachment.id))
    if (docId && !attachment.message_id) {
      void chatApi.deleteImage(docId, attachment.id).catch(() => {
        // The attachment may have been claimed by a concurrent send; history remains authoritative.
      })
    }
  }, [docId])

  const discardDraftChatImages = useCallback((attachments: ChatImageAttachment[] = chatImages) => {
    chatImageDraftEpochRef.current += 1
    setChatImageUploadProgress(null)
    if (!attachments.length) return
    setChatImages([])
    const attachmentDocumentId = chatImageDocumentIdRef.current ?? docId
    chatImageDocumentIdRef.current = null
    if (attachmentDocumentId) {
      void Promise.allSettled(attachments.filter((attachment) => !attachment.message_id).map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
  }, [chatImages, docId, setChatImageUploadProgress])

  useEffect(() => {
    const previousDocumentId = observedDocumentIdRef.current
    if (previousDocumentId !== null && previousDocumentId !== docId) {
      chatImageDraftEpochRef.current += 1
      setChatImageUploadProgress(null)
    }
    if (previousDocumentId !== null && previousDocumentId !== docId && chatImagesRef.current.length) {
      const attachments = chatImagesRef.current
      const attachmentDocumentId = chatImageDocumentIdRef.current ?? previousDocumentId
      chatImageDocumentIdRef.current = null
      setChatImages([])
      void Promise.allSettled(attachments.filter((attachment) => !attachment.message_id).map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
    if (previousDocumentId !== null && previousDocumentId !== docId) setChatQueuePaused(false)
    if (previousDocumentId !== null && previousDocumentId !== docId && queuedChatRequestsRef.current.length) {
      const queuedRequests = queuedChatRequestsRef.current
      queuedChatRequestsRef.current = []
      setQueuedChatRequests([])
      void Promise.allSettled(
        queuedRequests.flatMap((request) => request.images.filter((image) => !image.message_id).map((image) => chatApi.deleteImage(previousDocumentId, image.id))),
      )
    }
    observedDocumentIdRef.current = docId || null
  }, [docId, setChatImageUploadProgress])

  useEffect(() => () => {
    const attachmentDocumentId = chatImageDocumentIdRef.current
    const attachments = chatImagesRef.current
    if (attachmentDocumentId && attachments.length) {
      void Promise.allSettled(attachments.filter((attachment) => !attachment.message_id).map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
    const queuedRequests = queuedChatRequestsRef.current
    const queuedDocumentId = documentIdRef.current
    if (queuedDocumentId && queuedRequests.length) {
      void Promise.allSettled(
        queuedRequests.flatMap((request) => request.images.filter((image) => !image.message_id).map((image) => chatApi.deleteImage(queuedDocumentId, image.id))),
      )
    }
  }, [])

  const handleSendMessage = async (
    text: string,
    attachedElements: SelectedElementContext[] = selectedElements,
    existingRunId?: string,
    layoutReferenceId?: string,
    sessionIdOverride?: number,
    gzhThemeProposalId?: string,
    layoutReferenceAssetsConfirmed?: boolean,
    attachedImages: ChatImageAttachment[] = chatImages,
    layoutReferenceSelectedAssetIds: string[] = [],
    layoutReferenceImitationStrength: LayoutReferenceImitationStrength = 'structure',
    reaskConflictResolution?: ReaskConflictResolution,
    streamAfter = 0,
    ignoredUserQuestionId?: string,
    runOptions?: ChatRunOptions,
    resumeTimeline?: AgentRunTimeline | null,
  ) => {
    const sessionId = sessionIdOverride ?? activeChatSessionId
    const requestModelId = runOptions?.modelId ?? modelId
    const requestThinkingMode = runOptions?.thinkingMode ?? thinkingMode
    const requestThinkingEffort = runOptions?.thinkingEffort ?? thinkingEffort
    const attachedTexts = runOptions?.textAttachments ?? []
    const referencedTemplates = [...(runOptions?.referencedTemplates ?? composerTemplates)]
    const requestTemplates = runOptions?.templates
      ? [...runOptions.templates]
      : orderMessageTemplates([...composerTemplates, ...attachedTemplates], referencedTemplates.map(item => item.id))
    if (!docId || !sessionId || (!requestModelId && !existingRunId)) return
    if (documentIdRef.current !== docId || attachedEditorDocumentRef.current !== docId) return
    if (!existingRunId && chatSessions.find((item) => item.id === sessionId)?.is_archived) {
      message.warning('请先恢复该对话后再继续发送')
      return
    }
    if (compactionControllerRef.current || (!existingRunId && chatStartInProgressRef.current)) return
    const isNewRun = !existingRunId
    retireChatRunConnection(chatRunConnectionRef.current)
    const connection = createChatRunConnection()
    connection.detached = attachedEditorDocumentRef.current !== docId
    const { controller } = connection
    chatRunConnectionRef.current = connection
    const ownsConnection = () => ownsChatRunConnection(
      connection, chatRunConnectionRef.current, docId, attachedEditorDocumentRef.current,
    ) && documentIdRef.current === docId
    if (!ownsConnection()) return
    if (isNewRun && !queuedChatRequestsRef.current.length) setChatQueuePaused(false)
    let startFinished = !isNewRun
    const finishStarting = () => {
      if (startFinished) return
      startFinished = true
      if (!ownsConnection()) return
      chatStartInProgressRef.current = false
      setChatSubmitting(false)
    }
    if (isNewRun) {
      chatStartInProgressRef.current = true
      setChatSubmitting(true)
    }
    if (!existingRunId) previewFrameRef.current?.flushPendingChange()
    const sanitizedAttachedElements = sanitizeSelectedElements(attachedElements)
    const restoreSubmittedElements = () => {
      if (!ownsConnection() || !sanitizedAttachedElements.length) return
      setSelectedElements((current) => current.length ? current : sanitizedAttachedElements)
    }
    const attachedTemplateRefs = requestTemplates.map((template) => ({ id: template.id, name: template.name }))
    const sentDraftImages = existingRunId ? [] : attachedImages
    const sentImageIds = new Set(sentDraftImages.map((item) => item.id))
    let sentImagesDetached = false
    const detachSentDraftImages = () => {
      if (!ownsConnection() || !sentImageIds.size || sentImagesDetached) return
      sentImagesDetached = true
      chatImagesRef.current = chatImagesRef.current.filter((item) => !sentImageIds.has(item.id))
      setChatImages((items) => items.filter((item) => !sentImageIds.has(item.id)))
    }
    let sentImagesRestored = false
    const restoreSentDraftImages = () => {
      if (!ownsConnection() || sentImagesRestored || !sentDraftImages.length) return
      sentImagesRestored = true
      const merged = [...chatImagesRef.current]
      const presentIds = new Set(merged.map((item) => item.id))
      sentDraftImages.forEach((item) => {
        if (!presentIds.has(item.id) && merged.length < MAX_CHAT_IMAGES_PER_MESSAGE) {
          merged.push(item)
          presentIds.add(item.id)
        }
      })
      chatImagesRef.current = merged
      chatImageDocumentIdRef.current = docId
      setChatImages(merged)
    }

    const reaskFromMessageId = !existingRunId && !layoutReferenceId ? pendingReaskMessageId : null
    let persistedHtml: string | null
    if (existingRunId) {
      persistedHtml = html
    } else if (pendingReaskMessageId !== null && !layoutReferenceId) {
      if (draftHtmlRef.current !== htmlRef.current) {
        setReaskConflict({ kind: 'local_draft' })
        finishStarting()
        chatRunConnectionRef.current = null
        return
      }
      // The server restores the selected snapshot and archives the abandoned
      // suffix atomically with this new Agent run.
      persistedHtml = html
    } else {
      // Agent 从数据库读取最新 HTML，预览/源码里的手工草稿必须先保存，避免模型基于旧稿操作。
      persistedHtml = await persistDraftHtml()
    }
    if (!ownsConnection()) return
    if (persistedHtml === null) {
      setContextDraft((current) => current || text)
      restoreSubmittedElements()
      restoreSentDraftImages()
      setChatQueuePaused(true)
      finishStarting()
      chatRunConnectionRef.current = null
      return
    }

    let optimisticMessageId: number | null = null
    if (!existingRunId) {
      optimisticMessageId = Date.now()
      const optimistic: ChatMessageItem = {
        id: optimisticMessageId,
        role: 'user',
        content: text,
        created_by: currentUser
          ? { id: currentUser.id, username: currentUser.username, display_name: currentUser.display_name }
          : null,
        model_usage: null,
        image_attachments: attachedImages,
        text_attachments: attachedTexts,
        tool_calls: [],
        reasoning_trace: { status: 'idle', content: '', detail: '' },
        turn_blocks: [],
        selected_elements: sanitizedAttachedElements,
        template_refs: attachedTemplateRefs,
        can_revert: false,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, optimistic])
    }
    setStreaming(true)
    setStopping(false)
    const restoredTimeline = !isNewRun && resumeTimeline ? {
      tools: Array.isArray(resumeTimeline.tool_calls) ? resumeTimeline.tool_calls : [],
      blocks: Array.isArray(resumeTimeline.turn_blocks) ? resumeTimeline.turn_blocks : [],
      reasoning: resumeTimeline.reasoning ?? { status: 'idle', content: '', detail: '' },
    } : null
    if (isNewRun) {
      setStreamText('')
      setToolActivities([])
      setStreamBlocks([])
      setReasoningTrace({ status: 'idle', content: '', detail: '' })
    } else if (restoredTimeline) {
      setStreamText(timelineContent(restoredTimeline.blocks))
      setToolActivities(restoredTimeline.tools)
      setStreamBlocks(restoredTimeline.blocks)
      setReasoningTrace(restoredTimeline.reasoning)
    }
    setStreamNotice(null)
    setRecoveryNotice(null)
    setConversationError(null)
    setThinkingStatus(isNewRun ? null : '正在继续处理排版…')

    // A resumed run starts its SSE subscription after the question event, so
    // retain the locally rendered prefix instead of waiting for events that
    // will never be replayed.
    let accumulated = isNewRun ? '' : restoredTimeline ? timelineContent(restoredTimeline.blocks) : streamText
    let latestHtml = persistedHtml
    let activeTools: ToolExecution[] = isNewRun ? [] : restoredTimeline ? restoredTimeline.tools : toolActivities
    let activeBlocks: AssistantTurnBlock[] = isNewRun ? [] : restoredTimeline ? restoredTimeline.blocks : streamBlocks
    let activeReasoning: ReasoningTrace = isNewRun
      ? { status: 'idle', content: '', detail: '' }
      : restoredTimeline ? restoredTimeline.reasoning : reasoningTrace
    let modelTurnCheckpoint: {
      turn: number
      accumulated: string
      tools: ToolExecution[]
      blocks: AssistantTurnBlock[]
      reasoning: ReasoningTrace
    } | null = null
    let runId: string | null = null
    let lastSequence = streamAfter
    let completed = false
    let terminalRunStatus: string | undefined
    let pausedForUserQuestion = false
    let queueCanAdvance = false
    let streamRenderTimer: number | null = null
    let streamRenderFrame: number | null = null
    let lastStreamRenderAt = 0
    const savedComposerDraft = isNewRun ? readChatComposerDraft(docId, sessionId) : null
    let reusableRequestId = savedComposerDraft?.phase === 'retry'
      && savedComposerDraft.message === text
      && savedComposerDraft.reaskFromMessageId === reaskFromMessageId
      && JSON.stringify((savedComposerDraft.textAttachments ?? []).map(item => item.id)) === JSON.stringify(attachedTexts.map(item => item.id))
      && JSON.stringify((savedComposerDraft.templateRefs ?? []).map(item => item.id)) === JSON.stringify(referencedTemplates.map(item => item.id))
      ? savedComposerDraft.clientRequestId
      : undefined
    if (reusableRequestId) {
      try {
        const savedRun = savedComposerDraft?.runId
          ? await chatApi.getRun(docId, savedComposerDraft.runId)
          : await chatApi.getRunByClientRequest(docId, reusableRequestId)
        if (savedRun && ['completed', 'cancelled', 'failed'].includes(savedRun.status)) {
          reusableRequestId = undefined
          writeChatComposerDraft(docId, sessionId, {
            message: text,
            textAttachments: attachedTexts,
            templateRefs: referencedTemplates.map(({ id, name }) => ({ id, name })),
            reaskFromMessageId,
            phase: 'retry',
          })
        }
      } catch {
        // Keep the key when status reconciliation is unavailable; the POST
        // still needs idempotency protection if the original request exists.
      }
    }
    if (!ownsConnection()) return
    const clientRequestId = existingRunId ? null : reusableRequestId ?? createClientRequestId()
    const submittedDraft = isNewRun
      ? { message: text, reaskFromMessageId, clientRequestId: clientRequestId as string, textAttachments: attachedTexts,
          templateRefs: referencedTemplates.map(({ id, name }) => ({ id, name })) }
      : null
    if (submittedDraft) {
      writeChatComposerDraft(docId, sessionId, { ...submittedDraft, phase: 'starting' })
      // Navigation must not delete attachments while the accepted POST binds
      // them to its user message. A rejected POST restores them below.
      detachSentDraftImages()
      detachChatTexts(attachedTexts)
    }
    const restoreSubmittedDraft = (withFreshRequestId = false, nextReaskFromMessageId = submittedDraft?.reaskFromMessageId ?? null) => {
      if (!submittedDraft) return
      const storedDraft = readChatComposerDraft(docId, sessionId)
      const hasNewerDraft = Boolean(
        (storedDraft?.message.trim() || storedDraft?.textAttachments?.length)
        && storedDraft?.clientRequestId !== submittedDraft.clientRequestId,
      )
      if (hasNewerDraft) return
      if (ownsConnection()) {
        setContextDraft(submittedDraft.message)
        setPendingReaskMessageId(nextReaskFromMessageId)
        restoreSubmittedElements()
        restoreChatTexts(attachedTexts)
        setComposerTemplates(referencedTemplates)
      }
      writeChatComposerDraft(
        docId,
        sessionId,
        withFreshRequestId
          ? {
              message: submittedDraft.message,
              textAttachments: attachedTexts,
              templateRefs: submittedDraft.templateRefs,
              reaskFromMessageId: nextReaskFromMessageId,
              phase: 'retry',
            }
          : { ...submittedDraft, reaskFromMessageId: nextReaskFromMessageId, phase: 'retry' },
      )
    }

    const commitStreamRender = () => {
      if (!ownsConnection()) return
      setStreamText(accumulated)
      setToolActivities(activeTools)
      setStreamBlocks(activeBlocks)
      setReasoningTrace(activeReasoning)
    }

    const cancelStreamRender = () => {
      if (streamRenderTimer !== null) {
        window.clearTimeout(streamRenderTimer)
        streamRenderTimer = null
      }
      if (streamRenderFrame !== null) {
        window.cancelAnimationFrame(streamRenderFrame)
        streamRenderFrame = null
      }
    }

    const flushStreamRender = () => {
      cancelStreamRender()
      lastStreamRenderAt = performance.now()
      commitStreamRender()
    }

    const scheduleStreamRender = () => {
      if (!ownsConnection()) return
      if (streamRenderTimer !== null || streamRenderFrame !== null) return
      const delay = Math.max(0, STREAM_RENDER_INTERVAL_MS - (performance.now() - lastStreamRenderAt))
      streamRenderTimer = window.setTimeout(() => {
        streamRenderTimer = null
        streamRenderFrame = window.requestAnimationFrame(() => {
          streamRenderFrame = null
          lastStreamRenderAt = performance.now()
          commitStreamRender()
        })
      }, delay)
    }

    try {
      const run = existingRunId
        ? { run_id: existingRunId }
        : await (async () => {
          try {
            return await startChatRun(
              docId,
              sessionId,
              text,
              requestModelId as number,
              requestThinkingMode,
              requestThinkingEffort,
              clientRequestId as string,
              sanitizedAttachedElements,
              layoutReferenceId,
              gzhThemeProposalId,
              layoutReferenceAssetsConfirmed,
              attachedImages.map((item) => item.id),
              layoutReferenceSelectedAssetIds,
              layoutReferenceImitationStrength,
              requestTemplates.map((template) => template.id),
              reaskFromMessageId ?? undefined,
              reaskConflictResolution,
              controller.signal,
              (status) => { if (ownsConnection()) setStreamNotice(retryNotice(status)) },
              attachedTexts.map(item => item.id),
            )
          } catch (startError) {
            // A timeout or an aborted browser request is ambiguous: the
            // server may have committed the run before its response was cut.
            // Resolve through the idempotency key before touching optimistic UI.
            const retryableStartError = startError instanceof ApiError
              && (startError.status === 408 || startError.status === 429 || startError.status >= 500)
            if (startError instanceof ApiError && !retryableStartError) throw startError
            const recovered = await chatApi.getRunByClientRequest(docId, clientRequestId as string).catch(() => null)
            if (!recovered) throw startError
            return recovered
          }
        })()
      if (isNewRun && submittedDraft) {
        finishStarting()
        writeChatComposerDraft(docId, sessionId, { ...submittedDraft, phase: 'running', runId: run.run_id })
        // The composer becomes editable while a run is active. Do not erase
        // anything the user has entered after submitting this request.
        if (ownsConnection()) {
          setContextDraft((current) => current === submittedDraft.message ? '' : current)
          setComposerTemplates([])
          detachSentDraftImages()
        }
      }
      runId = run.run_id
      connection.phase = 'streaming'
      if (ownsConnection()) activeRunRef.current = run.run_id
      if (optimisticMessageId !== null && 'user_message_id' in run && ownsConnection()) {
        const persistedMessageId = run.user_message_id
        setMessages((previous) => previous.map((item) => (
          item.id === optimisticMessageId ? { ...item, id: persistedMessageId } : item
        )))
      }
      if (connection.stopRequested) {
        try {
          await cancelChatRun(docId, run.run_id)
        } catch {
          // The persisted run remains discoverable and the next page resume
          // will continue cancellation/reconciliation if this request failed.
        }
        if (ownsConnection()) {
          const [freshDocument, freshMessages] = await Promise.all([
            documentsApi.get(docId),
            loadRecentMessages(docId, sessionId),
          ])
          if (!ownsConnection()) return
          applyExternalHtml(freshDocument.current_html)
          setPreviewRevision((value) => value + 1)
          setRecentMessages(freshMessages)
          invalidateCompliance()
        }
        completed = true
      }
      if (!ownsConnection()) return
      if ('reask_activation' in run && run.reask_activation && !completed) {
        latestHtml = run.reask_activation.current_html
        applyExternalHtml(latestHtml)
        setPreviewRevision((value) => value + 1)
        const reaskedMessages = await loadRecentMessages(docId, sessionId)
        if (!ownsConnection()) return
        setRecentMessages(reaskedMessages)
        setPendingReaskMessageId(null)
        invalidateCompliance()
      }

      let reconnectAttempts = 0
      let outageStartedAt: number | null = null
      let pendingTransientContent = ''
      let pendingTransientReasoning = ''
      while (!completed) {
        try {
          const connectedAt = performance.now()
          if (reconnectAttempts > 0) setStreamNotice((current) => current?.operationId === 'stream-reconnect'
            ? { ...current, phase: 'attempting', title: '恢复实时输出：正在连接', retryDelaySeconds: undefined } : current)
          for await (const received of streamChatRunEvents(docId, run.run_id, lastSequence, controller.signal)) {
            if (!ownsConnection()) return
            if (received.sequence && received.sequence <= lastSequence) continue
            if (received.sequence) lastSequence = received.sequence
            const eventOccurredAtMs = Date.now() - received.eventAgeMs
            const evt = received
        if (evt.event === 'text_delta' || evt.event === 'reasoning_delta') {
          const key = evt.event === 'text_delta' ? 'content' : 'reasoning'
          const rawText = typeof evt.data.text === 'string' ? evt.data.text : ''
          const transient = '_transient' in evt.data && evt.data._transient === true
          let nextText = rawText
          if (transient) {
            if (key === 'content') pendingTransientContent += rawText
            else pendingTransientReasoning += rawText
          } else {
            const pendingTransient = key === 'content' ? pendingTransientContent : pendingTransientReasoning
            if (pendingTransient) {
              if (pendingTransient.startsWith(rawText)) {
                const remaining = pendingTransient.slice(rawText.length)
                if (key === 'content') pendingTransientContent = remaining
                else pendingTransientReasoning = remaining
                continue
              }
              if (rawText.startsWith(pendingTransient)) {
                nextText = rawText.slice(pendingTransient.length)
              }
              if (key === 'content') pendingTransientContent = ''
              else pendingTransientReasoning = ''
            }
          }
          if (!nextText) continue
          evt.data = { ...evt.data, text: nextText }
        }
        const freshProgress = received.eventAgeMs < 10_000 && ['text_delta', 'reasoning_delta', 'tool_call', 'tool_result'].includes(evt.event)
        const healthyConnection = evt.event === 'heartbeat' && performance.now() - connectedAt >= 10_000
        if (freshProgress || healthyConnection) { reconnectAttempts = 0; outageStartedAt = null }
        setStreamNotice((current) => current?.operationId === 'stream-reconnect' ? null : current)
        if (['text_delta', 'reasoning_delta', 'tool_call', 'tool_result'].includes(evt.event)) setStreamNotice(null)
        if (evt.event === 'text_delta') {
          accumulated += evt.data.text
          activeBlocks = appendStreamTextBlock(activeBlocks, 'content', evt.data.text, eventOccurredAtMs)
          scheduleStreamRender()
        } else if (evt.event === 'reasoning_delta') {
          activeReasoning = {
            status: 'thinking',
            content: activeReasoning.content + evt.data.text,
            detail: activeReasoning.detail,
          }
          activeBlocks = appendStreamTextBlock(activeBlocks, 'thought', evt.data.text, eventOccurredAtMs)
          scheduleStreamRender()
        } else if (evt.event === 'tool_call') {
          const toolId = evt.data.id ?? `tool-${Date.now()}-${activeTools.length}`
          const replacesId = typeof evt.data.replaces_id === 'string' ? evt.data.replaces_id : null
          const argumentTokens = typeof evt.data.argument_tokens === 'number' && Number.isFinite(evt.data.argument_tokens)
            ? Math.max(0, Math.round(evt.data.argument_tokens))
            : null
          // The call's own ID takes precedence over a stale replacement alias.
          const directIndex = activeTools.findIndex((item) => item.id === toolId)
          const existingIndex = directIndex >= 0
            ? directIndex
            : activeTools.findIndex((item) => item.id === replacesId)
          if (existingIndex >= 0) {
            const previousToolId = activeTools[existingIndex].id
            const previousArgumentTokens = activeTools[existingIndex].argument_tokens ?? 0
            const nextTool = {
              ...activeTools[existingIndex],
              id: toolId,
              name: evt.data.name,
              arguments: evt.data.arguments,
              preparing: Boolean(evt.data.preparing),
              // Provider chunks may be replayed after a newer durable event.
              // Keep the visible count monotonic so an older small fragment
              // cannot pin a large patch at its initial token value.
              ...(argumentTokens === null ? {} : { argument_tokens: Math.max(previousArgumentTokens, argumentTokens) }),
            }
            activeTools = activeTools.map((item, index) => index === existingIndex ? nextTool : item)
            activeBlocks = activeBlocks.map((block) =>
              block.type === 'tool' && (block.tool?.id === toolId || block.tool?.id === previousToolId)
                ? { ...block, tool: nextTool }
                : block,
            )
          } else {
            activeBlocks = finishActiveTextBlock(activeBlocks, eventOccurredAtMs)
            const nextTool: ToolExecution = {
              id: toolId,
              name: evt.data.name,
              arguments: evt.data.arguments,
              status: 'running',
              preparing: Boolean(evt.data.preparing),
              ...(argumentTokens === null ? {} : { argument_tokens: argumentTokens }),
              result: null,
              html_changed: false,
              activity: null,
              model_input: { state: 'pending', message: '工具正在执行，尚未向模型提供结果。' },
              read_range: null,
              change_summary: null,
            }
            activeTools = [...activeTools, nextTool]
            activeBlocks = [
              ...activeBlocks,
              { id: `block-${toolId}`, type: 'tool', state: 'done', content: '', tool: nextTool },
            ]
          }
          flushStreamRender()
        } else if (evt.event === 'tool_result') {
          const nextTools = [...activeTools]
          const resultToolId = typeof evt.data.id === 'string' ? evt.data.id : null
          const directIndex = resultToolId
            ? nextTools.findIndex((item) => item.id === resultToolId)
            : -1
          const fallbackReverseIndex = resultToolId
            ? -1
            : [...nextTools].reverse().findIndex((item) => (
              item.name === evt.data.name && (item.status === 'running' || item.status === 'waiting')
            ))
          const target = directIndex >= 0
            ? directIndex
            : fallbackReverseIndex >= 0
              ? nextTools.length - 1 - fallbackReverseIndex
              : -1
          let updatedToolId: string | null = null
          if (target >= 0) {
            nextTools[target] = {
                ...nextTools[target],
                result: evt.data.result,
                status: evt.data.result.startsWith('错误') ? 'error' : 'success',
                preparing: false,
                html_changed: Boolean(evt.data.html),
                activity: evt.data.activity ?? null,
                model_input: evt.data.model_input ?? null,
                read_range: evt.data.read_range ?? null,
              change_summary: evt.data.change_summary ?? null,
            }
            updatedToolId = nextTools[target].id
          }
          activeTools = nextTools
          activeBlocks = activeBlocks.map((block) =>
            block.type === 'tool' && block.tool?.id === updatedToolId
              ? { ...block, tool: nextTools.find((tool) => tool.id === updatedToolId) ?? block.tool }
              : block,
          )
          flushStreamRender()
          if (evt.data.name === 'check_compliance') {
            const report = complianceReportFromToolActivity(evt.data.activity)
            if (report) setCompliance(report)
          }
          if (evt.data.html) {
            latestHtml = evt.data.html
            applyExternalHtml(latestHtml)
            setPreviewRevision((value) => value + 1)
            invalidateCompliance()
          }
        } else if (evt.event === 'user_question') {
          // A retry after an accepted answer can replay the original question
          // when its persisted event sequence was unavailable. Ignore only
          // that one event so a later question in the same run remains usable.
          if (ignoredUserQuestionId && evt.data.id === ignoredUserQuestionId) continue
          const pendingQuestion = { ...evt.data, event_sequence: evt.sequence || undefined }
          if (activeBlocks.length === 0 && pendingQuestion.timeline) {
            activeTools = Array.isArray(pendingQuestion.timeline.tool_calls) ? pendingQuestion.timeline.tool_calls : []
            activeBlocks = Array.isArray(pendingQuestion.timeline.turn_blocks) ? pendingQuestion.timeline.turn_blocks : []
            activeReasoning = pendingQuestion.timeline.reasoning ?? { status: 'idle', content: '', detail: '' }
          }
          // The question event pauses before a normal tool_result is emitted.
          // Synchronize the ask_user card from its durable timeline so it
          // leaves the parameter-token state and clearly waits for the answer.
          const waitingTimelineTools = Array.isArray(pendingQuestion.timeline?.tool_calls)
            ? pendingQuestion.timeline.tool_calls
            : []
          const waitingQuestionTool = [...waitingTimelineTools].reverse().find((tool) => tool.name === 'ask_user')
          const activeQuestionToolIndex = [...activeTools].reverse().findIndex((tool) => (
            tool.name === 'ask_user' && (tool.status === 'running' || tool.status === 'waiting')
          ))
          const questionToolIndex = activeQuestionToolIndex >= 0
            ? activeTools.length - 1 - activeQuestionToolIndex
            : -1
          const settledQuestionTool: ToolExecution | null = waitingQuestionTool
            ? {
                ...waitingQuestionTool,
                status: 'waiting',
                preparing: false,
                result: waitingQuestionTool.result || '等待用户回答',
                activity: waitingQuestionTool.activity ?? { kind: 'question', summary: '等待用户回答' },
              }
            : questionToolIndex >= 0
              ? {
                  ...activeTools[questionToolIndex],
                  status: 'waiting',
                  preparing: false,
                  result: activeTools[questionToolIndex].result || '等待用户回答',
                  activity: activeTools[questionToolIndex].activity ?? { kind: 'question', summary: '等待用户回答' },
                }
              : null
          if (settledQuestionTool) {
            if (questionToolIndex >= 0) {
              const previousQuestionToolId = activeTools[questionToolIndex].id
              activeTools = activeTools.map((tool, index) => index === questionToolIndex ? settledQuestionTool : tool)
              activeBlocks = activeBlocks.map((block) => (
                block.type === 'tool' && block.tool?.id === previousQuestionToolId
                  ? { ...block, tool: settledQuestionTool }
                  : block
              ))
            } else {
              activeTools = [...activeTools, settledQuestionTool]
              activeBlocks = [
                ...activeBlocks,
                { id: `block-${settledQuestionTool.id}`, type: 'tool', state: 'done', content: '', tool: settledQuestionTool },
              ]
            }
          }
          setPendingUserQuestion(pendingQuestion)
          setQuestionSubmitting(false)
          setThinkingStatus('等待你确认排版偏好')
          flushStreamRender()
          pausedForUserQuestion = true
          completed = true
          break
        } else if (evt.event === 'agent_status') {
          setThinkingStatus(evt.data.thinking.detail)
          if (evt.data.thinking.applied || evt.data.thinking.requested === 'enabled') {
            activeReasoning = {
              status: evt.data.thinking.applied
                ? (activeReasoning.content ? 'thinking' : 'idle')
                : 'unavailable',
              content: activeReasoning.content,
              detail: evt.data.thinking.detail,
            }
          }
          flushStreamRender()
        } else if (evt.event === 'thinking_capability_fallback') {
          handleThinkingCapabilityFallback(evt.data)
        } else if (evt.event === 'retry_status') {
          setStreamNotice((current) => evt.data.phase === 'recovered' && current?.operationId !== evt.data.operation_id
            ? current : retryNotice(evt.data, received.eventAgeMs))
        } else if (evt.event === 'model_turn_retry') {
          pendingTransientContent = ''
          pendingTransientReasoning = ''
          if (modelTurnCheckpoint && (evt.data.turn === undefined || evt.data.turn === modelTurnCheckpoint.turn)) {
            const restored = preserveRetriedToolPreviews(
              modelTurnCheckpoint,
              activeTools,
              activeBlocks,
              evt.data.attempt,
            )
            accumulated = modelTurnCheckpoint.accumulated
            activeTools = restored.tools
            activeBlocks = restored.blocks
            activeReasoning = { ...modelTurnCheckpoint.reasoning }
            flushStreamRender()
          }
          const retryReason = formatModelRetryReason(evt.data.reason)
          const retryDelay = evt.data.delay_seconds
          const returnedError = evt.data.detail?.trim() || retryReason
          const errorCode = evt.data.reason?.trim()
          const maxRetries = evt.data.max_attempts
          const retryAttempt = evt.data.attempt
          setStreamNotice({
            kind: 'retrying',
            title: '正在重新连接模型服务',
            detail: `${returnedError}${errorCode ? `（错误码：${errorCode}）` : ''}`,
            attempt: retryAttempt,
            maxAttempts: maxRetries,
            retryDelaySeconds: retryDelay,
            retryStartedAtMs: Date.now() - received.eventAgeMs,
          })
          setThinkingStatus(retryReason)
        } else if (evt.event === 'context_compaction') {
          activeBlocks = [
            ...activeBlocks,
            {
              id: evt.data.id ?? `context-compaction-${activeBlocks.length + 1}`,
              type: 'context_compaction',
              state: 'done',
              content: '',
              duration_ms: null,
              tool: null,
              context_compaction: {
                summary: evt.data.summary,
                original_tokens: evt.data.original_tokens,
                used_tokens: evt.data.used_tokens,
                summarized_cycles: evt.data.summarized_cycles,
                digested_cycles: evt.data.digested_cycles,
                dropped_cycles: evt.data.dropped_cycles,
                summary_tokens: evt.data.summary_tokens,
                durable_snapshot: evt.data.durable_snapshot,
              },
            },
          ]
          flushStreamRender()
        } else if (evt.event === 'context_stats') {
          setContextStats((current) => mergeContextStats(current, evt.data))
        } else if (evt.event === 'heartbeat') {
          if (evt.data.phase === 'model_turn_started') {
            if (typeof evt.data.turn === 'number') {
              modelTurnCheckpoint = {
                turn: evt.data.turn,
                accumulated,
                tools: [...activeTools],
                blocks: [...activeBlocks],
                reasoning: { ...activeReasoning },
              }
            }
            setThinkingStatus(null)
            continue
          }
          if (evt.data.detail) {
            setThinkingStatus(evt.data.detail)
            continue
          }
          const idleSeconds = Number(evt.data.idle_seconds ?? 0)
          if (idleSeconds >= 20) {
            setThinkingStatus(`等待模型继续输出（${idleSeconds}s 未产生有效内容）`)
          }
        } else if (evt.event === 'final') {
          terminalRunStatus = evt.data.run_status
          setPendingUserQuestion(null)
          setQuestionSubmitting(false)
          if (evt.data.partial && evt.data.partial_save_state === 'preserved') {
            setStreamNotice({ kind: 'success', title: '部分完成', detail: '已保留部分排版修改。' })
            setThinkingStatus('已保留部分排版修改')
          } else if (evt.data.partial && evt.data.partial_save_state === 'conflict') {
            setStreamNotice({ kind: 'error', title: '部分完成但未保存', detail: '文档已被其他修改更新，候选排版未自动覆盖。' })
            setThinkingStatus('部分修改未自动保存，原因是文档冲突')
          } else if (evt.data.partial && evt.data.partial_save_state === 'unavailable') {
            setStreamNotice({ kind: 'error', title: '部分完成，保存状态未知', detail: '终态保存暂时不可用，请刷新文档确认当前内容。' })
            setThinkingStatus('部分修改的保存状态暂时无法确认')
          } else {
            setStreamNotice(null)
          }
          setConversationError(null)
          latestHtml = evt.data.html
          applyExternalHtml(latestHtml)
          setPreviewRevision((value) => value + 1)
          if (evt.data.compliance) {
            setCompliance(evt.data.compliance as ComplianceReport)
          } else {
            invalidateCompliance()
          }
          if (activeReasoning.content) {
            activeReasoning = { ...activeReasoning, status: 'complete' }
          }
          activeBlocks = finishActiveTextBlock(activeBlocks, eventOccurredAtMs)
          flushStreamRender()
          const assistant: ChatMessageItem = {
            id: Date.now() + 1,
            role: 'assistant',
            content: evt.data.content || '（已完成编辑）',
            created_by: null,
            model_usage: null,
            image_attachments: [],
            tool_calls: activeTools,
            reasoning_trace: activeReasoning,
            turn_blocks: activeBlocks,
            selected_elements: [],
            template_refs: [],
            can_revert: evt.data.html_changed,
            created_at: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, assistant])
          if (evt.data.html_changed) setVersionRefreshToken((value) => value + 1)
          if (evt.data.run_status === 'failed') {
            if (isNewRun) restoreSubmittedDraft(true)
            setConversationError(evt.data.error_message || '对话请求失败')
          } else if (isNewRun) {
            clearChatComposerDraftForRequest(docId, sessionId, submittedDraft?.clientRequestId ?? '')
          }
          queueCanAdvance = canAdvanceQueuedChat(evt.data.run_status)
          completed = true
          break
        } else if (evt.event === 'error') {
          setStreamNotice({ kind: 'error', title: '本轮执行失败', detail: evt.data.message })
          setThinkingStatus(null)
        }
      }
          if (!completed) throw new Error('输出连接已结束')
        } catch (err) {
          if (!ownsConnection()) return
          if ((err as Error).name === 'AbortError') throw err
          try {
            const runState = await chatApi.getRun(docId, run.run_id, controller.signal)
            if (!ownsConnection()) return
            if (runState.status === 'waiting_for_input' && runState.user_question) {
              // Recover directly from durable state if a proxy disconnect or
              // an older backend drops the final user_question SSE frame.
              // Waiting for repeated reconnects used to leave this panel
              // hidden until the whole editor was refreshed.
              const recoveredQuestion = {
                ...runState.user_question,
                event_sequence: runState.user_question.event_sequence ?? runState.event_sequence,
              }
              const timeline = recoveredQuestion.timeline
              if (timeline) {
                activeTools = Array.isArray(timeline.tool_calls) ? timeline.tool_calls : activeTools
                activeBlocks = Array.isArray(timeline.turn_blocks) ? timeline.turn_blocks : activeBlocks
                activeReasoning = timeline.reasoning ?? activeReasoning
                accumulated = timelineContent(activeBlocks)
              }
              activeRunRef.current = run.run_id
              setPendingUserQuestion(recoveredQuestion)
              setQuestionSubmitting(false)
              setThinkingStatus('等待你确认排版偏好')
              flushStreamRender()
              pausedForUserQuestion = true
              completed = true
              break
            }
            if (['completed', 'cancelled', 'failed'].includes(runState.status)) {
              terminalRunStatus = runState.status
              completed = true
              queueCanAdvance = canAdvanceQueuedChat(runState.status)
              setThinkingStatus(null)
              if (runState.status === 'failed') {
                if (isNewRun) restoreSubmittedDraft(true)
                setConversationError(runState.error_message || '对话请求失败')
              } else {
                setConversationError(null)
                if (isNewRun) clearChatComposerDraftForRequest(docId, sessionId, submittedDraft?.clientRequestId ?? '')
              }
              setRecoveryNotice(null)
              const [freshDocument, freshMessages] = await Promise.all([
                documentsApi.get(docId),
                loadRecentMessages(docId, sessionId),
              ])
              if (!ownsConnection()) return
              applyExternalHtml(freshDocument.current_html)
              setPreviewRevision((value) => value + 1)
              const recoveredCompliance = latestComplianceReportFromTools(runState.timeline?.tool_calls)
              if (recoveredCompliance) setCompliance(recoveredCompliance)
              else invalidateCompliance()
              setRecentMessages(freshMessages)
              break
            }
          } catch (statusError) {
            if (!ownsConnection()) return
            if (completed || (statusError as Error).name === 'AbortError') throw statusError
          }
          if (!isRetryable(err)) throw err
          reconnectAttempts += 1
          outageStartedAt ??= performance.now()
          const reconnectDelay = retryDelayMs(err, reconnectAttempts, 400, 15_000)
          if (reconnectDelay === null || reconnectAttempts > MAX_STREAM_RECONNECT_ATTEMPTS
              || performance.now() - outageStartedAt + reconnectDelay >= 180_000) {
            throw new Error('实时输出多次无法恢复，已停止等待。后台任务可能仍在执行，请刷新页面恢复连接或点击停止。')
          }
          setStreamNotice({
            kind: 'retrying',
            title: '正在恢复实时输出连接',
            detail: '后台 Agent 仍在执行，正在补拉遗漏的输出。',
            operationId: 'stream-reconnect', phase: 'waiting',
            attempt: reconnectAttempts + 1,
            maxAttempts: MAX_STREAM_RECONNECT_ATTEMPTS + 1,
            retryDelaySeconds: reconnectDelay / 1000,
            retryStartedAtMs: Date.now(),
          })
          setThinkingStatus(null)
          await abortableDelay(reconnectDelay, controller.signal)
        }
      }

      // 流结束后重新拉取消息列表，与数据库记录对齐
      const freshMsgs = await loadRecentMessages(docId, sessionId)
      const refreshedSessions = await chatApi.listSessions(docId)
      if (!ownsConnection()) return
      setRecentMessages(freshMsgs)
      setChatSessions(refreshedSessions)
      if (sessionId === activeChatSessionId) {
        setAttachedTemplates(refreshedSessions.find((item) => item.id === sessionId)?.attached_templates ?? [])
      }
    } catch (err) {
      if (!ownsConnection()) {
        if (!runId && isNewRun) restoreSubmittedDraft()
        return
      }
      if (completed) {
        if (terminalRunStatus === 'completed' || terminalRunStatus === 'cancelled') setConversationError(null)
        setRecoveryNotice({ kind: 'info', operationId: 'history-sync',
          title: pausedForUserQuestion ? '确认面板已恢复，记录同步暂时失败' : '本轮已结束，记录同步暂时失败',
          detail: '当前界面内容已保留，可重新检查并同步任务状态和记录。', phase: 'exhausted' })
        return
      }
      // A failed POST may leave only the client-side placeholder. It has no
      // server ID and must not be offered as a history branch for re-asking.
      if (!runId && optimisticMessageId !== null) {
        setMessages((previous) => previous.filter((item) => item.id !== optimisticMessageId))
      }
      if (!runId) restoreSentDraftImages()
      if ((err as Error).name !== 'AbortError') {
        const conflict = reaskDocumentConflictFromError(err)
        const unavailableReaskSource = reaskSourceUnavailableFromError(err)
        if (conflict && reaskFromMessageId !== null) {
          restoreSubmittedDraft()
          setReaskConflict({ kind: 'server', currentChecksum: conflict.current_checksum })
          setConversationError(null)
        } else if (unavailableReaskSource && reaskFromMessageId !== null) {
          // The selected historical message was already retired. Keep the
          // user's instruction, but make the next send a normal continuation
          // rather than persisting an anchor that can never succeed.
          restoreSubmittedDraft(true, null)
          setReaskConflict(null)
          setConversationError(null)
          message.warning('历史重新提问已失效，已保留输入并切换为普通对话，请直接再次发送')
        } else {
          if (isNewRun) restoreSubmittedDraft()
          setConversationError(err instanceof ApiError ? err.message : '对话请求失败')
        }
        setThinkingStatus(null)
      }
    } finally {
      cancelStreamRender()
      finishStarting()
      if (ownsConnection()) {
        if (!pausedForUserQuestion && !queueCanAdvance) setChatQueuePaused(true)
        chatRunConnectionRef.current = null
        if (!pausedForUserQuestion && runId && activeRunRef.current === runId) activeRunRef.current = null
        setStreaming(false)
        setStopping(false)
        if (!pausedForUserQuestion) {
          setStreamText('')
          setToolActivities([])
          setStreamBlocks([])
          setStreamNotice(null)
          setThinkingStatus(null)
        }
      }
    }
  }

  queuedRequestStarterRef.current = (nextRequest) => {
    void handleSendMessage(
      nextRequest.content,
      nextRequest.references,
      undefined,
      undefined,
      nextRequest.sessionId,
      undefined,
      undefined,
      nextRequest.images,
      [],
      'structure',
      undefined,
      0,
      undefined,
      {
        modelId: nextRequest.modelId,
        thinkingMode: nextRequest.thinkingMode,
        thinkingEffort: nextRequest.thinkingEffort,
        templates: nextRequest.templates,
        referencedTemplates: nextRequest.referencedTemplates,
        textAttachments: nextRequest.texts,
      },
    )
  }

  const enqueueChatRequest = (
    text: string,
    references: SelectedElementContext[],
    images: ChatImageAttachment[],
    texts: ChatTextAttachment[] = [],
    templates: TemplateItem[] = attachedTemplates,
    referencedTemplates: TemplateItem[] = composerTemplates,
  ) => {
    if (!docId || !activeChatSessionId || !modelId) return
    const queuedRequest: QueuedChatRequest = {
      id: createClientRequestId(),
      content: text,
      sessionId: activeChatSessionId,
      references: sanitizeSelectedElements(references),
      images: [...images],
      texts: [...texts],
      templates: [...templates],
      referencedTemplates: [...referencedTemplates],
      modelId,
      thinkingMode,
      thinkingEffort,
    }
    setQueuedChatRequests((items) => [...items, queuedRequest])
    detachChatTexts(texts)
    setContextDraft('')
    setComposerTemplates([])
    setPendingReaskMessageId(null)
    clearChatComposerDraft(docId, activeChatSessionId)

    const queuedImageIds = new Set(images.map((image) => image.id))
    if (queuedImageIds.size) {
      chatImagesRef.current = chatImagesRef.current.filter((image) => !queuedImageIds.has(image.id))
      setChatImages((items) => items.filter((image) => !queuedImageIds.has(image.id)))
    }
  }

  const removeQueuedChatRequest = useCallback((requestId: string) => {
    const queuedRequest = queuedChatRequestsRef.current.find((item) => item.id === requestId)
    setQueuedChatRequests((items) => items.filter((item) => item.id !== requestId))
    if (queuedChatRequestsRef.current.length === 1) setChatQueuePaused(false)
    if (queuedRequest?.texts.length) restoreChatTexts(queuedRequest.texts)
    if (docId && queuedRequest?.images.length) {
      void Promise.allSettled(queuedRequest.images.map((image) => chatApi.deleteImage(docId, image.id)))
    }
  }, [docId, restoreChatTexts])

  const updateQueuedChatRequest = useCallback((requestId: string, nextContent: string, texts: ChatTextAttachment[] = []) => {
    const content = nextContent.trim()
    if (!content) return
    const queued = queuedChatRequestsRef.current.find(item => item.id === requestId)
    if (!queued || queued.texts.length + texts.length > 8) { message.error('每条任务最多 8 份文本附件'); return }
    setQueuedChatRequests((items) => updateQueuedChatContent(items, requestId, content).map(item => item.id === requestId ? { ...item, texts: [...item.texts, ...texts] } : item))
    detachChatTexts(texts)
  }, [detachChatTexts])

  const moveQueuedChatRequest = useCallback((fromIndex: number, toIndex: number) => {
    setQueuedChatRequests((items) => moveQueuedChatItem(items, fromIndex, toIndex))
  }, [])

  useEffect(() => {
    if (chatQueuePaused || streaming || stopping || chatSubmitting || templateAttachmentsUpdating || pendingUserQuestion) return
    const nextRequest = queuedChatRequests[0]
    if (!nextRequest || nextRequest.sessionId !== activeChatSessionId) return

    setQueuedChatRequests((items) => items.filter((item) => item.id !== nextRequest.id))
    queuedRequestStarterRef.current?.(nextRequest)
  }, [activeChatSessionId, chatQueuePaused, chatSubmitting, templateAttachmentsUpdating, pendingUserQuestion, queuedChatRequests, stopping, streaming])

  const handleLayoutImitation = async (
    reference: LayoutReferencePreview,
    assetsConfirmed: boolean,
    selectedAssetIds: string[],
    imitationStrength: LayoutReferenceImitationStrength,
  ) => {
    if (!modelId) {
      message.warning('请先选择 AI 模型')
      return
    }
    const imitationRequest = {
      style: '请按风格强度模仿已绑定参考模板。保留当前文案和图片，主要复刻颜色、标题与装饰风格。',
      structure: '请按结构强度模仿已绑定参考模板。保留当前文案和图片；必须读取模板源码，强力复刻主要组件层次、关键 flex 布局、对齐、间距、主要尺寸与定位关系。',
      maximum: '请按最大还原强度模仿已绑定参考模板。保留当前文案和图片；必须按需读取模板源码，严格复刻复杂容器、flex 结构、定位、尺寸与层叠关系。',
    }[imitationStrength]
    setLayoutImitationOpen(false)
    await handleSendMessage(
      imitationRequest,
      [],
      undefined,
      reference.reference_id,
      undefined,
      undefined,
      assetsConfirmed,
      undefined,
      selectedAssetIds,
      imitationStrength,
    )
  }

  const handleThemeApplication = async (proposal: GzhThemeProposal) => {
    if (!modelId) {
      message.warning('请先选择 AI 模型')
      return
    }
    await handleSendMessage(
      `应用已批准的主题排版提案「${proposal.theme_name}」，按「${proposal.apply_mode}」执行并完成严格校验。`,
      [],
      undefined,
      undefined,
      undefined,
      proposal.id,
    )
  }

  const handleEditRequest = useCallback((messageItem: ChatMessageItem) => {
    if (chatImageUploadInProgressRef.current) {
      message.warning('请等待当前图片上传完成后再从历史消息重新提问')
      return
    }
    discardDraftChatImages()
    setReaskConflict(null)
    setSelectedElements(sanitizeSelectedElements(messageItem.selected_elements))
    restoreChatTexts(messageItem.text_attachments ?? [])
    setComposerTemplates(restoreComposerTemplates(messageItem.template_refs))
    setPendingReaskMessageId(messageItem.id)

    const historyImages = (messageItem.image_attachments ?? []).slice(0, MAX_CHAT_IMAGES_PER_MESSAGE)
    if (!historyImages.length || !docId) return
    const selectedModel = modelsRef.current.find((item) => item.id === modelIdRef.current)
    if (!selectedModel?.is_multimodal) {
      message.warning('当前模型未启用图片交互，未恢复历史图片')
      return
    }

    const restored = historyImages.map((image) => ({ ...image, message_id: messageItem.id }))
    chatImageDocumentIdRef.current = docId
    chatImagesRef.current = restored
    setChatImages(restored)
  }, [discardDraftChatImages, docId, restoreChatTexts])

  const handleDismissReaskConflict = useCallback(() => {
    if (resolvingReaskConflict) return
    setReaskConflict(null)
  }, [resolvingReaskConflict])

  const handleDiscardReaskConflict = () => {
    if (!reaskConflict || resolvingReaskConflict || !pendingReaskMessageId) return
    const retryTexts = chatTexts.items.filter(item => item.status !== 'uploading' && item.status !== 'error')
    const retryText = contextDraft.trim() || (retryTexts.length > 0 ? '请按当前对话要求读取并处理所附文本。' : selectedElements.length > 0
      ? '请处理所附元素。'
      : chatImages.length > 0
        ? '请分析所附图片，并继续处理当前推文。'
        : attachedTemplates.length > 0
          ? '请依据已附组件库处理当前推文。'
          : '')
    if (!retryText) return

    setResolvingReaskConflict(true)
    const resolution: ReaskConflictResolution | undefined = reaskConflict.kind === 'server' && reaskConflict.currentChecksum
      ? { resolution: 'discard_current_changes', currentChecksum: reaskConflict.currentChecksum }
      : undefined
    if (reaskConflict.kind === 'local_draft') {
      applyExternalHtml(htmlRef.current)
      setPreviewRevision((value) => value + 1)
      invalidateCompliance()
    }
    setReaskConflict(null)
    setResolvingReaskConflict(false)
    void handleSendMessage(
      retryText,
      selectedElements,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      chatImages,
      [],
      'structure',
      resolution,
      0,
      undefined,
      modelId ? { modelId, thinkingMode, thinkingEffort, textAttachments: retryTexts } : undefined,
    )
  }

  const handleAnswerUserQuestion = async (answer: UserQuestionAnswer) => {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting) return
    const loadVersion = documentLoadVersionRef.current
    const ownsQuestion = () => loadVersion === documentLoadVersionRef.current
      && attachedEditorDocumentRef.current === docId && pendingUserQuestionRef.current?.id === question.id
    const answerKey = JSON.stringify(answer)
    const previousRequest = questionAnswerRequestRef.current
    const clientRequestId = previousRequest
      && previousRequest.questionId === question.id
      && previousRequest.answerKey === answerKey
      ? previousRequest.clientRequestId
      : createClientRequestId()
    questionAnswerRequestRef.current = { questionId: question.id, answerKey, clientRequestId }
    setQuestionSubmitting(true)
    setConversationError(null)
    try {
      const resumed = await chatApi.answerUserQuestion(
        docId,
        question.run_id,
        question.id,
        answer,
        clientRequestId,
        (status) => { if (ownsQuestion()) setStreamNotice(retryNotice(status)) },
      )
      if (!ownsQuestion()) return
      setPendingUserQuestion(null)
      setQuestionSubmitting(false)
      await handleSendMessage(
        '',
        [],
        resumed.run_id,
        undefined,
        resumed.session_id,
        undefined,
        undefined,
        [],
        [],
        'structure',
        undefined,
        question.event_sequence ?? 0,
        question.id,
      )
    } catch (err) {
      if (!ownsQuestion()) return
      setQuestionSubmitting(false)
      // A dropped response or a concurrent timeout can leave the browser
      // unsure whether its answer was accepted. The run record is authoritative
      // and lets us continue its original SSE stream when it already moved on.
      if (await handleUserQuestionTimeoutElapsed()) return
      if (!ownsQuestion()) return
      setConversationError(err instanceof ApiError ? err.message : '提交排版偏好失败')
    }
  }

  const handleUserQuestionActivity = () => {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting) return
    const loadVersion = documentLoadVersionRef.current
    const now = Date.now()
    const previous = questionActivityRef.current
    if (previous?.questionId === question.id && now - previous.lastSentAt < USER_QUESTION_ACTIVITY_THROTTLE_MS) return
    questionActivityRef.current = { questionId: question.id, lastSentAt: now }
    void chatApi.recordUserQuestionActivity(docId, question.run_id, question.id)
      // The panel owns its displayed countdown between question loads. Do not
      // replace the full question object for an activity acknowledgement:
      // that can remount a controlled option/modal while a click is in flight.
      .then(() => undefined)
      .catch(() => {
        if (loadVersion !== documentLoadVersionRef.current || pendingUserQuestionRef.current?.id !== question.id) return
        // A failed activity request is ambiguous: the server may already have
        // accepted the timeout answer and resumed the run. Reconcile instead
        // of leaving an interactive-looking stale panel on screen.
        void handleUserQuestionTimeoutElapsed()
      })
  }

  async function handleUserQuestionTimeoutElapsed(): Promise<boolean> {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting || questionTimeoutRecoveryRef.current === question.id) return false
    const loadVersion = documentLoadVersionRef.current
    const ownsQuestion = () => loadVersion === documentLoadVersionRef.current
      && attachedEditorDocumentRef.current === docId && pendingUserQuestionRef.current?.id === question.id
    questionTimeoutRecoveryRef.current = question.id
    try {
      const run = await chatApi.getRun(docId, question.run_id)
      if (!ownsQuestion()) return false
      if (run.status === 'waiting_for_input' && run.user_question?.id === question.id) return false
      if (run.status === 'waiting_for_input' && run.user_question) {
        setPendingUserQuestion(run.user_question)
        const timeline = run.user_question.timeline
        if (timeline) {
          const timelineTools = Array.isArray(timeline.tool_calls) ? timeline.tool_calls : []
          const timelineBlocks = Array.isArray(timeline.turn_blocks) ? timeline.turn_blocks : []
          setToolActivities(timelineTools)
          setStreamBlocks(timelineBlocks)
          setReasoningTrace(timeline.reasoning ?? { status: 'idle', content: '', detail: '' })
          const latestContent = [...timelineBlocks].reverse().find((block) => block.type === 'content')
          setStreamText(latestContent?.content ?? '')
        }
        setQuestionSubmitting(false)
        setThinkingStatus('等待你确认排版偏好')
        return true
      }
      if (['completed', 'cancelled', 'failed'].includes(run.status)) {
        const [freshMessages, sessions, refreshedDocument] = await Promise.all([
          loadRecentMessages(docId, run.session_id),
          chatApi.listSessions(docId),
          documentsApi.get(docId),
        ])
        if (loadVersion !== documentLoadVersionRef.current || attachedEditorDocumentRef.current !== docId) return false
        setPendingUserQuestion(null)
        setRecentMessages(freshMessages)
        applyExternalHtml(refreshedDocument.current_html)
        setPreviewRevision((value) => value + 1)
        setVersionRefreshToken((value) => value + 1)
        setChatSessions(sessions)
        setAttachedTemplates(sessions.find((item) => item.id === run.session_id)?.attached_templates ?? [])
        setThinkingStatus(null)
        if (run.status === 'failed') setConversationError(run.error_message || '对话请求失败')
        return true
      }
      setPendingUserQuestion(null)
      activeRunRef.current = run.run_id
      setThinkingStatus('用户未回复，正在继续处理排版…')
      await handleSendMessage(
        '',
        [],
        run.run_id,
        undefined,
        run.session_id,
        undefined,
        undefined,
        [],
        [],
        'structure',
        undefined,
        question.event_sequence ?? 0,
        question.id,
      )
      return true
    } catch (err) {
      if (!ownsQuestion()) return false
      if (err instanceof ApiError && err.status === 409) return false
      setConversationError(err instanceof ApiError ? err.message : '检查提问超时状态失败')
      return false
    } finally {
      if (loadVersion === documentLoadVersionRef.current && questionTimeoutRecoveryRef.current === question.id) {
        questionTimeoutRecoveryRef.current = null
      }
    }
  }

  resumeHandlerRef.current = async (
    runId: string,
    sessionId?: number,
    streamAfter = 0,
    timeline?: AgentRunTimeline | null,
  ) => handleSendMessage('', [], runId, undefined, sessionId, undefined, undefined, [], [], 'structure', undefined, streamAfter, undefined, undefined, timeline)

  const handleStopAgent = async () => {
    if (compactionControllerRef.current) {
      compactionControllerRef.current.abort()
      return
    }
    const runId = activeRunRef.current
    if (!docId) return
    const loadVersion = documentLoadVersionRef.current
    const ownsStop = () => loadVersion === documentLoadVersionRef.current
      && attachedEditorDocumentRef.current === docId
      && (activeRunRef.current === runId || activeRunRef.current === null)
    if (!runId) {
      setStopping(true)
      setThinkingStatus('正在等待任务创建后停止…')
      requestChatRunStop(chatRunConnectionRef.current)
      return
    }
    try {
      setStopping(true)
      setThinkingStatus('正在停止 Agent…')
      const cancelled = await cancelChatRun(docId, runId,
        (status) => { if (ownsStop()) setStreamNotice(retryNotice(status)) })
      if (!ownsStop()) return
      if (['completed', 'cancelled', 'failed'].includes(cancelled.status)) {
        const [stoppedMessages, refreshedDocument] = await Promise.all([
          loadRecentMessages(docId, cancelled.session_id),
          documentsApi.get(docId),
        ])
        if (!ownsStop()) return
        applyExternalHtml(refreshedDocument.current_html)
        setPreviewRevision((value) => value + 1)
        setVersionRefreshToken((value) => value + 1)
        setPendingUserQuestion(null)
        setQuestionSubmitting(false)
        activeRunRef.current = null
        setStopping(false)
        setThinkingStatus(null)
        setStreamNotice(null)
        setRecentMessages(stoppedMessages)
      }
    } catch (err) {
      if (!ownsStop()) return
      setStopping(false)
      setConversationError(err instanceof ApiError ? err.message : '停止 Agent 失败')
    }
  }

  const selectChatSession = async (sessionId: number) => {
    if (!docId || streaming || chatStartInProgressRef.current || pendingUserQuestion || sessionId === activeChatSessionId) return
    try {
      if (activeChatSessionId && (contextDraft.trim() || chatTexts.items.length)) {
        const current = readChatComposerDraft(docId, activeChatSessionId)
        writeChatComposerDraft(docId, activeChatSessionId, {
          message: contextDraft,
          textAttachments: chatTexts.items.filter(item => item.status !== 'uploading' && item.status !== 'error'),
          templateRefs: composerTemplates.map(({ id, name }) => ({ id, name })),
          reaskFromMessageId: pendingReaskMessageId,
          phase: current?.phase === 'retry' ? 'retry' : 'editing',
          ...(current?.phase === 'retry' && current.clientRequestId ? { clientRequestId: current.clientRequestId } : {}),
        })
      }
      const [sessionMessages, restoredComposerDraft] = await Promise.all([
        loadRecentMessages(docId, sessionId),
        resolveStoredComposerDraft(docId, sessionId),
      ])
      if (attachedEditorDocumentRef.current !== docId || chatStartInProgressRef.current || chatRunConnectionRef.current) return
      setContextStats(null)
      discardDraftChatImages()
      setContextDraft(restoredComposerDraft?.message ?? '')
      setPendingReaskMessageId(restoredComposerDraft?.reaskFromMessageId ?? null)
      setSelectedElements([])
      setReaskConflict(null)
      setActiveChatSessionId(sessionId)
      setAttachedTemplates(chatSessions.find((item) => item.id === sessionId)?.attached_templates ?? [])
      setComposerTemplates(restoreComposerTemplates(restoredComposerDraft?.templateRefs))
      setRecentMessages(sessionMessages)
      setHiddenHistory([])
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '切换对话失败')
    }
  }

  const refreshChatSessions = async () => {
    if (!docId) return []
    const sessions = await chatApi.listSessions(docId)
    setChatSessions(sessions)
    return sessions
  }

  const handleCreateChatSession = async () => {
    if (!docId || streaming || chatStartInProgressRef.current) return
    const emptySession = chatSessions.find((item) => (
      !item.is_archived
      && item.title === '新对话'
      && item.visible_message_count === 0
      && item.hidden_message_count === 0
    ))
    if (emptySession) {
      await selectChatSession(emptySession.id)
      return
    }
    if (creatingChatSessionRef.current) return
    creatingChatSessionRef.current = true
    try {
      const session = await chatApi.createSession(docId)
      if (attachedEditorDocumentRef.current !== docId || chatStartInProgressRef.current || chatRunConnectionRef.current) return
      setChatSessions((items) => {
        const exists = items.some((item) => item.id === session.id)
        return exists ? items : [session, ...items]
      })
      setActiveChatSessionId(session.id)
      setAttachedTemplates(session.attached_templates ?? [])
      setComposerTemplates([])
      setMessages([])
      setHasOlderMessages(false)
      setHiddenHistory([])
      setContextStats(null)
      setContextDraft('')
      discardDraftChatImages()
      setPendingReaskMessageId(null)
      setSelectedElements([])
      setReaskConflict(null)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '新建对话失败')
    } finally {
      creatingChatSessionRef.current = false
    }
  }

  const handleRenameChatSession = async (sessionId: number, nextTitle: string) => {
    if (!docId || streaming) return
    try {
      const updated = await chatApi.renameSession(docId, sessionId, nextTitle)
      setChatSessions((items) => items.map((item) => item.id === sessionId ? updated : item))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '重命名对话失败')
    }
  }

  const handleClearLayoutReference = async () => {
    if (!docId || !activeChatSessionId || streaming) return
    try {
      await chatApi.clearLayoutReference(docId, activeChatSessionId)
      await refreshChatSessions()
      message.success('已清除当前对话的参考模板')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '清除参考模板失败')
    }
  }

  const handleArchiveChatSession = async (sessionId: number) => {
    if (!docId || streaming || chatStartInProgressRef.current) return
    try {
      const archived = await chatApi.archiveSession(docId, sessionId)
      let sessions = await refreshChatSessions()
      if (sessionId === activeChatSessionId) {
        let next = sessions.find((item) => !item.is_archived)
        if (!next) {
          next = await chatApi.createSession(docId)
          sessions = [next, ...sessions]
          setChatSessions(sessions)
        }
        const [nextMessages, restoredComposerDraft] = await Promise.all([
          loadRecentMessages(docId, next.id),
          resolveStoredComposerDraft(docId, next.id),
        ])
        setActiveChatSessionId(next.id)
        setAttachedTemplates(next.attached_templates ?? [])
        setComposerTemplates(restoreComposerTemplates(restoredComposerDraft?.templateRefs))
        setRecentMessages(nextMessages)
        setHiddenHistory([])
        setContextStats(null)
        discardDraftChatImages()
        setContextDraft(restoredComposerDraft?.message ?? '')
        setPendingReaskMessageId(restoredComposerDraft?.reaskFromMessageId ?? null)
        setSelectedElements([])
      } else {
        setChatSessions((items) => items.map((item) => item.id === sessionId ? archived : item))
      }
      message.success('对话已归档')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '归档对话失败')
    }
  }

  const handleRestoreChatSession = async (sessionId: number) => {
    if (!docId || streaming || chatStartInProgressRef.current) return
    try {
      const restored = await chatApi.restoreSession(docId, sessionId)
      setChatSessions((items) => items.map((item) => item.id === sessionId ? restored : item))
      await selectChatSession(sessionId)
      message.success('对话已恢复')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '恢复对话失败')
    }
  }

  const handleTruncateChatContext = async () => {
    if (!docId || !activeChatSession || streaming || chatStartInProgressRef.current) return
    try {
      const updated = await chatApi.truncateSession(docId, activeChatSession.id)
      setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
      setMessages([])
      setHasOlderMessages(false)
      setHiddenHistory([])
      setContextStats(null)
      setContextDraft('')
      setPendingReaskMessageId(null)
      setSelectedElements([])
      setComposerTemplates([])
      clearChatComposerDraft(docId, activeChatSession.id)
      message.success('当前对话上下文已截断')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '截断上下文失败')
    }
  }

  const handleRestoreChatContext = async () => {
    if (!docId || !activeChatSession || streaming || chatStartInProgressRef.current) return
    try {
      const updated = await chatApi.restoreSessionContext(docId, activeChatSession.id)
      setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
      setRecentMessages(await loadRecentMessages(docId, activeChatSession.id))
      setHiddenHistory([])
      setContextStats(null)
      message.success('历史已恢复到模型上下文')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '恢复上下文失败')
    }
  }

  const handleCompactChatContext = async (rebuild: boolean) => {
    if (compactionControllerRef.current || !docId || !activeChatSession || !modelId || streaming || chatStartInProgressRef.current) return
    const controller = new AbortController()
    compactionControllerRef.current = controller
    const ownsCompaction = () => compactionControllerRef.current === controller && !controller.signal.aborted
    setStreamNotice({ kind: 'info', title: '正在压缩上下文', detail: '正在整理较早对话和工具结果，可点击停止取消。' })
    setContextStats((current) => current ? { ...current, state: 'compacting' } : current)
    try {
      const stats = await chatApi.compactContext(docId, modelId, activeChatSession.id, rebuild,
        (status) => { if (ownsCompaction()) setStreamNotice(retryNotice(status)) }, controller.signal)
      if (!ownsCompaction()) return
      setStreamNotice(null)
      setContextStats(stats)
      const compactionNotice = stats.compaction_notice
      if (compactionNotice) {
        setMessages((current) => (
          current.some((item) => item.id === compactionNotice.id)
            ? current
            : [...current, compactionNotice]
        ))
      }
      if (stats.thinking_capability_fallback) {
        handleThinkingCapabilityFallback(stats.thinking_capability_fallback)
      }
      message.success(rebuild ? '已从完整历史重建上下文摘要' : '已压缩当前对话上下文')
    } catch (err) {
      if (compactionControllerRef.current !== controller) return
      if (controller.signal.aborted) {
        setStreamNotice(null)
        setContextStats(null)
        return
      }
      setStreamNotice({ kind: 'error', title: '上下文压缩失败', detail: err instanceof Error ? err.message : '可稍后重试' })
      setContextStats(null)
      message.error(err instanceof ApiError ? String(err.detail) : '上下文压缩失败，可稍后重试')
    } finally {
      if (compactionControllerRef.current === controller) compactionControllerRef.current = null
    }
  }

  const handleViewHiddenHistory = async () => {
    if (!docId || !activeChatSession || activeChatSession.hidden_message_count === 0) return
    try {
      const allMessages = await chatApi.listMessages(docId, activeChatSession.id, true)
      setHiddenHistory(allMessages.slice(0, activeChatSession.hidden_message_count))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载已隐藏历史失败')
    }
  }

  useEffect(() => {
    if (!docId || loading || streaming || chatSubmitting || !pageVisible) return
    let disposed = false
    const controller = new AbortController()
    const loadVersion = documentLoadVersionRef.current
    const ownsRecovery = () => !disposed && !controller.signal.aborted
      && loadVersion === documentLoadVersionRef.current && attachedEditorDocumentRef.current === docId
    void (async () => {
      try {
        const activeRun = await chatApi.getActiveRun(docId, controller.signal, status => {
          if (!ownsRecovery() || status.phase === 'recovered') return
          setRecoveryNotice({ ...retryNotice(status), title: '正在重试检查后台任务状态',
            detail: '状态检查暂时未连通，尚未确认任务是否仍在运行。已有对话结果会保留。' })
        })
        if (!ownsRecovery()) return
        if (!activeRun && recoveryCheck > recoveredCheckRef.current) {
          const [freshDocument, freshMessages] = await Promise.all([
            documentsApi.get(docId),
            activeChatSessionId ? loadRecentMessages(docId, activeChatSessionId) : Promise.resolve([]),
          ])
          if (!ownsRecovery() || chatStartInProgressRef.current || chatRunConnectionRef.current) return
          recoveredCheckRef.current = recoveryCheck
          setRecoveryNotice(null)
          setRecentMessages(freshMessages)
          // Synchronizing history must not replace a newer unsaved source edit.
          if (draftHtmlRef.current === htmlRef.current) applyExternalHtml(freshDocument.current_html)
        }
        setRecoveryNotice(current => current?.operationId === 'history-sync' ? current : null)
        if (!activeRun || !ownsRecovery() || chatStartInProgressRef.current || chatRunConnectionRef.current || resumedRunRef.current === activeRun.run_id) return
        const resumedMessages = activeRun.session_id !== activeChatSessionId
          ? await loadRecentMessages(docId, activeRun.session_id)
          : null
        if (!ownsRecovery() || chatStartInProgressRef.current || chatRunConnectionRef.current) return
        resumedRunRef.current = activeRun.run_id
        if (activeRun.session_id !== activeChatSessionId) {
          setActiveChatSessionId(activeRun.session_id)
          setRecentMessages(resumedMessages ?? [])
          setHiddenHistory([])
        }
        if (activeRun.status === 'waiting_for_input' && activeRun.user_question) {
          activeRunRef.current = activeRun.run_id
          setPendingUserQuestion(activeRun.user_question)
          const timeline = activeRun.user_question.timeline
          if (timeline) {
            const timelineTools = Array.isArray(timeline.tool_calls) ? timeline.tool_calls : []
            const timelineBlocks = Array.isArray(timeline.turn_blocks) ? timeline.turn_blocks : []
            setToolActivities(timelineTools)
            setStreamBlocks(timelineBlocks)
            setReasoningTrace(timeline.reasoning ?? { status: 'idle', content: '', detail: '' })
            const latestContent = [...timelineBlocks].reverse().find((block) => block.type === 'content')
            setStreamText(latestContent?.content ?? '')
          }
          setQuestionSubmitting(false)
          setThinkingStatus('等待你确认排版偏好')
          return
        }
        setThinkingStatus('正在恢复 Agent 输出…')
        await resumeHandlerRef.current?.(
          activeRun.run_id,
          activeRun.session_id,
          activeRun.event_sequence,
          activeRun.timeline,
        )
      } catch (err) {
        if (!ownsRecovery() || (err instanceof Error && err.name === 'AbortError')) return
        setThinkingStatus(null)
        setRecoveryNotice({ kind: 'info', title: '暂时无法检查后台任务状态', phase: 'exhausted',
          detail: `已有结果仍保留，可重试检查。${err instanceof Error ? `（${err.message}）` : ''}` })
      }
    })()
    return () => {
      disposed = true
      controller.abort()
    }
  }, [activeChatSessionId, chatSubmitting, docId, loadRecentMessages, loading, pageVisible, recoveryCheck, setRecentMessages, streaming, applyExternalHtml])

  const handleVersionRestored = async (document: { title: string; current_html: string }) => {
    if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
    setTitle(document.title)
    applyExternalHtml(document.current_html)
    setPreviewRevision((value) => value + 1)
    setComposerTemplates([])
    setPendingReaskMessageId(null)
    if (docId && activeChatSessionId) clearChatComposerDraft(docId, activeChatSessionId)
    setContextDraft('')
    setCenterView('preview')
    invalidateCompliance()
    setVersionRefreshToken((value) => value + 1)
  }

  const columnsStyle = (chatPaneWidth === null && resourcePaneWidth === null)
    ? undefined
    : ({
        ...(chatPaneWidth === null ? {} : { '--chat-pane-width': `${chatPaneWidth}px` }),
        ...(resourcePaneWidth === null ? {} : { '--resource-pane-width': `${resourcePaneWidth}px` }),
      } as CSSProperties)

  const handleSetLibraryCover = useCallback(async (assetId: string) => {
    if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
    const saved = await persistDraftHtml(false, true)
    if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
    if (saved === null) throw new Error('正文保存失败')
    try {
      await imageLibraryApi.setCover(assetId, docId)
      if (!ownsRenderedDocument()) return
      setVersionRefreshToken((value) => value + 1)
      message.success('已设为文章封面')
    } catch (error) {
      if (!ownsRenderedDocument()) return
      message.error(error instanceof ApiError ? String(error.detail) : '设置封面失败')
      throw error
    }
  }, [docId, ownsRenderedDocument, ownsRenderedMutation, persistDraftHtml])
  // Streaming deltas only change the chat; keep resource previews and controls
  // outside that update cycle while retaining all resource-specific inputs.
  const resourceLibrary = useMemo(() => (
    <TemplateLibraryPanel
      modelId={modelId}
      models={models}
      disabled={documentEditingLocked || saving || materializingTemplateImages || localizingArticleImages}
      attachmentDisabled={templateAttachmentsUpdating || !activeChatSession || activeChatSession.is_archived || stopping || chatSubmitting || Boolean(pendingUserQuestion)}
      canInsertAtCaret={centerView === 'preview' && previewMode === 'edit' && hasPreviewCaret}
      attachedTemplateIds={attachedTemplates.map((item) => item.id)}
      themeContext={activeChatSession?.theme_context ?? null}
      onPrepend={(template) => handleInsertTemplateAtBoundary(template, 'prepend')}
      onAppend={(template) => handleInsertTemplateAtBoundary(template, 'append')}
      onInsertAtCaret={handleInsertTemplateAtCaret}
      onAttachToChat={attachTemplateToChat}
      onClearThemeContext={() => { void clearSessionThemeContext() }}
      collection={templateCollection}
      onCollectionHandled={handleTemplateCollection}
      activeResourceTab={activeResourceTab}
      onResourceTabChange={setActiveResourceTab}
      imagePanel={<ImageLibraryPanel
        key={`${docId}:${renderedDocumentEpoch}`}
        documentId={docId}
        sessionId={activeChatSessionId}
        initialModelId={activeChatSession?.image_model_id}
        disabled={documentEditingLocked || saving || localizingArticleImages}
        applicationTarget={imageApplicationTarget}
        selectedImage={activeCanvasImage}
        command={imageLibraryCommand}
        onApply={(url, alt) => ownsRenderedMutation() && !documentEditingLockedRef.current && Boolean(previewFrameRef.current?.applyLibraryImage(url, alt))}
        onSetCover={handleSetLibraryCover}
        onReference={handleReferenceLibraryImage}
        referenceDisabled={chatImageUploading || chatImages.length >= MAX_CHAT_IMAGES_PER_MESSAGE || !models.find((item) => item.id === modelId)?.is_multimodal || !activeChatSession || activeChatSession.is_archived || stopping || chatSubmitting || Boolean(pendingUserQuestion)}
      />}
      onOpenThemeGallery={(themeKey) => {
        setResourceDrawerOpen(false)
        setThemeGalleryInitialKey(themeKey ?? null)
        setThemeGalleryOpen(true)
      }}
    />
  ), [
    modelId, models, documentEditingLocked, saving, materializingTemplateImages, localizingArticleImages,
    centerView, previewMode, hasPreviewCaret, attachedTemplates, activeChatSession,
    handleInsertTemplateAtBoundary, handleInsertTemplateAtCaret, attachTemplateToChat, ownsRenderedMutation,
    clearSessionThemeContext, templateCollection, handleTemplateCollection,
    activeResourceTab, docId, renderedDocumentEpoch, activeChatSessionId, imageApplicationTarget,
    activeCanvasImage, imageLibraryCommand, handleSetLibraryCover,
    handleReferenceLibraryImage, chatImageUploading, chatImages.length, stopping, chatSubmitting, templateAttachmentsUpdating, pendingUserQuestion,
  ])

  if (loading) {
    const completedLoadProgress = WORKSPACE_LOAD_STEPS.reduce((total, step) => {
      const status = workspaceLoadSteps[step.key]
      if (status === 'completed') return total + 1
      if (step.key === 'resources' && status === 'loading' && workspaceResourceProgress.total > 0) {
        return total + workspaceResourceProgress.loaded / workspaceResourceProgress.total
      }
      return total
    }, 0)
    const progress = Math.round((completedLoadProgress / WORKSPACE_LOAD_STEPS.length) * 100)
    const waitingSteps = WORKSPACE_LOAD_STEPS
      .filter((step) => workspaceLoadSteps[step.key] === 'loading')
      .map((step) => step.label)
    const pendingSteps = WORKSPACE_LOAD_STEPS
      .filter((step) => workspaceLoadSteps[step.key] === 'pending')
      .map((step) => step.label)
    const loadingDetail = waitingSteps.length > 0
      ? `正在等待${waitingSteps.join('、')}…`
      : pendingSteps.length > 0
        ? `即将准备${pendingSteps.join('、')}…`
        : '正在打开编辑器…'
    const loadStepLabel = (step: typeof WORKSPACE_LOAD_STEPS[number], status: WorkspaceLoadStepStatus) => {
      if (step.key === 'resources' && status === 'loading' && workspaceResourceProgress.total > 0) {
        return `加载中 ${workspaceResourceProgress.loaded}/${workspaceResourceProgress.total}`
      }
      return status === 'completed' ? '已完成' : status === 'loading' ? '加载中' : '等待中'
    }
    return (
      <main className="editor-workbench-loading" aria-live="polite" aria-busy="true">
        <section className="editor-workbench-loading-panel" aria-label="排版工作台加载进度">
          <div className="editor-workbench-loading-heading">
            <div>
              <span>排版工作台</span>
              <strong>正在加载</strong>
            </div>
            <b>{progress}%</b>
          </div>
          <Progress percent={progress} status="active" showInfo={false} strokeColor="#1677ff" trailColor="#dfe8f7" />
          <p className="editor-workbench-loading-detail">{loadingDetail}</p>
          <div className="editor-workbench-loading-steps">
            {WORKSPACE_LOAD_STEPS.map((step) => {
              const status = workspaceLoadSteps[step.key]
              return (
                <div key={step.key} className={`editor-workbench-loading-step is-${status}`}>
                  <span aria-hidden="true" />
                  <span>{step.label}</span>
                  <small>{loadStepLabel(step, status)}</small>
                </div>
              )
            })}
          </div>
        </section>
      </main>
    )
  }

  const complianceButtonStatus = getComplianceButtonStatus(compliance, complianceLoading)
  const complianceButtonLabel = getComplianceButtonLabel(complianceButtonStatus)
  const selectCenterView = (nextView: CenterView) => {
    // Keep CodeMirror alive after its first use so switching back does not
    // recreate the language state and reparse the whole document.
    codeViewerHtmlRef.current = draftHtmlRef.current
    if (nextView === 'code') setCodeViewMounted(true)
    setCenterView(nextView)
    setMobileWorkspace(nextView)
  }
  const selectMobileWorkspace = (workspace: MobileWorkspace) => {
    if (workspace === 'chat') {
      setMobileWorkspace(workspace)
      return
    }
    selectCenterView(workspace)
  }
  const changePreviewDarkMode = (enabled: boolean) => {
    setPreviewDarkMode(enabled)
    if (enabled) setPreviewMode('browse')
  }

  return (
    <div className="editor-workbench">
      <div className="editor-toolbar">
        <div className="editor-toolbar-title">
          <Button aria-label="返回工作台" icon={<ArrowLeftOutlined />} onClick={() => navigate('/workbench')}>
            <span className="editor-toolbar-back-label">返回</span>
          </Button>
          <Input
            className="editor-toolbar-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleSaveTitle}
            disabled={documentEditingLocked}
            style={{ width: 280 }}
            placeholder="文档标题"
          />
          {isCompact && (
            <Tooltip title="更多文章操作">
              <Button
                aria-label="更多文章操作"
                className="editor-mobile-toolbar-action"
                icon={<MoreOutlined />}
                onClick={() => setMobileActionsDrawerOpen(true)}
              />
            </Tooltip>
          )}
        </div>
        {isCompact ? (
          <div className="editor-mobile-toolbar-actions">
            <Segmented
              className="editor-mobile-workspace-switcher"
              value={mobileWorkspace}
              onChange={(value) => selectMobileWorkspace(value as MobileWorkspace)}
              options={[
                { label: '对话', value: 'chat' },
                { label: '预览', value: 'preview' },
                { label: '源码', value: 'code' },
              ]}
            />
            <Tooltip title="打开资源库">
              <Button
                aria-label="资源库"
                className="editor-mobile-toolbar-action"
                icon={<AppstoreOutlined />}
                disabled={saving || materializingTemplateImages || localizingArticleImages}
                onClick={() => setResourceDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="保存预览或源码中的手动修改">
              <Button
                aria-label="保存手动修改"
                className="editor-mobile-toolbar-action"
                icon={<SaveOutlined />}
                type={draftHtml !== html ? 'primary' : 'default'}
                disabled={documentEditingLocked || saving || draftHtml === html}
                loading={saving}
                onClick={handleSaveHtml}
              />
            </Tooltip>
          </div>
        ) : (
          <Space className="editor-toolbar-controls" wrap>
            <Segmented
              className="editor-desktop-view-switcher"
              value={centerView}
              onChange={(v) => selectCenterView(v as CenterView)}
              options={[
                { label: '实时预览', value: 'preview' },
                { label: '源码编辑', value: 'code' },
              ]}
            />
            {centerView === 'preview' ? (
              <Segmented
                size="small"
                value={effectivePreviewMode}
                onChange={(value) => setPreviewMode(value as PreviewMode)}
                options={[
                  { label: '浏览', value: 'browse' },
                  { label: <><SelectOutlined /> 选择</>, value: 'select', disabled: previewDarkMode },
                  { label: <><EditOutlined /> 直接编辑</>, value: 'edit', disabled: documentEditingLocked || localizingArticleImages || previewDarkMode },
                ]}
              />
            ) : (
              <Tooltip title="直接编辑仅在实时预览页可用">
                <Button aria-label="直接编辑" icon={<EditOutlined />} disabled />
              </Tooltip>
            )}
            {centerView === 'preview' && effectivePreviewMode === 'edit' && (
              <>
                <Tooltip title="撤销（Ctrl+Z）">
                  <Button
                    aria-label="撤销"
                    icon={<UndoOutlined />}
                    disabled={documentEditingLocked || saving || !editHistoryState.canUndo}
                    onClick={() => previewFrameRef.current?.undo()}
                  />
                </Tooltip>
                <Tooltip title="恢复（Ctrl+Y）">
                  <Button
                    aria-label="恢复"
                    icon={<RedoOutlined />}
                    disabled={documentEditingLocked || saving || !editHistoryState.canRedo}
                    onClick={() => previewFrameRef.current?.redo()}
                  />
                </Tooltip>
              </>
            )}
            {centerView === 'preview' && (
              <>
                <Popover
                  title="预览显示"
                  trigger="click"
                  content={(
                    <div className="preview-brightness-control">
                      <div className="preview-dark-mode-control">
                        <span><MoonOutlined /> 微信 Dark Mode</span>
                        <Switch aria-label="微信 Dark Mode" checked={previewDarkMode} onChange={changePreviewDarkMode} />
                      </div>
                      <Slider
                        aria-label="预览亮度"
                        min={40}
                        max={140}
                        value={previewBrightness}
                        tooltip={{ formatter: (value) => `${value ?? 100}%` }}
                        onChange={setPreviewBrightness}
                      />
                      <Tooltip title="恢复默认亮度">
                        <Button
                          aria-label="恢复默认亮度"
                          type="text"
                          size="small"
                          icon={<ReloadOutlined />}
                          disabled={previewBrightness === 100}
                          onClick={() => setPreviewBrightness(100)}
                        />
                      </Tooltip>
                    </div>
                  )}
                >
                  <Tooltip title="调节预览亮度和显示模式">
                    <Button
                      aria-label="调节预览亮度"
                      icon={<BulbOutlined />}
                      type={previewBrightness === 100 && !previewDarkMode ? 'default' : 'primary'}
                    />
                  </Tooltip>
                </Popover>
                <Tooltip title="复制当前预览为可粘贴的富文本文章">
                  <Button
                    aria-label="复制文章"
                    icon={<CopyOutlined />}
                    disabled={!draftHtml.trim()}
                    onClick={() => { void handleCopyPreviewArticle() }}
                  >
                    复制文章
                  </Button>
                </Tooltip>
              </>
            )}
            <Tooltip title={resourceCollapsed ? '展开资源库' : '收起资源库'}>
              <Button
                icon={<AppstoreOutlined />}
                aria-label="资源库"
                type={!resourceCollapsed ? 'primary' : 'default'}
                disabled={saving}
                onClick={() => setResourceCollapsed((value) => !value)}
              >
                资源库
              </Button>
            </Tooltip>
            <Tooltip title="批量转存当前文章的外链图片">
              <span>
                <Popconfirm
                  title="转存当前文章中的外链图片？"
                  description="任一图片转存失败时，文章将保持原样。"
                  okText="开始转存"
                  cancelText="取消"
                  onConfirm={() => handleLocalizeArticleImages()}
                >
                  <Button
                    aria-label="批量转存当前文章的外链图片"
                    icon={<CloudDownloadOutlined />}
                    disabled={documentEditingLocked || saving || materializingTemplateImages || localizingArticleImages}
                    loading={localizingArticleImages}
                  />
                </Popconfirm>
              </span>
            </Tooltip>
            {(currentUser?.role === 'admin' || wechatAccounts.length > 0) && (
              <Tooltip title={wechatAccounts.length ? '推送至公众号草稿箱' : '请先在后台配置并启用公众号账号'}>
                <Button
                  aria-label="推送至公众号草稿箱"
                  icon={<SendOutlined />}
                  disabled={documentEditingLocked || saving || wechatAccounts.length === 0}
                  onClick={() => setWechatDraftOpen(true)}
                />
              </Tooltip>
            )}
            <Tooltip title="保存预览或源码中的手动修改">
              <Button
                aria-label="保存手动修改"
                icon={<SaveOutlined />}
                type={draftHtml !== html ? 'primary' : 'default'}
                disabled={documentEditingLocked || saving || draftHtml === html}
                loading={saving}
                onClick={handleSaveHtml}
              />
            </Tooltip>
            <Tooltip title={complianceButtonLabel}>
              <Button
                aria-label={`打开合规检测：${complianceButtonLabel}`}
                className={`compliance-status-trigger is-${complianceButtonStatus}`}
                icon={<SafetyCertificateOutlined />}
                onClick={() => setComplianceDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="版本历史">
              <Button
                aria-label="打开版本历史"
                icon={<HistoryOutlined />}
                type={versionDrawerOpen ? 'primary' : 'default'}
                onClick={() => setVersionDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="分享只读预览">
              <Button
                aria-label="分享只读预览"
                icon={<LinkOutlined />}
                disabled={saving}
                onClick={() => setDocumentShareOpen(true)}
              />
            </Tooltip>
            {hasSourceFile && (
              <Tooltip title="原文校审">
                <Button
                  aria-label="打开原文校审"
                  icon={<FileSearchOutlined />}
                  onClick={() => setSourcePreviewOpen(true)}
                />
              </Tooltip>
            )}
            <Button icon={<ReloadOutlined />} disabled={documentEditingLocked || saving} onClick={loadDocument}>
              刷新
            </Button>
          </Space>
        )}
      </div>

      <div
        ref={columnsRef}
        className={`editor-columns${resizingChatPane || resizingResourcePane ? ' is-resizing' : ''}${!isCompact && !resourceCollapsed ? ' has-resource' : ''} mobile-workspace-${mobileWorkspace}`}
        style={columnsStyle}
      >
        <div className="editor-col editor-col-chat">
          <ChatPanel
            models={models}
            modelId={modelId}
            onModelChange={(nextModelId) => {
              // Do not briefly apply the prior model's context verdict while
              // the selected model is being evaluated by chat-context.
              setContextStats(null)
              const nextModel = models.find((item) => item.id === nextModelId)
              if (!nextModel?.is_multimodal) {
                discardDraftChatImages()
              }
              setModelId(nextModelId)
              saveLastSelectedModelId(currentUser?.id, nextModelId)
              const restoredThinkingPreference = resolveThinkingPreference(
                currentUser?.id,
                nextModel,
                temporarilyUnsupportedThinkingModelIds.has(nextModelId),
              )
              setThinkingMode(restoredThinkingPreference.mode)
              setThinkingEffort(restoredThinkingPreference.effort)
            }}
            thinkingMode={thinkingMode}
            onThinkingModeChange={(nextMode) => {
              setThinkingMode(nextMode)
              if (modelId) saveThinkingPreference(currentUser?.id, modelId, { mode: nextMode, effort: thinkingEffort })
            }}
            thinkingEffort={thinkingEffort}
            onThinkingEffortChange={(nextEffort) => {
              const nextMode = thinkingMode === 'disabled' ? 'enabled' : thinkingMode
              setThinkingMode(nextMode)
              setThinkingEffort(nextEffort)
              if (modelId) saveThinkingPreference(currentUser?.id, modelId, { mode: nextMode, effort: nextEffort })
            }}
            temporarilyUnsupportedThinkingModelIds={temporarilyUnsupportedThinkingModelIds}
            thinkingStatus={thinkingStatus}
            contextStats={contextStats}
            chatSessions={chatSessions}
            activeChatSession={activeChatSession}
            hiddenHistory={hiddenHistory}
            messages={messages}
            hasOlderMessages={hasOlderMessages}
            olderMessagesLoading={olderMessagesLoading}
            onLoadOlderMessages={loadOlderMessages}
            queuedMessages={queuedChatRequests.map(({ id, content, images, texts }) => ({ id, content, images, texts }))}
            queuePaused={chatQueuePaused}
            streaming={streaming}
            stopping={stopping}
            streamText={streamText}
            toolActivities={toolActivities}
            reasoningTrace={reasoningTrace}
            streamBlocks={streamBlocks}
            streamNotice={streamNotice}
            recoveryNotice={recoveryNotice}
            onRetryRecovery={() => {
              if (chatStartInProgressRef.current || chatRunConnectionRef.current) return
              resumedRunRef.current = null
              setRecoveryNotice(null)
              setRecoveryCheck(value => value + 1)
            }}
            conversationError={conversationError}
            composerDraft={contextDraft}
            submitting={chatSubmitting || templateAttachmentsUpdating}
            starting={chatSubmitting}
            pendingUserQuestion={pendingUserQuestion}
            questionSubmitting={questionSubmitting}
            reaskConflict={reaskConflict}
            resolvingReaskConflict={resolvingReaskConflict}
            selectedElements={selectedElements}
            attachedTemplates={attachedTemplates}
            composerTemplates={composerTemplates}
            imageAttachments={chatImages}
            textAttachments={chatTexts.items}
            textAttachmentLoadError={chatTexts.loadError}
            onReloadTexts={() => { void chatTexts.reload() }}
            onPasteText={(text) => {
              try { return chatTexts.paste(text) }
              catch (error) { message.error(error instanceof Error ? error.message : '文本附件上传失败'); return false }
            }}
            onRemoveText={(item) => { void chatTexts.remove(item).catch(error => message.error(error instanceof Error ? error.message : '移除失败')) }}
            onRetryText={(item) => { void chatTexts.retry(item) }}
            imageUploading={chatImageUploading}
            imageUploadProgress={chatImageUploadProgress}
            onRemoveSelectedElement={(index) => setSelectedElements((items) => items.filter((_, itemIndex) => itemIndex !== index))}
            onDuplicateSelectedElement={(index) => {
              setSelectedElements((items) => {
                if (items.length >= 12) {
                  message.warning('最多可附带 12 个元素引用')
                  return items
                }
                return [...items.slice(0, index + 1), { ...items[index] }, ...items.slice(index + 1)]
              })
            }}
            onMoveSelectedElement={(fromIndex, toIndex) => {
              setSelectedElements((items) => {
                const next = [...items]
                const [moved] = next.splice(fromIndex, 1)
                next.splice(toIndex, 0, moved)
                return next
              })
            }}
            onRemoveAttachedTemplate={(templateId) => { void removeAttachedTemplate(templateId) }}
            onRemoveComposerTemplate={(templateId) => setComposerTemplates((items) => items.filter((item) => item.id !== templateId))}
            onRemoveQueuedMessage={removeQueuedChatRequest}
            onUpdateQueuedMessage={updateQueuedChatRequest}
            onMoveQueuedMessage={moveQueuedChatRequest}
            onResumeQueuedMessages={() => setChatQueuePaused(false)}
            onEditRequest={handleEditRequest}
            onSend={(text, references, images, texts = [], templateIds = composerTemplates.map(item => item.id)) => {
              let templates: TemplateItem[]
              try {
                templates = orderMessageTemplates([...composerTemplates, ...attachedTemplates], templateIds)
              } catch (error) {
                message.error(error instanceof Error ? error.message : '组件引用无效，请重新附加')
                return
              }
              const byId = new Map(templates.map(item => [item.id, item]))
              const referencedTemplates = templateIds.map(id => byId.get(id)!)
              requestChatQuestionNotificationPermissionOnce()
              // Clear the submitted draft immediately. The request handler
              // still owns recovery if persisting or starting the run fails.
              setContextDraft('')
              setSelectedElements([])
              if (streaming || chatSubmitting) {
                enqueueChatRequest(text, references, images, texts, templates, referencedTemplates)
                return
              }
              void handleSendMessage(text, references, undefined, undefined, undefined, undefined, undefined, images,
                [], 'structure', undefined, 0, undefined, modelId ? { modelId, thinkingMode, thinkingEffort, textAttachments: texts, templates, referencedTemplates } : undefined)
            }}
            onAnswerUserQuestion={(answer) => { void handleAnswerUserQuestion(answer) }}
            onUserQuestionActivity={handleUserQuestionActivity}
            onUserQuestionTimeoutElapsed={() => { void handleUserQuestionTimeoutElapsed() }}
            onUploadImages={handleChatImageUpload}
            onRemoveImage={handleRemoveChatImage}
            onMoveImage={(fromIndex, toIndex) => {
              setChatImages((items) => {
                const next = [...items]
                const [moved] = next.splice(fromIndex, 1)
                next.splice(toIndex, 0, moved)
                return next
              })
            }}
            onContextDraftChange={setContextDraft}
            onDismissReaskConflict={handleDismissReaskConflict}
            onDiscardReaskConflict={handleDiscardReaskConflict}
            onOpenLayoutImitation={() => setLayoutImitationOpen(true)}
            onStop={handleStopAgent}
            onSessionChange={selectChatSession}
            onCreateSession={handleCreateChatSession}
            onRenameSession={handleRenameChatSession}
            onArchiveSession={handleArchiveChatSession}
            onRestoreSession={handleRestoreChatSession}
            onTruncateContext={handleTruncateChatContext}
            onRestoreContext={handleRestoreChatContext}
            onCompactContext={handleCompactChatContext}
            onViewHiddenHistory={handleViewHiddenHistory}
            onClearHiddenHistory={() => setHiddenHistory([])}
            onClearLayoutReference={handleClearLayoutReference}
            onClearThemeContext={clearSessionThemeContext}
          />
        </div>
        <div
          className="editor-col-resizer"
          role="separator"
          aria-label="调整对话栏宽度"
          aria-orientation="vertical"
          onPointerDown={handleChatPaneResizeStart}
        />

        <div className="editor-col editor-col-center">
          <div className={`editor-center-panel${centerView === 'preview' ? '' : ' is-hidden'}`}>
            <PreviewFrame
              ref={previewFrameRef}
              html={draftHtml}
              revision={previewRevision}
              active={centerView === 'preview'}
              mode={effectivePreviewMode}
              brightness={previewBrightness}
              darkMode={previewDarkMode}
              compact={isCompact}
              selectedElements={selectedElements}
              onHtmlChange={handleHtmlChange}
              onUploadImage={handleImageUpload}
              onAiImageAction={(mode, target) => {
                setActiveCanvasImage(target)
                openImageLibrary('generate', mode === 'edit')
              }}
              onImageApplicationTargetChange={setImageApplicationTarget}
              onActiveImageChange={setActiveCanvasImage}
              onExternalImagesPasted={handleExternalImagesPasted}
              onToggleSelection={(element, selected) => {
                setSelectedElements((items) => {
                  if (selected) return items.length < 12 ? [...items, sanitizeSelectedElement(element)] : items
                  const matchedIndex = items.findIndex((candidate) => candidate.selector === element.selector)
                  return items.filter((_, index) => index !== matchedIndex)
                })
              }}
              onAttachSelectedBlocks={(elements) => {
                setSelectedElements((items) => {
                  const next = [...items]
                  for (const element of elements) {
                    if (next.length >= 12) break
                    const sanitized = sanitizeSelectedElement(element)
                    const alreadyAttached = next.some((candidate) => (
                      candidate.selector === sanitized.selector && candidate.html === sanitized.html
                    ))
                    if (!alreadyAttached) next.push(sanitized)
                  }
                  return next
                })
              }}
              onCollectTemplateHtml={collectTemplateHtml}
              onHistoryStateChange={setEditHistoryState}
              onCaretAvailabilityChange={setHasPreviewCaret}
              onCaretTargetChange={setActiveCaretTarget}
            />
          </div>
          <div className={`editor-center-panel${centerView === 'code' ? '' : ' is-hidden'}`}>
            {codeViewMounted && (
              <Suspense fallback={<div className="editor-panel-loading" aria-busy="true" />}>
                <CodeViewer html={centerView === 'code' ? draftHtml : codeViewerHtmlRef.current} onChange={handleHtmlChange} onSave={handleSaveHtml} saving={saving || localizingArticleImages} disabled={documentEditingLocked || localizingArticleImages} />
              </Suspense>
            )}
          </div>
        </div>

        {!isCompact && !resourceCollapsed && (
          <>
            <div
              className="editor-col-resizer editor-resource-resizer"
              role="separator"
              aria-label="调整资源库宽度"
              aria-orientation="vertical"
              onPointerDown={handleResourcePaneResizeStart}
            />
            <div className="editor-col editor-col-resource">
              {resourceLibrary}
            </div>
          </>
        )}

      </div>
      <Drawer
        title="资源库"
        placement="right"
        size="min(420px, 100vw)"
        open={isCompact && resourceDrawerOpen}
        onClose={() => setResourceDrawerOpen(false)}
        destroyOnHidden
        className="resource-library-drawer"
      >
        {resourceLibrary}
      </Drawer>
      <Drawer
        title="文章工具"
        placement="bottom"
        height={centerView === 'preview' ? 400 : 268}
        open={isCompact && mobileActionsDrawerOpen}
        onClose={() => setMobileActionsDrawerOpen(false)}
        destroyOnHidden
        className="editor-mobile-actions-drawer"
      >
        {centerView === 'preview' && (
          <section className="editor-mobile-actions-section" aria-label="预览工具">
            <span className="editor-mobile-actions-heading">预览</span>
            <Segmented
              block
              value={effectivePreviewMode}
              onChange={(value) => {
                setPreviewMode(value as PreviewMode)
                setMobileActionsDrawerOpen(false)
              }}
              options={[
                { label: '浏览', value: 'browse' },
                { label: '选择', value: 'select', disabled: previewDarkMode },
                { label: '直接编辑', value: 'edit', disabled: documentEditingLocked || localizingArticleImages || previewDarkMode },
              ]}
            />
            <div className="editor-mobile-dark-mode-control">
              <span><MoonOutlined /> 微信 Dark Mode</span>
              <Switch aria-label="微信 Dark Mode" checked={previewDarkMode} onChange={changePreviewDarkMode} />
            </div>
            <div className="editor-mobile-brightness-control">
              <span>预览亮度 {previewBrightness}%</span>
              <Slider
                aria-label="预览亮度"
                min={40}
                max={140}
                value={previewBrightness}
                tooltip={{ formatter: (value) => `${value ?? 100}%` }}
                onChange={setPreviewBrightness}
              />
              <Tooltip title="恢复默认亮度">
                <Button
                  aria-label="恢复默认亮度"
                  type="text"
                  icon={<ReloadOutlined />}
                  disabled={previewBrightness === 100}
                  onClick={() => setPreviewBrightness(100)}
                />
              </Tooltip>
            </div>
          </section>
        )}
        <section className="editor-mobile-actions-section" aria-label="文章操作">
          <span className="editor-mobile-actions-heading">文章</span>
          <div className="editor-mobile-actions-grid">
            <Button
              icon={<CopyOutlined />}
              disabled={!draftHtml.trim()}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                void handleCopyPreviewArticle()
              }}
            >
              复制文章
            </Button>
            <Popconfirm
              title="转存当前文章中的外链图片？"
              description="任一图片转存失败时，文章将保持原样。"
              okText="开始转存"
              cancelText="取消"
              onConfirm={() => {
                setMobileActionsDrawerOpen(false)
                return handleLocalizeArticleImages()
              }}
            >
              <Button
                icon={<CloudDownloadOutlined />}
                disabled={documentEditingLocked || saving || materializingTemplateImages || localizingArticleImages}
                loading={localizingArticleImages}
              >
                转存外链图片
              </Button>
            </Popconfirm>
            <Button
              icon={<SafetyCertificateOutlined />}
              className={`compliance-status-trigger is-${complianceButtonStatus}`}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setComplianceDrawerOpen(true)
              }}
            >
              合规检测
            </Button>
            <Button
              icon={<HistoryOutlined />}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setVersionDrawerOpen(true)
              }}
            >
              版本历史
            </Button>
            <Button
              icon={<LinkOutlined />}
              disabled={saving}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setDocumentShareOpen(true)
              }}
            >
              分享预览
            </Button>
            {hasSourceFile && (
              <Button
                icon={<FileSearchOutlined />}
                onClick={() => {
                  setMobileActionsDrawerOpen(false)
                  setSourcePreviewOpen(true)
                }}
              >
                原文校审
              </Button>
            )}
            <Button
              icon={<ReloadOutlined />}
              disabled={documentEditingLocked || saving}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                void loadDocument()
              }}
            >
              刷新文章
            </Button>
          </div>
        </section>
        {(currentUser?.role === 'admin' || wechatAccounts.length > 0) && (
          <section className="editor-mobile-actions-section" aria-label="发布操作">
            <span className="editor-mobile-actions-heading">发布</span>
            <div className="editor-mobile-actions-grid">
              <Button
                icon={<SendOutlined />}
                disabled={documentEditingLocked || saving || wechatAccounts.length === 0}
                onClick={() => {
                  setMobileActionsDrawerOpen(false)
                  setWechatDraftOpen(true)
                }}
              >
                推送至公众号草稿箱
              </Button>
            </div>
          </section>
        )}
      </Drawer>
      <Drawer
        title="合规检测"
        placement="right"
        size={isCompact ? '100vw' : 360}
        open={complianceDrawerOpen}
        onClose={() => setComplianceDrawerOpen(false)}
      >
        <CompliancePanel
          report={compliance}
          loading={complianceLoading}
          onCheck={() => void handleManualComplianceCheck()}
        />
      </Drawer>
      <VersionHistoryDrawer
        key={`${docId}:${renderedDocumentEpoch}`}
        documentId={docId}
        open={versionDrawerOpen}
        refreshToken={versionRefreshToken}
        restoreDisabled={documentEditingLocked || saving || draftHtml !== html}
        copyDisabled={documentEditingLocked || saving || draftHtml !== html}
        copyDefaults={versionCopyDefaults}
        onClose={() => setVersionDrawerOpen(false)}
        onRestored={handleVersionRestored}
        onCopied={(document) => navigate(`/editor/${document.id}`)}
      />
      {layoutImitationOpen && (
        <Suspense fallback={null}>
          <LayoutImitationModal
            open
            streaming={streaming}
            modelAvailable={Boolean(modelId)}
            onClose={() => setLayoutImitationOpen(false)}
            onConfirm={(reference, assetsConfirmed, selectedAssetIds, imitationStrength) => {
              void handleLayoutImitation(reference, assetsConfirmed, selectedAssetIds, imitationStrength)
            }}
          />
        </Suspense>
      )}
      {themeGalleryOpen && (
        <Suspense fallback={null}>
          <ThemeGalleryModal
            open
            initialThemeKey={themeGalleryInitialKey}
            documentId={docId}
            sessionId={activeChatSessionId}
            modelId={modelId}
            models={models}
            disabled={documentEditingLocked || saving || !modelId}
            onClose={() => {
              setThemeGalleryOpen(false)
              setThemeGalleryInitialKey(null)
            }}
            onApproved={(proposal) => { void handleThemeApplication(proposal) }}
          />
        </Suspense>
      )}
      {wechatDraftOpen && (
        <Suspense fallback={null}>
          <WeChatDraftModal
            key={`${docId}:${renderedDocumentEpoch}`}
            open
            documentId={docId}
            disabled={documentEditingLocked || saving || draftHtml !== html}
            onClose={() => setWechatDraftOpen(false)}
            onMetadataSaved={(_nextMetadata, nextTitle) => {
              setTitle(nextTitle)
              setVersionRefreshToken((value) => value + 1)
            }}
            onDocumentRefreshed={(document) => {
              if (!ownsRenderedMutation() || documentEditingLockedRef.current) return
              applyExternalHtml(document.current_html)
              setTitle(document.title)
              setPreviewRevision((value) => value + 1)
              setVersionRefreshToken((value) => value + 1)
              invalidateCompliance()
            }}
          />
        </Suspense>
      )}
      {documentShareOpen && (
        <Suspense fallback={null}>
          <DocumentShareModal
            open
            documentId={docId}
            documentTitle={title}
            onClose={() => setDocumentShareOpen(false)}
          />
        </Suspense>
      )}
      {sourcePreviewOpen && (
        <Suspense fallback={null}>
          <SourceDocumentModal documentId={docId} currentHtml={draftHtml} open onClose={() => setSourcePreviewOpen(false)} />
        </Suspense>
      )}
    </div>
  )
}
