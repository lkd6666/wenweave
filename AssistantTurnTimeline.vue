<template>
  <div v-if="hasRenderableContent" ref="assistantTurnRef" class="assistant-turn-view" :class="rootClasses">
    <div v-if="shouldArchiveHistory" key="archive-mode" class="trace-archive">
      <el-collapse v-model="archiveExpandedNames" class="trace-collapse trace-archive-collapse">
        <el-collapse-item name="archive">
          <template #title>
            <span class="trace-title-row">
              <span class="trace-title">Thinking</span>
              <span v-if="archiveDurationText" class="trace-duration">{{ archiveDurationText }}</span>
              <span v-if="archiveSummaryText" class="trace-summary">{{ archiveSummaryText }}</span>
            </span>
          </template>
        <transition-group v-if="isArchiveExpanded" name="trace-entry" tag="div" class="archive-body">
          <template v-for="entry in historyEntries" :key="entry.id">
            <div v-if="entry.kind === 'thought'" class="timeline-entry thought-entry is-archived">
              <div class="process-rail"><span class="process-dot" :class="{ 'is-live': entry.item.state === 'active' }"></span></div>
              <div class="process-main">
                <el-collapse
                  :key="`archive-thought-${entry.id}-${entry.item.state}`"
                  :model-value="getThoughtModel(entry)"
                  class="trace-collapse thought-collapse"
                  @update:model-value="setThoughtModel(entry, $event)"
                >
                  <el-collapse-item :name="entry.id" :disabled="entry.item.state === 'active'">
                    <template #title>
                      <span class="trace-title-row" :class="{ 'is-live': entry.item.state === 'active' }">
                        <span class="trace-title">Thinking</span>
                        <span v-if="entry.durationMs" class="trace-duration">({{ formatReasoningDuration(entry.durationMs) }})</span>
                      </span>
                    </template>
                    <div
                      class="thought-detail"
                      :class="{ 'is-live': entry.item.state === 'active' }"
                      @scroll.passive="handleProcessScroll"
                    >
                      <div
                        class="thought-text"
                        :class="{ 'is-live': entry.item.state === 'active' }"
                      >{{ entry.item.fullText }}</div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>

            <div
              v-else-if="entry.kind === 'tool'"
              class="timeline-entry tool-entry is-archived"
              :class="getToolEntryClasses(entry.item)"
            >
              <div class="process-rail tool-rail">
                <span
                  class="process-dot tool-dot"
                  :class="getToolDotClasses(entry.item)"
                ></span>
              </div>
              <div class="process-main">
                <el-collapse
                  :key="`archive-tool-${entry.item.id}-${entry.item.status}`"
                  :model-value="getToolModel(entry.item)"
                  class="trace-collapse tool-collapse"
                  :class="getToolEntryClasses(entry.item)"
                  @update:model-value="setToolModel(entry.item, $event)"
                >
                  <el-collapse-item :name="entry.item.id">
                    <template #title>
                      <span class="trace-title-row tool-title-row" :class="getToolTitleClasses(entry.item)">
                        <span class="tool-name">{{ formatToolHeadline(entry.item) }}</span>
                        <span class="tool-status">{{ getToolStatusText(entry.item) }}</span>
                      </span>
                    </template>
                    <div
                      class="tool-detail"
                      :class="getToolDetailClasses(entry.item)"
                      @scroll.passive="handleProcessScroll"
                    >
                      <div
                        class="tool-detail-rendered"
                        :class="getToolRenderedClasses(entry.item)"
                        v-html="renderCachedToolDetail(entry.item)"
                      ></div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>

            <div v-else-if="entry.kind === 'content'" class="timeline-entry content-entry is-archived">
              <div class="process-rail content-rail"></div>
              <div class="process-main content-main">
                <div class="message-bubble" v-html="renderCachedMarkdown(entry.id, entry.content)"></div>
              </div>
            </div>
          </template>
        </transition-group>
        </el-collapse-item>
      </el-collapse>
    </div>

    <transition-group v-else key="live-mode" name="trace-entry" tag="div" class="live-body">
      <template v-for="entry in liveEntries" :key="entry.id">
        <div v-if="entry.kind === 'thought'" class="timeline-entry thought-entry">
          <div class="process-rail"><span class="process-dot" :class="{ 'is-live': entry.item.state === 'active' }"></span></div>
          <div class="process-main">
            <el-collapse
              :key="`live-thought-${entry.id}-${entry.item.state}`"
              :model-value="getThoughtModel(entry)"
              class="trace-collapse thought-collapse"
              @update:model-value="setThoughtModel(entry, $event)"
            >
              <el-collapse-item :name="entry.id" :disabled="entry.item.state === 'active'">
                <template #title>
                  <span class="trace-title-row" :class="{ 'is-live': entry.item.state === 'active' }">
                    <span class="trace-title">Thinking</span>
                    <span v-if="entry.durationMs" class="trace-duration">({{ formatReasoningDuration(entry.durationMs) }})</span>
                  </span>
                </template>
                <div
                  class="thought-detail"
                  :class="{ 'is-live': entry.item.state === 'active' }"
                  @scroll.passive="handleProcessScroll"
                >
                  <div
                    class="thought-text"
                    :class="{ 'is-live': entry.item.state === 'active' }"
                  >{{ entry.item.fullText }}</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>

        <div v-else-if="entry.kind === 'tool'" class="timeline-entry tool-entry" :class="getToolEntryClasses(entry.item)">
          <div class="process-rail tool-rail">
            <span
              class="process-dot tool-dot"
              :class="getToolDotClasses(entry.item)"
            ></span>
          </div>
          <div class="process-main">
            <el-collapse
              :key="`live-tool-${entry.item.id}-${entry.item.status}`"
              :model-value="getToolModel(entry.item)"
              class="trace-collapse tool-collapse"
              :class="getToolEntryClasses(entry.item)"
              @update:model-value="setToolModel(entry.item, $event)"
            >
              <el-collapse-item :name="entry.item.id">
                <template #title>
                  <span class="trace-title-row tool-title-row" :class="getToolTitleClasses(entry.item)">
                    <span class="tool-name">{{ formatToolHeadline(entry.item) }}</span>
                    <span class="tool-status">{{ getToolStatusText(entry.item) }}</span>
                  </span>
                </template>
                <div
                  class="tool-detail"
                  :class="getToolDetailClasses(entry.item)"
                  @scroll.passive="handleProcessScroll"
                >
                  <div
                    class="tool-detail-rendered"
                    :class="getToolRenderedClasses(entry.item)"
                    v-html="renderCachedToolDetail(entry.item)"
                  ></div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>

        <div v-else-if="entry.kind === 'content'" class="timeline-entry content-entry">
          <div class="process-rail content-rail"></div>
          <div class="process-main content-main">
            <div class="message-bubble" v-html="renderCachedMarkdown(entry.id, entry.content)"></div>
          </div>
        </div>
      </template>
    </transition-group>

    <transition name="final-bubble" appear>
      <div
        v-if="finalContent"
        class="turn-final-content message-bubble"
        v-html="renderCachedMarkdown('final-content', finalContent)"
      ></div>
    </transition>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { buildMessageBlocks, formatReasoningDuration } from '@/composables/useAssistantTurnBlocks'
import { formatToolDetail, renderFormattedToolDetail } from '@/utils/aiMarkdown'

const props = defineProps({
  blocks: {
    type: Array,
    default: () => []
  },
  fallbackContent: {
    type: String,
    default: ''
  },
  thinking: {
    type: Boolean,
    default: false
  },
  reasoningDuration: {
    type: Number,
    default: 0
  },
  renderMarkdown: {
    type: Function,
    required: true
  }
})

const archiveExpandedNames = ref([])
const expandedThoughtIds = ref([])
const toolExpandedState = ref({})
const toolAutoExpandedState = ref({})
const toolVisualState = ref({})
const assistantTurnRef = ref(null)
const isProcessAtBottom = ref(true)
const lastProcessScrollTop = ref(0)
let processScrollRaf = 0

const markdownCache = new Map()
const toolDetailCache = new Map()
const toolStatusMemory = new Map()
const toolStateTimers = new Map()

const normalizedBlocks = computed(() => buildMessageBlocks(props.blocks, { fastTrusted: true }))
const hasStructuredContent = computed(() => normalizedBlocks.value.some(block => block.type === 'content' && block.content))

const buildSegments = (blocks) => {
  const segments = []
  let pendingProcess = []
  let processIndex = 0
  let contentIndex = 0

  const flushProcess = (durationMs = null) => {
    if (pendingProcess.length === 0) return

    const items = pendingProcess
    const tools = items.filter(item => item.type === 'tool')
    const thoughts = items.filter(item => item.type === 'thought')
    const active = props.thinking && items.some(item =>
      item.state === 'active' || (item.type === 'tool' && item.status === 'loading')
    )
    const stableKey = items.map(item => item.id).filter(Boolean).join('-') || `process-${processIndex}`

    segments.push({
      id: `process-${stableKey}`,
      kind: 'process',
      items,
      tools,
      thoughts,
      durationMs,
      status: active ? 'active' : 'done',
      summary: buildProcessSummary(thoughts, tools)
    })
    pendingProcess = []
    processIndex += 1
  }

  blocks.forEach(block => {
    if (block.type === 'content') {
      flushProcess(block.roundDurationMs ?? null)
      if (block.content) {
        segments.push({
          id: block.id || `content-${contentIndex}`,
          kind: 'content',
          content: block.content,
          state: block.state || 'done'
        })
      }
      contentIndex += 1
      return
    }

    pendingProcess.push(block)
  })

  flushProcess(null)

  if (!props.thinking && props.reasoningDuration) {
    const firstProcess = segments.find(segment => segment.kind === 'process' && !segment.durationMs)
    if (firstProcess) firstProcess.durationMs = props.reasoningDuration
  }

  return segments
}

function findLastIndex(items, predicate) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index], index)) return index
  }
  return -1
}

const allSegments = computed(() => {
  const segments = buildSegments(normalizedBlocks.value)
  if (!hasStructuredContent.value && props.fallbackContent) {
    segments.push({
      id: 'fallback-content',
      kind: 'content',
      content: props.fallbackContent,
      state: props.thinking ? 'active' : 'done'
    })
  }
  return segments
})

const splitSegments = computed(() => {
  if (props.thinking) {
    return {
      liveSegments: allSegments.value,
      historySegments: [],
      finalContent: ''
    }
  }

  const segments = allSegments.value
  const lastContentIndex = findLastIndex(segments, segment => segment.kind === 'content' && segment.content)
  if (lastContentIndex === -1) {
    return {
      liveSegments: [],
      historySegments: segments,
      finalContent: ''
    }
  }

  return {
    liveSegments: [],
    historySegments: segments.filter((_, index) => index !== lastContentIndex),
    finalContent: segments[lastContentIndex].content || ''
  }
})

const liveSegments = computed(() => splitSegments.value.liveSegments)
const historySegments = computed(() => splitSegments.value.historySegments)
const finalContent = computed(() => splitSegments.value.finalContent)
const expandTimelineEntries = (segments) => {
  const entries = []

  segments.forEach(segment => {
    if (segment.kind === 'content') {
      entries.push(segment)
      return
    }

    segment.items.forEach((item, itemIndex) => {
      entries.push({
        id: item.id || `${segment.id}-${item.type}-${itemIndex}`,
        kind: item.type === 'tool' ? 'tool' : 'thought',
        item,
        durationMs: item.type === 'thought' ? segment.durationMs : null,
      })
    })
  })

  return entries
}
const liveEntries = computed(() => expandTimelineEntries(liveSegments.value))
const historyEntries = computed(() => expandTimelineEntries(historySegments.value))
const shouldArchiveHistory = computed(() => !props.thinking && historySegments.value.length > 0)
const hasRenderableContent = computed(() =>
  liveEntries.value.length > 0 || historyEntries.value.length > 0 || !!finalContent.value
)
const visualPhase = computed(() => {
  if (props.thinking) {
    for (let index = liveEntries.value.length - 1; index >= 0; index -= 1) {
      const entry = liveEntries.value[index]
      if (entry.kind === 'content' && entry.content) return 'responding'
      if (entry.kind === 'tool' && entry.item?.status === 'loading') return 'tool'
      if (entry.kind === 'thought' && entry.item?.state === 'active') return 'thinking'
    }
    return liveEntries.value.some(entry => entry.kind === 'tool') ? 'tool' : 'thinking'
  }

  if (finalContent.value) return 'final'
  if (historyEntries.value.some(entry => entry.kind === 'tool')) return 'settled'
  return 'idle'
})
const rootClasses = computed(() => [
  `phase-${visualPhase.value}`,
  {
    'is-streaming': props.thinking,
    'has-final-content': !!finalContent.value,
    'has-history': historyEntries.value.length > 0,
  },
])
const isArchiveExpanded = computed(() =>
  Array.isArray(archiveExpandedNames.value)
    ? archiveExpandedNames.value.includes('archive')
    : archiveExpandedNames.value === 'archive'
)

const archiveDurationText = computed(() => {
  if (props.reasoningDuration) return `(${formatReasoningDuration(props.reasoningDuration)})`
  const total = historySegments.value
    .filter(segment => segment.kind === 'process')
    .reduce((sum, segment) => sum + (segment.durationMs || 0), 0)
  return total ? `(${formatReasoningDuration(total)})` : ''
})

const archiveSummaryText = computed(() => buildArchiveSummary(historySegments.value))

watch(
  () => props.thinking,
  (value) => {
    archiveExpandedNames.value = []
    if (!value) expandedThoughtIds.value = []
    isProcessAtBottom.value = true
    lastProcessScrollTop.value = 0
    if (value) {
      scheduleProcessScroll(true)
    }
  },
  { immediate: true }
)

watch(
  liveEntries,
  () => {
    if (props.thinking) {
      scheduleProcessScroll()
    }
  },
  { deep: true }
)

watch(
  () => normalizedBlocks.value
    .filter(item => item.type === 'tool')
    .map(item => ({ id: item.id, status: item.status })),
  (tools) => {
    syncToolPresentationState(tools)
  },
  { immediate: true, deep: true }
)

onBeforeUnmount(() => {
  if (processScrollRaf) {
    cancelAnimationFrame(processScrollRaf)
    processScrollRaf = 0
  }
  toolStateTimers.forEach(handles => handles.forEach(handle => clearTimeout(handle)))
  toolStateTimers.clear()
})

function buildProcessSummary(thoughts, tools) {
  if (tools.length === 1 && thoughts.length === 0) return `调用了 ${tools[0].name || '工具'}`
  if (tools.length === 1) return `调用了 ${tools[0].name || '工具'}`
  if (tools.length > 1) {
    const names = tools.slice(0, 2).map(tool => tool.name || '工具').join('、')
    return `调用了 ${names} 等 ${tools.length} 个工具`
  }
  return thoughts.length > 1 ? `${thoughts.length} 段思考` : '思考过程'
}

function buildArchiveSummary(segments) {
  const processSegments = segments.filter(segment => segment.kind === 'process')
  const contentCount = segments.filter(segment => segment.kind === 'content' && segment.content).length
  const toolCount = processSegments.reduce((count, segment) => count + segment.tools.length, 0)
  const parts = []
  if (processSegments.length > 0) parts.push(`${processSegments.length} 轮过程`)
  if (toolCount === 1) {
    const tool = processSegments.flatMap(segment => segment.tools)[0]
    parts.push(`调用了 ${tool?.name || '工具'}`)
  } else if (toolCount > 1) {
    const tool = processSegments.flatMap(segment => segment.tools)[0]
    parts.push(`调用了 ${tool?.name || '工具'} 等 ${toolCount} 个工具`)
  }
  if (contentCount > 0) parts.push(`${contentCount} 段中间正文`)
  return parts.join(' · ')
}

const getToolStatusText = (tool) => {
  if (!tool) return '未知状态'
  if (tool.status === 'loading') return tool.message || '执行中'
  if (tool.status === 'error') return tool.resultSummary || tool.message || '调用失败'
  return tool.resultSummary || tool.message || '调用成功'
}

function getActiveProcessDetail() {
  const root = assistantTurnRef.value
  if (!root) return null
  return root.querySelector('.thought-detail.is-live, .tool-detail.is-live')
}

function handleProcessScroll(event) {
  const el = event?.target
  if (!el) return

  const currentScrollTop = el.scrollTop
  const atBottom = el.scrollHeight - currentScrollTop - el.clientHeight < 30

  if (currentScrollTop < lastProcessScrollTop.value - 10) {
    isProcessAtBottom.value = false
  } else if (atBottom) {
    isProcessAtBottom.value = true
  }

  lastProcessScrollTop.value = currentScrollTop
}

function scrollProcessToBottom(force = false) {
  nextTick(() => {
    const el = getActiveProcessDetail()
    if (!el) return

    const currentlyAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    if (!force && !isProcessAtBottom.value && !currentlyAtBottom) {
      return
    }

    el.scrollTop = el.scrollHeight
    isProcessAtBottom.value = true
    lastProcessScrollTop.value = el.scrollTop
  })
}

function scheduleProcessScroll(force = false) {
  if (processScrollRaf) return
  processScrollRaf = requestAnimationFrame(() => {
    processScrollRaf = 0
    scrollProcessToBottom(force)
  })
}

const getToolModel = (tool) => {
  if (!tool?.id) return []
  if (Object.prototype.hasOwnProperty.call(toolExpandedState.value, tool.id)) {
    return toolExpandedState.value[tool.id] ? [tool.id] : []
  }
  if (tool.status === 'loading') return [tool.id]
  if (toolAutoExpandedState.value[tool.id]) return [tool.id]
  if (tool.expanded) return [tool.id]
  return []
}

const setToolModel = (tool, value) => {
  if (!tool?.id) return
  const nextExpanded = Array.isArray(value) && value.includes(tool.id)
  const nextAutoExpanded = { ...toolAutoExpandedState.value }
  delete nextAutoExpanded[tool.id]
  toolAutoExpandedState.value = nextAutoExpanded
  toolExpandedState.value = {
    ...toolExpandedState.value,
    [tool.id]: nextExpanded
  }
}

const isToolExpanded = (tool) => {
  if (!tool?.id) return false
  return getToolModel(tool).includes(tool.id)
}

const getThoughtModel = (entry) => {
  if (!entry?.id) return []
  if (entry.item?.state === 'active') return [entry.id]
  return expandedThoughtIds.value.includes(entry.id) ? [entry.id] : []
}

const setThoughtModel = (entry, value) => {
  if (!entry?.id || entry.item?.state === 'active') return
  expandedThoughtIds.value = Array.isArray(value) && value.includes(entry.id)
    ? [...new Set([...expandedThoughtIds.value.filter(id => id !== entry.id), entry.id])]
    : expandedThoughtIds.value.filter(id => id !== entry.id)
}

const isThoughtExpanded = (entry) => {
  if (!entry?.id) return false
  return getThoughtModel(entry).includes(entry.id)
}

const formatToolHeadline = (tool) => {
  if (!tool) return 'Tool'
  if (String(tool.name || '').toLowerCase() === 'web_search_proxy') return '联网搜索'
  return tool.name || '工具调用'
}

const hasManualToolExpandedState = (toolId) => Object.prototype.hasOwnProperty.call(toolExpandedState.value, toolId)

function clearToolTimers(toolId) {
  const handles = toolStateTimers.get(toolId)
  if (handles) {
    handles.forEach(handle => clearTimeout(handle))
    toolStateTimers.delete(toolId)
  }
}

function queueToolTimer(toolId, callback, delay) {
  const handle = setTimeout(() => {
    const handles = toolStateTimers.get(toolId)
    if (handles) {
      toolStateTimers.set(toolId, handles.filter(item => item !== handle))
    }
    callback()
  }, delay)

  const handles = toolStateTimers.get(toolId) || []
  handles.push(handle)
  toolStateTimers.set(toolId, handles)
}

function patchToolVisualState(toolId, patch) {
  if (!toolId) return
  toolVisualState.value = {
    ...toolVisualState.value,
    [toolId]: {
      ...(toolVisualState.value[toolId] || {}),
      ...patch
    }
  }
}

function clearToolVisualState(toolId) {
  if (!toolId || !toolVisualState.value[toolId]) return
  const nextState = { ...toolVisualState.value }
  delete nextState[toolId]
  toolVisualState.value = nextState
}

function setToolAutoExpanded(toolId, expanded) {
  if (!toolId) return
  const nextState = { ...toolAutoExpandedState.value }
  if (expanded) {
    nextState[toolId] = true
  } else {
    delete nextState[toolId]
  }
  toolAutoExpandedState.value = nextState
}

function triggerToolLoadingState(toolId) {
  if (!toolId) return
  clearToolTimers(toolId)
  patchToolVisualState(toolId, { phase: 'starting' })
  if (!hasManualToolExpandedState(toolId)) {
    setToolAutoExpanded(toolId, true)
  }
  queueToolTimer(toolId, () => {
    patchToolVisualState(toolId, { phase: 'loading' })
  }, 520)
}

function triggerToolCompleteState(toolId, status) {
  if (!toolId) return
  clearToolTimers(toolId)

  if (status === 'error') {
    patchToolVisualState(toolId, { phase: 'error' })
    if (!hasManualToolExpandedState(toolId)) {
      setToolAutoExpanded(toolId, true)
    }
    return
  }

  patchToolVisualState(toolId, { phase: 'settling' })
  if (!hasManualToolExpandedState(toolId)) {
    setToolAutoExpanded(toolId, true)
    queueToolTimer(toolId, () => {
      if (!hasManualToolExpandedState(toolId)) {
        setToolAutoExpanded(toolId, false)
      }
    }, 1480)
  }
  queueToolTimer(toolId, () => {
    patchToolVisualState(toolId, { phase: 'success' })
  }, 860)
  queueToolTimer(toolId, () => {
    clearToolVisualState(toolId)
  }, 2280)
}

function cleanupToolPresentationState(toolId) {
  clearToolTimers(toolId)
  clearToolVisualState(toolId)
  setToolAutoExpanded(toolId, false)
  toolStatusMemory.delete(toolId)
}

function syncToolPresentationState(tools) {
  const activeIds = new Set()

  tools.forEach(tool => {
    const toolId = tool?.id
    if (!toolId) return

    activeIds.add(toolId)
    const prevStatus = toolStatusMemory.get(toolId)
    const nextStatus = tool.status

    if (!prevStatus && nextStatus === 'loading') {
      triggerToolLoadingState(toolId)
    } else if (prevStatus && prevStatus !== nextStatus) {
      if (nextStatus === 'loading') {
        triggerToolLoadingState(toolId)
      } else if (nextStatus === 'success' || nextStatus === 'error') {
        triggerToolCompleteState(toolId, nextStatus)
      }
    }

    toolStatusMemory.set(toolId, nextStatus)
  })

  Array.from(toolStatusMemory.keys()).forEach(toolId => {
    if (!activeIds.has(toolId)) {
      cleanupToolPresentationState(toolId)
    }
  })
}

const getToolVisualPhase = (tool) => {
  if (!tool?.id) return ''
  return toolVisualState.value[tool.id]?.phase || ''
}

const getToolEntryClasses = (tool) => {
  const phase = getToolVisualPhase(tool)
  return {
    'is-loading': tool?.status === 'loading',
    'is-success': tool?.status === 'success',
    'is-error': tool?.status === 'error',
    'is-starting': phase === 'starting',
    'is-settling': phase === 'settling',
    'is-complete': phase === 'success',
    'is-expanded': isToolExpanded(tool),
  }
}

const getToolDotClasses = (tool) => ({
  'is-loading': tool?.status === 'loading',
  'is-error': tool?.status === 'error',
  'is-starting': getToolVisualPhase(tool) === 'starting',
  'is-settling': getToolVisualPhase(tool) === 'settling',
  'is-complete': getToolVisualPhase(tool) === 'success',
})

const getToolTitleClasses = (tool) => ({
  'is-live': tool?.status === 'loading',
  ...getToolEntryClasses(tool),
})

const getToolDetailClasses = (tool) => ({
  'is-live': tool?.status === 'loading',
  ...getToolEntryClasses(tool),
})

const getToolRenderedClasses = (tool) => ({
  ...getToolEntryClasses(tool),
})

const renderCachedMarkdown = (id, content) => {
  const raw = String(content || '')
  if (!raw) return ''

  // ai-photo 引用依赖父组件的异步签名刷新，不能按正文字符串长期缓存。
  if (raw.includes('ai-photo://')) {
    return props.renderMarkdown(raw)
  }

  const key = id || `content-${raw.length}`
  const cached = markdownCache.get(key)
  if (cached && cached.raw === raw) return cached.html

  const html = props.renderMarkdown(raw)
  markdownCache.set(key, { raw, html })
  if (markdownCache.size > 32) {
    markdownCache.delete(markdownCache.keys().next().value)
  }
  return html
}

const renderCachedToolDetail = (tool) => {
  const key = tool?.id || tool?.name || 'tool-detail'
  const cached = toolDetailCache.get(key)
  if (
    cached &&
    cached.status === tool?.status &&
    cached.message === tool?.message &&
    cached.error === tool?.error &&
    cached.argumentsRef === tool?.arguments &&
    cached.resultRef === tool?.result
  ) {
    return cached.html
  }

  const detail = formatToolDetail(tool)
  const html = renderFormattedToolDetail(detail)
  toolDetailCache.set(key, {
    status: tool?.status,
    message: tool?.message,
    error: tool?.error,
    argumentsRef: tool?.arguments,
    resultRef: tool?.result,
    html,
  })
  if (toolDetailCache.size > 32) {
    toolDetailCache.delete(toolDetailCache.keys().next().value)
  }
  return html
}

</script>

<style scoped>
.assistant-turn-view {
  --trace-accent: #4f8cff;
  --trace-accent-strong: #2f6fe4;
  --trace-accent-soft: #9fc2ff;
  --trace-accent-faint: rgba(79, 140, 255, 0.16);
  --trace-accent-line: rgba(79, 140, 255, 0.3);
  --trace-accent-glow: rgba(79, 140, 255, 0.3);
  --trace-dot-idle: #7f8fa6;
  --trace-dot-live: #5b98ff;
  --trace-thought-color: #5875a2;
  --trace-live-text: #4f8cff;
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 2px;
  background: var(--el-bg-color);
  box-sizing: border-box;
  contain: layout paint;
  overflow: hidden;
  transition: border-color 0.32s ease, background 0.32s ease, box-shadow 0.32s ease, transform 0.32s ease;
}

.assistant-turn-view.is-streaming {
  border-color: rgba(79, 140, 255, 0.24);
  box-shadow: 0 12px 28px rgba(79, 140, 255, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.18);
  animation: stream-shell-breathe 3.8s ease-in-out infinite;
}

.assistant-turn-view.phase-thinking {
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.035) 0%, var(--el-bg-color) 30%);
}

.assistant-turn-view.phase-tool {
  border-color: rgba(79, 140, 255, 0.3);
  box-shadow: 0 14px 32px rgba(79, 140, 255, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.assistant-turn-view.phase-responding {
  border-color: rgba(79, 140, 255, 0.28);
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.055) 0%, var(--el-bg-color) 26%);
}

.assistant-turn-view.phase-final,
.assistant-turn-view.has-final-content {
  border-color: rgba(79, 140, 255, 0.18);
  box-shadow: 0 8px 20px rgba(79, 140, 255, 0.05);
}

.trace-archive {
  width: 100%;
  border-radius: 2px;
}

.trace-title-row {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.trace-title,
.tool-name {
  font-size: 13px;
  line-height: 1.45;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

.trace-duration,
.trace-summary,
.tool-status {
  font-size: 12px;
  line-height: 1.45;
  color: var(--el-text-color-secondary);
}

.trace-summary {
  color: var(--el-text-color-secondary);
  opacity: 0.88;
}

.trace-summary,
.tool-status {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-collapse {
  border: 0;
  background: transparent;
}

.trace-collapse :deep(.el-collapse-item__header) {
  min-height: 24px;
  line-height: 1.45;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: inherit;
}

.trace-collapse :deep(.el-collapse-item__wrap) {
  border: 0;
  background: transparent;
}

.trace-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.trace-collapse :deep(.el-collapse-item__arrow) {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}

.trace-archive-collapse :deep(.el-collapse-item__header) {
  justify-content: space-between;
}

.process-collapse :deep(.el-collapse-item__header),
.tool-collapse :deep(.el-collapse-item__header) {
  justify-content: space-between;
}

.archive-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 10px;
  contain: layout paint;
}

.live-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timeline-entry {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  width: 100%;
  transition: transform 0.28s ease, opacity 0.28s ease;
}

.process-rail {
  position: relative;
  min-height: 30px;
}

.process-rail::before {
  content: '';
  position: absolute;
  left: 8px;
  top: -10px;
  bottom: -10px;
  width: 1px;
  background: linear-gradient(180deg, transparent 0%, var(--trace-accent-line) 14%, var(--trace-accent-line) 86%, transparent 100%);
}

.process-dot {
  position: absolute;
  left: 4px;
  top: 7px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--trace-dot-idle);
  border: 1px solid rgba(255, 255, 255, 0.18);
  box-shadow: 0 0 0 3px rgba(79, 140, 255, 0.08);
  z-index: 1;
  transition: transform 0.24s ease, box-shadow 0.24s ease, background-color 0.24s ease, border-color 0.24s ease;
}

.process-dot.is-live {
  background: var(--trace-dot-live);
  border-color: rgba(255, 255, 255, 0.34);
  box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.12);
  animation: thinking-pulse 1.55s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.process-main {
  min-width: 0;
  padding: 1px 0;
}

.thought-collapse,
.tool-collapse {
  width: 100%;
}

.tool-dot {
  width: 8px;
  height: 8px;
  left: 4px;
  top: 7px;
  border-radius: 50%;
  background: var(--trace-accent);
  border: 1px solid rgba(255, 255, 255, 0.22);
  box-shadow: 0 0 0 3px rgba(79, 140, 255, 0.1);
}

.tool-dot.is-loading {
  background: var(--trace-accent-strong);
  border-color: rgba(255, 255, 255, 0.38);
  box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.14);
  animation: thinking-pulse 1.35s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.tool-dot.is-starting {
  transform: scale(1.18);
  box-shadow: 0 0 0 6px rgba(79, 140, 255, 0.1);
}

.tool-dot.is-settling {
  animation: tool-dot-settle 0.72s cubic-bezier(0.22, 1, 0.36, 1) 1;
}

.tool-dot.is-complete {
  box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.08);
}

.tool-dot.is-error {
  background: #f56c6c;
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow: 0 0 0 3px rgba(245, 108, 108, 0.12);
}

.thought-detail {
  padding: 6px 0 4px;
  max-height: 240px;
  overflow-y: auto;
  contain: layout paint;
  transition: padding 0.28s ease, background-position 0.28s ease, border-color 0.28s ease, box-shadow 0.28s ease;
}

.thought-detail.is-live {
  padding-left: 14px;
  background-image: repeating-linear-gradient(
    180deg,
    rgba(159, 194, 255, 0.14) 0px,
    rgba(159, 194, 255, 0.14) 22px,
    var(--trace-accent-soft) 42px,
    var(--trace-accent) 66px,
    #e8f1ff 86px,
    var(--trace-accent-strong) 106px,
    rgba(159, 194, 255, 0.14) 132px
  );
  background-repeat: repeat-y;
  background-position: 0 8px;
  background-size: 2px 132px;
  animation: thinking-rail-flow 4.2s linear infinite;
}

.thought-text {
  color: var(--trace-thought-color);
  font-size: 14px;
  line-height: 1.68;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: break-word;
  opacity: 0.96;
  transition: color 0.25s ease, text-shadow 0.25s ease;
}

.trace-title-row.is-live .trace-title,
.trace-title-row.is-live .trace-duration,
.trace-title-row.is-live .tool-name,
.trace-title-row.is-live .tool-status,
.thought-text.is-live {
  color: var(--trace-live-text);
  text-shadow: 0 0 8px rgba(79, 140, 255, 0.08);
  animation: thinking-breathe 3.6s ease-in-out infinite;
}

@supports ((-webkit-background-clip: text) or (background-clip: text)) {
  .trace-title-row.is-live .trace-title,
  .trace-title-row.is-live .trace-duration,
  .trace-title-row.is-live .tool-name,
  .trace-title-row.is-live .tool-status,
  .thought-text.is-live {
    background: linear-gradient(110deg, var(--trace-live-text) 0%, var(--trace-accent-soft) 24%, #e7f0ff 42%, var(--trace-accent) 58%, var(--trace-accent-strong) 76%, var(--trace-live-text) 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    color: transparent;
    animation: thinking-shimmer 5.2s linear infinite, thinking-breathe 3.6s ease-in-out infinite;
  }
}

@keyframes thinking-shimmer {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

@keyframes thinking-breathe {
  0%, 100% {
    opacity: 0.96;
    filter: saturate(0.98);
  }
  50% {
    opacity: 1;
    filter: saturate(1.04);
  }
}

@keyframes thinking-pulse {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.1);
  }
  50% {
    transform: scale(1.08);
    box-shadow: 0 0 0 7px rgba(79, 140, 255, 0.06);
  }
}

@keyframes thinking-rail-flow {
  0% { background-position: 0 8px; }
  100% { background-position: 0 140px; }
}

@keyframes stream-shell-breathe {
  0%, 100% {
    border-color: rgba(79, 140, 255, 0.22);
    box-shadow: 0 10px 24px rgba(79, 140, 255, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.14);
  }
  50% {
    border-color: rgba(79, 140, 255, 0.3);
    box-shadow: 0 14px 30px rgba(79, 140, 255, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.22);
  }
}

@keyframes tool-panel-breathe {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.992);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.08);
  }
  50% {
    opacity: 1;
    transform: scale(1);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.14);
  }
}

@keyframes tool-dot-settle {
  0% {
    transform: scale(1.14);
    box-shadow: 0 0 0 7px rgba(79, 140, 255, 0.08);
  }
  100% {
    transform: scale(1);
    box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.08);
  }
}

@keyframes tool-title-settle {
  0% {
    transform: translateX(3px);
    opacity: 0.88;
  }
  100% {
    transform: translateX(0);
    opacity: 1;
  }
}

@keyframes tool-detail-land {
  0% {
    opacity: 0.72;
    transform: translateY(5px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes tool-detail-settle-frame {
  0% {
    transform: translateY(3px);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.14);
  }
  100% {
    transform: translateY(0);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.08);
  }
}

@keyframes tool-shell-settle {
  0% {
    opacity: 1;
    transform: scale(1);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.16);
  }
  100% {
    opacity: 0.86;
    transform: scale(0.996);
    box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.09);
  }
}

.tool-text-row {
  position: relative;
  padding-left: 0;
  min-width: 0;
}

.tool-entry .process-main {
  position: relative;
  padding-right: 6px;
}

.tool-entry .process-main::before {
  content: '';
  position: absolute;
  inset: -4px -8px -4px -12px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.08) 0%, rgba(79, 140, 255, 0.03) 100%);
  opacity: 0;
  transform: scale(0.986);
  transform-origin: center center;
  pointer-events: none;
  transition: opacity 0.34s ease, transform 0.34s ease, box-shadow 0.34s ease, background 0.34s ease;
}

.tool-entry.is-loading .process-main::before,
.tool-entry.is-starting .process-main::before,
.tool-entry.is-settling .process-main::before {
  opacity: 1;
  transform: scale(1);
}

.tool-entry.is-loading .process-main::before {
  box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.08);
  animation: tool-panel-breathe 2.8s ease-in-out infinite;
}

.tool-entry.is-settling .process-main::before {
  opacity: 0.86;
  animation: tool-shell-settle 0.72s cubic-bezier(0.22, 1, 0.36, 1) 1;
}

.tool-entry.is-error .process-main::before {
  opacity: 0.92;
  transform: scale(1);
  background: linear-gradient(180deg, rgba(245, 108, 108, 0.08) 0%, rgba(245, 108, 108, 0.03) 100%);
  box-shadow: inset 0 0 0 1px rgba(245, 108, 108, 0.12);
}

.tool-collapse {
  width: 100%;
}

.tool-title-row {
  position: relative;
  width: 100%;
  padding-right: 4px;
  transition: transform 0.28s ease, opacity 0.28s ease;
}

.tool-title-row::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -5px;
  width: min(240px, calc(100% - 22px));
  max-width: 100%;
  height: 1px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(79, 140, 255, 0.78) 0%, rgba(79, 140, 255, 0.2) 54%, transparent 100%);
  opacity: 0;
  transform: scaleX(0.16);
  transform-origin: left center;
  transition: opacity 0.3s ease, transform 0.3s ease;
  pointer-events: none;
}

.tool-entry.is-loading .tool-title-row::after {
  opacity: 0.5;
  transform: scaleX(0.9);
}

.tool-entry.is-starting .tool-title-row {
  transform: translateX(2px);
}

.tool-entry.is-settling .tool-title-row {
  animation: tool-title-settle 0.68s cubic-bezier(0.22, 1, 0.36, 1) 1;
}

.tool-entry.is-success .tool-status,
.tool-entry.is-complete .tool-status {
  color: var(--trace-accent-strong);
}

.tool-entry.is-error .tool-status {
  color: #d96565;
}

.tool-name {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.tool-status {
  flex: 1;
}

.tool-detail {
  width: min(760px, 100%);
  height: 220px;
  max-height: 38vh;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 2px;
  background: var(--el-bg-color);
  padding: 10px;
  box-sizing: border-box;
  margin-top: 7px;
  contain: layout paint;
  transition: border-color 0.28s ease, background 0.28s ease, box-shadow 0.28s ease, transform 0.28s ease;
}

.tool-entry .tool-detail {
  position: relative;
  transform-origin: top left;
}

.tool-detail.is-live {
  border-color: rgba(79, 140, 255, 0.32);
  background: linear-gradient(180deg, rgba(79, 140, 255, 0.08) 0%, var(--el-bg-color) 28%);
  box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.08);
}

.tool-entry.is-settling .tool-detail {
  animation: tool-detail-settle-frame 0.72s cubic-bezier(0.22, 1, 0.36, 1) 1;
}

.tool-entry.is-error .tool-detail {
  border-color: rgba(245, 108, 108, 0.28);
  box-shadow: inset 0 0 0 1px rgba(245, 108, 108, 0.08);
}

.tool-detail-rendered {
  position: relative;
  z-index: 1;
  transition: opacity 0.28s ease, transform 0.34s ease, filter 0.34s ease;
}

.tool-detail-rendered.is-loading {
  opacity: 0.98;
}

.tool-detail-rendered.is-settling {
  animation: tool-detail-land 0.66s cubic-bezier(0.22, 1, 0.36, 1) 1;
}

.tool-detail-rendered.is-error {
  filter: saturate(0.94);
}

.tool-detail pre {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: break-word;
}

.content-entry {
  align-items: stretch;
}

.content-main {
  min-width: 0;
  padding: 4px 0 10px;
  transition: opacity 0.28s ease, transform 0.28s ease;
}

.content-rail::before {
  top: -8px;
  bottom: -8px;
}

.archive-body > .timeline-entry:first-child .process-rail::before,
.live-body > .timeline-entry:first-child .process-rail::before {
  top: 8px;
}

.message-bubble {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: 16px;
  line-height: 1.65;
  color: var(--el-text-color-primary);
  word-break: break-word;
  overflow-wrap: break-word;
  min-width: 0;
}

.turn-final-content {
  width: 100%;
  position: relative;
  padding-top: 2px;
}

.turn-final-content::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 48px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--trace-accent), rgba(79, 140, 255, 0));
  opacity: 0.48;
}

.trace-entry-enter-active,
.trace-entry-leave-active,
.trace-entry-move {
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.24s ease;
}

.trace-entry-enter-from,
.trace-entry-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.985);
}

.final-bubble-enter-active,
.final-bubble-leave-active {
  transition: opacity 0.34s ease, transform 0.34s cubic-bezier(0.22, 1, 0.36, 1), filter 0.34s ease;
}

.final-bubble-enter-from,
.final-bubble-leave-to {
  opacity: 0;
  transform: translateY(10px);
  filter: blur(2px);
}

.message-bubble :deep(*) {
  max-width: 100%;
  box-sizing: border-box;
}

.message-bubble :deep(p) {
  margin: 0.45em 0;
}

.message-bubble :deep(pre) {
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: break-word;
  border-radius: 2px;
}

.message-bubble :deep(code) {
  background: var(--el-fill-color-darker);
  color: var(--el-color-warning);
  padding: 2px 6px;
  border-radius: 2px;
  font-family: monospace;
  word-break: break-all;
  overflow-wrap: break-word;
}

.message-bubble :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 2px;
}

.message-bubble :deep(ol),
.message-bubble :deep(ul) {
  padding-left: 1.5em;
  margin: 0.5em 0;
}

.message-bubble :deep(ol) {
  list-style-type: decimal;
}

.message-bubble :deep(ul) {
  list-style-type: disc;
}

.message-bubble :deep(li) {
  margin-bottom: 0.25em;
  padding-left: 0.15em;
}

.message-bubble :deep(.table-wrapper) {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 12px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 2px;
  box-sizing: border-box;
}

.message-bubble :deep(table) {
  width: 100%;
  min-width: max-content;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
  border: none;
  display: table;
}

.message-bubble :deep(th),
.message-bubble :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 8px 12px;
  text-align: left;
  vertical-align: middle;
  min-width: 80px;
}

.message-bubble :deep(th) {
  background-color: var(--el-fill-color-lighter);
  font-weight: 600;
  color: var(--el-text-color-primary);
  white-space: nowrap;
}

.message-bubble :deep(tr:nth-child(2n)) {
  background-color: var(--el-fill-color-extra-light);
}

.message-bubble :deep(.ai-photo-wrap) {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px;
  margin: 8px 0;
  border-radius: 2px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-lighter);
}

.message-bubble :deep(.ai-photo-image) {
  display: block;
  border-radius: 2px;
  cursor: zoom-in;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color-page);
}

.message-bubble :deep(.ai-photo-image.avatar) {
  width: 96px;
  height: 96px;
  object-fit: cover;
}

.message-bubble :deep(.ai-photo-image.id_photo) {
  width: min(220px, 100%);
  max-height: 300px;
  object-fit: contain;
}

.message-bubble :deep(.ai-photo-label) {
  font-size: 12px;
  line-height: 1;
  padding: 3px 8px;
  border-radius: 2px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
}

.message-bubble :deep(.sensitive-tag) {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background: rgba(245, 108, 108, 0.08);
  color: #f56c6c;
  border-radius: 2px;
  font-size: 0.9em;
  margin: 0 2px;
  gap: 4px;
}

.message-bubble :deep(.sensitive-tag.phone) {
  background: rgba(64, 158, 255, 0.08);
  color: #409eff;
}

.message-bubble :deep(.sensitive-tag.revealed) {
  background: rgba(103, 194, 58, 0.08);
  color: #4a9c2a;
  border: 1px solid rgba(103, 194, 58, 0.3);
}

html.dark .assistant-turn-view {
  --trace-accent: #6ea8ff;
  --trace-accent-strong: #3d7dff;
  --trace-accent-soft: #bdd6ff;
  --trace-accent-faint: rgba(110, 168, 255, 0.18);
  --trace-accent-line: rgba(110, 168, 255, 0.26);
  --trace-accent-glow: rgba(110, 168, 255, 0.34);
  --trace-dot-idle: #98a8bf;
  --trace-dot-live: #7fb3ff;
  --trace-thought-color: #b7c7de;
  --trace-live-text: #a8cbff;
  background: #1d1e1f;
  border-color: #363637;
}

html.dark .assistant-turn-view.is-streaming {
  border-color: rgba(110, 168, 255, 0.26);
  box-shadow: 0 14px 30px rgba(13, 43, 92, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

html.dark .assistant-turn-view.phase-thinking {
  background: linear-gradient(180deg, rgba(110, 168, 255, 0.06) 0%, #1d1e1f 28%);
}

html.dark .assistant-turn-view.phase-responding {
  background: linear-gradient(180deg, rgba(110, 168, 255, 0.08) 0%, #1d1e1f 24%);
}

html.dark .trace-title,
html.dark .tool-name {
  color: #d7e4fb;
}

html.dark .trace-duration,
html.dark .trace-summary,
html.dark .tool-status,
html.dark .thought-text,
html.dark .tool-detail pre {
  color: #b7c7de;
}

html.dark .message-bubble {
  color: #e5eaf3;
}

html.dark .tool-detail {
  background: #1d1e1f;
  border-color: #363637;
}

html.dark .tool-detail.is-live {
  border-color: rgba(110, 168, 255, 0.34);
  background: linear-gradient(180deg, rgba(110, 168, 255, 0.12) 0%, #1d1e1f 28%);
  box-shadow: inset 0 0 0 1px rgba(110, 168, 255, 0.12);
}

html.dark .tool-entry.is-loading .process-main::before {
  box-shadow: inset 0 0 0 1px rgba(110, 168, 255, 0.12);
}

html.dark .tool-title-row::after {
  background: linear-gradient(90deg, rgba(110, 168, 255, 0.9) 0%, rgba(110, 168, 255, 0.26) 56%, transparent 100%);
}

html.dark .tool-entry.is-success .tool-status,
html.dark .tool-entry.is-complete .tool-status {
  color: #b8d6ff;
}

html.dark .tool-entry.is-error .tool-status {
  color: #ff9d9d;
}

html.dark .message-bubble :deep(code) {
  background: #363637;
  color: #e6a23c;
}

html.dark .message-bubble :deep(th) {
  color: #e5eaf3;
  background-color: #242629;
}

html.dark .message-bubble :deep(td) {
  color: #cfd3dc;
}

html.dark .message-bubble :deep(tr:nth-child(2n)) {
  background-color: rgba(255, 255, 255, 0.03);
}

html.dark .message-bubble :deep(.table-wrapper) {
  border-color: #363637;
}

html.dark .message-bubble :deep(.ai-photo-wrap) {
  background: #242629;
  border-color: #3a3d42;
}

html.dark .message-bubble :deep(.ai-photo-image) {
  border-color: #3a3d42;
  background: #1a1b1d;
}

html.dark .message-bubble :deep(.sensitive-tag) {
  background: rgba(245, 108, 108, 0.15);
  color: #f89898;
}

html.dark .message-bubble :deep(.sensitive-tag.phone) {
  background: rgba(64, 158, 255, 0.15);
  color: #79bbff;
}

html.dark .message-bubble :deep(.sensitive-tag.revealed) {
  background: rgba(103, 194, 58, 0.12);
  color: #85ce61;
  border-color: rgba(103, 194, 58, 0.25);
}
</style>
