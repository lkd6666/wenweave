import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { UIEvent } from 'react'
import { Alert, Button, Collapse, Popover, Segmented, Select, Tag, Tooltip, Typography, message } from 'antd'
import {
  EditOutlined,
  FormatPainterOutlined,
  InfoCircleOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons'
import type { AssistantTurnBlock, ChangeSummary, ChatContextStats, ChatMessageItem, ReasoningTrace, SelectedElementContext, ToolExecution } from '../types'
import type { ThinkingEffort, ThinkingMode } from '../api/chat'
import ModelSelector from './ModelSelector'
import type { AIModelItem } from '../types'
import MarkdownContent from './MarkdownContent'
import CodeBlock from './CodeBlock'
import PromptComposer from './PromptComposer'
import type { PromptComposerHandle } from './PromptComposer'
import ElementRenderPreview from './ElementRenderPreview'

const { Text } = Typography

const TOOL_LABELS: Record<string, string> = {
  get_document_map: '读取文档地图',
  search_html: '查找排版块',
  read_blocks: '读取排版块',
  apply_html_patch: '应用排版补丁',
  replace_document: '整体重写',
  check_compliance: '合规检测',
  apply_layout_reference: '应用参考排版',
}

const BOTTOM_FOLLOW_THRESHOLD = 48
const MemoMarkdownContent = memo(MarkdownContent)

function isNearBottom(container: HTMLElement): boolean {
  return container.scrollHeight - container.scrollTop - container.clientHeight < BOTTOM_FOLLOW_THRESHOLD
}

// AssistantTurnTimeline.vue renders every live delta through its Markdown
// renderer. Keep that behavior so inline Markdown such as **bold** is never
// shown as literal source while the Agent is still streaming.
const StreamingMarkdownContent = memo(function StreamingMarkdownContent({ content }: { content: string }) {
  return <MemoMarkdownContent content={content} />
})

function ContextUsage({ stats }: { stats: ChatContextStats }) {
  const breakdownLabels: Record<string, string> = {
    system: '系统提示',
    document_map: '文档地图',
    memory: '压缩记忆',
    recent_history: '近期对话',
    tool_replay: '工具回放',
    current_request: '当前请求',
    selected_context: '选中元素',
  }
  const stateLabel = stats.state === 'compacted'
    ? '已压缩历史'
    : stats.state === 'fallback_compacted'
      ? '已安全裁剪'
      : stats.state === 'requires_compaction'
        ? '发送时将压缩'
        : stats.state === 'context_overflow'
          ? '当前配置不足'
          : '当前预算'
  const detail = (
    <div className="chat-context-popover">
      <div className="chat-context-popover-head">
        <strong>{stats.used_tokens.toLocaleString()} / {stats.usable_tokens.toLocaleString()} tokens</strong>
        <span>{stateLabel}</span>
      </div>
      <div className="chat-context-breakdown">
        {Object.entries(stats.breakdown).map(([key, value]) => (
          <span key={key}><i>{breakdownLabels[key] ?? key}</i><b>{value.toLocaleString()}</b></span>
        ))}
      </div>
      <div className="chat-context-foot">
        工具摘要 {stats.tool_summary_replayed_count} 条，已节省约 {stats.tokens_saved.toLocaleString()} tokens
        {stats.is_estimate ? '，为估算值' : ''}
        <br />输出上限 {stats.max_output_tokens.toLocaleString()}，工具返回上限 {stats.tool_result_max_tokens.toLocaleString()} tokens
      </div>
    </div>
  )
  return (
    <Popover content={detail} trigger="click" placement="bottomRight">
      <button className={`chat-context-trigger${stats.usage_percent >= 85 ? ' is-warning' : ''}`} type="button" title="上下文预算">
        <InfoCircleOutlined /> <span>{stats.usage_percent}%</span>
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
  thinkingStatus: string | null
  contextStats: ChatContextStats | null
  messages: ChatMessageItem[]
  streaming: boolean
  stopping: boolean
  streamText: string
  toolActivities: ToolExecution[]
  reasoningTrace: ReasoningTrace
  streamBlocks: AssistantTurnBlock[]
  selectedElements: SelectedElementContext[]
  onRemoveSelectedElement: (index: number) => void
  onDuplicateSelectedElement: (index: number) => void
  onMoveSelectedElement: (fromIndex: number, toIndex: number) => void
  onClearSelectedElements: () => void
  onEditRequest: (message: ChatMessageItem) => void
  onSend: (text: string, references: SelectedElementContext[]) => void
  onOpenLayoutImitation: () => void
  onStop: () => void
}

export default function ChatPanel({
  models,
  modelId,
  onModelChange,
  thinkingMode,
  onThinkingModeChange,
  thinkingEffort,
  onThinkingEffortChange,
  thinkingStatus,
  contextStats,
  messages,
  streaming,
  stopping,
  streamText,
  toolActivities,
  reasoningTrace,
  streamBlocks,
  selectedElements,
  onRemoveSelectedElement,
  onDuplicateSelectedElement,
  onMoveSelectedElement,
  onClearSelectedElements,
  onEditRequest,
  onSend,
  onOpenLayoutImitation,
  onStop,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const listContentRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<PromptComposerHandle>(null)
  const followStreamRef = useRef(true)
  const lastScrollTopRef = useRef(0)
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
    const payload = composerRef.current?.getPayload() ?? { message: input.trim(), references: selectedElements }
    const text = payload.message || (payload.references.length > 0 ? '请处理所附元素。' : '')
    if (!text) return
    if (!modelId) {
      message.warning('请先选择 AI 模型')
      return
    }
    if (contextStats?.can_fit_after_compaction === false) {
      message.error('当前模型的压缩阈值不足以容纳此文档，请选择更大上下文模型或在模型管理中调整预算')
      return
    }
    setInput('')
    followStreamRef.current = true
    onClearSelectedElements()
    onSend(text, payload.references)
    scheduleFollowScroll(true)
  }

  const handleEditRequest = useCallback((message: ChatMessageItem) => {
    onEditRequest(message)
    setInput(message.content)
  }, [onEditRequest])

  const handleMessageScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return
    const container = event.currentTarget
    const currentTop = container.scrollTop
    if (currentTop < lastScrollTopRef.current - 10) {
      followStreamRef.current = false
    } else if (isNearBottom(container)) {
      followStreamRef.current = true
    }
    lastScrollTopRef.current = currentTop
  }, [])

  const selectedModel = models.find((model) => model.id === modelId)
  const contextCannotFit = contextStats?.can_fit_after_compaction === false
  const canSend = Boolean(modelId && !contextCannotFit && (input.trim() || selectedElements.length > 0))
  const effortConfig = selectedModel?.thinking_config?.efforts
  const effortOptions = effortConfig && typeof effortConfig === 'object' && !Array.isArray(effortConfig)
    ? Object.keys(effortConfig)
    : []
  const activeTool = getRunningTool(streamBlocks)
  const liveLabel = stopping ? '正在停止 Agent' : streamingLabel(streamBlocks, streamText)

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
  }, [forceScrollToLatest, messages, reasoningTrace, scheduleFollowScroll, streamBlocks, streamText, streaming, toolActivities])

  return (
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
          {contextStats && <ContextUsage stats={contextStats} />}
        </div>
        <div className="chat-panel-controls">
          <ModelSelector models={models} value={modelId} onChange={onModelChange} disabled={streaming} />
          <Segmented
            block
            size="small"
            value={thinkingMode}
            disabled={streaming}
            onChange={(value) => onThinkingModeChange(value as ThinkingMode)}
            options={[
              { label: '自动', value: 'auto' },
              { label: '思考', value: 'enabled' },
              { label: '直答', value: 'disabled' },
            ]}
          />
          {thinkingMode === 'enabled' && effortOptions.length > 0 && (
            <Select
              className="thinking-effort-select"
              aria-label="思考强度"
              size="small"
              value={thinkingEffort}
              disabled={streaming}
              onChange={(value) => onThinkingEffortChange(value as ThinkingEffort)}
              options={[
                { value: 'auto', label: '思考强度：默认' },
                ...effortOptions.map((effort) => ({ value: effort, label: `思考强度：${effort}` })),
              ]}
            />
          )}
        </div>
        {contextStats?.requires_compaction && !contextCannotFit && (
          <Alert
            className="chat-context-notice"
            type="warning"
            showIcon
            message={`切换到当前模型后，本轮会先压缩较早对话（预计 ${contextStats.projected_used_tokens.toLocaleString()} / ${contextStats.active_context_threshold_tokens.toLocaleString()} tokens）。`}
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

      <div
        className="chat-messages"
        ref={listRef}
        onScroll={handleMessageScroll}
      >
        <div className="chat-messages-content" ref={listContentRef}>
        {messages.length === 0 && !streaming && (
          <div className="chat-empty">
            <Text strong>开始排版对话</Text>
            <Text type="secondary">告诉我想如何调整这篇推文，我会直接修改预览内容。</Text>
            <div className="chat-quick-prompts">
              {['优化标题与开头层级', '统一正文段落和行距', '检查并修复公众号兼容性'].map((prompt) => (
                <button key={prompt} type="button" onClick={() => setInput(prompt)}>
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
            editingDisabled={streaming}
            onEditRequest={handleEditRequest}
          />
        ))}

        {streaming && (
          <article className="chat-turn chat-turn-assistant chat-turn-streaming">
              <div className="chat-turn-body">
              <div className="chat-turn-bubble">
                <div className={`chat-streaming-label${activeTool ? ' is-tool' : ''}`}>
                  <i /> <span className="chat-streaming-label-text">{liveLabel}</span>
                </div>
                <AssistantTurnTimeline
                  blocks={streamBlocks}
                  fallbackContent={streamText}
                  fallbackTrace={reasoningTrace}
                  fallbackTools={toolActivities}
                  streaming
                />
                {streamBlocks.length === 0 && !streamText && reasoningTrace.status === 'idle' && toolActivities.length === 0 ? (
                  <div className="chat-streaming-placeholder">正在准备排版方案…</div>
                ) : null}
              </div>
              <div className="chat-turn-meta"><span>排版助手</span></div>
            </div>
          </article>
        )}
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-composer-shell">
          <PromptComposer
            ref={composerRef}
            value={input}
            references={selectedElements}
            onChange={setInput}
            onSubmit={handleSend}
            disabled={streaming}
            onRemoveReference={onRemoveSelectedElement}
            onDuplicateReference={onDuplicateSelectedElement}
            onMoveReference={onMoveSelectedElement}
          />
          <div className="chat-input-actions">
            <Tooltip title="模仿排版">
              <Button
                aria-label="模仿排版"
                icon={<FormatPainterOutlined />}
                disabled={streaming || !modelId}
                onClick={onOpenLayoutImitation}
              />
            </Tooltip>
            <Text type="secondary">Enter 发送，Shift+Enter 换行</Text>
            {streaming ? (
              <Tooltip title="停止生成">
                <Button aria-label="停止生成" danger icon={<StopOutlined />} loading={stopping} disabled={stopping} onClick={onStop} />
              </Tooltip>
            ) : (
              <Tooltip title="发送">
                <Button aria-label="发送" type="primary" icon={<SendOutlined />} disabled={!canSend} onClick={handleSend} />
              </Tooltip>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

const ChatHistoryTurn = memo(function ChatHistoryTurn({
  messageItem,
  editingDisabled,
  onEditRequest,
}: {
  messageItem: ChatMessageItem
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
              <UserMessageContent content={messageItem.content} elements={messageItem.selected_elements} />
            </div>
          )}
        </div>
        <div className="chat-turn-meta">
          <span>{messageItem.role === 'user' ? '你' : '排版助手'} · {formatMessageTime(messageItem.created_at)}</span>
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

function formatMessageTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
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

function UserMessageContent({ content, elements }: { content: string; elements: SelectedElementContext[] }) {
  const referenced = new Set<number>()
  const parts = content.split(/(@元素\d+)/g)
  return (
    <>
      {parts.map((part, index) => {
        const match = /^@元素(\d+)$/.exec(part)
        if (!match) return <span key={`${part}-${index}`}>{part}</span>
        const referenceIndex = Number(match[1]) - 1
        const element = elements[referenceIndex]
        if (!element) return <span key={`${part}-${index}`}>{part}</span>
        referenced.add(referenceIndex)
        return (
          <Tooltip key={`${part}-${index}`} title={<ElementRenderPreview html={element.html} />}>
            <Tag className="selected-element-tag">@元素{referenceIndex + 1} &lt;{element.tag_name}&gt;</Tag>
          </Tooltip>
        )
      })}
      {elements.map((element, index) => !referenced.has(index) && (
        <Tooltip key={`fallback-${index}`} title={<ElementRenderPreview html={element.html} />}>
          <Tag className="selected-element-tag">@元素{index + 1} &lt;{element.tag_name}&gt;</Tag>
        </Tooltip>
      ))}
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
  const hasStructuredContent = blocks.some((block) => block.type === 'content' && block.content.trim())
  const timelineBlocks = blocks.length > 0
    ? (!hasStructuredContent && fallbackContent
        ? [...blocks, { id: 'legacy-final-content', type: 'content' as const, state: 'done' as const, content: fallbackContent, duration_ms: null, tool: null }]
        : blocks)
    : legacyTimelineBlocks(fallbackContent, fallbackTrace, fallbackTools)
  const displayBlocks = streaming ? timelineBlocks : settleHistoricalTimeline(timelineBlocks)
  const [archiveExpanded, setArchiveExpanded] = useState(false)
  const timelineRef = useRef<HTMLDivElement>(null)
  const processResizeFrameRef = useRef<number | null>(null)
  const processFollowRef = useRef(new WeakMap<HTMLElement, boolean>())
  const processLastScrollTopRef = useRef(new WeakMap<HTMLElement, number>())

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

  const getActiveProcessDetails = useCallback((): HTMLElement[] => {
    return Array.from(
      timelineRef.current?.querySelectorAll<HTMLElement>(
        '.thinking-trace-detail.is-live, .tool-trace-detail.is-live',
      ) ?? [],
    )
  }, [])

  const scheduleProcessScroll = useCallback((force = false) => {
    if (!isStreamingProcess) return
    getActiveProcessDetails().forEach((container) => {
      const shouldFollow = processFollowRef.current.get(container) ?? true
      if (!force && !shouldFollow) return
      container.scrollTop = Math.max(0, container.scrollHeight - container.clientHeight)
      processFollowRef.current.set(container, true)
      processLastScrollTopRef.current.set(container, container.scrollTop)
    })
  }, [getActiveProcessDetails, isStreamingProcess])

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
      <div className="assistant-action-list is-live" ref={timelineRef}>
        {displayBlocks.map((block) => (
          <AssistantTimelineBlock key={block.id} block={block} streaming onProcessScroll={handleProcessScroll} />
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
          expandIconPosition="end"
          activeKey={archiveExpanded ? ['process'] : []}
          onChange={(keys) => setArchiveExpanded((Array.isArray(keys) ? keys : [keys]).includes('process'))}
          items={[
            {
              key: 'process',
              label: <ProcessArchiveLabel blocks={archiveBlocks} />,
              children: (
                <div className="assistant-action-summary-body">
                  <div className="assistant-action-list">
                    {archiveBlocks.map((block) => (
                      <AssistantTimelineBlock key={block.id} block={block} archived onProcessScroll={handleProcessScroll} />
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

function findLastTimelineContentIndex(blocks: AssistantTurnBlock[]): number {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (blocks[index].type === 'content' && blocks[index].content.trim()) return index
  }
  return -1
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
  const toolCount = blocks.filter((block) => block.type === 'tool').length
  const summary = toolCount > 0
    ? `编辑了推文，执行了 ${toolCount} 项操作`
    : thoughtCount > 0
      ? `完成了 ${thoughtCount} 段思考`
      : '完成了本轮操作'

  return <span className="assistant-action-summary-label">{summary}</span>
}

const AssistantTimelineBlock = memo(function AssistantTimelineBlock({
  block,
  archived = false,
  streaming = false,
  onProcessScroll,
}: {
  block: AssistantTurnBlock
  archived?: boolean
  streaming?: boolean
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
}) {
  if (block.type === 'thought') {
    const trace: ReasoningTrace = {
      status: block.state === 'active' ? 'thinking' : block.content ? 'complete' : 'unavailable',
      content: block.content,
      detail: block.content ? '' : '模型未返回可展示的思考内容',
    }
    return (
      <div className={`assistant-action-entry assistant-action-thought is-${trace.status}${archived ? ' is-archived' : ''}`}>
        <ThinkingTrace trace={trace} durationMs={block.duration_ms} onProcessScroll={onProcessScroll} />
      </div>
    )
  }

  if (block.type === 'tool' && block.tool) {
    return (
      <div className={`assistant-action-entry assistant-action-tool is-${block.tool.status}${archived ? ' is-archived' : ''}`}>
        <ToolTrace tool={block.tool} onProcessScroll={onProcessScroll} />
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

  return (
    <Collapse
      className="assistant-action-row assistant-action-tool-row"
      size="small"
      expandIconPosition="end"
      activeKey={expanded ? [tool.id] : []}
      onChange={(keys) => setExpanded((Array.isArray(keys) ? keys : [keys]).includes(tool.id))}
      items={[{
        key: tool.id,
        label: (
          <span className="tool-trace-label">
            {isRunning ? (
              <span className="tool-trace-name is-running" title={toolLabel(tool.name)}>{toolLabel(tool.name)}</span>
            ) : tool.status === 'error' ? (
              <>
                <span className="tool-trace-name" title={toolLabel(tool.name)}>{toolLabel(tool.name)}</span>
                <span className="tool-trace-status is-error">{status.label}</span>
              </>
            ) : (
              <>
                <span className="tool-trace-name" title={toolLabel(tool.name)}>{toolLabel(tool.name)}</span>
                <span className="tool-trace-name" title={toolActionTarget(tool)}>{toolActionTarget(tool)}</span>
              </>
            )}
            {tool.change_summary && !activity && <ChangeSummaryInline summary={tool.change_summary} />}
          </span>
        ),
        children: (
          <div className={`tool-trace-detail${isRunning ? ' is-live' : ''}`} onScroll={onProcessScroll}>
            {activity?.targets && activity.targets.length > 0 && (
              <div className="tool-activity-targets">
                {activity.targets.slice(0, 4).map((target, index) => (
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

function toolStatusSummary(tool: ToolExecution): { label: string } {
  if (tool.status === 'running' && tool.preparing) return { label: '准备中' }
  if (tool.status === 'running') return { label: '执行中' }
  if (tool.status === 'error') return { label: '执行失败' }
  if (tool.html_changed) return { label: '已更新预览' }
  return { label: '已完成' }
}

function toolActionTarget(tool: ToolExecution): string {
  if (tool.activity?.summary) return tool.activity.summary
  if (['get_document_map', 'search_html', 'read_blocks', 'view_html'].includes(tool.name)) return 'HTML'
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
  onProcessScroll,
}: {
  trace: ReasoningTrace
  durationMs?: number | null
  onProcessScroll: (event: UIEvent<HTMLDivElement>) => void
}) {
  const isThinking = trace.status === 'thinking'
  const [expanded, setExpanded] = useState(isThinking)

  useEffect(() => {
    setExpanded(isThinking)
  }, [isThinking])

  const label = isThinking ? 'Thinking' : 'Thought'

  return (
    <Collapse
      className={`assistant-action-row assistant-action-thought-row is-${trace.status}`}
      size="small"
      expandIconPosition="end"
      activeKey={expanded ? ['thinking'] : []}
      onChange={(keys) => {
        if (!isThinking) setExpanded((Array.isArray(keys) ? keys : [keys]).includes('thinking'))
      }}
      items={[
        {
          key: 'thinking',
          label: (
            <span className="thinking-action-label">
              <span>{label}</span>
              {!isThinking && durationMs !== null && durationMs !== undefined && (
                <span className="thought-duration">({formatThoughtDuration(durationMs)})</span>
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

function formatThoughtDuration(durationMs: number): string {
  if (durationMs < 60_000) return `${Math.max(0.1, durationMs / 1000).toFixed(1)}s`
  const minutes = Math.floor(durationMs / 60_000)
  const seconds = Math.round((durationMs % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}
