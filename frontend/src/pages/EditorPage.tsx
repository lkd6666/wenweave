import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { Button, Drawer, Grid, Input, Modal, Popconfirm, Popover, Segmented, Slider, Space, Spin, Tooltip, message } from 'antd'
import { AppstoreOutlined, ArrowLeftOutlined, BulbOutlined, CloudDownloadOutlined, CopyOutlined, EditOutlined, FileSearchOutlined, HistoryOutlined, LinkOutlined, MoreOutlined, PictureOutlined, RedoOutlined, ReloadOutlined, SafetyCertificateOutlined, SaveOutlined, SelectOutlined, SendOutlined, UndoOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router'
import ChatPanel, { type ChatRunNotice, type QueuedChatMessage, type ReaskConflictNotice } from '../components/ChatPanel'
import type { UserQuestionAnswer } from '../components/UserQuestionPanel'
import PreviewFrame from '../components/PreviewFrame'
import type { PreviewFrameHandle, PreviewMode } from '../components/PreviewFrame'
import CompliancePanel from '../components/CompliancePanel'
import VersionHistoryDrawer from '../components/VersionHistoryDrawer'
import TemplateLibraryPanel from '../components/TemplateLibraryPanel'
import AIImageGenerationModal from '../components/AIImageGenerationModal'
import { documentsApi } from '../api/documents'
import { modelsApi } from '../api/models'
import { aiProvidersApi } from '../api/aiProviders'
import { complianceApi } from '../api/compliance'
import { wechatAccountsApi } from '../api/wechatAccounts'
import { cancelChatRun, chatApi, reaskDocumentConflictFromError, startChatRun, streamChatRunEvents } from '../api/chat'
import type { ReaskConflictResolution, ThinkingEffort, ThinkingMode } from '../api/chat'
import { ApiError } from '../api/client'
import type { AIModelItem, AssistantTurnBlock, ChatContextStats, ChatImageAttachment, ChatMessageItem, ChatSessionItem, ChatUserQuestion, ComplianceReport, GzhThemeProposal, LayoutReferenceImitationStrength, LayoutReferencePreview, ReasoningTrace, SelectedElementContext, TemplateItem, ToolExecution, VisibilitySettings, WeChatArticleMetadata, WeChatAvailableAccount } from '../types'
import { sanitizeSelectedElement, sanitizeSelectedElements } from '../utils/selectedElements'
import { formatWeChatImageSize, prepareWeChatBodyImage } from '../utils/wechatBodyImage'
import { clearChatComposerDraft, clearChatComposerDraftForRequest, readChatComposerDraft, writeChatComposerDraft } from '../utils/chatComposerDraft'
import { moveQueuedChatItem, updateQueuedChatContent } from '../utils/chatQueue'
import { useAuthStore } from '../store/authStore'

const CodeViewer = lazy(() => import('../components/CodeViewer'))
const LayoutImitationModal = lazy(() => import('../components/LayoutImitationModal'))
const SourceDocumentModal = lazy(() => import('../components/SourceDocumentModal'))
const ThemeGalleryModal = lazy(() => import('../components/ThemeGalleryModal'))
const WeChatDraftModal = lazy(() => import('../components/WeChatDraftModal'))
const DocumentShareModal = lazy(() => import('../components/DocumentShareModal'))

type CenterView = 'preview' | 'code'
type MobileWorkspace = 'chat' | CenterView
const STREAM_RENDER_INTERVAL_MS = 48
const MAX_STREAM_RECONNECT_ATTEMPTS = 12
const MIN_CHAT_PANE_WIDTH = 300
const MIN_CENTER_PANE_WIDTH = 440
const MIN_TOUCH_CENTER_PANE_WIDTH = 320
const MIN_RESOURCE_PANE_WIDTH = 260
const COLUMN_RESIZER_WIDTH = 8
const AUTO_SAVE_DELAY_MS = 5000
const USER_QUESTION_ACTIVITY_THROTTLE_MS = 10_000
const LAST_SELECTED_MODEL_STORAGE_KEY_PREFIX = 'yibanpaiban-last-selected-model'

type ComplianceButtonStatus = 'unknown' | 'checking' | 'success' | 'warning' | 'error'

type ReaskConflictState = ReaskConflictNotice & { currentChecksum?: string }

interface QueuedChatRequest extends QueuedChatMessage {
  sessionId: number
  references: SelectedElementContext[]
  images: ChatImageAttachment[]
  modelId: number
  thinkingMode: ThinkingMode
  thinkingEffort: ThinkingEffort
}

interface ChatRunOptions {
  modelId: number
  thinkingMode: ThinkingMode
  thinkingEffort: ThinkingEffort
}

function getComplianceButtonStatus(
  report: ComplianceReport | null,
  loading: boolean,
): ComplianceButtonStatus {
  if (loading) return 'checking'
  if (!report) return 'unknown'
  if (report.hasError) return 'error'
  if (report.hasWarning) return 'warning'
  return 'success'
}

function getComplianceButtonLabel(status: ComplianceButtonStatus): string {
  switch (status) {
    case 'checking':
      return '正在检测合规性'
    case 'success':
      return '合规检测通过'
    case 'warning':
      return '合规检测存在潜在警告'
    case 'error':
      return '合规检测存在严重错误'
    default:
      return '尚未完成合规检测'
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

function startThinkingBlock(blocks: AssistantTurnBlock[], occurredAtMs = Date.now()): AssistantTurnBlock[] {
  const last = blocks.at(-1)
  if (last?.type === 'thought' && last.state === 'active') return blocks
  return [
    ...finishActiveTextBlock(blocks, occurredAtMs),
    {
      id: `thought-${blocks.length + 1}`,
      type: 'thought',
      state: 'active',
      content: '',
      duration_ms: null,
      started_at_ms: occurredAtMs,
      tool: null,
    },
  ]
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

function waitForReconnect(attempt: number, signal: AbortSignal): Promise<void> {
  const delay = Math.min(5000, 400 * 2 ** (attempt - 1))
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(cleanupAndResolve, delay)
    const abort = () => {
      window.clearTimeout(timer)
      cleanup()
      reject(new DOMException('请求已取消', 'AbortError'))
    }
    const cleanup = () => signal.removeEventListener('abort', abort)
    function cleanupAndResolve() {
      cleanup()
      resolve()
    }
    if (signal.aborted) {
      abort()
      return
    }
    signal.addEventListener('abort', abort, { once: true })
  })
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
  const [wechatMetadata, setWechatMetadata] = useState<WeChatArticleMetadata>({
    title: '', author: '', digest: '', content_source_url: '', cover_url: '',
    pic_crop_235_1: '', pic_crop_1_1: '', need_open_comment: false, only_fans_can_comment: false,
  })
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
  const [aiImageModalOpen, setAiImageModalOpen] = useState(false)

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
  const [reasoningTrace, setReasoningTrace] = useState<ReasoningTrace>({ status: 'idle', content: '', detail: '' })

  const [messages, setMessages] = useState<ChatMessageItem[]>([])
  const [chatSessions, setChatSessions] = useState<ChatSessionItem[]>([])
  const [activeChatSessionId, setActiveChatSessionId] = useState<number | null>(null)
  const [hiddenHistory, setHiddenHistory] = useState<ChatMessageItem[]>([])
  const [streaming, setStreaming] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [toolActivities, setToolActivities] = useState<ToolExecution[]>([])
  const [streamBlocks, setStreamBlocks] = useState<AssistantTurnBlock[]>([])
  const [streamNotice, setStreamNotice] = useState<ChatRunNotice | null>(null)
  const [conversationError, setConversationError] = useState<string | null>(null)
  const [chatSubmitting, setChatSubmitting] = useState(false)
  const [queuedChatRequests, setQueuedChatRequests] = useState<QueuedChatRequest[]>([])
  const [pendingUserQuestion, setPendingUserQuestion] = useState<ChatUserQuestion | null>(null)
  const [questionSubmitting, setQuestionSubmitting] = useState(false)
  const [reaskConflict, setReaskConflict] = useState<ReaskConflictState | null>(null)
  const [resolvingReaskConflict, setResolvingReaskConflict] = useState(false)

  const [centerView, setCenterView] = useState<CenterView>('preview')
  const [codeViewMounted, setCodeViewMounted] = useState(false)
  const [mobileWorkspace, setMobileWorkspace] = useState<MobileWorkspace>('preview')
  const [previewMode, setPreviewMode] = useState<PreviewMode>('browse')
  const [previewBrightness, setPreviewBrightness] = useState(100)
  const [editHistoryState, setEditHistoryState] = useState({ canUndo: false, canRedo: false })
  const [selectedElements, setSelectedElements] = useState<SelectedElementContext[]>([])
  const [attachedTemplates, setAttachedTemplates] = useState<TemplateItem[]>([])
  const [templateCollection, setTemplateCollection] = useState<{ id: number; html: string } | null>(null)
  const [hasPreviewCaret, setHasPreviewCaret] = useState(false)
  const [pendingReaskMessageId, setPendingReaskMessageId] = useState<number | null>(null)
  const [complianceDrawerOpen, setComplianceDrawerOpen] = useState(false)
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false)
  const [layoutImitationOpen, setLayoutImitationOpen] = useState(false)
  const [versionRefreshToken, setVersionRefreshToken] = useState(0)
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null)
  const [complianceLoading, setComplianceLoading] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const activeRunRef = useRef<string | null>(null)
  const resumedRunRef = useRef<string | null>(null)
  const resumeHandlerRef = useRef<((runId: string, sessionId?: number) => Promise<void>) | null>(null)
  const questionAnswerRequestRef = useRef<{
    questionId: string
    answerKey: string
    clientRequestId: string
  } | null>(null)
  const questionActivityRef = useRef<{ questionId: string; lastSentAt: number } | null>(null)
  const questionTimeoutRecoveryRef = useRef<string | null>(null)
  const complianceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const columnsRef = useRef<HTMLDivElement>(null)
  const resizeCleanupRef = useRef<(() => void) | null>(null)
  const htmlRef = useRef('')
  const draftHtmlRef = useRef('')
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRequestRef = useRef<Promise<string | null> | null>(null)
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
  const versionCopyDefaults = useMemo(() => ({ group_id: documentGroupId, ...documentVisibility }), [documentGroupId, documentVisibility])

  useEffect(() => () => resizeCleanupRef.current?.(), [])

  const cancelAutoSave = useCallback(() => {
    if (!autoSaveTimerRef.current) return
    clearTimeout(autoSaveTimerRef.current)
    autoSaveTimerRef.current = null
  }, [])

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
    if (!contextDraft.trim()) {
      if (saved?.phase === 'editing' || saved?.phase === 'retry') clearChatComposerDraft(docId, activeChatSessionId)
      return
    }
    const retainRetryIdentity = saved?.phase === 'retry'
      && saved.message === contextDraft
      && saved.reaskFromMessageId === pendingReaskMessageId
    writeChatComposerDraft(docId, activeChatSessionId, {
      message: contextDraft,
      reaskFromMessageId: pendingReaskMessageId,
      phase: retainRetryIdentity ? 'retry' : 'editing',
      ...(retainRetryIdentity && saved.clientRequestId ? { clientRequestId: saved.clientRequestId } : {}),
    })
  }, [activeChatSessionId, chatSubmitting, contextDraft, docId, loading, pendingReaskMessageId])

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

  const runComplianceCheck = useCallback(async (content: string) => {
    setComplianceLoading(true)
    try {
      const report = await complianceApi.check(content)
      setCompliance(report)
    } catch {
      // 合规检测失败不阻断编辑
    } finally {
      setComplianceLoading(false)
    }
  }, [])

  const scheduleComplianceCheck = useCallback(
    (content: string) => {
      if (complianceTimerRef.current) clearTimeout(complianceTimerRef.current)
      setCompliance(null)
      complianceTimerRef.current = setTimeout(() => runComplianceCheck(content), 600)
    },
    [runComplianceCheck],
  )

  const loadDocument = useCallback(async () => {
    if (!docId || Number.isNaN(docId)) return
    setLoading(true)
    try {
      const [doc, sessions, modelList] = await Promise.all([
        documentsApi.get(docId),
        chatApi.listSessions(docId),
        modelsApi.list(),
      ])
      const activeSession = sessions.find((item) => !item.is_archived) ?? sessions[0]
      const msgs = activeSession ? await chatApi.listMessages(docId, activeSession.id) : []
      const restoredComposerDraft = activeSession ? await resolveStoredComposerDraft(docId, activeSession.id) : null
      setTitle(doc.title)
      setHasSourceFile(doc.has_source_file)
      setDocumentGroupId(doc.group_id)
      setDocumentVisibility({
        visibility_mode: doc.visibility_mode,
        allowed_user_ids: doc.allowed_user_ids,
        allowed_group_ids: doc.allowed_group_ids,
      })
      setWechatMetadata(doc.wechat_metadata)
      applyExternalHtml(doc.current_html)
      setPreviewRevision((value) => value + 1)
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
      setMessages(msgs)
      setChatSessions(sessions)
      setActiveChatSessionId(activeSession?.id ?? null)
      setAttachedTemplates(activeSession?.attached_templates ?? [])
      setComposerTemplates([])
      setContextDraft(restoredComposerDraft?.message ?? '')
      setPendingReaskMessageId(restoredComposerDraft?.reaskFromMessageId ?? null)
      setHiddenHistory([])
      setModels(modelList)
      const lastSelectedModelId = getLastSelectedModelId(currentUser?.id)
      const lastSelectedModel = modelList.find((model) => model.id === lastSelectedModelId)
      const defaultModel = modelList.find((m) => m.is_default) ?? modelList[0]
      if (lastSelectedModel) {
        setModelId(lastSelectedModel.id)
      } else {
        if (lastSelectedModelId !== null) clearLastSelectedModelId(currentUser?.id)
        setModelId(defaultModel?.id ?? null)
      }
      scheduleComplianceCheck(doc.current_html)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载文档失败')
      navigate('/')
    } finally {
      setLoading(false)
    }
  }, [applyExternalHtml, currentUser?.id, docId, navigate, resolveStoredComposerDraft, scheduleComplianceCheck])

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
    loadDocument()
    return () => {
      abortRef.current?.abort()
      if (complianceTimerRef.current) clearTimeout(complianceTimerRef.current)
      cancelAutoSave()
    }
  }, [cancelAutoSave, loadDocument])

  useEffect(() => {
    if (!docId || Number.isNaN(docId) || !modelId || !activeChatSessionId || activeChatSession?.is_archived) {
      setContextStats(null)
      return
    }
    if (streaming) return
    let active = true
    const timer = window.setTimeout(() => {
      void chatApi.previewContext(
        docId,
        modelId,
        activeChatSessionId,
        contextDraft,
        selectedElements,
        chatImages.map((item) => item.id),
        attachedTemplates.map((item) => item.id),
      )
        .then((stats) => {
          if (active) setContextStats(stats)
        })
        .catch(() => {
          if (active) setContextStats(null)
        })
    }, contextDraft || selectedElements.length > 0 || chatImages.length > 0 || attachedTemplates.length > 0 ? 300 : 0)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [activeChatSession, activeChatSessionId, attachedTemplates, chatImages, contextDraft, docId, messages.length, modelId, selectedElements, streaming])

  const handleImageUpload = useCallback(async (file: File): Promise<string> => {
    if (!docId) throw new Error('文档不存在')
    try {
      const prepared = await prepareWeChatBodyImage(file)
      const result = await documentsApi.uploadImage(docId, prepared.file)
      if (prepared.wasCompressed) {
        message.info(`图片已在本地压缩：${formatWeChatImageSize(prepared.originalSize)} -> ${formatWeChatImageSize(prepared.file.size)}`)
      }
      return result.url
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '图片上传失败')
      throw err
    }
  }, [docId])

  const persistDraftHtml = useCallback(async (showSuccess = false, saveLatest = true): Promise<string | null> => {
    if (!docId) return null
    cancelAutoSave()

    // 同一文档同一时刻仅保存一笔。显式保存和发送前保存会继续写入最新草稿；
    // 自动保存只落当前快照，后续输入交给新的空闲计时器处理。
    while (true) {
      const inFlight = saveRequestRef.current
      if (inFlight) {
        const saved = await inFlight
        if (saved === null) return null
        if (!saveLatest) return saved
        continue
      }

      const snapshot = draftHtmlRef.current
      if (snapshot === htmlRef.current) {
        if (showSuccess) message.success('预览修改已保存')
        return htmlRef.current
      }

      const request = (async (): Promise<string | null> => {
        setSaving(true)
        try {
          const patch = {
            ...buildHtmlSplice(htmlRef.current, snapshot),
            base_checksum: await sha256(htmlRef.current),
          }
          await documentsApi.patchContent(docId, patch)
          htmlRef.current = snapshot
          setHtml(snapshot)

          // 用户在请求中继续编辑时保留新草稿，下一轮循环会自动保存它。
          if (draftHtmlRef.current === snapshot) {
            draftHtmlRef.current = snapshot
            setDraftHtml(snapshot)
            runComplianceCheck(snapshot)
          }
          setPreviewRevision((value) => value + 1)
          setVersionRefreshToken((value) => value + 1)
          return snapshot
        } catch (err) {
          message.error(err instanceof ApiError ? String(err.detail) : '保存失败')
          return null
        } finally {
          setSaving(false)
        }
      })()

      saveRequestRef.current = request
      const saved = await request
      if (saveRequestRef.current === request) saveRequestRef.current = null
      if (saved === null) return null
      if (!saveLatest) return saved
    }
  }, [cancelAutoSave, docId, runComplianceCheck])

  const scheduleAutoSave = useCallback(() => {
    cancelAutoSave()
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      void persistDraftHtml(false, false)
    }, AUTO_SAVE_DELAY_MS)
  }, [cancelAutoSave, persistDraftHtml])

  const handleHtmlChange = useCallback((next: string) => {
    if (streaming || localizingArticleImages || next === draftHtmlRef.current) return
    draftHtmlRef.current = next
    setDraftHtml(next)
    scheduleComplianceCheck(next)
    scheduleAutoSave()
  }, [localizingArticleImages, scheduleAutoSave, scheduleComplianceCheck, streaming])

  const handleAppendTemplate = useCallback(async (template: TemplateItem) => {
    if (!docId || streaming || saving || materializingTemplateImages || localizingArticleImages) return
    setMaterializingTemplateImages(true)
    try {
      const result = await documentsApi.materializeTemplateImages(docId, template.id)
      const inserted = previewFrameRef.current?.insertTemplateHtml(result.html, 'append')
      if (!inserted) {
        message.error('画布尚未准备好，无法添加模板')
        return
      }
      message.success(result.localized_count ? `已转存 ${result.localized_count} 张图片并添加「${template.name}」` : `已将「${template.name}」添加到文末`)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '组件图片转存失败，未插入文章')
    } finally {
      setMaterializingTemplateImages(false)
    }
  }, [docId, localizingArticleImages, materializingTemplateImages, saving, streaming])

  const handleInsertTemplateAtCaret = useCallback(async (template: TemplateItem) => {
    if (!docId || streaming || saving || materializingTemplateImages || localizingArticleImages) return
    setMaterializingTemplateImages(true)
    try {
      const result = await documentsApi.materializeTemplateImages(docId, template.id)
      const inserted = previewFrameRef.current?.insertTemplateHtml(result.html, 'caret')
      if (!inserted) {
        setHasPreviewCaret(false)
        message.warning('请在直接编辑模式中将真实文本光标放到画布内，再插入模板')
        return
      }
      message.success(result.localized_count ? `已转存 ${result.localized_count} 张图片并插入「${template.name}」` : `已将「${template.name}」插入光标处`)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '组件图片转存失败，未插入文章')
    } finally {
      setMaterializingTemplateImages(false)
    }
  }, [docId, localizingArticleImages, materializingTemplateImages, saving, streaming])

  const handleLocalizeArticleImages = useCallback(async () => {
    if (!docId || streaming || saving || materializingTemplateImages || localizingArticleImages) return
    setLocalizingArticleImages(true)
    try {
      previewFrameRef.current?.flushPendingChange()
      if (await persistDraftHtml(false) === null) return
      const result = await documentsApi.localizeExternalImages(docId)
      applyExternalHtml(result.html)
      setPreviewRevision((value) => value + 1)
      setVersionRefreshToken((value) => value + 1)
      scheduleComplianceCheck(result.html)
      message.success(result.localized_count ? `已转存 ${result.localized_count} 张外链图片` : '未发现需要转存的外链图片')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '文章图片转存失败，正文未修改')
    } finally {
      setLocalizingArticleImages(false)
    }
  }, [applyExternalHtml, docId, localizingArticleImages, materializingTemplateImages, persistDraftHtml, saving, scheduleComplianceCheck, streaming])

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
        || streaming
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
  }, [centerView, saving, streaming])

  const applySessionResourceContext = useCallback((updated: ChatSessionItem) => {
    setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
    if (updated.id === activeChatSessionId) {
      const nextTemplates = updated.attached_templates ?? []
      setAttachedTemplates(nextTemplates)
      setComposerTemplates((items) => {
        const availableIds = new Set(nextTemplates.map((item) => item.id))
        return items.filter((item) => availableIds.has(item.id))
      })
    }
  }, [activeChatSessionId])

  const toggleAttachedTemplate = useCallback(async (template: TemplateItem) => {
    if (!docId || !activeChatSessionId || activeChatSession?.is_archived) return
    const isAttached = attachedTemplates.some((item) => item.id === template.id)
    const next = isAttached
      ? attachedTemplates.filter((item) => item.id !== template.id)
      : [...attachedTemplates, template]
    if (next.length > 6) {
      message.warning('每个对话最多附加 6 个模板')
      return
    }
    try {
      const updated = await chatApi.replaceTemplateAttachments(docId, activeChatSessionId, next.map((item) => item.id))
      applySessionResourceContext(updated)
      setComposerTemplates((items) => (
        isAttached
          ? items.filter((item) => item.id !== template.id)
          : items.some((item) => item.id === template.id) ? items : [...items, template]
      ))
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '更新对话组件失败')
    }
  }, [activeChatSession?.is_archived, activeChatSessionId, applySessionResourceContext, attachedTemplates, docId])

  const removeAttachedTemplate = useCallback(async (templateId: number) => {
    if (!docId || !activeChatSessionId || activeChatSession?.is_archived) return
    try {
      const updated = await chatApi.removeTemplateAttachment(docId, activeChatSessionId, templateId)
      applySessionResourceContext(updated)
      setComposerTemplates((items) => items.filter((item) => item.id !== templateId))
    } catch (err) {
      setAttachedTemplates((items) => [...items])
      message.error(err instanceof ApiError ? String(err.detail) : '移除对话组件失败')
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
    previewFrameRef.current?.flushPendingChange()
    await persistDraftHtml(true)
  }

  const handleSaveTitle = async () => {
    if (!docId) return
    try {
      await documentsApi.update(docId, { title })
      setVersionRefreshToken((value) => value + 1)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '标题保存失败')
    }
  }

  const handleChatImageUpload = useCallback((files: File[]) => {
    if (!docId || chatImageUploadInProgressRef.current) return
    const selectedModel = models.find((item) => item.id === modelId)
    if (!selectedModel?.is_multimodal) {
      message.warning('当前模型未启用图片交互')
      return
    }
    const remaining = Math.max(0, 5 - chatImages.length)
    const candidates = files.slice(0, remaining)
    if (files.length > remaining) message.warning('每条消息最多附加 5 张图片')
    const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
    const validCandidates = candidates.filter((file) => {
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
    if (!validCandidates.length) return
    const draftEpoch = chatImageDraftEpochRef.current
    chatImageUploadInProgressRef.current = true
    setChatImageUploading(true)
    const uploadDocumentId = docId
    void Promise.allSettled(validCandidates.map((file) => chatApi.uploadImage(uploadDocumentId, file)))
      .then((results) => {
        const attachments = results
          .filter((result): result is PromiseFulfilledResult<ChatImageAttachment> => result.status === 'fulfilled')
          .map((result) => result.value)
        if (results.some((result) => result.status === 'rejected')) {
          message.error('部分聊天图片上传失败')
        }
        if (!attachments.length) return
        const currentModel = modelsRef.current.find((item) => item.id === modelIdRef.current)
        if (
          draftEpoch !== chatImageDraftEpochRef.current
          || documentIdRef.current !== uploadDocumentId
          || !currentModel?.is_multimodal
        ) {
          void Promise.allSettled(attachments.map((attachment) => chatApi.deleteImage(uploadDocumentId, attachment.id)))
          return
        }
        chatImageDocumentIdRef.current = uploadDocumentId
        setChatImages((items) => [...items, ...attachments].slice(0, 5))
      })
      .catch((err) => {
        message.error(err instanceof ApiError ? String(err.detail) : '聊天图片上传失败')
      })
      .finally(() => {
        chatImageUploadInProgressRef.current = false
        setChatImageUploading(false)
      })
  }, [chatImages.length, docId, modelId, models])

  const handleRemoveChatImage = useCallback((attachment: ChatImageAttachment) => {
    setChatImages((items) => items.filter((item) => item.id !== attachment.id))
    if (docId) {
      void chatApi.deleteImage(docId, attachment.id).catch(() => {
        // The attachment may have been claimed by a concurrent send; history remains authoritative.
      })
    }
  }, [docId])

  const discardDraftChatImages = useCallback((attachments: ChatImageAttachment[] = chatImages) => {
    chatImageDraftEpochRef.current += 1
    if (!attachments.length) return
    setChatImages([])
    const attachmentDocumentId = chatImageDocumentIdRef.current ?? docId
    chatImageDocumentIdRef.current = null
    if (attachmentDocumentId) {
      void Promise.allSettled(attachments.map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
  }, [chatImages, docId])

  useEffect(() => {
    const previousDocumentId = observedDocumentIdRef.current
    if (previousDocumentId !== null && previousDocumentId !== docId) {
      chatImageDraftEpochRef.current += 1
    }
    if (previousDocumentId !== null && previousDocumentId !== docId && chatImagesRef.current.length) {
      const attachments = chatImagesRef.current
      const attachmentDocumentId = chatImageDocumentIdRef.current ?? previousDocumentId
      chatImageDocumentIdRef.current = null
      setChatImages([])
      void Promise.allSettled(attachments.map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
    if (previousDocumentId !== null && previousDocumentId !== docId && queuedChatRequestsRef.current.length) {
      const queuedRequests = queuedChatRequestsRef.current
      queuedChatRequestsRef.current = []
      setQueuedChatRequests([])
      void Promise.allSettled(
        queuedRequests.flatMap((request) => request.images.map((image) => chatApi.deleteImage(previousDocumentId, image.id))),
      )
    }
    observedDocumentIdRef.current = docId || null
  }, [docId])

  useEffect(() => () => {
    const attachmentDocumentId = chatImageDocumentIdRef.current
    const attachments = chatImagesRef.current
    if (attachmentDocumentId && attachments.length) {
      void Promise.allSettled(attachments.map((attachment) => chatApi.deleteImage(attachmentDocumentId, attachment.id)))
    }
    const queuedRequests = queuedChatRequestsRef.current
    const queuedDocumentId = documentIdRef.current
    if (queuedDocumentId && queuedRequests.length) {
      void Promise.allSettled(
        queuedRequests.flatMap((request) => request.images.map((image) => chatApi.deleteImage(queuedDocumentId, image.id))),
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
  ) => {
    const sessionId = sessionIdOverride ?? activeChatSessionId
    const requestModelId = runOptions?.modelId ?? modelId
    const requestThinkingMode = runOptions?.thinkingMode ?? thinkingMode
    const requestThinkingEffort = runOptions?.thinkingEffort ?? thinkingEffort
    if (!docId || !sessionId || (!requestModelId && !existingRunId)) return
    if (!existingRunId && chatSessions.find((item) => item.id === sessionId)?.is_archived) {
      message.warning('请先恢复该对话后再继续发送')
      return
    }
    if (!existingRunId && chatStartInProgressRef.current) return
    const isNewRun = !existingRunId
    let startFinished = !isNewRun
    const finishStarting = () => {
      if (startFinished) return
      startFinished = true
      chatStartInProgressRef.current = false
      setChatSubmitting(false)
    }
    if (isNewRun) {
      chatStartInProgressRef.current = true
      setChatSubmitting(true)
    }
    if (!existingRunId) previewFrameRef.current?.flushPendingChange()
    const sanitizedAttachedElements = sanitizeSelectedElements(attachedElements)
    const attachedTemplateRefs = attachedTemplates.map((template) => ({ id: template.id, name: template.name }))
    const sentDraftImages = existingRunId ? [] : attachedImages
    const sentImageIds = new Set(sentDraftImages.map((item) => item.id))
    let sentImagesDetached = false
    const detachSentDraftImages = () => {
      if (!sentImageIds.size || sentImagesDetached) return
      sentImagesDetached = true
      chatImagesRef.current = chatImagesRef.current.filter((item) => !sentImageIds.has(item.id))
      setChatImages((items) => items.filter((item) => !sentImageIds.has(item.id)))
    }
    let sentImagesRestored = false
    const restoreSentDraftImages = () => {
      if (sentImagesRestored || !sentDraftImages.length) return
      sentImagesRestored = true
      const merged = [...chatImagesRef.current]
      const presentIds = new Set(merged.map((item) => item.id))
      sentDraftImages.forEach((item) => {
        if (!presentIds.has(item.id) && merged.length < 5) merged.push(item)
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
        return
      }
      // The server restores the selected snapshot and archives the abandoned
      // suffix atomically with this new Agent run.
      persistedHtml = html
    } else {
      // Agent 从数据库读取最新 HTML，预览/源码里的手工草稿必须先保存，避免模型基于旧稿操作。
      persistedHtml = await persistDraftHtml()
    }
    if (persistedHtml === null) {
      restoreSentDraftImages()
      finishStarting()
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

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
    if (isNewRun) {
      setStreamText('')
      setToolActivities([])
      setStreamBlocks([])
      setReasoningTrace({ status: 'idle', content: '', detail: '' })
    }
    setStreamNotice(null)
    setConversationError(null)
    setThinkingStatus(isNewRun ? null : '正在继续处理排版…')

    // A resumed run starts its SSE subscription after the question event, so
    // retain the locally rendered prefix instead of waiting for events that
    // will never be replayed.
    let accumulated = isNewRun ? '' : streamText
    let latestHtml = persistedHtml
    let activeTools: ToolExecution[] = isNewRun ? [] : toolActivities
    let activeBlocks: AssistantTurnBlock[] = isNewRun ? [] : streamBlocks
    let activeReasoning: ReasoningTrace = isNewRun
      ? { status: 'idle', content: '', detail: '' }
      : reasoningTrace
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
    let pausedForUserQuestion = false
    let streamRenderTimer: number | null = null
    let streamRenderFrame: number | null = null
    let lastStreamRenderAt = 0
    const savedComposerDraft = isNewRun ? readChatComposerDraft(docId, sessionId) : null
    let reusableRequestId = savedComposerDraft?.phase === 'retry'
      && savedComposerDraft.message === text
      && savedComposerDraft.reaskFromMessageId === reaskFromMessageId
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
            reaskFromMessageId,
            phase: 'retry',
          })
        }
      } catch {
        // Keep the key when status reconciliation is unavailable; the POST
        // still needs idempotency protection if the original request exists.
      }
    }
    const clientRequestId = existingRunId ? null : reusableRequestId ?? createClientRequestId()
    const submittedDraft = isNewRun
      ? { message: text, reaskFromMessageId, clientRequestId: clientRequestId as string }
      : null
    if (submittedDraft) {
      writeChatComposerDraft(docId, sessionId, { ...submittedDraft, phase: 'starting' })
    }
    const restoreSubmittedDraft = (withFreshRequestId = false) => {
      if (!submittedDraft) return
      const storedDraft = readChatComposerDraft(docId, sessionId)
      const hasNewerDraft = Boolean(
        storedDraft?.message.trim()
        && storedDraft.clientRequestId !== submittedDraft.clientRequestId,
      )
      if (hasNewerDraft) return
      setContextDraft(submittedDraft.message)
      setPendingReaskMessageId(submittedDraft.reaskFromMessageId)
      writeChatComposerDraft(
        docId,
        sessionId,
        withFreshRequestId
          ? {
              message: submittedDraft.message,
              reaskFromMessageId: submittedDraft.reaskFromMessageId,
              phase: 'retry',
            }
          : { ...submittedDraft, phase: 'retry' },
      )
    }

    const commitStreamRender = () => {
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
              undefined,
              reaskFromMessageId ?? undefined,
              reaskConflictResolution,
              controller.signal,
            )
          } catch (startError) {
            // A timeout or an aborted browser request is ambiguous: the
            // server may have committed the run before its response was cut.
            // Resolve through the idempotency key before touching optimistic UI.
            if (startError instanceof ApiError) throw startError
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
        setContextDraft((current) => current === submittedDraft.message ? '' : current)
        setComposerTemplates([])
        detachSentDraftImages()
      }
      if (optimisticMessageId !== null && 'user_message_id' in run) {
        const persistedMessageId = run.user_message_id
        setMessages((previous) => previous.map((item) => (
          item.id === optimisticMessageId ? { ...item, id: persistedMessageId } : item
        )))
      }
      if ('reask_activation' in run && run.reask_activation) {
        latestHtml = run.reask_activation.current_html
        applyExternalHtml(latestHtml)
        setPreviewRevision((value) => value + 1)
        setMessages(await chatApi.listMessages(docId, sessionId))
        setPendingReaskMessageId(null)
        scheduleComplianceCheck(latestHtml)
      }
      runId = run.run_id
      activeRunRef.current = run.run_id

      if (controller.signal.aborted) {
        try {
          await cancelChatRun(docId, run.run_id)
        } catch {
          // The persisted run remains discoverable and the next page resume
          // will continue cancellation/reconciliation if this request failed.
        }
        if (abortRef.current === controller) {
          const [freshDocument, freshMessages] = await Promise.all([
            documentsApi.get(docId),
            chatApi.listMessages(docId, sessionId),
          ])
          applyExternalHtml(freshDocument.current_html)
          setPreviewRevision((value) => value + 1)
          setMessages(freshMessages)
          scheduleComplianceCheck(freshDocument.current_html)
        }
        completed = true
      }

      let reconnectAttempts = 0
      let pendingTransientContent = ''
      let pendingTransientReasoning = ''
      while (!completed) {
        try {
          for await (const received of streamChatRunEvents(docId, run.run_id, lastSequence, controller.signal)) {
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
        if (evt.event !== 'heartbeat') reconnectAttempts = 0
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
          const existingIndex = activeTools.findIndex((item) => item.id === toolId || item.id === replacesId)
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
          if (evt.data.html) {
            latestHtml = evt.data.html
            applyExternalHtml(latestHtml)
            setPreviewRevision((value) => value + 1)
            scheduleComplianceCheck(latestHtml)
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
              status: evt.data.thinking.applied ? 'thinking' : 'unavailable',
              content: '',
              detail: evt.data.thinking.detail,
            }
            if (evt.data.thinking.applied) {
              activeBlocks = startThinkingBlock(activeBlocks, eventOccurredAtMs)
            }
          }
          flushStreamRender()
        } else if (evt.event === 'thinking_capability_fallback') {
          handleThinkingCapabilityFallback(evt.data)
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
          const retryDelay = evt.data.retry_after_seconds ?? evt.data.delay_seconds
          const returnedError = evt.data.detail?.trim() || retryReason
          const errorCode = evt.data.reason?.trim()
          const remainingAttempts = Math.max(0, evt.data.max_attempts - evt.data.attempt)
          const retrySchedule = `${retryDelay} 秒后重试（第 ${evt.data.attempt}/${evt.data.max_attempts} 次，剩余 ${remainingAttempts} 次）`
          setStreamNotice({
            kind: 'retrying',
            title: '正在重新连接模型服务',
            detail: `${returnedError}；${retrySchedule}。${errorCode ? `（错误码：${errorCode}）` : ''}`,
            attempt: evt.data.attempt,
            maxAttempts: evt.data.max_attempts,
          })
          setThinkingStatus(`${retryReason}，${retryDelay} 秒后重试`)
        } else if (evt.event === 'context_stats') {
          setContextStats(evt.data)
        } else if (evt.event === 'heartbeat') {
          if (evt.data.phase === 'model_turn_started' && typeof evt.data.turn === 'number') {
            modelTurnCheckpoint = {
              turn: evt.data.turn,
              accumulated,
              tools: [...activeTools],
              blocks: [...activeBlocks],
              reasoning: { ...activeReasoning },
            }
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
            scheduleComplianceCheck(latestHtml)
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
          if (isNewRun && evt.data.run_status === 'failed') {
            restoreSubmittedDraft(true)
            setConversationError(evt.data.error_message || '对话请求失败')
          } else if (isNewRun) {
            clearChatComposerDraftForRequest(docId, sessionId, submittedDraft?.clientRequestId ?? '')
          }
          completed = true
          break
        } else if (evt.event === 'error') {
          setStreamNotice({ kind: 'error', title: '本轮执行失败', detail: evt.data.message })
          setThinkingStatus(null)
        }
      }
          if (!completed) throw new Error('输出连接已结束')
        } catch (err) {
          if ((err as Error).name === 'AbortError') throw err
          try {
            const runState = await chatApi.getRun(docId, run.run_id)
            if (['completed', 'cancelled', 'failed'].includes(runState.status)) {
              setThinkingStatus(null)
              const [freshDocument, freshMessages] = await Promise.all([
                documentsApi.get(docId),
                chatApi.listMessages(docId, sessionId),
              ])
              applyExternalHtml(freshDocument.current_html)
              setPreviewRevision((value) => value + 1)
              scheduleComplianceCheck(freshDocument.current_html)
              setMessages(freshMessages)
              if (runState.status === 'failed') {
                restoreSubmittedDraft(true)
              setConversationError(runState.error_message || '对话请求失败')
              } else if ((runState.status === 'completed' || runState.status === 'cancelled') && isNewRun) {
                clearChatComposerDraftForRequest(docId, sessionId, submittedDraft?.clientRequestId ?? '')
              }
              completed = true
              break
            }
          } catch (statusError) {
            if ((statusError as Error).name === 'AbortError') throw statusError
          }
          reconnectAttempts += 1
          if (reconnectAttempts > MAX_STREAM_RECONNECT_ATTEMPTS) {
            throw new Error('实时输出多次无法恢复，已停止等待。后台任务可能仍在执行，请刷新页面恢复连接或点击停止。')
          }
          setStreamNotice({
            kind: 'retrying',
            title: '正在恢复实时输出连接',
            detail: '后台 Agent 仍在执行，正在补拉遗漏的输出。',
            attempt: reconnectAttempts,
            maxAttempts: MAX_STREAM_RECONNECT_ATTEMPTS,
          })
          setThinkingStatus(null)
          await waitForReconnect(reconnectAttempts, controller.signal)
        }
      }

      // 流结束后重新拉取消息列表，与数据库记录对齐
      const freshMsgs = await chatApi.listMessages(docId, sessionId)
      const refreshedSessions = await chatApi.listSessions(docId)
      setMessages(freshMsgs)
      setChatSessions(refreshedSessions)
      if (sessionId === activeChatSessionId) {
        setAttachedTemplates(refreshedSessions.find((item) => item.id === sessionId)?.attached_templates ?? [])
      }
    } catch (err) {
      // A failed POST may leave only the client-side placeholder. It has no
      // server ID and must not be offered as a history branch for re-asking.
      if (!runId && optimisticMessageId !== null) {
        setMessages((previous) => previous.filter((item) => item.id !== optimisticMessageId))
      }
      if (!runId) restoreSentDraftImages()
      if ((err as Error).name !== 'AbortError') {
        const conflict = reaskDocumentConflictFromError(err)
        if (conflict && reaskFromMessageId !== null) {
          restoreSubmittedDraft()
          setReaskConflict({ kind: 'server', currentChecksum: conflict.current_checksum })
          setConversationError(null)
        } else {
          if (isNewRun) restoreSubmittedDraft()
          setConversationError(err instanceof ApiError ? String(err.detail) : '对话请求失败')
        }
        setThinkingStatus(null)
      }
    } finally {
      cancelStreamRender()
      finishStarting()
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
      },
    )
  }

  const enqueueChatRequest = (
    text: string,
    references: SelectedElementContext[],
    images: ChatImageAttachment[],
  ) => {
    if (!docId || !activeChatSessionId || !modelId) return
    const queuedRequest: QueuedChatRequest = {
      id: createClientRequestId(),
      content: text,
      sessionId: activeChatSessionId,
      references: sanitizeSelectedElements(references),
      images: [...images],
      modelId,
      thinkingMode,
      thinkingEffort,
    }
    setQueuedChatRequests((items) => [...items, queuedRequest])
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
    if (docId && queuedRequest?.images.length) {
      void Promise.allSettled(queuedRequest.images.map((image) => chatApi.deleteImage(docId, image.id)))
    }
  }, [docId])

  const updateQueuedChatRequest = useCallback((requestId: string, nextContent: string) => {
    const content = nextContent.trim()
    if (!content) return
    setQueuedChatRequests((items) => updateQueuedChatContent(items, requestId, content))
  }, [])

  const moveQueuedChatRequest = useCallback((fromIndex: number, toIndex: number) => {
    setQueuedChatRequests((items) => moveQueuedChatItem(items, fromIndex, toIndex))
  }, [])

  useEffect(() => {
    if (streaming || stopping || chatSubmitting || pendingUserQuestion) return
    const nextRequest = queuedChatRequests[0]
    if (!nextRequest || nextRequest.sessionId !== activeChatSessionId) return

    setQueuedChatRequests((items) => items.filter((item) => item.id !== nextRequest.id))
    queuedRequestStarterRef.current?.(nextRequest)
  }, [activeChatSessionId, chatSubmitting, pendingUserQuestion, queuedChatRequests, stopping, streaming])

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
    setPendingReaskMessageId(messageItem.id)

    const historyImages = (messageItem.image_attachments ?? []).slice(0, 5)
    if (!historyImages.length || !docId) return
    const selectedModel = modelsRef.current.find((item) => item.id === modelIdRef.current)
    if (!selectedModel?.is_multimodal) {
      message.warning('当前模型未启用图片交互，未恢复历史图片')
      return
    }

    const restoreEpoch = chatImageDraftEpochRef.current
    chatImageUploadInProgressRef.current = true
    setChatImageUploading(true)
    void Promise.allSettled(historyImages.map((image) => chatApi.duplicateImage(docId, image.id)))
      .then((results) => {
        const restored = results
          .filter((result): result is PromiseFulfilledResult<ChatImageAttachment> => result.status === 'fulfilled')
          .map((result) => result.value)
        if (results.some((result) => result.status === 'rejected')) {
          message.warning('部分历史图片恢复失败，请检查后再发送')
        }
        if (!restored.length) return
        if (restoreEpoch !== chatImageDraftEpochRef.current || documentIdRef.current !== docId) {
          void Promise.allSettled(restored.map((image) => chatApi.deleteImage(docId, image.id)))
          return
        }
        chatImageDocumentIdRef.current = docId
        chatImagesRef.current = restored
        setChatImages(restored)
      })
      .catch(() => {
        message.error('历史图片恢复失败，请稍后重试')
      })
      .finally(() => {
        chatImageUploadInProgressRef.current = false
        setChatImageUploading(false)
      })
  }, [discardDraftChatImages, docId])

  const handleDismissReaskConflict = useCallback(() => {
    if (resolvingReaskConflict) return
    setReaskConflict(null)
  }, [resolvingReaskConflict])

  const handleDiscardReaskConflict = () => {
    if (!reaskConflict || resolvingReaskConflict || !pendingReaskMessageId) return
    const retryText = contextDraft.trim() || (selectedElements.length > 0
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
      scheduleComplianceCheck(htmlRef.current)
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
    )
  }

  const handleAnswerUserQuestion = async (answer: UserQuestionAnswer) => {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting) return
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
      )
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
      setQuestionSubmitting(false)
      // A dropped response or a concurrent timeout can leave the browser
      // unsure whether its answer was accepted. The run record is authoritative
      // and lets us continue its original SSE stream when it already moved on.
      if (await handleUserQuestionTimeoutElapsed()) return
      setConversationError(err instanceof ApiError ? String(err.detail) : '提交排版偏好失败')
    }
  }

  const handleUserQuestionActivity = () => {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting) return
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
        // A failed activity request is ambiguous: the server may already have
        // accepted the timeout answer and resumed the run. Reconcile instead
        // of leaving an interactive-looking stale panel on screen.
        void handleUserQuestionTimeoutElapsed()
      })
  }

  async function handleUserQuestionTimeoutElapsed(): Promise<boolean> {
    const question = pendingUserQuestion
    if (!docId || !question || questionSubmitting || questionTimeoutRecoveryRef.current === question.id) return false
    questionTimeoutRecoveryRef.current = question.id
    try {
      const run = await chatApi.getRun(docId, question.run_id)
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
      setPendingUserQuestion(null)
      if (['completed', 'cancelled', 'failed'].includes(run.status)) {
        const [freshMessages, sessions] = await Promise.all([
          chatApi.listMessages(docId, run.session_id),
          chatApi.listSessions(docId),
        ])
        setMessages(freshMessages)
        setChatSessions(sessions)
        setAttachedTemplates(sessions.find((item) => item.id === run.session_id)?.attached_templates ?? [])
        setThinkingStatus(null)
        if (run.status === 'failed') setConversationError(run.error_message || '对话请求失败')
        return true
      }
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
      if (err instanceof ApiError && err.status === 409) return false
      setConversationError(err instanceof ApiError ? String(err.detail) : '检查提问超时状态失败')
      return false
    } finally {
      questionTimeoutRecoveryRef.current = null
    }
  }

  resumeHandlerRef.current = async (runId: string, sessionId?: number) => handleSendMessage('', [], runId, undefined, sessionId)

  const handleStopAgent = async () => {
    const runId = activeRunRef.current
    if (!docId || !runId) {
      abortRef.current?.abort()
      return
    }
    try {
      setStopping(true)
      setThinkingStatus('正在停止 Agent…')
      const cancelled = await cancelChatRun(docId, runId)
      if (cancelled.status === 'cancelled') {
        setPendingUserQuestion(null)
        setQuestionSubmitting(false)
        activeRunRef.current = null
        setMessages(await chatApi.listMessages(docId, cancelled.session_id))
        setThinkingStatus(null)
      }
    } catch (err) {
      setStopping(false)
      setConversationError(err instanceof ApiError ? String(err.detail) : '停止 Agent 失败')
    }
  }

  const selectChatSession = async (sessionId: number) => {
    if (!docId || streaming || pendingUserQuestion || sessionId === activeChatSessionId) return
    try {
      if (activeChatSessionId && contextDraft.trim()) {
        const current = readChatComposerDraft(docId, activeChatSessionId)
        writeChatComposerDraft(docId, activeChatSessionId, {
          message: contextDraft,
          reaskFromMessageId: pendingReaskMessageId,
          phase: current?.phase === 'retry' ? 'retry' : 'editing',
          ...(current?.phase === 'retry' && current.clientRequestId ? { clientRequestId: current.clientRequestId } : {}),
        })
      }
      const [sessionMessages, restoredComposerDraft] = await Promise.all([
        chatApi.listMessages(docId, sessionId),
        resolveStoredComposerDraft(docId, sessionId),
      ])
      setContextStats(null)
      discardDraftChatImages()
      setContextDraft(restoredComposerDraft?.message ?? '')
      setPendingReaskMessageId(restoredComposerDraft?.reaskFromMessageId ?? null)
      setSelectedElements([])
      setReaskConflict(null)
      setActiveChatSessionId(sessionId)
      setAttachedTemplates(chatSessions.find((item) => item.id === sessionId)?.attached_templates ?? [])
      setComposerTemplates([])
      setMessages(sessionMessages)
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
    if (!docId || streaming) return
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
      setChatSessions((items) => {
        const exists = items.some((item) => item.id === session.id)
        return exists ? items : [session, ...items]
      })
      setActiveChatSessionId(session.id)
      setAttachedTemplates(session.attached_templates ?? [])
      setComposerTemplates([])
      setMessages([])
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
    if (!docId || streaming) return
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
          chatApi.listMessages(docId, next.id),
          resolveStoredComposerDraft(docId, next.id),
        ])
        setActiveChatSessionId(next.id)
        setAttachedTemplates(next.attached_templates ?? [])
        setComposerTemplates([])
        setMessages(nextMessages)
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
    if (!docId || streaming) return
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
    if (!docId || !activeChatSession || streaming) return
    try {
      const updated = await chatApi.truncateSession(docId, activeChatSession.id)
      setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
      setMessages([])
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
    if (!docId || !activeChatSession || streaming) return
    try {
      const updated = await chatApi.restoreSessionContext(docId, activeChatSession.id)
      setChatSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
      setMessages(await chatApi.listMessages(docId, activeChatSession.id))
      setHiddenHistory([])
      setContextStats(null)
      message.success('历史已恢复到模型上下文')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '恢复上下文失败')
    }
  }

  const handleCompactChatContext = async (rebuild: boolean) => {
    if (!docId || !activeChatSession || !modelId || streaming) return
    setContextStats((current) => current ? { ...current, state: 'compacting' } : current)
    try {
      const stats = await chatApi.compactContext(docId, modelId, activeChatSession.id, rebuild)
      setContextStats(stats)
      if (stats.thinking_capability_fallback) {
        handleThinkingCapabilityFallback(stats.thinking_capability_fallback)
      }
      message.success(rebuild ? '已从完整历史重建上下文摘要' : '已压缩当前对话上下文')
    } catch (err) {
      setContextStats(null)
      message.error(err instanceof ApiError ? String(err.detail) : '上下文压缩失败，可稍后重试')
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
    if (!docId || loading || streaming) return
    let disposed = false
    void (async () => {
      try {
        const activeRun = await chatApi.getActiveRun(docId)
        if (!activeRun || disposed || resumedRunRef.current === activeRun.run_id) return
        resumedRunRef.current = activeRun.run_id
        if (activeRun.session_id !== activeChatSessionId) {
          setActiveChatSessionId(activeRun.session_id)
          setMessages(await chatApi.listMessages(docId, activeRun.session_id))
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
        await resumeHandlerRef.current?.(activeRun.run_id, activeRun.session_id)
      } catch (err) {
        if (!disposed) setConversationError(err instanceof ApiError ? String(err.detail) : '恢复 Agent 输出失败')
      }
    })()
    return () => {
      disposed = true
    }
  }, [activeChatSessionId, docId, loading, streaming])

  const handleVersionRestored = async (document: { title: string; current_html: string }) => {
    setTitle(document.title)
    applyExternalHtml(document.current_html)
    setPreviewRevision((value) => value + 1)
    setComposerTemplates([])
    setPendingReaskMessageId(null)
    if (docId && activeChatSessionId) clearChatComposerDraft(docId, activeChatSessionId)
    setContextDraft('')
    setCenterView('preview')
    scheduleComplianceCheck(document.current_html)
    setVersionRefreshToken((value) => value + 1)
  }

  const columnsStyle = (chatPaneWidth === null && resourcePaneWidth === null)
    ? undefined
    : ({
        ...(chatPaneWidth === null ? {} : { '--chat-pane-width': `${chatPaneWidth}px` }),
        ...(resourcePaneWidth === null ? {} : { '--resource-pane-width': `${resourcePaneWidth}px` }),
      } as CSSProperties)

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" description="加载排版工作台…" />
      </div>
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
  const resourceLibrary = (
    <TemplateLibraryPanel
      modelId={modelId}
      disabled={streaming || saving || materializingTemplateImages || localizingArticleImages}
      canInsertAtCaret={centerView === 'preview' && previewMode === 'edit' && hasPreviewCaret}
      attachedTemplateIds={attachedTemplates.map((item) => item.id)}
      themeContext={activeChatSession?.theme_context ?? null}
      onAppend={handleAppendTemplate}
      onInsertAtCaret={handleInsertTemplateAtCaret}
      onToggleAttach={toggleAttachedTemplate}
      onClearThemeContext={() => { void clearSessionThemeContext() }}
      collection={templateCollection}
      onCollectionHandled={handleTemplateCollection}
      onOpenThemeGallery={(themeKey) => {
        setResourceDrawerOpen(false)
        setThemeGalleryInitialKey(themeKey ?? null)
        setThemeGalleryOpen(true)
      }}
    />
  )

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
            disabled={streaming}
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
                disabled={streaming || saving || materializingTemplateImages || localizingArticleImages}
                onClick={() => setResourceDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="保存预览或源码中的手动修改">
              <Button
                aria-label="保存手动修改"
                className="editor-mobile-toolbar-action"
                icon={<SaveOutlined />}
                type={draftHtml !== html ? 'primary' : 'default'}
                disabled={streaming || saving || draftHtml === html}
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
                value={previewMode}
                disabled={streaming}
                onChange={(value) => setPreviewMode(value as PreviewMode)}
                options={[
                  { label: '浏览', value: 'browse' },
                  { label: <><SelectOutlined /> 选择</>, value: 'select' },
                  { label: <><EditOutlined /> 直接编辑</>, value: 'edit' },
                ]}
              />
            ) : (
              <Tooltip title="直接编辑仅在实时预览页可用">
                <Button aria-label="直接编辑" icon={<EditOutlined />} disabled />
              </Tooltip>
            )}
            {centerView === 'preview' && previewMode === 'edit' && (
              <>
                <Tooltip title="撤销（Ctrl+Z）">
                  <Button
                    aria-label="撤销"
                    icon={<UndoOutlined />}
                    disabled={streaming || saving || !editHistoryState.canUndo}
                    onClick={() => previewFrameRef.current?.undo()}
                  />
                </Tooltip>
                <Tooltip title="恢复（Ctrl+Y）">
                  <Button
                    aria-label="恢复"
                    icon={<RedoOutlined />}
                    disabled={streaming || saving || !editHistoryState.canRedo}
                    onClick={() => previewFrameRef.current?.redo()}
                  />
                </Tooltip>
                <Tooltip title="插入图片">
                  <Button
                    aria-label="插入图片"
                    icon={<PictureOutlined />}
                    disabled={streaming || saving}
                    onClick={() => previewFrameRef.current?.openImagePickerForInsert()}
                  />
                </Tooltip>
              </>
            )}
            <Tooltip title="AI 配图">
              <Button aria-label="AI 配图" icon={<PictureOutlined />} disabled={streaming || saving} onClick={() => setAiImageModalOpen(true)}>AI 配图</Button>
            </Tooltip>
            {centerView === 'preview' && (
              <>
                <Popover
                  title="预览亮度"
                  trigger="click"
                  content={(
                    <div className="preview-brightness-control">
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
                  <Tooltip title="调节预览亮度">
                    <Button
                      aria-label="调节预览亮度"
                      icon={<BulbOutlined />}
                      type={previewBrightness === 100 ? 'default' : 'primary'}
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
                disabled={streaming || saving}
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
                    disabled={streaming || saving || materializingTemplateImages || localizingArticleImages}
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
                  disabled={streaming || saving || wechatAccounts.length === 0}
                  onClick={() => setWechatDraftOpen(true)}
                />
              </Tooltip>
            )}
            <Tooltip title="保存预览或源码中的手动修改">
              <Button
                aria-label="保存手动修改"
                icon={<SaveOutlined />}
                type={draftHtml !== html ? 'primary' : 'default'}
                disabled={streaming || saving || draftHtml === html}
                loading={saving}
                onClick={handleSaveHtml}
              />
            </Tooltip>
            <Tooltip title={complianceButtonLabel}>
              <Button
                aria-label={`打开合规检测：${complianceButtonLabel}`}
                className={`compliance-status-trigger is-${complianceButtonStatus}`}
                icon={<SafetyCertificateOutlined />}
                disabled={streaming}
                onClick={() => setComplianceDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="版本历史">
              <Button
                aria-label="打开版本历史"
                icon={<HistoryOutlined />}
                type={versionDrawerOpen ? 'primary' : 'default'}
                disabled={streaming}
                onClick={() => setVersionDrawerOpen(true)}
              />
            </Tooltip>
            <Tooltip title="分享只读预览">
              <Button
                aria-label="分享只读预览"
                icon={<LinkOutlined />}
                disabled={streaming || saving}
                onClick={() => setDocumentShareOpen(true)}
              />
            </Tooltip>
            {hasSourceFile && (
              <Tooltip title="原文校审">
                <Button
                  aria-label="打开原文校审"
                  icon={<FileSearchOutlined />}
                  disabled={streaming}
                  onClick={() => setSourcePreviewOpen(true)}
                />
              </Tooltip>
            )}
            <Button icon={<ReloadOutlined />} disabled={streaming || saving} onClick={loadDocument}>
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
              if (
                nextModel?.supports_disabled_thinking === false
                || temporarilyUnsupportedThinkingModelIds.has(nextModelId)
              ) {
                setThinkingMode('auto')
              }
              setThinkingEffort('auto')
            }}
            thinkingMode={thinkingMode}
            onThinkingModeChange={setThinkingMode}
            thinkingEffort={thinkingEffort}
            onThinkingEffortChange={setThinkingEffort}
            temporarilyUnsupportedThinkingModelIds={temporarilyUnsupportedThinkingModelIds}
            thinkingStatus={thinkingStatus}
            contextStats={contextStats}
            chatSessions={chatSessions}
            activeChatSession={activeChatSession}
            hiddenHistory={hiddenHistory}
            messages={messages}
            queuedMessages={queuedChatRequests.map(({ id, content }) => ({ id, content }))}
            streaming={streaming}
            stopping={stopping}
            streamText={streamText}
            toolActivities={toolActivities}
            reasoningTrace={reasoningTrace}
            streamBlocks={streamBlocks}
            streamNotice={streamNotice}
            conversationError={conversationError}
            composerDraft={contextDraft}
            submitting={chatSubmitting}
            pendingUserQuestion={pendingUserQuestion}
            questionSubmitting={questionSubmitting}
            reaskConflict={reaskConflict}
            resolvingReaskConflict={resolvingReaskConflict}
            selectedElements={selectedElements}
            attachedTemplates={attachedTemplates}
            composerTemplates={composerTemplates}
            imageAttachments={chatImages}
            imageUploading={chatImageUploading}
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
            onEditRequest={handleEditRequest}
            onSend={(text, references, images) => {
              if (streaming || chatSubmitting) {
                enqueueChatRequest(text, references, images)
                return
              }
              void handleSendMessage(text, references, undefined, undefined, undefined, undefined, undefined, images)
            }}
            onAnswerUserQuestion={(answer) => { void handleAnswerUserQuestion(answer) }}
            onUserQuestionActivity={handleUserQuestionActivity}
            onUserQuestionTimeoutElapsed={() => { void handleUserQuestionTimeoutElapsed() }}
            onUploadImages={handleChatImageUpload}
            onRemoveImage={handleRemoveChatImage}
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
              mode={streaming || localizingArticleImages ? 'browse' : previewMode}
              brightness={previewBrightness}
              compact={isCompact}
              selectedElements={selectedElements}
              onHtmlChange={handleHtmlChange}
              onUploadImage={handleImageUpload}
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
            />
          </div>
          <div className={`editor-center-panel${centerView === 'code' ? '' : ' is-hidden'}`}>
            {codeViewMounted && (
              <Suspense fallback={<div className="editor-panel-loading" aria-busy="true" />}>
                <CodeViewer html={centerView === 'code' ? draftHtml : codeViewerHtmlRef.current} onChange={handleHtmlChange} onSave={handleSaveHtml} saving={saving || localizingArticleImages} disabled={streaming || localizingArticleImages} />
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
        height={centerView === 'preview' ? 360 : 268}
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
              value={previewMode}
              disabled={streaming}
              onChange={(value) => {
                setPreviewMode(value as PreviewMode)
                setMobileActionsDrawerOpen(false)
              }}
              options={[
                { label: '浏览', value: 'browse' },
                { label: '选择', value: 'select' },
                { label: '直接编辑', value: 'edit' },
              ]}
            />
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
              icon={<PictureOutlined />}
              disabled={streaming || saving}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setAiImageModalOpen(true)
              }}
            >
              AI 配图
            </Button>
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
                disabled={streaming || saving || materializingTemplateImages || localizingArticleImages}
                loading={localizingArticleImages}
              >
                转存外链图片
              </Button>
            </Popconfirm>
            <Button
              icon={<SafetyCertificateOutlined />}
              className={`compliance-status-trigger is-${complianceButtonStatus}`}
              disabled={streaming}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setComplianceDrawerOpen(true)
              }}
            >
              合规检测
            </Button>
            <Button
              icon={<HistoryOutlined />}
              disabled={streaming}
              onClick={() => {
                setMobileActionsDrawerOpen(false)
                setVersionDrawerOpen(true)
              }}
            >
              版本历史
            </Button>
            <Button
              icon={<LinkOutlined />}
              disabled={streaming || saving}
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
                disabled={streaming}
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
              disabled={streaming || saving}
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
                disabled={streaming || saving || wechatAccounts.length === 0}
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
        <CompliancePanel report={compliance} loading={complianceLoading} />
      </Drawer>
      <AIImageGenerationModal
        open={aiImageModalOpen}
        documentId={docId}
        sessionId={activeChatSessionId}
        initialModelId={activeChatSession?.image_model_id}
        initialAutoEnabled={activeChatSession?.auto_image_generation_enabled}
        selectedBlock={selectedElements[0] ?? null}
        onClose={() => setAiImageModalOpen(false)}
        onApplied={() => { void loadDocument() }}
      />
      <VersionHistoryDrawer
        documentId={docId}
        open={versionDrawerOpen}
        refreshToken={versionRefreshToken}
        restoreDisabled={streaming || saving || draftHtml !== html}
        copyDisabled={streaming || saving || draftHtml !== html}
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
            disabled={streaming || saving || !modelId}
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
            open
            documentId={docId}
            documentTitle={title}
            metadata={wechatMetadata}
            accounts={wechatAccounts}
            disabled={streaming || saving || draftHtml !== html}
            onClose={() => setWechatDraftOpen(false)}
            onMetadataSaved={(nextMetadata, nextTitle) => {
              setWechatMetadata(nextMetadata)
              setTitle(nextTitle)
              setVersionRefreshToken((value) => value + 1)
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
