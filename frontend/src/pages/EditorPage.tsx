import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { Button, Drawer, Input, Popover, Segmented, Slider, Space, Spin, Tooltip, message } from 'antd'
import { ArrowLeftOutlined, BulbOutlined, EditOutlined, FileSearchOutlined, FormatPainterOutlined, HistoryOutlined, PictureOutlined, ReloadOutlined, SafetyCertificateOutlined, SaveOutlined, SelectOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import ChatPanel from '../components/ChatPanel'
import PreviewFrame from '../components/PreviewFrame'
import type { PreviewFrameHandle, PreviewMode } from '../components/PreviewFrame'
import CompliancePanel from '../components/CompliancePanel'
import CodeViewer from '../components/CodeViewer'
import VersionHistoryDrawer from '../components/VersionHistoryDrawer'
import LayoutImitationModal from '../components/LayoutImitationModal'
import SourceDocumentModal from '../components/SourceDocumentModal'
import { documentsApi } from '../api/documents'
import { modelsApi } from '../api/models'
import { complianceApi } from '../api/compliance'
import { cancelChatRun, chatApi, startChatRun, streamChatRunEvents } from '../api/chat'
import type { ThinkingEffort, ThinkingMode } from '../api/chat'
import { ApiError } from '../api/client'
import type { AIModelItem, AssistantTurnBlock, ChatContextStats, ChatMessageItem, ComplianceReport, LayoutReferencePreview, ReasoningTrace, SelectedElementContext, ToolExecution } from '../types'
import { sanitizeSelectedElement, sanitizeSelectedElements } from '../utils/selectedElements'

type CenterView = 'preview' | 'code'
const STREAM_RENDER_INTERVAL_MS = 48
const MAX_STREAM_RECONNECT_ATTEMPTS = 12
const MIN_CHAT_PANE_WIDTH = 300
const MIN_CENTER_PANE_WIDTH = 440
const COLUMN_RESIZER_WIDTH = 8
const AUTO_SAVE_DELAY_MS = 1200

function finishActiveTextBlock(blocks: AssistantTurnBlock[]): AssistantTurnBlock[] {
  const last = blocks.at(-1)
  if (!last || (last.type !== 'thought' && last.type !== 'content') || last.state === 'done') return blocks
  const duration_ms = last.type === 'thought' && last.started_at_ms
    ? Math.max(0, Date.now() - last.started_at_ms)
    : last.duration_ms
  return [...blocks.slice(0, -1), { ...last, state: 'done', duration_ms }]
}

function appendStreamTextBlock(
  blocks: AssistantTurnBlock[],
  type: Extract<AssistantTurnBlock['type'], 'thought' | 'content'>,
  text: string,
): AssistantTurnBlock[] {
  if (!text) return blocks
  const last = blocks.at(-1)
  if (last?.type === type && last.state === 'active') {
    return [...blocks.slice(0, -1), { ...last, content: last.content + text }]
  }
  return [
    ...finishActiveTextBlock(blocks),
    {
      id: `${type}-${blocks.length + 1}`,
      type,
      state: 'active',
      content: text,
      duration_ms: null,
      ...(type === 'thought' ? { started_at_ms: Date.now() } : {}),
      tool: null,
    },
  ]
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

export default function EditorPage() {
  const { documentId } = useParams()
  const navigate = useNavigate()
  const docId = Number(documentId)

  const [title, setTitle] = useState('')
  const [html, setHtml] = useState('')
  const [draftHtml, setDraftHtml] = useState('')
  const [previewRevision, setPreviewRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [hasSourceFile, setHasSourceFile] = useState(false)
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [chatPaneWidth, setChatPaneWidth] = useState<number | null>(null)
  const [resizingChatPane, setResizingChatPane] = useState(false)

  const [models, setModels] = useState<AIModelItem[]>([])
  const [modelId, setModelId] = useState<number | null>(null)
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>('auto')
  const [thinkingEffort, setThinkingEffort] = useState<ThinkingEffort>('auto')
  const [thinkingStatus, setThinkingStatus] = useState<string | null>(null)
  const [contextStats, setContextStats] = useState<ChatContextStats | null>(null)
  const [reasoningTrace, setReasoningTrace] = useState<ReasoningTrace>({ status: 'idle', content: '', detail: '' })

  const [messages, setMessages] = useState<ChatMessageItem[]>([])
  const [streaming, setStreaming] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [toolActivities, setToolActivities] = useState<ToolExecution[]>([])
  const [streamBlocks, setStreamBlocks] = useState<AssistantTurnBlock[]>([])

  const [centerView, setCenterView] = useState<CenterView>('preview')
  const [previewMode, setPreviewMode] = useState<PreviewMode>('browse')
  const [previewBrightness, setPreviewBrightness] = useState(100)
  const [selectedElements, setSelectedElements] = useState<SelectedElementContext[]>([])
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
  const resumeHandlerRef = useRef<((runId: string) => Promise<void>) | null>(null)
  const complianceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const columnsRef = useRef<HTMLDivElement>(null)
  const resizeCleanupRef = useRef<(() => void) | null>(null)
  const htmlRef = useRef('')
  const draftHtmlRef = useRef('')
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRequestRef = useRef<Promise<string | null> | null>(null)
  const previewFrameRef = useRef<PreviewFrameHandle>(null)

  htmlRef.current = html
  draftHtmlRef.current = draftHtml

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

  const handleChatPaneResizeStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || window.matchMedia('(max-width: 720px)').matches) return
    const columns = columnsRef.current
    if (!columns) return
    const bounds = columns.getBoundingClientRect()
    const maximumWidth = bounds.width - MIN_CENTER_PANE_WIDTH - COLUMN_RESIZER_WIDTH
    if (maximumWidth < MIN_CHAT_PANE_WIDTH) return

    event.preventDefault()
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
      resizeCleanupRef.current = null
      setResizingChatPane(false)
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }, [])

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
      complianceTimerRef.current = setTimeout(() => runComplianceCheck(content), 600)
    },
    [runComplianceCheck],
  )

  const loadDocument = useCallback(async () => {
    if (!docId || Number.isNaN(docId)) return
    setLoading(true)
    try {
      const [doc, msgs, modelList] = await Promise.all([
        documentsApi.get(docId),
        chatApi.listMessages(docId),
        modelsApi.list(),
      ])
      setTitle(doc.title)
      setHasSourceFile(doc.has_source_file)
      applyExternalHtml(doc.current_html)
      setPreviewRevision((value) => value + 1)
      setSelectedElements([])
      setVersionRefreshToken((value) => value + 1)
      setMessages(msgs)
      setModels(modelList)
      const defaultModel = modelList.find((m) => m.is_default) ?? modelList[0]
      setModelId(defaultModel?.id ?? null)
      scheduleComplianceCheck(doc.current_html)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载文档失败')
      navigate('/')
    } finally {
      setLoading(false)
    }
  }, [applyExternalHtml, docId, navigate, scheduleComplianceCheck])

  useEffect(() => {
    loadDocument()
    return () => {
      abortRef.current?.abort()
      if (complianceTimerRef.current) clearTimeout(complianceTimerRef.current)
      cancelAutoSave()
    }
  }, [cancelAutoSave, loadDocument])

  useEffect(() => {
    if (!docId || Number.isNaN(docId) || !modelId) {
      setContextStats(null)
      return
    }
    let active = true
    void chatApi.getContext(docId, modelId)
      .then((stats) => {
        if (active) setContextStats(stats)
      })
      .catch(() => {
        if (active) setContextStats(null)
      })
    return () => {
      active = false
    }
  }, [docId, messages.length, modelId])

  const handleImageUpload = useCallback(async (file: File): Promise<string> => {
    if (!docId) throw new Error('文档不存在')
    try {
      const result = await documentsApi.uploadImage(docId, file)
      return result.url
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '图片上传失败')
      throw err
    }
  }, [docId])

  const persistDraftHtml = useCallback(async (showSuccess = false): Promise<string | null> => {
    if (!docId) return null
    cancelAutoSave()

    // 同一文档同一时刻仅保存一笔。请求期间的后续输入留在 draftHtmlRef，
    // 前一笔返回后继续写入，避免旧响应把新草稿覆盖掉。
    while (true) {
      const inFlight = saveRequestRef.current
      if (inFlight) {
        const saved = await inFlight
        if (saved === null) return null
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
          const doc = await documentsApi.update(docId, { current_html: snapshot })
          htmlRef.current = doc.current_html
          setHtml(doc.current_html)

          // 用户在请求中继续编辑时保留新草稿，下一轮循环会自动保存它。
          if (draftHtmlRef.current === snapshot) {
            draftHtmlRef.current = doc.current_html
            setDraftHtml(doc.current_html)
            runComplianceCheck(doc.current_html)
          }
          setPreviewRevision((value) => value + 1)
          setVersionRefreshToken((value) => value + 1)
          return doc.current_html
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
    }
  }, [cancelAutoSave, docId, runComplianceCheck])

  const scheduleAutoSave = useCallback(() => {
    cancelAutoSave()
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      void persistDraftHtml()
    }, AUTO_SAVE_DELAY_MS)
  }, [cancelAutoSave, persistDraftHtml])

  const handleHtmlChange = useCallback((next: string) => {
    if (streaming || next === draftHtmlRef.current) return
    draftHtmlRef.current = next
    setDraftHtml(next)
    scheduleComplianceCheck(next)
    scheduleAutoSave()
  }, [scheduleAutoSave, scheduleComplianceCheck, streaming])

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

  const handleSendMessage = async (
    text: string,
    attachedElements: SelectedElementContext[] = selectedElements,
    existingRunId?: string,
    layoutReferenceId?: string,
  ) => {
    if (!docId || (!modelId && !existingRunId)) return
    if (!existingRunId) previewFrameRef.current?.flushPendingChange()
    const sanitizedAttachedElements = sanitizeSelectedElements(attachedElements)

    let persistedHtml: string | null
    if (existingRunId) {
      persistedHtml = html
    } else if (pendingReaskMessageId !== null && !layoutReferenceId) {
      if (draftHtmlRef.current !== htmlRef.current) {
        message.warning('请先处理或保存当前手动修改后，再从历史要求重新提问')
        return
      }
      try {
        const reverted = await documentsApi.revertToMessage(docId, pendingReaskMessageId)
        persistedHtml = reverted.current_html
        applyExternalHtml(persistedHtml)
        setPreviewRevision((value) => value + 1)
        setMessages(await chatApi.listMessages(docId))
        scheduleComplianceCheck(persistedHtml)
        setPendingReaskMessageId(null)
      } catch (err) {
        message.error(err instanceof ApiError ? String(err.detail) : '回退历史要求失败')
        return
      }
    } else {
      // Agent 从数据库读取最新 HTML，预览/源码里的手工草稿必须先保存，避免模型基于旧稿操作。
      persistedHtml = await persistDraftHtml()
    }
    if (persistedHtml === null) return

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
        tool_calls: [],
        reasoning_trace: { status: 'idle', content: '', detail: '' },
        turn_blocks: [],
        selected_elements: sanitizedAttachedElements,
        can_revert: false,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, optimistic])
    }
    setStreaming(true)
    setStopping(false)
    setStreamText('')
    setToolActivities([])
    setStreamBlocks([])
    setThinkingStatus(null)
    setReasoningTrace({ status: 'idle', content: '', detail: '' })

    let accumulated = ''
    let latestHtml = persistedHtml
    let activeTools: ToolExecution[] = []
    let activeBlocks: AssistantTurnBlock[] = []
    let activeReasoning: ReasoningTrace = { status: 'idle', content: '', detail: '' }
    let runId: string | null = null
    let lastSequence = 0
    let completed = false
    let streamRenderTimer: number | null = null
    let streamRenderFrame: number | null = null
    let lastStreamRenderAt = 0

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
        : await startChatRun(
          docId,
          text,
          modelId as number,
          thinkingMode,
          thinkingEffort,
          createClientRequestId(),
          sanitizedAttachedElements,
          layoutReferenceId,
        )
      if (optimisticMessageId !== null && 'user_message_id' in run) {
        const persistedMessageId = run.user_message_id
        setMessages((previous) => previous.map((item) => (
          item.id === optimisticMessageId ? { ...item, id: persistedMessageId } : item
        )))
      }
      runId = run.run_id
      activeRunRef.current = run.run_id

      let reconnectAttempts = 0
      while (!completed) {
        try {
          for await (const received of streamChatRunEvents(docId, run.run_id, lastSequence, controller.signal)) {
            if (received.sequence && received.sequence <= lastSequence) continue
            if (received.sequence) lastSequence = received.sequence
            const evt = received
        if (evt.event !== 'heartbeat') reconnectAttempts = 0
        if (evt.event === 'text_delta') {
          accumulated += evt.data.text
          activeBlocks = appendStreamTextBlock(activeBlocks, 'content', evt.data.text)
          scheduleStreamRender()
        } else if (evt.event === 'reasoning_delta') {
          activeReasoning = {
            status: 'thinking',
            content: activeReasoning.content + evt.data.text,
            detail: activeReasoning.detail,
          }
          activeBlocks = appendStreamTextBlock(activeBlocks, 'thought', evt.data.text)
          scheduleStreamRender()
        } else if (evt.event === 'tool_call') {
          const toolId = evt.data.id ?? `tool-${Date.now()}-${activeTools.length}`
          const existingIndex = activeTools.findIndex((item) => item.id === toolId)
          if (existingIndex >= 0) {
            const nextTool = {
              ...activeTools[existingIndex],
              name: evt.data.name,
              arguments: evt.data.arguments,
              preparing: Boolean(evt.data.preparing),
            }
            activeTools = activeTools.map((item, index) => index === existingIndex ? nextTool : item)
            activeBlocks = activeBlocks.map((block) =>
              block.type === 'tool' && block.tool?.id === toolId ? { ...block, tool: nextTool } : block,
            )
          } else {
            activeBlocks = finishActiveTextBlock(activeBlocks)
            const nextTool: ToolExecution = {
              id: toolId,
              name: evt.data.name,
              arguments: evt.data.arguments,
              status: 'running',
              preparing: Boolean(evt.data.preparing),
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
          const index = [...nextTools].reverse().findIndex((item) => item.name === evt.data.name && item.status === 'running')
          let updatedToolId: string | null = null
          if (index >= 0) {
            const target = nextTools.length - 1 - index
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
            setSelectedElements([])
            setPreviewRevision((value) => value + 1)
            scheduleComplianceCheck(latestHtml)
          }
        } else if (evt.event === 'agent_status') {
          setThinkingStatus(evt.data.thinking.detail)
          if (evt.data.thinking.requested === 'enabled') {
            activeReasoning = {
              status: evt.data.thinking.applied ? 'thinking' : 'unavailable',
              content: '',
              detail: evt.data.thinking.detail,
            }
          }
          flushStreamRender()
        } else if (evt.event === 'context_stats') {
          setContextStats(evt.data)
        } else if (evt.event === 'heartbeat') {
          if (evt.data.detail) {
            setThinkingStatus(evt.data.detail)
            continue
          }
          const idleSeconds = Number(evt.data.idle_seconds ?? 0)
          if (idleSeconds >= 20) {
            setThinkingStatus(`连接正常，Agent 仍在处理（${idleSeconds}s 未产生新输出）`)
          }
        } else if (evt.event === 'final') {
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
          activeBlocks = finishActiveTextBlock(activeBlocks)
          flushStreamRender()
          const assistant: ChatMessageItem = {
            id: Date.now() + 1,
            role: 'assistant',
            content: evt.data.content || '（已完成编辑）',
            tool_calls: activeTools,
            reasoning_trace: activeReasoning,
            turn_blocks: activeBlocks,
            selected_elements: [],
            can_revert: evt.data.html_changed,
            created_at: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, assistant])
          setSelectedElements([])
          if (evt.data.html_changed) setVersionRefreshToken((value) => value + 1)
          completed = true
        } else if (evt.event === 'error') {
          message.error(evt.data.message)
        }
      }
          if (!completed) throw new Error('输出连接已结束')
        } catch (err) {
          if ((err as Error).name === 'AbortError') throw err
          try {
            const runState = await chatApi.getRun(docId, run.run_id)
            if (['completed', 'cancelled', 'failed'].includes(runState.status)) {
              if (runState.status !== 'completed' && runState.error_message) {
                message.error(runState.error_message)
              }
              setThinkingStatus(runState.error_message || null)
              setMessages(await chatApi.listMessages(docId))
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
          setThinkingStatus(`实时连接中断，正在恢复输出（${reconnectAttempts}/${MAX_STREAM_RECONNECT_ATTEMPTS}）…`)
          await waitForReconnect(reconnectAttempts, controller.signal)
        }
      }

      // 流结束后重新拉取消息列表，与数据库记录对齐
      const freshMsgs = await chatApi.listMessages(docId)
      setMessages(freshMsgs)
    } catch (err) {
      // A failed POST may leave only the client-side placeholder. It has no
      // server ID and must not be offered as a history branch for re-asking.
      if (!runId && optimisticMessageId !== null) {
        setMessages((previous) => previous.filter((item) => item.id !== optimisticMessageId))
      }
      if ((err as Error).name !== 'AbortError') {
        message.error(err instanceof ApiError ? String(err.detail) : '对话请求失败')
      }
    } finally {
      cancelStreamRender()
      if (runId && activeRunRef.current === runId) activeRunRef.current = null
      setStreaming(false)
      setStopping(false)
      setStreamText('')
      setToolActivities([])
      setStreamBlocks([])
    }
  }

  const handleLayoutImitation = async (reference: LayoutReferencePreview) => {
    if (!modelId) {
      message.warning('请先选择 AI 模型')
      return
    }
    setLayoutImitationOpen(false)
    await handleSendMessage(
      `请模仿参考链接的排版风格：${reference.canonical_url}。仅迁移视觉结构与样式，保留当前文案和图片。`,
      [],
      undefined,
      reference.reference_id,
    )
  }

  const handleEditRequest = useCallback((messageItem: ChatMessageItem) => {
    setSelectedElements(sanitizeSelectedElements(messageItem.selected_elements))
    setPendingReaskMessageId(messageItem.id)
  }, [])

  resumeHandlerRef.current = async (runId: string) => handleSendMessage('', [], runId)

  const handleStopAgent = async () => {
    const runId = activeRunRef.current
    if (!docId || !runId) {
      abortRef.current?.abort()
      return
    }
    try {
      setStopping(true)
      setThinkingStatus('正在停止 Agent…')
      await cancelChatRun(docId, runId)
    } catch (err) {
      setStopping(false)
      message.error(err instanceof ApiError ? String(err.detail) : '停止 Agent 失败')
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
        setThinkingStatus('正在恢复 Agent 输出…')
        await resumeHandlerRef.current?.(activeRun.run_id)
      } catch (err) {
        if (!disposed) message.error(err instanceof ApiError ? String(err.detail) : '恢复 Agent 输出失败')
      }
    })()
    return () => {
      disposed = true
    }
  }, [docId, loading, streaming])

  const handleVersionRestored = async (document: { title: string; current_html: string }) => {
    setTitle(document.title)
    applyExternalHtml(document.current_html)
    setPreviewRevision((value) => value + 1)
    setSelectedElements([])
    setPendingReaskMessageId(null)
    setCenterView('preview')
    scheduleComplianceCheck(document.current_html)
    setVersionRefreshToken((value) => value + 1)
  }

  const columnsStyle = chatPaneWidth === null
    ? undefined
    : ({ '--chat-pane-width': `${chatPaneWidth}px` } as CSSProperties)

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" description="加载排版工作台…" />
      </div>
    )
  }

  return (
    <div className="editor-workbench">
      <div className="editor-toolbar">
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
            返回
          </Button>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleSaveTitle}
            disabled={streaming}
            style={{ width: 280 }}
            placeholder="文档标题"
          />
        </Space>
        <Space>
          <Segmented
            value={centerView}
            disabled={streaming}
            onChange={(v) => setCenterView(v as CenterView)}
            options={[
              { label: '实时预览', value: 'preview' },
              { label: '源码编辑', value: 'code' },
            ]}
          />
          {centerView === 'preview' && (
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
          )}
          {centerView === 'preview' && previewMode === 'edit' && (
            <Tooltip title="插入图片">
              <Button
                aria-label="插入图片"
                icon={<PictureOutlined />}
                disabled={streaming || saving}
                onClick={() => previewFrameRef.current?.openImagePickerForInsert()}
              />
            </Tooltip>
          )}
          {centerView === 'preview' && (
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
          )}
          <Tooltip title="模仿排版">
            <Button
              aria-label="模仿排版"
              icon={<FormatPainterOutlined />}
              disabled={streaming || saving || !modelId}
              onClick={() => setLayoutImitationOpen(true)}
            />
          </Tooltip>
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
          <Tooltip title="合规检测">
            <Button
              aria-label="打开合规检测"
              icon={<SafetyCertificateOutlined />}
              type={complianceDrawerOpen ? 'primary' : 'default'}
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
          {hasSourceFile && (
            <Tooltip title="查看原文件">
              <Button
                aria-label="查看原文件"
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
      </div>

      <div
        ref={columnsRef}
        className={`editor-columns${resizingChatPane ? ' is-resizing' : ''}`}
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
              setModelId(nextModelId)
              setThinkingEffort('auto')
            }}
            thinkingMode={thinkingMode}
            onThinkingModeChange={setThinkingMode}
            thinkingEffort={thinkingEffort}
            onThinkingEffortChange={setThinkingEffort}
            thinkingStatus={thinkingStatus}
            contextStats={contextStats}
            messages={messages}
            streaming={streaming}
            stopping={stopping}
            streamText={streamText}
            toolActivities={toolActivities}
            reasoningTrace={reasoningTrace}
            streamBlocks={streamBlocks}
            selectedElements={selectedElements}
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
            onClearSelectedElements={() => setSelectedElements([])}
            onEditRequest={handleEditRequest}
            onSend={handleSendMessage}
            onOpenLayoutImitation={() => setLayoutImitationOpen(true)}
            onStop={handleStopAgent}
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
          {centerView === 'preview' ? (
            <PreviewFrame
              ref={previewFrameRef}
              html={draftHtml}
              revision={previewRevision}
              mode={streaming ? 'browse' : previewMode}
              brightness={previewBrightness}
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
              onClearSelections={() => setSelectedElements([])}
            />
          ) : (
            <CodeViewer html={draftHtml} onChange={handleHtmlChange} onSave={handleSaveHtml} saving={saving} disabled={streaming} />
          )}
        </div>

      </div>
      <Drawer
        title="合规检测"
        placement="right"
        width={360}
        open={complianceDrawerOpen}
        onClose={() => setComplianceDrawerOpen(false)}
      >
        <CompliancePanel report={compliance} loading={complianceLoading} />
      </Drawer>
      <VersionHistoryDrawer
        documentId={docId}
        open={versionDrawerOpen}
        refreshToken={versionRefreshToken}
        restoreDisabled={streaming || saving || draftHtml !== html}
        onClose={() => setVersionDrawerOpen(false)}
        onRestored={handleVersionRestored}
      />
      <LayoutImitationModal
        open={layoutImitationOpen}
        streaming={streaming}
        modelAvailable={Boolean(modelId)}
        onClose={() => setLayoutImitationOpen(false)}
        onConfirm={(reference) => { void handleLayoutImitation(reference) }}
      />
      <SourceDocumentModal documentId={docId} open={sourcePreviewOpen} onClose={() => setSourcePreviewOpen(false)} />
    </div>
  )
}
