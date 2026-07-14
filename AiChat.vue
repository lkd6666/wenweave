<template>
  <div class="ai-chat">
    <div class="chat-container">
      <!-- 左侧会话列表 (桌面版) -->
      <div class="session-list" v-if="!isMobile">
        <div class="session-header">
          <span>会话记录</span>
          <el-button type="primary" :icon="Plus" circle size="small" @click="newSession" />
        </div>
        <!-- 搜索框 -->
        <div class="session-search">
          <el-input
            v-model="sessionKeyword"
            placeholder="搜索会话..."
            :prefix-icon="Search"
            clearable
            size="small"
            @input="handleSessionSearch"
          />
        </div>
        <div class="session-items">
          <!-- 加载中 -->
          <div v-if="sessionsLoading" class="sessions-loading-wrapper" style="display: flex; flex-direction: column; align-items: center; padding: 40px 0; color: var(--el-text-color-secondary);">
            <el-icon class="is-loading" :size="28" style="margin-bottom: 10px; color: var(--el-color-primary);"><Loading /></el-icon>
            <p style="margin: 0; font-size: 13px;">加载会话中...</p>
          </div>
          
          <template v-else>
            <div
              v-for="session in sessions"
            :key="session.session_id"
            class="session-item"
            :class="getSessionItemClass(session)"
            @click="switchSession(session.session_id)"
          >
            <!-- 左侧：状态图标 -->
            <div class="session-icon-wrapper">
              <el-icon v-if="isSessionStreaming(session.session_id)" class="session-icon streaming"><Loading /></el-icon>
              <el-icon v-else-if="session.task_status === 'running'" class="session-icon processing"><Loading /></el-icon>
              <el-icon v-else-if="session.task_status === 'pending'" class="session-icon pending"><Clock /></el-icon>
              <el-icon v-else-if="completedUnviewedSessions.has(session.session_id)" class="session-icon task-completed"><Check /></el-icon>
              <el-icon v-else-if="isTitlePending(session.session_id)" class="session-icon generating"><Loading /></el-icon>
              <el-icon v-else class="session-icon"><ChatDotRound /></el-icon>
            </div>
            <!-- 中间：标题和状态 -->
            <div class="session-info">
              <div class="session-title-row">
                <span 
                  class="session-title" 
                  :class="{ 'is-temp': isTempTitle(session.title), 'is-generating': isTitlePending(session.session_id) }"
                  :title="formatTokenTooltip(session)"
                >
                  {{ getDisplayTitle(session) }}
                </span>
                <!-- 状态标签 -->
                <span v-if="isSessionStreaming(session.session_id)" class="status-dot streaming" title="正在输出"></span>
                <span v-else-if="session.task_status === 'running'" class="status-dot processing" title="后台处理中"></span>
                <span v-else-if="session.task_status === 'pending'" class="status-dot pending" title="队列等待中"></span>
                <span v-else-if="completedUnviewedSessions.has(session.session_id)" class="status-dot task-completed" title="任务已完成"></span>
              </div>
              <div class="session-meta">
                <span class="session-time">{{ formatSessionTime(session.last_time) }}</span>
                <span v-if="session.msg_count" class="session-count">{{ session.msg_count }}条</span>
              </div>
            </div>
            <!-- 右侧：状态文字（仅在有状态时显示） -->
            <div class="session-status" v-if="getSessionStatus(session)">
              <span class="status-text" :class="getSessionStatus(session).class">
                {{ getSessionStatus(session).text }}
              </span>
            </div>
          </div>
          <!-- 空状态 -->
          <div class="empty-sessions" v-if="sessions.length === 0 && !loadingMore">
            <el-icon class="empty-icon"><ChatDotRound /></el-icon>
            <p>暂无会话记录</p>
            <el-button type="primary" size="small" @click="newSession">开始新对话</el-button>
          </div>
          <!-- 加载更多 -->
          <div class="load-more" v-if="hasMoreSessions">
            <el-button link type="primary" :loading="loadingMore" @click="loadMoreSessions">
              {{ loadingMore ? '加载中...' : '查看更早' }}
            </el-button>
          </div>
          <div class="no-more" v-else-if="sessions.length > 0">
              <span>— 没有更多了 —</span>
            </div>
          </template>
        </div>
      </div>

      <!-- 移动端会话抽屉 -->
      <el-drawer
        v-model="drawerVisible"
        title="会话记录"
        direction="ltr"
        size="100%"
        v-if="isMobile"
      >
        <div class="session-header">
          <span>会话记录</span>
          <el-button type="primary" :icon="Plus" circle size="small" @click="newSession" />
        </div>
        <!-- 搜索框 -->
        <div class="session-search">
          <el-input
            v-model="sessionKeyword"
            placeholder="搜索会话..."
            :prefix-icon="Search"
            clearable
            size="small"
            @input="handleSessionSearch"
          />
        </div>
        <div class="session-items">
          <!-- 加载中 -->
          <div v-if="sessionsLoading" class="sessions-loading-wrapper" style="display: flex; flex-direction: column; align-items: center; padding: 40px 0; color: var(--el-text-color-secondary);">
            <el-icon class="is-loading" :size="28" style="margin-bottom: 10px; color: var(--el-color-primary);"><Loading /></el-icon>
            <p style="margin: 0; font-size: 13px;">加载会话中...</p>
          </div>
          
          <template v-else>
            <div
              v-for="session in sessions"
            :key="session.session_id"
            class="session-item"
            :class="getSessionItemClass(session)"
            @click="switchSession(session.session_id)"
          >
            <!-- 左侧：状态图标 -->
            <div class="session-icon-wrapper">
              <el-icon v-if="isSessionStreaming(session.session_id)" class="session-icon streaming"><Loading /></el-icon>
              <el-icon v-else-if="session.task_status === 'running'" class="session-icon processing"><Loading /></el-icon>
              <el-icon v-else-if="session.task_status === 'pending'" class="session-icon pending"><Clock /></el-icon>
              <el-icon v-else-if="completedUnviewedSessions.has(session.session_id)" class="session-icon task-completed"><Check /></el-icon>
              <el-icon v-else-if="isTitlePending(session.session_id)" class="session-icon generating"><Loading /></el-icon>
              <el-icon v-else class="session-icon"><ChatDotRound /></el-icon>
            </div>
            <!-- 中间：标题和状态 -->
            <div class="session-info">
              <div class="session-title-row">
                <span 
                  class="session-title" 
                  :class="{ 'is-temp': isTempTitle(session.title), 'is-generating': isTitlePending(session.session_id) }"
                  :title="formatTokenTooltip(session)"
                >
                  {{ getDisplayTitle(session) }}
                </span>
                <!-- 状态标签 -->
                <span v-if="isSessionStreaming(session.session_id)" class="status-dot streaming" title="正在输出"></span>
                <span v-else-if="session.task_status === 'running'" class="status-dot processing" title="后台处理中"></span>
                <span v-else-if="session.task_status === 'pending'" class="status-dot pending" title="队列等待中"></span>
                <span v-else-if="completedUnviewedSessions.has(session.session_id)" class="status-dot task-completed" title="任务已完成"></span>
              </div>
              <div class="session-meta">
                <span class="session-time">{{ formatSessionTime(session.last_time) }}</span>
                <span v-if="session.msg_count" class="session-count">{{ session.msg_count }}条</span>
              </div>
            </div>
            <!-- 右侧：状态文字（仅在有状态时显示） -->
            <div class="session-status" v-if="getSessionStatus(session)">
              <span class="status-text" :class="getSessionStatus(session).class">
                {{ getSessionStatus(session).text }}
              </span>
            </div>
          </div>
          <!-- 空状态 -->
          <div class="empty-sessions" v-if="sessions.length === 0 && !loadingMore">
            <el-icon class="empty-icon"><ChatDotRound /></el-icon>
            <p>暂无会话记录</p>
            <el-button type="primary" size="small" @click="newSession">开始新对话</el-button>
          </div>
          <!-- 加载更多 -->
          <div class="load-more" v-if="hasMoreSessions">
            <el-button link type="primary" :loading="loadingMore" @click="loadMoreSessions">
              {{ loadingMore ? '加载中...' : '查看更早' }}
            </el-button>
          </div>
          <div class="no-more" v-else-if="sessions.length > 0">
              <span>— 没有更多了 —</span>
            </div>
          </template>
        </div>
      </el-drawer>

      <!-- 右侧聊天区 -->
      <div class="chat-main">
        <!-- 移动端标题栏 -->
        <div class="mobile-chat-header" v-if="isMobile">
          <el-button link :icon="Operation" @click="drawerVisible = true">历史记录</el-button>
          <span class="current-session-title">{{ currentSessionTitle }}</span>
          <el-button link :icon="Plus" @click="newSession">新建</el-button>
        </div>
        <!-- 消息列表 -->
        <div class="message-list" ref="messageListRef" @scroll="handleScroll" @click="handleSensitiveClick">
          <div class="welcome-tip" v-if="messages.length === 0 && !historyLoading">
            <el-icon class="welcome-icon"><ChatDotRound /></el-icon>
            <h3>您好，我是学工智能助手</h3>
            <p>我可以帮您查询学生数据、请假统计、就业情况等信息。</p>
            <div class="quick-questions">
              <span @click="sendQuickQuestion('本班最近一周请假情况如何？')">
                📊 本班最近一周请假情况如何？
              </span>
              <span @click="sendQuickQuestion('就业率统计')">
                📈 就业率统计
              </span>
              <span @click="sendQuickQuestion('查询张三的学生信息')">
                👤 查询学生信息
              </span>
            </div>
          </div>

          <!-- 加载中 -->
          <div v-if="historyLoading" class="history-loading-wrapper" style="display: flex; flex-direction: column; align-items: center; padding: 60px 0; color: var(--el-text-color-secondary);">
            <el-icon class="is-loading" :size="32" style="margin-bottom: 12px; color: var(--el-color-primary);"><Loading /></el-icon>
            <p style="margin: 0; font-size: 14px;">正在加载会话记录...</p>
          </div>

          <template v-else>
            <!-- 懒加载：更早历史入口 -->
            <div v-if="hasMoreHistory" class="load-earlier-history">
              <el-button
                link
                type="primary"
                :loading="loadingMoreHistory"
                @click="loadMoreHistory"
                style="font-size:13px;"
              >
                {{ loadingMoreHistory ? '加载中...' : '查看更早的消息' }}
              </el-button>
            </div>
            <div v-else-if="messages.length > 0 && !hasMoreHistory && oldestMessageId > 0"
                 class="load-earlier-history no-more">
              <span>— 已显示全部历史 —</span>
            </div>

            <div
              v-for="(msg, index) in messages"
              :key="getMessageRenderKey(msg, index)"
              class="message-item"
              :class="msg.role"
            >
            <div class="message-avatar">
              <el-avatar v-if="msg.role === 'user'" :size="36" :src="userAvatar" :icon="UserFilled" />
              <el-avatar v-else :size="36">
                <el-icon><ChatDotRound /></el-icon>
              </el-avatar>
            </div>
            <div class="message-content">
              <div v-if="msg.isEditing" class="edit-message-area" style="width: 100%; margin-top: 8px;">
                <el-input
                  v-model="msg.editContent"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 8 }"
                  placeholder="修改此消息..."
                  style="margin-bottom: 8px;"
                />
                <div style="text-align: right;">
                  <el-button size="small" @click="cancelEdit(msg)" :disabled="msg.submitLoading">取消</el-button>
                  <el-button type="primary" size="small" @click="submitEdit(msg)" :loading="msg.submitLoading">发送并替换其后对话</el-button>
                </div>
              </div>
                <template v-else>
                <template v-if="msg.role === 'assistant'">
                  <assistant-turn-timeline
                    :key="`${getMessageRenderKey(msg, index)}-timeline`"
                    :blocks="msg.renderBlocks"
                    :fallback-content="msg.content"
                    :thinking="false"
                    :reasoning-duration="msg.reasoning_duration || 0"
                    :render-markdown="renderMarkdown"
                  />
                </template>
                <div v-else class="message-bubble" v-html="renderMarkdown(msg.content)"></div>
              </template>
              <div v-if="msg.role === 'assistant' && msg.ai_provider" class="message-disclaimer">
                AI回答可能存在误差，仅供参考，请谨慎甄别。
              </div>
              <!-- 模型信息标签（仅assistant消息且有模型信息时显示） -->
              <div v-if="msg.role === 'assistant' && msg.ai_provider" class="message-model-tag">
                <el-tag size="small" type="info" effect="plain">
                  {{ msg.ai_provider === 'deepseek' ? 'DeepSeek' : '豆包' }} · {{ msg.ai_model }}
                </el-tag>
              </div>
              <div class="message-time">
                {{ msg.time }}
                <el-button 
                  v-if="msg.role === 'user'" 
                  link 
                  type="primary" 
                  style="margin-left: 8px; font-size: 12px; opacity: 0.8; padding: 0; min-height: auto; height: auto;"
                  @click="editMessage(msg)"
                >
                  <el-icon style="margin-right: 2px;"><Edit /></el-icon> 修改重新提问
                </el-button>
              </div>
            </div>
          </div>

          <!-- 流式回复中 -->
          <transition name="streaming-turn" appear>
            <div
              class="message-item assistant streaming-message"
              v-if="streamingReasoningList.length > 0 || streamingContent || thinking"
              :class="{
                'is-thinking': thinking,
                'has-live-content': !!streamingContent,
                'has-live-trace': streamingReasoningList.length > 0
              }"
            >
              <div class="message-avatar">
                <el-avatar :size="36">
                  <el-icon><ChatDotRound /></el-icon>
                </el-avatar>
              </div>
              <div class="message-content">
                <assistant-turn-timeline
                  :key="getStreamingTimelineKey()"
                  :blocks="streamingReasoningList"
                  :fallback-content="streamingContent"
                  :thinking="thinking"
                  :reasoning-duration="reasoningDuration"
                  :render-markdown="renderMarkdown"
                />
                <!-- 🔧 继续按钮：达到工具调用上限时显示 -->
                <div class="continue-prompt" v-if="showContinueButton">
                  <div class="continue-prompt-inner">
                    <span class="continue-text">已完成 {{ continueIteration }} 轮工具调用，点击继续获取更完整的结果</span>
                    <el-button type="primary" size="small" :loading="continueLoading" @click="handleContinue">
                      <el-icon v-if="!continueLoading"><Promotion /></el-icon>
                      继续分析
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </transition>
          </template>
        </div>

        <!-- 输入区 -->
        <div class="input-area">
          <template v-if="isMobile">
            <div class="mobile-composer-toolbar">
              <el-popover
                v-if="contextUsageVisible"
                :trigger="isMobile ? 'click' : 'hover'"
                placement="top-start"
                :width="isMobile ? 286 : 320"
                :disabled="!hasContextPopoverContent"
                popper-class="context-usage-popover"
              >
                <template #reference>
                  <button
                    type="button"
                    class="context-status context-indicator mobile-context-status"
                    :class="`is-${contextUsageTone}`"
                    @mousedown.stop
                    @touchstart.stop
                  >
                    <span
                      class="context-ring"
                      :style="{ '--context-usage-angle': `${Math.max(Math.min(contextStats.usage_percent, 100), 0) * 3.6}deg` }"
                    >
                      <span class="context-ring-core"></span>
                    </span>
                    <span class="context-indicator-text">{{ contextPercentText }}</span>
                  </button>
                </template>
                <div class="context-usage-panel">
                  <div class="context-usage-header">
                    <div class="context-usage-header-main">
                      <div class="context-usage-title">上下文窗口</div>
                      <div class="context-usage-summary">{{ contextSummaryText }}</div>
                    </div>
                    <span class="context-usage-percent" :class="`is-${contextUsageTone}`">{{ contextPercentText }}</span>
                  </div>
                  <div v-if="contextBreakdownItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">上下文明细</div>
                    <div v-for="item in contextBreakdownItems" :key="`context-breakdown-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextToolMetaItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">工具处理</div>
                    <div v-for="item in contextToolMetaItems" :key="`context-tool-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextReplayItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">工具回放</div>
                    <div v-for="item in contextReplayItems" :key="`context-replay-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextRouteItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">路由信息</div>
                    <div v-for="item in contextRouteItems" :key="`context-route-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextStats.tool_full_replayed_count > 0 || contextStats.is_estimate" class="context-usage-footer">
                    <span v-if="contextStats.tool_full_replayed_count > 0" class="context-usage-flag">直带最近工具结果</span>
                    <span v-if="contextStats.is_estimate" class="context-usage-flag is-estimate">估算值（历史数据）</span>
                  </div>
                </div>
              </el-popover>
              <div class="mobile-toolbar-scroll" @mousedown.stop @touchstart.stop>
                <button
                  v-if="aiConfig.webSearchEnabled"
                  type="button"
                  class="option-select-chip web-search-toggle"
                  :class="{ 'is-active': currentSessionWebSearchEnabled, 'is-disabled': thinking }"
                  :disabled="thinking"
                  @click="toggleWebSearchMode"
                >
                  <el-icon class="option-select-indicator" aria-hidden="true"><Search /></el-icon>
                  <span class="web-search-label">搜索</span>
                </button>
                <div class="cloud-proxy-control">
                  <el-tooltip 
                    content="开启后可在等待回复时切换会话或离开页面，AI将在后台继续处理，完成后通知您" 
                    placement="top"
                  >
                    <button
                      type="button"
                      class="option-select-chip cloud-proxy-toggle"
                      :class="{ 'is-active': cloudProxyMode }"
                      @click="toggleCloudProxyMode"
                    >
                      <el-icon class="option-select-indicator" aria-hidden="true"><component :is="CloudIcon" /></el-icon>
                      <span class="cloud-proxy-label">后台</span>
                    </button>
                  </el-tooltip>
                  <el-badge v-if="pendingTaskCount > 0" :value="pendingTaskCount" class="task-badge">
                    <el-button link type="primary" size="small" @click="showPendingTasks">
                      队列
                    </el-button>
                  </el-badge>
                </div>
                <div
                  v-if="aiConfig.manualSelectEnabled && aiConfig.availableModels.length"
                  class="model-selector mobile-model-selector"
                >
                  <el-select v-model="aiConfig.selectedModel" size="small" :disabled="thinking" placeholder="模型" @change="handleModelChange">
                    <el-option v-for="item in aiConfig.availableModels" :key="item.model" :label="item.label" :value="item.model" />
                  </el-select>
                  <el-select v-if="selectedModelSupportsThinking" v-model="aiConfig.selectedMode" size="small" :disabled="thinking" placeholder="模式">
                    <el-option label="Auto" value="auto" />
                    <el-option label="Thinking" value="thinking" />
                    <el-option label="No Thinking" value="non_thinking" />
                  </el-select>
                </div>
              </div>
            </div>
          </template>
          <template v-else>
            <!-- 上下文使用状态和云端代理模式 -->
            <div class="input-options">
              <el-popover
                v-if="contextUsageVisible"
                :trigger="isMobile ? 'click' : 'hover'"
                placement="top-start"
                :width="isMobile ? 286 : 320"
                :disabled="!hasContextPopoverContent"
                popper-class="context-usage-popover"
              >
                <template #reference>
                  <button
                    type="button"
                    class="context-status context-indicator"
                    :class="`is-${contextUsageTone}`"
                    @mousedown.stop
                    @touchstart.stop
                  >
                    <span
                      class="context-ring"
                      :style="{ '--context-usage-angle': `${Math.max(Math.min(contextStats.usage_percent, 100), 0) * 3.6}deg` }"
                    >
                      <span class="context-ring-core"></span>
                    </span>
                    <span class="context-indicator-text">{{ contextPercentText }}</span>
                  </button>
                </template>
                <div class="context-usage-panel">
                  <div class="context-usage-header">
                    <div class="context-usage-header-main">
                      <div class="context-usage-title">上下文窗口</div>
                      <div class="context-usage-summary">{{ contextSummaryText }}</div>
                    </div>
                    <span class="context-usage-percent" :class="`is-${contextUsageTone}`">{{ contextPercentText }}</span>
                  </div>
                  <div v-if="contextBreakdownItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">上下文明细</div>
                    <div v-for="item in contextBreakdownItems" :key="`context-breakdown-desktop-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextToolMetaItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">工具处理</div>
                    <div v-for="item in contextToolMetaItems" :key="`context-tool-desktop-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextReplayItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">工具回放</div>
                    <div v-for="item in contextReplayItems" :key="`context-replay-desktop-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextRouteItems.length" class="context-usage-section">
                    <div class="context-usage-section-title">路由信息</div>
                    <div v-for="item in contextRouteItems" :key="`context-route-desktop-${item.label}`" class="context-usage-row">
                      <span>{{ item.label }}</span>
                      <span>{{ item.value }}</span>
                    </div>
                  </div>
                  <div v-if="contextStats.tool_full_replayed_count > 0 || contextStats.is_estimate" class="context-usage-footer">
                    <span v-if="contextStats.tool_full_replayed_count > 0" class="context-usage-flag">直带最近工具结果</span>
                    <span v-if="contextStats.is_estimate" class="context-usage-flag is-estimate">估算值（历史数据）</span>
                  </div>
                </div>
              </el-popover>
              <div class="input-option-toggles">
                <button
                  v-if="aiConfig.webSearchEnabled"
                  type="button"
                  class="option-select-chip web-search-toggle"
                  :class="{ 'is-active': currentSessionWebSearchEnabled, 'is-disabled': thinking }"
                  :disabled="thinking"
                  @click="toggleWebSearchMode"
                >
                  <el-icon class="option-select-indicator" aria-hidden="true"><Search /></el-icon>
                  <span class="web-search-label">联网搜索</span>
                </button>
                <div class="cloud-proxy-control">
                  <el-tooltip 
                    content="开启后可在等待回复时切换会话或离开页面，AI将在后台继续处理，完成后通知您" 
                    placement="top"
                  >
                    <button
                      type="button"
                      class="option-select-chip cloud-proxy-toggle"
                      :class="{ 'is-active': cloudProxyMode }"
                      @click="toggleCloudProxyMode"
                    >
                      <el-icon class="option-select-indicator" aria-hidden="true"><component :is="CloudIcon" /></el-icon>
                      <span class="cloud-proxy-label">后台</span>
                    </button>
                  </el-tooltip>
                  <el-badge v-if="pendingTaskCount > 0" :value="pendingTaskCount" class="task-badge">
                    <el-button link type="primary" size="small" @click="showPendingTasks">
                      远端队列
                    </el-button>
                  </el-badge>
                </div>
              </div>
            </div>
            <div
              v-if="aiConfig.manualSelectEnabled && aiConfig.availableModels.length"
              class="chat-controls"
              @mousedown.stop
              @touchstart.stop
            >
              <div v-if="aiConfig.manualSelectEnabled && aiConfig.availableModels.length" class="model-selector">
                <el-select v-model="aiConfig.selectedModel" size="small" :disabled="thinking" placeholder="Model" @change="handleModelChange">
                  <el-option v-for="item in aiConfig.availableModels" :key="item.model" :label="item.label" :value="item.model" />
                </el-select>
                <el-select v-if="selectedModelSupportsThinking" v-model="aiConfig.selectedMode" size="small" :disabled="thinking" placeholder="Thinking">
                  <el-option label="Auto" value="auto" />
                  <el-option label="Thinking" value="thinking" />
                  <el-option label="No Thinking" value="non_thinking" />
                </el-select>
              </div>
            </div>
          </template>
          <div class="input-row">
            <el-input
              ref="inputRef"
              v-model="inputText"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 8 }"
              :placeholder="cloudProxyMode ? '输入问题后可离开页面，AI会在后台处理...' : '输入您的问题...'"
              resize="none"
              @keydown.enter.exact.prevent="sendMessage"
            />
            <div class="input-actions">
              <el-button
                v-if="thinking && !cloudProxyMode"
                type="danger"
                plain
                :class="{ 'mobile-send-button': isMobile }"
                @click="stopAiGeneration"
              >
                <el-icon><Close /></el-icon><span v-if="!isMobile"> 停止</span>
              </el-button>
              <el-button
                v-else
                :type="cloudProxyMode ? 'warning' : 'primary'"
                :disabled="!inputText.trim()"
                :class="{ 'mobile-send-button': isMobile }"
                @click="sendMessage"
              >
                <el-icon><Position /></el-icon><span v-if="!isMobile"> {{ cloudProxyMode ? '后台发送' : '发送' }}</span>
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 流程图预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      title="流程图预览"
      width="90%"
      top="5vh"
      append-to-body
      class="mermaid-preview-dialog"
      @opened="initZoom"
    >
      <div class="preview-toolbar">
        <el-button-group>
          <el-button :icon="ZoomIn" @click="handleZoom(0.2)">放大</el-button>
          <el-button :icon="ZoomOut" @click="handleZoom(-0.2)">缩小</el-button>
          <el-button :icon="Refresh" @click="resetZoom">重置</el-button>
        </el-button-group>
        <span class="zoom-tip">可在区域内拖动和滚动缩放</span>
      </div>
      <div 
        class="mermaid-preview-viewport" 
        ref="viewportRef"
        @mousedown="startDrag"
        @wheel.prevent="handleWheel"
      >
        <div 
          class="mermaid-preview-container" 
          :style="zoomStyle"
          v-html="previewContent"
        ></div>
      </div>
    </el-dialog>

    <!-- 聊天图片原生预览（Element Plus） -->
    <el-image-viewer
      v-if="imageViewerVisible && imageViewerUrlList.length > 0"
      :url-list="imageViewerUrlList"
      :initial-index="0"
      :infinite="false"
      :hide-on-click-modal="true"
      :zoom-rate="1.2"
      :min-scale="0.2"
      :max-scale="7"
      @close="closeImageViewer"
    />
    
    <!-- 敏感信息验证弹窗 -->
    <wait-verify-dialog ref="verifyDialogRef" @success="handleVerifySuccess" />
    
    <!-- 远端队列弹窗 -->
    <el-dialog
      v-model="taskQueueVisible"
      title="远端队列"
      width="400px"
      :close-on-click-modal="true"
      class="task-queue-dialog"
    >
      <div class="tq-list" v-if="taskQueueList.length > 0">
        <div 
          v-for="task in taskQueueList" 
          :key="task.id"
          class="tq-item"
          :class="{ 'is-processing': task.status === 'running', 'is-pending': task.status === 'pending' }"
        >
          <div class="tq-icon-wrapper">
            <el-icon v-if="task.status === 'running'" class="tq-icon processing"><Loading /></el-icon>
            <el-icon v-else class="tq-icon pending"><Clock /></el-icon>
          </div>
          <div class="tq-info">
            <div class="tq-title">{{ task.message.substring(0, 40) + (task.message.length > 40 ? '...' : '') }}</div>
            <div class="tq-meta">
              <span class="tq-status">{{ task.status === 'running' ? '处理中' : '队列中' }}</span>
              <span class="tq-time">{{ task.status === 'running' ? '已进行' : '已等待' }} {{ formatDuration(task.status === 'running' ? task.start_time : task.create_time) }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="tq-empty">
        <el-icon :size="48" color="var(--el-text-color-placeholder)"><Check /></el-icon>
        <p>队列为空，没有待处理的任务</p>
      </div>
      <template #footer>
        <el-button type="primary" @click="taskQueueVisible = false">知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, onActivated, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification, ElImageViewer } from 'element-plus'
import { Plus, ChatDotRound, UserFilled, Position, Operation, Loading, Cpu, ArrowRight, ZoomIn, ZoomOut, Refresh, Check, Close, Search, Promotion, Clock, Connection, Edit } from '@element-plus/icons-vue'
import { shallowRef, h } from 'vue'

const route = useRoute()
const router = useRouter()

// 云端图标组件
const CloudIcon = shallowRef(h('svg', { 
  viewBox: '0 0 1024 1024', 
  width: '1em', 
  height: '1em',
  style: 'vertical-align: middle;'
}, [
  h('path', { 
    fill: 'currentColor',
    d: 'M811.4 418.7C765.6 297.9 648.9 212 512.2 212S258.8 297.8 213 418.6C127.3 441.1 64 519.1 64 612c0 110.5 89.5 200 199.9 200h496.2C870.5 812 960 722.5 960 612c0-92.7-63.1-170.7-148.6-193.3z'
  })
]))
import api from '@/utils/api'
import { probeIllegalRequest } from '@/utils/wafGuard'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify' // 【安全修复】XSS 防护
import { useUserStore } from '@/stores/user'
import { createAiMarkdownRenderer } from '@/utils/aiMarkdown'
import WaitVerifyDialog from '@/components/WaitVerifyDialog.vue'
import AssistantTurnTimeline from '@/components/AssistantTurnTimeline.vue'
import {
  appendStreamingContentBlock,
  appendStreamingReasoningBlock,
  buildMessageBlocks,
  cloneBlocks,
  enrichAssistantMessage,
  extractFinalContentFromBlocks,
  finalizeStreamingThought,
  mergeStreamingText,
  parseReasoning
} from '@/composables/useAssistantTurnBlocks'

const isMobile = ref(window.innerWidth <= 768)
const drawerVisible = ref(false)

const checkMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

// 页面可见性状态
const isPageVisible = ref(!document.hidden)
const pendingScrollRequest = ref(false)

// 页面可见性变化处理
const handleVisibilityChange = () => {
  isPageVisible.value = !document.hidden
  
  // 当页面重新可见时，如果有待处理的滚动请求，立即执行
  if (isPageVisible.value && pendingScrollRequest.value) {
    pendingScrollRequest.value = false
    nextTick(() => {
      scrollToBottom(true)
      if (showStreamingReasoning.value) {
        scrollReasoningToBottom(true)
      }
    })
  }
}

onMounted(async () => {
  window.addEventListener('resize', checkMobile)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  
  await fetchAiConfig()  // 获取AI配置
  await fetchSessions()
  await fetchPendingTaskCount()  // 获取待处理的后台任务数量
  startTaskRefresh()  // 启动定时刷新任务状态
  
  // 处理从通知跳转过来的情况（带有 task_id 参数）
  const taskId = route.query.task_id
  if (taskId) {
    await handleTaskRedirect(taskId)
    // 清除 URL 参数，避免刷新时重复处理
    router.replace({ path: route.path })
  }
  
  // 处理 URL 中的 session_id（优先从路由参数读取，其次从 query 读取）
  const sessionId = route.params.sessionId || route.query.session_id
  if (sessionId && !taskId) {
    const session = sessions.value.find(s => s.session_id === sessionId)
    if (session) {
      await switchSession(sessionId)
    } else {
      // 会话不存在，清除 URL 中的 sessionId
      router.replace({ name: 'AiChat' })
    }
  }

  scheduleObserveAiPhotoPlaceholders()
})

// 监听路由参数变化，处理组件被 keep-alive 缓存时 URL 改变的情况
watch(
  () => [route.params.sessionId, route.query.session_id],
  ([newParamId, newQueryId]) => {
    const newSessionId = newParamId || newQueryId
    if (newSessionId && newSessionId !== currentSessionId.value) {
      const session = sessions.value.find(s => s.session_id === newSessionId)
      if (session) {
        switchSession(newSessionId)
      } else {
        router.replace({ name: 'AiChat' })
      }
    } else if (!newSessionId && currentSessionId.value) {
      // 用户主动导航回 /ai 基础路径，保留当前会话，不自动新建
      // （自动新建会导致每次点击侧边栏 AI 菜单都无谓创建新会话）
    }
  }
)

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  stopTaskRefresh()  // 停止定时刷新
  stopTaskQueueRefresh()  // 停止任务队列弹窗轮询
  Object.keys(titleRefreshTimers).forEach(clearTitleRefreshTimer)
  if (aiPhotoObserveRaf) {
    cancelAnimationFrame(aiPhotoObserveRaf)
    aiPhotoObserveRaf = 0
  }
  aiPhotoObserver?.disconnect()
  aiPhotoObserver = null
})

const currentSessionId = ref('')
const sessions = ref([])
const messages = ref([])
const editingMessage = ref(null) // 当前正在编辑的消息

// AI配置（从后端获取）
const aiConfig = reactive({
  showModelInfo: false,
  autoSelect: false,
  provider: '',
  model: '',
  manualSelectEnabled: false,
  availableModels: [],
  selectedModel: '',
  selectedMode: 'auto',
  webSearchEnabled: false,
  webSearchDefault: false,
  webSearchProxyModel: ''
})
const draftWebSearchEnabled = ref(false)
const WEB_SEARCH_PREFERENCE_PREFIX = 'ai:web-search'

const getWebSearchPreferenceKey = () => {
  const userId = userStore?.user?.id || 'guest'
  return `${WEB_SEARCH_PREFERENCE_PREFIX}:${userId}`
}

const loadWebSearchPreference = (defaultValue = false) => {
  try {
    const saved = localStorage.getItem(getWebSearchPreferenceKey())
    if (saved === '1' || saved === 'true') return true
    if (saved === '0' || saved === 'false') return false
  } catch (error) {
    console.warn('读取联网搜索偏好失败:', error)
  }
  return !!defaultValue
}

const saveWebSearchPreference = (enabled) => {
  try {
    localStorage.setItem(getWebSearchPreferenceKey(), enabled ? '1' : '0')
  } catch (error) {
    console.warn('保存联网搜索偏好失败:', error)
  }
}

// ==================== 多会话并行状态管理（重构版）====================
// 使用 reactive + 更新计数器确保响应式更新

// 会话状态存储（使用 reactive 确保深层响应）
const sessionStatesMap = reactive({})
// 状态更新计数器（用于强制触发视图更新）
const stateUpdateCounter = ref(0)

// 云端代理模式
const cloudProxyMode = ref(false)
const pendingTaskCount = ref(0)
const processorChecked = ref(false) // 是否已检查过处理器状态

// 检查队列处理器状态
const checkProcessorStatus = async () => {
  try {
    const res = await api.get('/ai/task/processor-status')
    if (res.code === 200) {
      if (!res.data.running) {
        ElMessageBox.confirm(
          '检测到后台任务处理器可能未运行，云端代理模式下的任务可能无法被处理。是否仍要开启？',
          '处理器状态警告',
          {
            confirmButtonText: '仍要开启',
            cancelButtonText: '取消',
            type: 'warning',
          }
        ).then(() => {
          processorChecked.value = true
        }).catch(() => {
          cloudProxyMode.value = false
        })
        return false
      }
      processorChecked.value = true
      return true
    }
  } catch (error) {
    console.error('检查处理器状态失败:', error)
  }
  return true
}

// 监听云端代理模式切换
watch(cloudProxyMode, async (newVal, oldVal) => {
  if (newVal && !oldVal && !processorChecked.value) {
    await checkProcessorStatus()
  }
})

// 追踪任务刚完成但用户未查看的会话（用于绿色闪烁提示）
const completedUnviewedSessions = ref(new Set())

// 远端队列弹窗状态
const taskQueueVisible = ref(false)
const taskQueueList = ref([])
let taskQueueRefreshTimer = null

// 创建默认会话状态
const createDefaultState = () => ({
  eventSource: null,
  thinking: false,
  completed: false,
  streamStatus: 'idle',
  streamingContent: '',
  reasoningContent: '',
  streamingReasoningList: [],
  streamingPhase: 'idle',
  currentRoundStartedAt: 0,
  reasoningStartTime: 0,
  reasoningDuration: 0,
  toolStatus: '',
  toolCallLogs: [],
  titlePending: false,
  webSearchEnabled: draftWebSearchEnabled.value,
  lastUpdate: Date.now(),
})

const beginBackgroundStreamingPhase = (state, phase) => {
  if (!state) return
  if (state.streamingPhase === 'content' || !state.currentRoundStartedAt) {
    state.currentRoundStartedAt = Date.now()
  }
  state.streamingPhase = phase
}

const beginBackgroundContentPhase = (state) => {
  if (!state) return null

  let roundDurationMs = null
  if ((state.streamingPhase === 'reasoning' || state.streamingPhase === 'tool') && state.currentRoundStartedAt) {
    roundDurationMs = Date.now() - state.currentRoundStartedAt
  }

  state.streamingPhase = 'content'
  state.currentRoundStartedAt = 0
  return roundDurationMs
}

const resetBackgroundStreamingPhase = (state) => {
  if (!state) return
  state.streamingPhase = 'idle'
  state.currentRoundStartedAt = 0
}

// 获取会话状态（如果不存在则创建）
const getSessionState = (sessionId) => {
  if (!sessionId) return null
  if (!sessionStatesMap[sessionId]) {
    sessionStatesMap[sessionId] = createDefaultState()
  }
  return sessionStatesMap[sessionId]
}

// 更新会话状态（触发响应式更新）
const updateSessionState = (sessionId, updates) => {
  if (!sessionId) return
  const state = getSessionState(sessionId)
  Object.assign(state, updates, { lastUpdate: Date.now() })
  stateUpdateCounter.value++ // 强制触发依赖更新
}

// 检查会话是否正在流式输出中（使用计数器触发响应）
const isSessionStreaming = (sessionId) => {
  // 引用计数器确保响应式
  const _ = stateUpdateCounter.value
  if (!sessionId) return false
  const state = sessionStatesMap[sessionId]
  if (!state) return false
  if (state.streamStatus) {
    return state.streamStatus === 'streaming'
  }
  return state.thinking && !state.completed
}

// 检查标题是否正在生成中
const isTitlePending = (sessionId) => {
  const _ = stateUpdateCounter.value
  if (!sessionId) return false
  const state = sessionStatesMap[sessionId]
  return state && state.titlePending
}

// 获取所有正在流式输出的会话ID列表
const streamingSessionIds = computed(() => {
  const _ = stateUpdateCounter.value
  return Object.keys(sessionStatesMap).filter(id => {
    const state = sessionStatesMap[id]
    if (!state) return false
    if (state.streamStatus) {
      return state.streamStatus === 'streaming'
    }
    return state.thinking && !state.completed
  })
})

// 检查是否是临时标题（以...结尾）
const isTempTitle = (title) => {
  if (!title) return false
  return title.endsWith('...')
}

// 会话 ID → 本地保存的临时标题（来自 SSE session_created 事件）
// 用于在 fetchSessions 返回 null 时兜底显示，防止退化为"新对话"
const localTempTitles = {}
const titleRefreshTimers = {}

const clearTitleRefreshTimer = (sessionId) => {
  const timers = titleRefreshTimers[sessionId]
  if (!timers) return
  timers.forEach(timerId => clearTimeout(timerId))
  delete titleRefreshTimers[sessionId]
}

const scheduleTitlePendingRefresh = (sessionId) => {
  if (!sessionId) return
  clearTitleRefreshTimer(sessionId)

  const delays = [1500, 5000]
  titleRefreshTimers[sessionId] = delays.map((delay, index) => setTimeout(async () => {
    if (!sessionStatesMap[sessionId]?.titlePending) return

    await fetchSessions(false, true)

    const session = sessions.value.find(item => item.session_id === sessionId)
    if (session?.title && !isTempTitle(session.title)) {
      delete localTempTitles[sessionId]
      updateSessionState(sessionId, { titlePending: false })
      clearTitleRefreshTimer(sessionId)
      return
    }

    if (index === delays.length - 1) {
      updateSessionState(sessionId, { titlePending: false })
      clearTitleRefreshTimer(sessionId)
    }
  }, delay))
}

// 获取显示标题
const getDisplayTitle = (session) => {
  const title = session.title || localTempTitles[session.session_id] || null
  if (!title) {
    // 无任何标题：pending 时显示「生成标题中…」，否则显示「新对话」
    return isTitlePending(session.session_id) ? '生成标题中…' : '新对话'
  }
  // 如果有临时标题（以...结尾），去掉省略号直接显示
  if (isTempTitle(title)) {
    return title.slice(0, -3) + '…'
  }
  return title
}

// 获取会话项的CSS类
const getSessionItemClass = (session) => {
  const _ = stateUpdateCounter.value // 确保响应式
  return {
    active: currentSessionId.value === session.session_id,
    'is-streaming': isSessionStreaming(session.session_id),
    'is-processing': session.task_status === 'running',
    'is-pending': session.task_status === 'pending',
    'is-generating': isTitlePending(session.session_id),
    'is-task-completed': completedUnviewedSessions.value.has(session.session_id),
  }
}

// 获取会话状态信息
const getSessionStatus = (session) => {
  const _ = stateUpdateCounter.value // 确保响应式
  if (isSessionStreaming(session.session_id)) {
    return { text: '输出中', class: 'streaming' }
  }
  if (session.task_status === 'running') {
    return { text: '处理中', class: 'processing' }
  }
  if (session.task_status === 'pending') {
    return { text: '等待中', class: 'pending' }
  }
  return null
}

// 清理会话状态
const clearSessionState = (sessionId) => {
  const state = sessionStatesMap[sessionId]
  if (state) {
    if (state.eventSource) {
      state.eventSource.close()
    }
    clearTitleRefreshTimer(sessionId)
    sessionStatesMap[sessionId] = {
      ...createDefaultState(),
      webSearchEnabled: typeof state.webSearchEnabled === 'boolean' ? state.webSearchEnabled : draftWebSearchEnabled.value,
      titlePending: false
    }
    stateUpdateCounter.value++
  }
}

// 兼容旧代码的 sessionStates
const sessionStates = computed(() => {
  const _ = stateUpdateCounter.value
  return { value: sessionStatesMap }
})

// 节流状态刷新（用于流式更新时定期触发视图更新）
let stateRefreshTimer = null
const throttleStateRefresh = () => {
  if (stateRefreshTimer) return
  stateRefreshTimer = setTimeout(() => {
    stateUpdateCounter.value++
    stateRefreshTimer = null
  }, 100)  // 100ms 节流
}

// 强制刷新状态（立即触发）
const forceStateRefresh = () => {
  if (stateRefreshTimer) {
    clearTimeout(stateRefreshTimer)
    stateRefreshTimer = null
  }
  stateUpdateCounter.value++
}

// 会话列表搜索和分页
const sessionKeyword = ref('')
const sessionPage = ref(1)
const sessionPageSize = ref(20)
const hasMoreSessions = ref(false)
const loadingMore = ref(false)
let searchDebounceTimer = null
const inputText = ref('')
const inputRef = ref(null)
const thinking = ref(false)
const historyLoading = ref(false)
const sessionsLoading = ref(false)
const messageListRef = ref(null)
// 历史懒加载
const hasMoreHistory = ref(false)       // 是否还有更早的消息可以加载
const loadingMoreHistory = ref(false)   // 加载更早消息中
const oldestMessageId = ref(0)          // 当前已加载的最早消息 id（用于 before_id 游标）
const streamingContent = ref('')  // 流式内容
const reasoningContent = ref('')  // 推理内容
const showStreamingReasoning = ref(true) // 流式推理展开状态
const toolStatus = ref('')        // 工具调用状态
const toolCallLogs = ref([])      // 工具调用日志数组
const useStreaming = ref(true)    // 是否使用流式输出
const streamingReasoningList = ref([]) // 结构化流式推理列表
const streamingThinkingExpanded = ref(false) // 单轮流式思考折叠状态
const streamingReasoningBodyRef = ref(null) // 流式推理内容容器引用
const showContinueButton = ref(false) // 🔧 是否显示继续按钮
const continueLoading = ref(false)    // 继续按钮loading状态
const continueIteration = ref(0)      // 当前轮数
const continueSessionId = ref('')     // 等待继续的会话ID
const reasoningStartTime = ref(0)     // 思考开始时间
const reasoningDuration = ref(0)      // 思考耗时（毫秒）
const reasoningDone = ref(false)      // 思考是否已完成
const streamingPhase = ref('idle')
const currentRoundStartedAt = ref(0)

const beginCurrentStreamingPhase = (phase) => {
  if (streamingPhase.value === 'content' || !currentRoundStartedAt.value) {
    currentRoundStartedAt.value = Date.now()
  }
  streamingPhase.value = phase
}

const beginCurrentContentPhase = () => {
  let roundDurationMs = null
  if ((streamingPhase.value === 'reasoning' || streamingPhase.value === 'tool') && currentRoundStartedAt.value) {
    roundDurationMs = Date.now() - currentRoundStartedAt.value
  }
  streamingPhase.value = 'content'
  currentRoundStartedAt.value = 0
  return roundDurationMs
}

const resetCurrentStreamingPhase = () => {
  streamingPhase.value = 'idle'
  currentRoundStartedAt.value = 0
}


// 上下文使用统计
const contextStats = ref({
  used_tokens: 0,
  max_tokens: 500000,
  usage_percent: 0,
  used_display: '0',
  max_display: '500K',
  breakdown: null,              // 详细分类（user, assistant, tool, system）
  tool_calls_count: 0,          // 工具调用次数
  tool_simplified_count: 0,     // 简化的工具调用次数
  tokens_saved: 0,              // 节省的 token 数
  tokens_saved_display: '0',    // 格式化显示
  tool_full_replayed_count: 0,
  tool_compact_replayed_count: 0,
  tool_summary_replayed_count: 0,
  tool_replay_tokens: 0,
  tool_replay_tokens_display: '0',
  context_policy: 'adaptive_tool_replay',
  route_reason: '',
  route_model: '',
  route_provider: '',
  route_strategy: '',
  candidate_costs: {},
  manual_model_locked: false,
  is_estimate: false            // 是否为估算值
})

// ai-photo 稳定引用动态解析缓存
const AI_PHOTO_REF_REGEX = /ai-photo:\/\/student\/(avatar|id_photo)\/(\d+)/g
const AI_PHOTO_IMAGE_MD_REGEX = /!\[([^\]]*)\]\((ai-photo:\/\/student\/(avatar|id_photo)\/(\d+))\)/g
const PHOTO_CACHE_FALLBACK_TTL_MS = 5 * 60 * 1000
const AI_PHOTO_PLACEHOLDER_SELECTOR = '.ai-photo-wrap[data-ai-photo-pending="1"]'
const photoUrlCache = reactive({})
const photoResolveInFlight = new Set()
const photoRenderTick = ref(0)
let aiPhotoObserver = null
let aiPhotoObserveRaf = 0

const getPhotoCacheKey = (type, studentId) => `${type}:${studentId}`

const parseExpireAtFromSignedUrl = (url) => {
  if (!url) return 0
  try {
    const parsedUrl = new URL(url)
    const expires = Number(parsedUrl.searchParams.get('Expires') || 0)
    if (!Number.isFinite(expires) || expires <= 0) return 0
    return expires * 1000
  } catch (e) {
    return 0
  }
}

const getCachedPhotoUrl = (type, studentId) => {
  const key = getPhotoCacheKey(type, studentId)
  const item = photoUrlCache[key]
  if (!item || !item.expireAt) return ''
  // 提前 60 秒刷新，避免渲染时刚好过期
  if (Date.now() >= item.expireAt - 60000) return ''
  return item.url || ''
}

const resolveStudentPhotoRef = async (type, studentId) => {
  const key = getPhotoCacheKey(type, studentId)
  if (photoResolveInFlight.has(key)) return
  photoResolveInFlight.add(key)

  try {
    const params = {}
    if (userStore?.isSensitiveVerified && userStore.isSensitiveVerified()) {
      params.with_sensitive = true
    }

    const res = await api.get(`/student/${studentId}`, { params })
    if (res.code !== 200) {
      photoUrlCache[key] = {
        url: '',
        expireAt: Date.now() + PHOTO_CACHE_FALLBACK_TTL_MS
      }
      return
    }

    const student = res.data || {}
    const url = type === 'avatar'
      ? (student.avatar || '')
      : (student.studentProfile?.id_photo || '')

    const expireAt = parseExpireAtFromSignedUrl(url) || (Date.now() + PHOTO_CACHE_FALLBACK_TTL_MS)
    photoUrlCache[key] = { url, expireAt }
  } catch (e) {
    photoUrlCache[key] = {
      url: '',
      expireAt: Date.now() + PHOTO_CACHE_FALLBACK_TTL_MS
    }
  } finally {
    photoResolveInFlight.delete(key)
    photoRenderTick.value++
  }
}

const queueAiPhotoRefResolution = (type, studentId) => {
  if (getCachedPhotoUrl(type, studentId)) return
  const key = getPhotoCacheKey(type, studentId)
  if (photoResolveInFlight.has(key)) return
  void resolveStudentPhotoRef(type, studentId)
}

const ensureAiPhotoObserver = () => {
  if (aiPhotoObserver || typeof window === 'undefined' || !('IntersectionObserver' in window)) return
  const root = messageListRef.value || null
  aiPhotoObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return
      const target = entry.target
      const type = target?.getAttribute('data-photo-type')
      const studentId = target?.getAttribute('data-student-id')
      if (type && studentId) {
        queueAiPhotoRefResolution(type, studentId)
      }
      aiPhotoObserver?.unobserve(target)
      if (target) target.dataset.aiPhotoObserved = 'done'
    })
  }, {
    root,
    rootMargin: '320px 0px',
    threshold: 0.01
  })
}

const observeVisibleAiPhotoPlaceholders = () => {
  const root = messageListRef.value
  if (!root) return

  ensureAiPhotoObserver()
  const nodes = root.querySelectorAll(AI_PHOTO_PLACEHOLDER_SELECTOR)
  nodes.forEach((node) => {
    const type = node.getAttribute('data-photo-type')
    const studentId = node.getAttribute('data-student-id')
    if (!type || !studentId) return
    if (getCachedPhotoUrl(type, studentId)) return
    if (node.dataset.aiPhotoObserved === '1' || node.dataset.aiPhotoObserved === 'done') return

    if (aiPhotoObserver) {
      aiPhotoObserver.observe(node)
      node.dataset.aiPhotoObserved = '1'
      return
    }

    queueAiPhotoRefResolution(type, studentId)
    node.dataset.aiPhotoObserved = 'done'
  })
}

const scheduleObserveAiPhotoPlaceholders = () => {
  if (aiPhotoObserveRaf) cancelAnimationFrame(aiPhotoObserveRaf)
  aiPhotoObserveRaf = requestAnimationFrame(() => {
    aiPhotoObserveRaf = 0
    nextTick(() => {
      observeVisibleAiPhotoPlaceholders()
    })
  })
}

// 滚动控制状态
const isAtBottom = ref(true) // 主消息列表是否在底部
const isReasoningAtBottom = ref(true) // 思考容器是否在底部
const lastScrollTop = ref(0) // 记录上次滚动位置，用于检测用户向上滚动
const lastReasoningScrollTop = ref(0) // 思考容器的上次滚动位置

// 预览缩放相关
const previewVisible = ref(false)
const previewContent = ref('')
const imageViewerVisible = ref(false)
const imageViewerUrlList = ref([])
const viewportRef = ref(null)
const zoomScale = ref(1)
const zoomOffset = reactive({ x: 0, y: 0 })
const isDragging = ref(false)
const lastMousePos = reactive({ x: 0, y: 0 })

const zoomStyle = computed(() => ({
  transform: `translate(${zoomOffset.x}px, ${zoomOffset.y}px) scale(${zoomScale.value})`,
  transition: isDragging.value ? 'none' : 'transform 0.1s ease-out'
}))

const currentSessionTitle = computed(() => {
  const session = sessions.value.find(s => s.session_id === currentSessionId.value)
  return session?.title || 'AI 助手'
})

const initZoom = () => {
  resetZoom()
}

const resetZoom = () => {
  zoomScale.value = 1
  zoomOffset.x = 0
  zoomOffset.y = 0
}

const handleZoom = (delta) => {
  const newScale = Math.max(0.2, Math.min(5, zoomScale.value + delta))
  zoomScale.value = newScale
}

const handleWheel = (e) => {
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  handleZoom(delta)
}

const openImagePreview = (src) => {
  if (!src) return
  imageViewerUrlList.value = [src]
  imageViewerVisible.value = true
}

const closeImageViewer = () => {
  imageViewerVisible.value = false
  imageViewerUrlList.value = []
}

const startDrag = (e) => {
  isDragging.value = true
  lastMousePos.x = e.clientX
  lastMousePos.y = e.clientY
  
  const handleMouseMove = (me) => {
    if (!isDragging.value) return
    const dx = me.clientX - lastMousePos.x
    const dy = me.clientY - lastMousePos.y
    zoomOffset.x += dx
    zoomOffset.y += dy
    lastMousePos.x = me.clientX
    lastMousePos.y = me.clientY
  }
  
  const handleMouseUp = () => {
    isDragging.value = false
    window.removeEventListener('mousemove', handleMouseMove)
    window.removeEventListener('mouseup', handleMouseUp)
  }
  
  window.addEventListener('mousemove', handleMouseMove)
  window.addEventListener('mouseup', handleMouseUp)
}

// 监听滚动事件 - 只有用户主动向上滚动时才阻止自动滚动
const handleScroll = () => {
  const el = messageListRef.value
  if (!el) return
  
  const currentScrollTop = el.scrollTop
  const atBottom = el.scrollHeight - currentScrollTop - el.clientHeight < 50
  
  // 只有当用户向上滚动（scrollTop 减小超过阈值）时，才设置 isAtBottom = false
  if (currentScrollTop < lastScrollTop.value - 10) {
    isAtBottom.value = false
  } else if (atBottom) {
    // 滚到底部了，恢复自动滚动
    isAtBottom.value = true
  }
  // 内容增加导致的 scrollHeight 变化不会影响 isAtBottom
  
  lastScrollTop.value = currentScrollTop

  // 滚到顶部附近（距顶 80px 内）且有更早历史时，自动懒加载
  if (currentScrollTop < 80 && hasMoreHistory.value && !loadingMoreHistory.value) {
    loadMoreHistory()
  }
}

// 监听思考容器滚动事件 - 同样逻辑
const handleReasoningScroll = (e) => {
  const el = e.target
  if (!el) return
  
  const currentScrollTop = el.scrollTop
  const atBottom = el.scrollHeight - currentScrollTop - el.clientHeight < 30
  
  // 只有当用户向上滚动时，才设置 isReasoningAtBottom = false
  if (currentScrollTop < lastReasoningScrollTop.value - 10) {
    isReasoningAtBottom.value = false
  } else if (atBottom) {
    isReasoningAtBottom.value = true
  }
  
  lastReasoningScrollTop.value = currentScrollTop
}

// 获取AI配置
const selectedModelInfo = computed(() => {
  return aiConfig.availableModels.find(item => item.model === aiConfig.selectedModel) || null
})

const formatContextWindow = (tokens) => {
  const value = Number(tokens || selectedModelInfo.value?.max_context_tokens || 500000)
  return value >= 1000 ? `${Math.round(value / 1000)}K` : `${value}`
}

const selectedContextWindow = computed(() => {
  const maxTokens = Number(selectedModelInfo.value?.max_context_tokens || contextStats.value.max_tokens || 500000)
  return {
    max_tokens: maxTokens,
    max_display: formatContextWindow(maxTokens)
  }
})

const normalizeContextStats = (stats = {}) => {
  const maxTokens = Number(stats.max_tokens || selectedContextWindow.value.max_tokens)
  return {
    ...stats,
    used_tokens: stats.used_tokens || 0,
    max_tokens: maxTokens,
    usage_percent: stats.usage_percent || 0,
    used_display: stats.used_display || '0',
    max_display: stats.max_display || formatContextWindow(maxTokens),
    breakdown: stats.breakdown || null,
    tool_calls_count: stats.tool_calls_count || 0,
    tool_simplified_count: stats.tool_simplified_count || 0,
    tokens_saved: stats.tokens_saved || 0,
    tokens_saved_display: stats.tokens_saved_display || '0',
    tool_full_replayed_count: stats.tool_full_replayed_count || 0,
    tool_compact_replayed_count: stats.tool_compact_replayed_count || 0,
    tool_summary_replayed_count: stats.tool_summary_replayed_count || 0,
    tool_replay_tokens: stats.tool_replay_tokens || 0,
    tool_replay_tokens_display: stats.tool_replay_tokens_display || '0',
    context_policy: stats.context_policy || 'adaptive_tool_replay',
    route_reason: stats.route_reason || '',
    route_model: stats.route_model || '',
    route_provider: stats.route_provider || '',
    route_strategy: stats.route_strategy || '',
    candidate_costs: stats.candidate_costs || {},
    manual_model_locked: !!stats.manual_model_locked,
    is_estimate: stats.is_estimate || false,
  }
}

const contextUsageVisible = computed(() => {
  return messages.value.length > 0 || contextStats.value.used_tokens > 0
})

const contextSummaryText = computed(() => {
  return `${contextStats.value.used_display} / ${contextStats.value.max_display} 个令牌`
})

const contextPercentText = computed(() => {
  return `${Math.max(0, Number(contextStats.value.usage_percent) || 0)}%`
})

const contextUsageTone = computed(() => {
  if (contextStats.value.usage_percent >= 90) return 'danger'
  if (contextStats.value.usage_percent >= 70) return 'warning'
  return 'normal'
})

const contextBreakdownItems = computed(() => {
  const breakdown = contextStats.value.breakdown
  if (!breakdown) return []

  const items = [
    { label: '用户消息', value: `${breakdown.user || 0} tokens` },
    { label: 'AI回复', value: `${breakdown.assistant || 0} tokens` },
  ]

  if (breakdown.tool) {
    items.push({ label: '工具调用', value: `${breakdown.tool} tokens` })
  }
  if (breakdown.system) {
    items.push({ label: '系统提示', value: `${breakdown.system} tokens` })
  }

  return items
})

const contextToolMetaItems = computed(() => {
  const items = []

  if (contextStats.value.tool_calls_count > 0) {
    items.push({ label: '工具调用次数', value: `${contextStats.value.tool_calls_count} 次` })
  }
  if (contextStats.value.tool_simplified_count > 0) {
    items.push({ label: '已简化', value: `${contextStats.value.tool_simplified_count} 次` })
  }
  if (contextStats.value.tokens_saved > 0) {
    items.push({ label: '节省 tokens', value: contextStats.value.tokens_saved_display || `${contextStats.value.tokens_saved}` })
  }

  return items
})

const contextReplayItems = computed(() => {
  const items = []

  if (contextStats.value.tool_full_replayed_count || contextStats.value.tool_compact_replayed_count || contextStats.value.tool_summary_replayed_count) {
    items.push(
      { label: '完整回放', value: `${contextStats.value.tool_full_replayed_count || 0} 次` },
      { label: '紧凑回放', value: `${contextStats.value.tool_compact_replayed_count || 0} 次` },
      { label: '摘要回放', value: `${contextStats.value.tool_summary_replayed_count || 0} 次` }
    )
  }

  if (contextStats.value.tool_replay_tokens > 0) {
    items.push({ label: '实际回放', value: `${contextStats.value.tool_replay_tokens_display || contextStats.value.tool_replay_tokens} tokens` })
  }
  if (contextStats.value.context_policy) {
    items.push({ label: '策略', value: contextStats.value.context_policy })
  }

  return items
})

const contextRouteItems = computed(() => {
  const items = []

  if (contextStats.value.route_provider || contextStats.value.route_model) {
    items.push({ label: '路由', value: `${contextStats.value.route_provider || '-'} / ${contextStats.value.route_model || '-'}` })
  }
  if (contextStats.value.route_reason) {
    items.push({ label: '原因', value: contextStats.value.route_reason })
  }
  if (contextStats.value.route_strategy) {
    items.push({ label: '策略', value: contextStats.value.route_strategy })
  }
  if (contextStats.value.manual_model_locked) {
    items.push({ label: '手动锁定', value: '已开启' })
  }

  return items
})

const hasContextPopoverContent = computed(() => {
  return !!(
    contextBreakdownItems.value.length ||
    contextToolMetaItems.value.length ||
    contextReplayItems.value.length ||
    contextRouteItems.value.length ||
    contextStats.value.is_estimate
  )
})

const selectedModelSupportsThinking = computed(() => {
  return !!selectedModelInfo.value?.supports_thinking
})

const currentSessionWebSearchEnabled = computed({
  get() {
    if (!currentSessionId.value) {
      return draftWebSearchEnabled.value
    }
    const state = getSessionState(currentSessionId.value)
    if (typeof state?.webSearchEnabled === 'boolean') {
      return state.webSearchEnabled
    }
    return draftWebSearchEnabled.value
  },
  set(value) {
    const enabled = !!value
    draftWebSearchEnabled.value = enabled
    saveWebSearchPreference(enabled)
    if (!currentSessionId.value) {
      return
    }
    updateSessionState(currentSessionId.value, { webSearchEnabled: enabled })
  }
})

const toggleWebSearchMode = () => {
  if (thinking.value) return
  currentSessionWebSearchEnabled.value = !currentSessionWebSearchEnabled.value
}

const toggleCloudProxyMode = () => {
  cloudProxyMode.value = !cloudProxyMode.value
}

const handleModelChange = () => {
  const item = selectedModelInfo.value
  if (!item) return
  aiConfig.provider = item.provider
  aiConfig.model = item.model
  aiConfig.selectedMode = item.supports_thinking ? (item.default_thinking || 'auto') : 'non_thinking'
  contextStats.value = normalizeContextStats({ ...contextStats.value, usage_percent: 0 })
}

const buildModelQuery = () => {
  const item = selectedModelInfo.value
  const params = new URLSearchParams()
  if (aiConfig.manualSelectEnabled && aiConfig.selectedModel && item) {
    params.set('provider', item.provider)
    params.set('model', item.model)
    params.set('thinking_mode', aiConfig.selectedMode || 'auto')
  }
  params.set('web_search', currentSessionWebSearchEnabled.value ? '1' : '0')
  const query = params.toString()
  if (!query) return ''
  return `&${query}`
}

const fetchAiConfig = async () => {
  try {
    const res = await api.get('/ai/config')
    if (res.code === 200) {
      aiConfig.showModelInfo = res.data.show_model_info || false
      aiConfig.autoSelect = res.data.auto_select || false
      aiConfig.provider = res.data.provider || ''
      aiConfig.model = res.data.model || ''
      aiConfig.manualSelectEnabled = res.data.manual_select_enabled || false
      aiConfig.availableModels = res.data.available_models || []
      aiConfig.selectedModel = res.data.selected_model || aiConfig.model
      aiConfig.selectedMode = res.data.selected_mode || 'auto'
      aiConfig.webSearchEnabled = !!res.data.web_search_enabled
      aiConfig.webSearchDefault = !!res.data.web_search_default
      aiConfig.webSearchProxyModel = res.data.web_search_proxy_model || ''
      draftWebSearchEnabled.value = loadWebSearchPreference(aiConfig.webSearchDefault)
      if (!aiConfig.selectedModel && aiConfig.availableModels.length) {
        aiConfig.selectedModel = aiConfig.availableModels[0].model
      }
    }
  } catch (error) {
    console.error('获取AI配置失败:', error)
  }
}

// 获取会话列表
const fetchSessions = async (append = false, silent = false) => {
  if (!append && !silent) {
    sessionsLoading.value = true
  }
  try {
    const params = {
      page: sessionPage.value,
      page_size: sessionPageSize.value
    }
    if (sessionKeyword.value.trim()) {
      params.keyword = sessionKeyword.value.trim()
    }
    
    const res = await api.get('/ai/sessions', { params })
    if (res.code === 200) {
      const list = res.data?.list || res.data || []
      const total = res.data?.total || list.length
      
      if (append) {
        sessions.value = [...sessions.value, ...list]
      } else {
        // 【修复】合并已存在的会话状态，避免覆盖SSE已更新的字段（如标题）
        const existingMap = new Map(sessions.value.map(s => [s.session_id, s]))
        sessions.value = list.map(newSession => {
          if (newSession.title && !isTempTitle(newSession.title)) {
            delete localTempTitles[newSession.session_id]
          }
          const existing = existingMap.get(newSession.session_id)
          if (existing) {
            // 标题优先级：正式标题 > 临时标题
            // 如果现有标题是正式标题（不是临时标题、不为空、不是"新对话"），保留现有标题
            // 如果新标题是正式标题，使用新标题（覆盖临时标题）
            const existingIsOfficial = existing.title && 
                                      existing.title !== '新对话' && 
                                      !isTempTitle(existing.title)
            const newIsOfficial = newSession.title && 
                                 newSession.title !== '新对话' && 
                                 !isTempTitle(newSession.title)
            
            return {
              ...newSession,
              // 永远不让 null/空 新标题覆盖本地已有的临时标题
              title: newIsOfficial ? newSession.title : (existingIsOfficial ? existing.title : (newSession.title ?? existing.title))
            }
          }
          return newSession
        })
      }
      
      // 判断是否还有更多
      hasMoreSessions.value = sessions.value.length < total
      
      // 不再自动选择最新会话，让用户主动选择
    }
  } catch (e) {
    console.error('获取会话列表失败:', e)
  } finally {
    if (!append && !silent) {
      sessionsLoading.value = false
    }
  }
}

// 搜索会话（防抖）
const handleSessionSearch = () => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  searchDebounceTimer = setTimeout(() => {
    sessionPage.value = 1
    fetchSessions(false)
  }, 300)
}

// 加载更多会话
const loadMoreSessions = async () => {
  if (loadingMore.value || !hasMoreSessions.value) return
  
  loadingMore.value = true
  sessionPage.value += 1
  try {
    await fetchSessions(true)
  } finally {
    loadingMore.value = false
  }
}

// 获取对话历史（初始加载最新 30 条）
const fetchHistory = async () => {
  if (!currentSessionId.value) return
  historyLoading.value = true
  hasMoreHistory.value = false
  oldestMessageId.value = 0
  try {
    const res = await api.get('/ai/history', {
      params: { session_id: currentSessionId.value, limit: 30 }
    })
    if (res.code === 200) {
      messages.value = (res.data.list || []).map(m => {
        // 解析工具调用记录（可能是 JSON 字符串）
        let toolCalls = m.tool_calls
        if (typeof toolCalls === 'string') {
          try {
            toolCalls = JSON.parse(toolCalls)
          } catch (e) {
            toolCalls = null
          }
        }
        
        // 解析推理内容
        let parsedReasoning = parseReasoning(m.reasoning)
        
        // 如果有工具调用记录但没有推理内容（云端代理任务），构建显示数据
        if (toolCalls && Array.isArray(toolCalls) && toolCalls.length > 0 && parsedReasoning.length === 0) {
          parsedReasoning = toolCalls.map(tc => ({
            type: 'tool',
            name: tc.name || 'unknown',
            arguments: tc.arguments || {},
            result: tc.result || null,
            resultSummary: tc.has_error 
              ? `失败: ${tc.result?.error || '未知错误'}` 
              : getToolResultSummary(tc.result),
            status: tc.has_error ? 'error' : 'success',
            expanded: tc.has_error // 错误时默认展开，成功时收起
          }))
        }

        const renderBlocks = buildMessageBlocks(parsedReasoning, m.content)
        const displayContent = extractFinalContentFromBlocks(renderBlocks, m.content)
        
        const mapped = {
          id: m.id, // 添加消息ID
          role: m.role,
          content: displayContent,
          reasoning: m.reasoning, // 后端已映射 reasoning_content -> reasoning
          parsedReasoning: parsedReasoning,
          renderBlocks: renderBlocks,
          toolCalls: toolCalls, // 原始工具调用记录
          showReasoning: false, // 历史记录默认收起思考容器
          reasoning_duration: m.reasoning_duration, // 保留思考耗时
          time: formatTime(m.create_time),
          ai_provider: m.ai_provider,  // 模型供应商
          ai_model: m.ai_model,          // 模型名称
          isEditing: false, // 是否正在编辑
          editContent: '', // 编辑内容
          submitLoading: false, // 提交编辑的loading状态
        }
        return m.role === 'assistant' ? enrichAssistantMessage(mapped) : mapped
      })
      
      // 检查是否有正在处理的后台任务（消息最后一条是用户消息，说明AI还没回复）
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg && lastMsg.role === 'user') {
        // 检查该会话是否有 pending/running 的任务
        const session = sessions.value.find(s => s.session_id === currentSessionId.value)
        if (session && (session.task_status === 'pending' || session.task_status === 'running')) {
          // 添加占位消息
          messages.value.push(enrichAssistantMessage({
            role: 'assistant',
            content: '⏳ 正在后台处理中，请稍候...',
            isPlaceholder: true,
            time: formatTime(new Date())
          }))
        }
      }

      // 更新 context 统计（刷新页面后恢复显示）
      if (res.data.context_stats) {
        contextStats.value = normalizeContextStats(res.data.context_stats)
      }

      // 记录懒加载游标
      hasMoreHistory.value = res.data.has_more || false
      const firstMsg = messages.value.find(m => m.id)
      oldestMessageId.value = firstMsg ? firstMsg.id : 0

      // 重置滚动状态
      isAtBottom.value = true
      isReasoningAtBottom.value = true
      setTimeout(() => {
        scrollToBottom(true)
      }, 100)
    }
  } catch (e) {
    console.error('获取部分历史记录失败:', e)
  } finally {
    historyLoading.value = false
  }
}

// 懒加载更早的历史消息（用户滚到顶部时触发）
const loadMoreHistory = async () => {
  if (loadingMoreHistory.value || !hasMoreHistory.value || !currentSessionId.value) return
  if (!oldestMessageId.value) return

  loadingMoreHistory.value = true
  const el = messageListRef.value
  // 记录加载前的滚动高度，prepend 后用于锁定位置
  const prevScrollHeight = el ? el.scrollHeight : 0

  try {
    const res = await api.get('/ai/history', {
      params: {
        session_id: currentSessionId.value,
        limit: 20,
        before_id: oldestMessageId.value
      }
    })
    if (res.code === 200) {
      const olderList = (res.data.list || []).map(m => {
        let toolCalls = m.tool_calls
        if (typeof toolCalls === 'string') {
          try { toolCalls = JSON.parse(toolCalls) } catch (e) { toolCalls = null }
        }
        let parsedReasoning = parseReasoning(m.reasoning)
        if (toolCalls && Array.isArray(toolCalls) && toolCalls.length > 0 && parsedReasoning.length === 0) {
          parsedReasoning = toolCalls.map(tc => ({
            type: 'tool',
            name: tc.name || 'unknown',
            arguments: tc.arguments || {},
            result: tc.result || null,
            resultSummary: tc.has_error
              ? `失败: ${tc.result?.error || '未知错误'}`
              : getToolResultSummary(tc.result),
            status: tc.has_error ? 'error' : 'success',
            expanded: tc.has_error
          }))
        }
        const renderBlocks = buildMessageBlocks(parsedReasoning, m.content)
        const displayContent = extractFinalContentFromBlocks(renderBlocks, m.content)
        const mapped = {
          id: m.id,
          role: m.role,
          content: displayContent,
          reasoning: m.reasoning,
          parsedReasoning,
          renderBlocks,
          toolCalls,
          showReasoning: false,
          reasoning_duration: m.reasoning_duration,
          time: formatTime(m.create_time),
          ai_provider: m.ai_provider,
          ai_model: m.ai_model,
          isEditing: false,
          editContent: '',
          submitLoading: false,
        }
        return m.role === 'assistant' ? enrichAssistantMessage(mapped) : mapped
      })

      if (olderList.length > 0) {
        // prepend 到消息列表头部
        messages.value = [...olderList, ...messages.value]
        hasMoreHistory.value = res.data.has_more || false
        // 更新游标为新的最早 id
        const first = olderList.find(m => m.id)
        if (first) oldestMessageId.value = first.id

        // 锁定滚动位置：补偿 prepend 导致的高度增量
        nextTick(() => {
          if (el) {
            el.scrollTop = el.scrollHeight - prevScrollHeight
          }
        })
      } else {
        hasMoreHistory.value = false
      }
    }
  } catch (e) {
    console.error('加载更早历史失败:', e)
  } finally {
    loadingMoreHistory.value = false
  }
}

/**
 * 流式结束后静默同步：只把服务端返回的消息 ID / context_stats 打补丁到
 * 已有的 messages 数组，不整体替换列表，避免可见的刷新闪烁。
 */
const silentSyncIds = async (sessionId) => {
  if (!sessionId) return
  try {
    const res = await api.get('/ai/history', {
      params: { session_id: sessionId, limit: 9999 }
    })
    if (res.code !== 200) return
    const serverList = res.data.list || []
    // 按 role+content 简单匹配，只回填缺少 id 的本地消息
    serverList.forEach(serverMsg => {
      if (!serverMsg.id) return
      // 优先找 id 已经匹配的（理论上不会有），然后找内容相同且没有 ID 的消息
      const local = messages.value.find(m =>
        m.id === serverMsg.id ||
        (!m.id && m.role === serverMsg.role && m.content === serverMsg.content)
      )
      if (local && !local.id) {
        local.id = serverMsg.id
      }
    })
    // 同步 context_stats（不触发列表重渲染）
    if (res.data.context_stats) {
      contextStats.value = normalizeContextStats(res.data.context_stats)
    }
  } catch (e) {
    // 静默失败，不影响用户体验
    console.warn('silentSyncIds 失败:', e)
  }
}

// 新建会话
const newSession = async () => {
  try {
    const res = await api.post('/ai/new-session')
    if (res.code === 200) {
      currentSessionId.value = res.data.session_id
      updateSessionState(res.data.session_id, { webSearchEnabled: draftWebSearchEnabled.value, completed: false, thinking: false })
      // 同步更新 URL，避免路由 watcher 因 URL 与 currentSessionId 不一致而重复触发
      router.replace({ name: 'AiChat', params: { sessionId: res.data.session_id } })
      messages.value = []
      
      // 重置上下文统计
      contextStats.value = normalizeContextStats({
        used_tokens: 0,
        max_tokens: selectedContextWindow.value.max_tokens,
        usage_percent: 0,
        used_display: '0',
        max_display: selectedContextWindow.value.max_display,
        is_estimate: false
      })
      
      // 重置流式状态
      streamingContent.value = ''
      reasoningContent.value = ''
      streamingReasoningList.value = []
      resetCurrentStreamingPhase()
      toolStatus.value = ''
      toolCallLogs.value = []
      thinking.value = false
      
      // 重置滚动状态
      isAtBottom.value = true
      isReasoningAtBottom.value = true
      
      fetchSessions()
    }
  } catch (e) {}
}

// 切换会话
const switchSession = async (sessionId) => {
  // 保存当前会话的状态（不关闭 SSE 连接，允许继续在后台运行）
  if (currentSessionId.value && thinking.value) {
    const currentState = getSessionState(currentSessionId.value)
    if (currentState) {
      // 保存当前流式状态到会话状态对象
      currentState.thinking = thinking.value
      currentState.streamingContent = streamingContent.value
      currentState.reasoningContent = reasoningContent.value
      currentState.streamingReasoningList = cloneBlocks(streamingReasoningList.value)
      currentState.streamingPhase = streamingPhase.value
      currentState.currentRoundStartedAt = currentRoundStartedAt.value
      currentState.reasoningStartTime = reasoningStartTime.value
      currentState.reasoningDuration = reasoningDuration.value
    }
  }
  
  // 清除该会话的闪烁状态（用户已进入查看）
  if (completedUnviewedSessions.value.has(sessionId)) {
    completedUnviewedSessions.value.delete(sessionId)
    stateUpdateCounter.value++ // 触发UI更新
  }
  
  currentSessionId.value = sessionId
  
  // 静默更新 URL（不触发路由导航，避免列表抖动）
  window.history.replaceState({}, '', `/ai/${sessionId}`)
  
  if (isMobile.value) {
    drawerVisible.value = false
  }
  
  // 【修复】先清空当前显示的流式状态，防止切换时短暂显示旧会话内容
  thinking.value = false
  streamingContent.value = ''
  reasoningContent.value = ''
  streamingReasoningList.value = []
  resetCurrentStreamingPhase()
  
  // 恢复新会话的状态（如果有的话）
  const newState = getSessionState(sessionId)
  const newStateIsStreaming = !!newState && (newState.streamStatus ? newState.streamStatus === 'streaming' : (newState.thinking && !newState.completed))
  if (newStateIsStreaming) {
    // 会话仍在流式响应中，恢复状态
    thinking.value = newState.thinking
    streamingContent.value = newState.streamingContent || ''
    reasoningContent.value = newState.reasoningContent || ''
    streamingReasoningList.value = cloneBlocks(newState.streamingReasoningList || [])
    streamingPhase.value = newState.streamingPhase || 'idle'
    currentRoundStartedAt.value = newState.currentRoundStartedAt || 0
    reasoningStartTime.value = newState.reasoningStartTime || 0
    reasoningDuration.value = newState.reasoningDuration || 0
    // 不需要 fetchHistory，因为数据还在流式传输
    // 重置滚动状态为底部
    isAtBottom.value = true
    isReasoningAtBottom.value = true
    setTimeout(() => {
      scrollToBottom(true)
    }, 100)
  } else if (newState && newState.completed) {
    // 会话在后台完成了，重新加载历史并清理状态
    clearSessionState(sessionId)  // 清理已完成的状态
    await fetchHistory()
  } else {
    // 重置为默认状态，加载历史消息
    await fetchHistory()
  }
}

// 发送消息
const editMessage = async (msg) => {
  if (!msg.id) {
    await silentSyncIds(currentSessionId.value)
  }
  if (!msg.id) {
    ElMessage.warning('这条消息还在保存中，请稍后再试')
    return
  }
  msg.isEditing = true
  msg.editContent = msg.content
}

const cancelEdit = (msg) => {
  msg.isEditing = false
}

const submitEdit = async (msg) => {
  const text = msg.editContent.trim()
  if (!text) {
    ElMessage.warning('消息内容不能为空')
    return
  }
  if (!cloudProxyMode.value && thinking.value) {
    ElMessage.warning('AI正在回复中，请稍后再试')
    return
  }
  
  msg.submitLoading = true
  try {
    const res = await api.post('/ai/rewind-history', {
      session_id: currentSessionId.value,
      message_id: msg.id
    })
    
    if (res.code === 200) {
      // 从前端列表中移除被修改的消息及其后的所有内容
      const idx = messages.value.findIndex(m => m.id === msg.id)
      if (idx !== -1) {
        messages.value.splice(idx)
      }
      msg.isEditing = false
      
      // 触发发送
      const oldInput = inputText.value
      inputText.value = text
      await sendMessage()
      // 等待发送完成后由于 inputText 会被自动清空，这里不恢复 oldInput 也是合理的体验
    }
  } catch (e) {
    if (!e.isBusinessError && !e.response) {
      ElMessage.error('回退历史记录发生错误，请重试')
    }
  } finally {
    msg.submitLoading = false
  }
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text) return
  
  // 云端代理模式下允许继续发送（不检查 thinking 状态）
  if (!cloudProxyMode.value && thinking.value) return

  // 如果没有会话，先创建
  if (!currentSessionId.value) {
    const res = await api.post('/ai/new-session')
    if (res.code === 200) {
      currentSessionId.value = res.data.session_id
      updateSessionState(res.data.session_id, { webSearchEnabled: draftWebSearchEnabled.value, completed: false, thinking: false })
    }
  }

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: text,
    time: formatTime(new Date()),
    isEditing: false,
    editContent: '',
    submitLoading: false,
  })
  inputText.value = ''
  
  // 保存当前用户消息，用于停止时上传
  currentUserMessage.value = text
  
  // 发送新消息时，重置滚动状态并强制滚动到底部
  isAtBottom.value = true
  isReasoningAtBottom.value = true
  scrollToBottom(true)

  // 云端代理模式：发送到后台任务队列
  if (cloudProxyMode.value) {
    await sendMessageToBackgroundTask(text)
    return
  }

  // 根据设置选择流式或非流式
  if (useStreaming.value) {
    await sendMessageStream(text)
  } else {
    await sendMessageSync(text)
  }
}

// 发送消息到后台任务队列（云端代理模式）
const sendMessageToBackgroundTask = async (text) => {
  try {
    const res = await api.post('/ai/task', {
      message: text,
      session_id: currentSessionId.value
    })
    
    if (res.code === 200) {
      ElMessage.success('已加入后台队列，处理完成后会通知您')
      
      // 更新会话ID（可能是新创建的）
      const newSessionId = res.data.session_id
      if (newSessionId) {
        currentSessionId.value = newSessionId
      }
      
      // 如果是首条消息（新会话），立即添加到会话列表，显示临时标题
      if (res.data.is_first_message) {
        const tempTitle = res.data.title || inputText.value.substring(0, 10) + (inputText.value.length > 10 ? '...' : '')
        sessions.value.unshift({
          session_id: newSessionId,
          title: tempTitle,  // 临时标题（用户消息前10字）
          task_status: 'pending',
          start_time: new Date().toISOString(),
          last_time: new Date().toISOString(),
          msg_count: 1
        })
      } else {
        // 不是首条消息，更新现有会话的任务状态
        const existingSession = sessions.value.find(s => s.session_id === newSessionId)
        if (existingSession) {
          existingSession.task_status = 'pending'
          existingSession.last_time = new Date().toISOString()
          // 将会话移到列表顶部
          const idx = sessions.value.indexOf(existingSession)
          if (idx > 0) {
            sessions.value.splice(idx, 1)
            sessions.value.unshift(existingSession)
          }
        } else {
          // 会话不在列表中，刷新列表
          await fetchSessions()
        }
      }
      
      // 添加一条占位消息表示正在后台处理
      messages.value.push(enrichAssistantMessage({
        role: 'assistant',
        content: '⏳ 正在后台处理中，您可以切换到其他会话或离开页面，处理完成后会通知您。',
        isPlaceholder: true,
        taskId: res.data.task_id,
        time: formatTime(new Date())
      }))
      
      // 刷新待处理任务数量
      fetchPendingTaskCount()
    }
  } catch (error) {
    console.error('发送后台任务失败:', error)
    if (!error.isBusinessError && !error.response) {
      ElMessage.error('发送失败，请重试')
    }
  }
}

// 获取待处理的后台任务数量
// 记录上次有任务状态的会话ID（用于检测任务完成）
let previousTaskingSessions = new Set()

// 静默更新当前会话历史：只追加新消息、移除占位符，不替换全部、不强制滚动
const silentUpdateCurrentHistory = async () => {
  if (!currentSessionId.value) return
  try {
    const res = await api.get('/ai/history', {
      params: { session_id: currentSessionId.value, limit: 9999 }
    })
    if (res.code !== 200) return

    const newMessages = (res.data.list || []).map(m => {
      let toolCalls = m.tool_calls
      if (typeof toolCalls === 'string') {
        try { toolCalls = JSON.parse(toolCalls) } catch (e) { toolCalls = null }
      }
      let parsedReasoning = parseReasoning(m.reasoning)
      if (toolCalls && Array.isArray(toolCalls) && toolCalls.length > 0 && parsedReasoning.length === 0) {
        parsedReasoning = toolCalls.map(tc => ({
          type: 'tool',
          name: tc.name || 'unknown',
          arguments: tc.arguments || {},
          result: tc.result || null,
          resultSummary: tc.has_error ? `失败: ${tc.result?.error || '未知错误'}` : getToolResultSummary(tc.result),
          status: tc.has_error ? 'error' : 'success',
          expanded: tc.has_error
        }))
      }
      const renderBlocks = buildMessageBlocks(parsedReasoning, m.content)
      const displayContent = extractFinalContentFromBlocks(renderBlocks, m.content)
      const mapped = {
        id: m.id,
        role: m.role,
        content: displayContent,
        reasoning: m.reasoning,
        parsedReasoning,
        renderBlocks,
        toolCalls,
        showReasoning: false,
        reasoning_duration: m.reasoning_duration,
        time: formatTime(m.create_time),
        ai_provider: m.ai_provider,
        ai_model: m.ai_model,
        isEditing: false,
        editContent: '',
        submitLoading: false,
      }
      return m.role === 'assistant' ? enrichAssistantMessage(mapped) : mapped
    })

    // 找出已有消息ID集合（排除占位符）
    const existingIds = new Set(messages.value.filter(m => m.id).map(m => m.id))
    // 只取新增的消息
    const added = newMessages.filter(m => m.id && !existingIds.has(m.id))

    // 移除占位符
    const placeholderIdx = messages.value.findIndex(m => m.isPlaceholder)
    if (placeholderIdx !== -1) {
      messages.value.splice(placeholderIdx, 1)
    }

    // 追加新消息
    if (added.length > 0) {
      messages.value.push(...added)
      // 只有用户已在底部时才滚动，避免打断阅读
      if (isAtBottom.value) {
        setTimeout(() => scrollToBottom(true), 100)
      }
    }

    // 静默更新 context 统计
  if (res.data.context_stats) {
    contextStats.value = normalizeContextStats(res.data.context_stats)
  }
  } catch (e) {
    console.error('静默更新历史失败:', e)
  }
}

const fetchPendingTaskCount = async () => {
  try {
    const res = await api.get('/ai/task/pending-count')
    if (res.code === 200) {
      const newCount = res.data.count || 0
      const oldCount = pendingTaskCount.value
      pendingTaskCount.value = newCount

      // 没有任务且之前也没有 → 什么都不做，定时器也可停止
      if (newCount === 0 && oldCount === 0) {
        stopTaskRefresh()
        return
      }

      // 记录刷新前有任务状态的会话
      const beforeTaskingSessions = new Set(
        sessions.value
          .filter(s => s.task_status === 'pending' || s.task_status === 'running')
          .map(s => s.session_id)
      )

      // 静默刷新会话列表（只更新数据，不触发视觉跳动）
      await fetchSessions(false, true)

      // 检测哪些会话的任务刚完成
      const afterTaskingSessions = new Set(
        sessions.value
          .filter(s => s.task_status === 'pending' || s.task_status === 'running')
          .map(s => s.session_id)
      )

      beforeTaskingSessions.forEach(sessionId => {
        if (!afterTaskingSessions.has(sessionId) && sessionId !== currentSessionId.value) {
          // 非当前会话任务完成：标记闪烁
          completedUnviewedSessions.value.add(sessionId)
          stateUpdateCounter.value++
        }
      })

      // 当前会话任务刚完成：静默追加新消息，不整体替换
      const currentSession = sessions.value.find(s => s.session_id === currentSessionId.value)
      if (currentSession && !currentSession.task_status && oldCount > 0) {
        await silentUpdateCurrentHistory()
      }

      // 任务全部完成后自动停止定时器
      if (newCount === 0) {
        stopTaskRefresh()
      }
    }
  } catch (error) {
    console.error('获取待处理任务数失败:', error)
  }
}

// 定时刷新任务状态（当有待处理任务时，每5秒一次）
let taskRefreshTimer = null
const startTaskRefresh = () => {
  if (taskRefreshTimer) return
  taskRefreshTimer = setInterval(() => {
    // 有任务才轮询；若外部已清零则停止定时器
    if (pendingTaskCount.value > 0) {
      fetchPendingTaskCount()
    } else {
      stopTaskRefresh()
    }
  }, 5000)
}

const stopTaskRefresh = () => {
  if (taskRefreshTimer) {
    clearInterval(taskRefreshTimer)
    taskRefreshTimer = null
  }
}

// 计算任务等待/进行时间
const formatDuration = (startTime) => {
  if (!startTime) return '--'
  const start = new Date(startTime).getTime()
  const now = Date.now()
  const diff = Math.floor((now - start) / 1000) // 秒
  
  if (diff < 60) return `${diff}秒`
  if (diff < 3600) return `${Math.floor(diff / 60)}分${diff % 60}秒`
  const hours = Math.floor(diff / 3600)
  const mins = Math.floor((diff % 3600) / 60)
  return `${hours}小时${mins}分`
}

// 格式化思考时长（毫秒转换为可读格式）
const formatReasoningDuration = (ms) => {
  if (!ms || ms < 0) return ''
  const seconds = Math.floor(ms / 1000)
  const milliseconds = Math.floor(ms % 1000)
  if (seconds === 0) {
    return `${milliseconds}毫秒`
  } else if (seconds < 60) {
    return `${seconds}.${Math.floor(milliseconds / 100)}秒`
  } else {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}分${remainingSeconds}秒`
  }
}

// 获取任务队列数据
const fetchTaskQueue = async () => {
  try {
    const [pendingRes, runningRes] = await Promise.all([
      api.get('/ai/tasks', { params: { status: 'pending' } }),
      api.get('/ai/tasks', { params: { status: 'running' } })
    ])
    
    const pendingTasks = pendingRes.code === 200 ? (pendingRes.data.list || []) : []
    const runningTasks = runningRes.code === 200 ? (runningRes.data.list || []) : []
    taskQueueList.value = [...runningTasks, ...pendingTasks]
    
    // 如果队列清空了，更新计数
    if (taskQueueList.value.length === 0) {
      pendingTaskCount.value = 0
    }
  } catch (error) {
    console.error('获取任务队列失败:', error)
  }
}

// 启动任务队列弹窗轮询
const startTaskQueueRefresh = () => {
  if (taskQueueRefreshTimer) return
  taskQueueRefreshTimer = setInterval(() => {
    if (taskQueueVisible.value) {
      fetchTaskQueue()
    }
  }, 2000)  // 每2秒刷新一次
}

// 停止任务队列弹窗轮询
const stopTaskQueueRefresh = () => {
  if (taskQueueRefreshTimer) {
    clearInterval(taskQueueRefreshTimer)
    taskQueueRefreshTimer = null
  }
}

// 监听弹窗状态
watch(taskQueueVisible, (visible) => {
  if (visible) {
    fetchTaskQueue()  // 打开时立即获取数据
    startTaskQueueRefresh()  // 启动轮询
  } else {
    stopTaskQueueRefresh()  // 关闭时停止轮询
  }
})

// 显示待处理任务列表弹窗
const showPendingTasks = () => {
  taskQueueVisible.value = true
}

// 处理从通知跳转过来查看任务结果（支持继续上下文对话）
const handleTaskRedirect = async (taskId) => {
  try {
    // 获取任务详情
    const res = await api.get(`/ai/task/${taskId}`)
    if (res.code !== 200 || !res.data) {
      ElMessage.error('任务不存在或已被删除')
      return
    }
    
    const task = res.data
    const sessionId = task.session_id
    
    // 切换到任务对应的会话
    currentSessionId.value = sessionId
    
    // 检查会话是否在列表中，如果不在则刷新会话列表
    if (!sessions.value.find(s => s.session_id === sessionId)) {
      await fetchSessions()
    }
    
    // 加载会话历史（这会显示完整的对话上下文）
    await fetchHistory()
    
    // 根据任务状态显示提示
    if (task.status === 'completed') {
      ElMessage.success('任务已完成，您可以继续在此会话中对话')
    } else if (task.status === 'failed') {
      ElMessage.error('任务处理失败: ' + (task.error_message || '未知错误'))
    } else if (task.status === 'pending' || task.status === 'running') {
      ElMessage.info('任务正在处理中，请稍候...')
    }
    
    // 滚动到底部
    setTimeout(() => {
      scrollToBottom(true)
    }, 100)
    
  } catch (error) {
    console.error('处理任务跳转失败:', error)
    if (!error.isBusinessError && !error.response) {
      ElMessage.error('加载任务信息失败')
    }
  }
}

// 节流滚动函数（主消息列表）
const throttleScroll = (() => {
  let tick = false
  return () => {
    // 如果页面不可见，标记有待处理的滚动请求但不实际执行
    if (!isPageVisible.value) {
      pendingScrollRequest.value = true
      return
    }
    
    if (!tick) {
      tick = true
      requestAnimationFrame(() => {
        // 在内容更新时，如果用户在底部，继续自动滚动
        scrollToBottom()
        tick = false
      })
    }
  }
})()

// 【新增】节流滚动思考容器
const throttleScrollReasoning = (() => {
  let tick = false
  return () => {
    if (!streamingReasoningBodyRef.value) {
      return
    }

    // 如果页面不可见，标记有待处理的滚动请求但不实际执行
    if (!isPageVisible.value) {
      pendingScrollRequest.value = true
      return
    }
    
    if (!tick) {
      tick = true
      requestAnimationFrame(() => {
        scrollReasoningToBottom()
        tick = false
      })
    }
  }
})()

// 【新增】滚动思考容器到底部
const scrollReasoningToBottom = (force = false) => {
  nextTick(() => {
    if (streamingReasoningBodyRef.value) {
      const el = streamingReasoningBodyRef.value
      const currentlyAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
      
      // 如果用户向上滚动过且还没滚回底部，则不自动滚动
      if (!force && !isReasoningAtBottom.value && !currentlyAtBottom) {
        return
      }
      
      el.scrollTop = el.scrollHeight
      isReasoningAtBottom.value = true

      const liveBody = el.querySelector('.thinking-card-body.is-live')
      if (liveBody) {
        liveBody.scrollTop = liveBody.scrollHeight
      }
    }
  })
}

const currentEventSource = ref(null)
const currentUserMessage = ref('') // 保存当前用户消息用于停止时上传

// 🔧 用户点击"继续分析"按钮 → 通过API通知后端继续
const handleContinue = async () => {
  if (!continueSessionId.value) return
  continueLoading.value = true
  try {
    await api.post('/ai/confirm-continue', { session_id: continueSessionId.value })
    // 后端会通过Redis信号继续，按钮状态会在收到 continue_confirmed 时清除
  } catch (e) {
    if (!e.isBusinessError && !e.response) {
      ElMessage.error('确认继续失败，请重试')
    }
    continueLoading.value = false
  }
}

const stopAiGeneration = async () => {
  if (!currentEventSource.value) return
  
  try {
    await ElMessageBox.confirm(
      '确定要停止当前的 AI 生成吗？已生成的内容将被保留。',
      '确认停止',
      {
        confirmButtonText: '确定停止',
        cancelButtonText: '继续生成',
        type: 'warning',
      }
    )
    
    // 用户确认后执行停止逻辑
    currentEventSource.value.close()
    currentEventSource.value = null
    thinking.value = false
    resetCurrentStreamingPhase()
    
    // 【修复】使用闭包中固定的 sessionId 发送保存请求
    const stopSessionId = currentSessionId.value
    
    // 更新会话状态为已完成（强制刷新以立即移除"输出中"状态）
    updateSessionState(stopSessionId, {
      eventSource: null,
      thinking: false,
      completed: true,
      streamStatus: 'completed',
      streamingPhase: 'idle',
      currentRoundStartedAt: 0,
      toolStatus: '',
      toolCallLogs: []
    })
    forceStateRefresh()  // 立即刷新UI移除"输出中"状态
    
    // 准备要保存的内容 (优先使用JSON结构)
    finalizeStreamingThought(streamingReasoningList.value, true)

    let finalReasoning = null
    if (streamingReasoningList.value.length > 0) {
      finalReasoning = JSON.stringify(streamingReasoningList.value)
    } else if (reasoningContent.value) {
      finalReasoning = reasoningContent.value
    }
    
    const assistantContent = streamingContent.value + '\n\n[已停止生成]'
    
  if (streamingContent.value || streamingReasoningList.value.length > 0) {
        messages.value.push(enrichAssistantMessage({
          role: 'assistant',
          content: assistantContent,
          reasoning: finalReasoning,
          parsedReasoning: streamingReasoningList.value.length > 0 ? JSON.parse(JSON.stringify(streamingReasoningList.value)) : parseReasoning(finalReasoning),
          showReasoning: true,
          ai_provider: aiConfig.provider,  // 新增：记录模型信息
          ai_model: aiConfig.model,        // 新增：记录模型信息
          time: formatTime(new Date())
        }))
       
       // 调用后端API保存到数据库
       try {
         await api.post('/ai/stop-and-save', {
           session_id: stopSessionId,
           user_message: currentUserMessage.value,
           assistant_content: assistantContent,
           reasoning: finalReasoning
         })
         
         // 立即清除本地会话的 task_status，防止 fetchSessions 返回 running 重新触发 loading 图标
         const stoppedSession = sessions.value.find(s => s.session_id === stopSessionId)
         if (stoppedSession) stoppedSession.task_status = null
         // 刷新会话列表以显示新标题
         fetchSessions()
       } catch (err) {
         console.error('保存停止的会话失败:', err)
         ElMessage.warning('会话保存失败，刷新页面后可能会丢失')
       }
       
       streamingContent.value = ''
       reasoningContent.value = ''
       streamingReasoningList.value = []
       resetCurrentStreamingPhase()
       toolStatus.value = ''
       toolCallLogs.value = []
       currentUserMessage.value = '' // 清空
       scrollToBottom()
    }
    
    ElMessage.info('已停止 AI 输出')
  } catch (error) {
    // 用户取消，不做任何操作
  }
}

// 流式发送消息 (EventSource)
const sendMessageStream = async (text) => {
  const sessionId = currentSessionId.value
  thinking.value = true
  streamingThinkingExpanded.value = true
  streamingContent.value = ''
  reasoningContent.value = ''
  streamingReasoningList.value = [] // 重置列表
  showStreamingReasoning.value = true // 新消息默认展开思考
  toolStatus.value = ''
  toolCallLogs.value = []
  isReasoningAtBottom.value = true // 重置思考容器滚动状态
  reasoningStartTime.value = Date.now() // 记录思考开始时间
  reasoningDuration.value = 0
  reasoningDone.value = false
  streamingPhase.value = 'reasoning'
  currentRoundStartedAt.value = reasoningStartTime.value
  
  // 获取或创建会话状态
  // 更新会话状态为正在思考（强制刷新以立即显示状态）
  updateSessionState(sessionId, {
    thinking: true,
    completed: false,
    streamStatus: 'streaming',
    streamingContent: '',
    reasoningContent: '',
    streamingReasoningList: [],
    streamingPhase: 'reasoning',
    currentRoundStartedAt: reasoningStartTime.value,
    reasoningStartTime: reasoningStartTime.value,
    reasoningDuration: 0
  })
  forceStateRefresh()  // 立即刷新UI显示"输出中"状态
  
  let ticketResponse
  try {
    ticketResponse = await api.post('/ai/stream-ticket', {
      kind: 'chat',
      message: text,
      session_id: sessionId,
    })
  } catch {
    thinking.value = false
    updateSessionState(sessionId, { thinking: false, streamStatus: 'idle' })
    return
  }

  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api'
  const url = `${baseUrl}/ai/chat-stream?ticket=${encodeURIComponent(ticketResponse.data.ticket)}${buildModelQuery()}`
  
  // 如果这个会话已有 EventSource，关闭它（不关闭其他会话的）
  const sessionState = getSessionState(sessionId)
  if (sessionState && sessionState.eventSource) {
    sessionState.eventSource.close()
  }
  if (currentEventSource.value && currentSessionId.value === sessionId) {
    currentEventSource.value.close()
  }
  
  const eventSource = new EventSource(url)
  currentEventSource.value = eventSource
  updateSessionState(sessionId, { eventSource, streamStatus: 'streaming' })

  let streamSettled = false
  let pendingCurrentKind = null
  let pendingCurrentDelta = ''
  let pendingCurrentRoundDurationMs = null
  let pendingCurrentFlushTimer = null

  const syncCurrentSessionSnapshot = (overrides = {}, refreshMode = 'throttle') => {
    const state = getSessionState(sessionId)
    Object.assign(state, {
      eventSource: currentEventSource.value === eventSource ? eventSource : null,
      thinking: thinking.value,
      completed: false,
      streamStatus: state.streamStatus || 'streaming',
      streamingContent: streamingContent.value,
      reasoningContent: reasoningContent.value,
      streamingReasoningList: cloneBlocks(streamingReasoningList.value),
      streamingPhase: streamingPhase.value,
      currentRoundStartedAt: currentRoundStartedAt.value,
      reasoningStartTime: reasoningStartTime.value,
      reasoningDuration: reasoningDuration.value,
      toolStatus: toolStatus.value,
      toolCallLogs: Array.isArray(toolCallLogs.value) ? [...toolCallLogs.value] : [],
      lastUpdate: Date.now(),
    }, overrides)

    if (refreshMode === 'force') {
      forceStateRefresh()
    } else if (refreshMode === 'throttle') {
      throttleStateRefresh()
    }
  }

  const clearCurrentStreamingUi = () => {
    if (currentEventSource.value === eventSource) {
      currentEventSource.value = null
    }
    thinking.value = false
    streamingContent.value = ''
    reasoningContent.value = ''
    streamingReasoningList.value = []
    toolStatus.value = ''
    toolCallLogs.value = []
    showContinueButton.value = false
    continueLoading.value = false
    currentUserMessage.value = ''
    resetCurrentStreamingPhase()
    reasoningStartTime.value = 0
    reasoningDuration.value = 0
    reasoningDone.value = false
  }

  const buildInterruptedContent = (baseContent, hasReasoning) => {
    if (baseContent) {
      return `${baseContent}\n\n> ⚠️ **连接中断**，以上为部分回复`
    }
    if (hasReasoning) {
      return '> ⚠️ **连接中断**，已保留部分思考过程'
    }
    return ''
  }

  const flushCurrentStreamBuffer = () => {
    if (pendingCurrentFlushTimer) {
      clearTimeout(pendingCurrentFlushTimer)
      pendingCurrentFlushTimer = null
    }
    if (!pendingCurrentKind || !pendingCurrentDelta) return

    // 流已结束、被手动停止，或当前 EventSource 已被新的连接替换时，丢弃挂起缓冲，
    // 避免旧定时器把会话状态重新写回 "streaming"。
    if (streamSettled || currentEventSource.value !== eventSource) {
      pendingCurrentKind = null
      pendingCurrentDelta = ''
      pendingCurrentRoundDurationMs = null
      return
    }

    const kind = pendingCurrentKind
    const delta = pendingCurrentDelta
    const roundDurationMs = pendingCurrentRoundDurationMs
    pendingCurrentKind = null
    pendingCurrentDelta = ''
    pendingCurrentRoundDurationMs = null

    if (kind === 'content') {
      finalizeStreamingThought(streamingReasoningList.value, false)
      streamingContent.value = mergeStreamingText(streamingContent.value, delta)
      appendStreamingContentBlock(streamingReasoningList.value, delta, { roundDurationMs })
      if (!streamSettled) {
        syncCurrentSessionSnapshot({ streamStatus: 'streaming' })
      }
      throttleScroll()
      return
    }

    reasoningContent.value = mergeStreamingText(reasoningContent.value, delta)
    appendStreamingReasoningBlock(streamingReasoningList.value, delta)
    if (!streamSettled) {
      syncCurrentSessionSnapshot({ streamStatus: 'streaming' })
    }
    throttleScrollReasoning()
    throttleScroll()
  }

  const enqueueCurrentStreamDelta = (kind, delta, options = {}) => {
    if (!delta) return
    if (pendingCurrentKind && pendingCurrentKind !== kind) {
      flushCurrentStreamBuffer()
    }
    pendingCurrentKind = kind
    pendingCurrentDelta += delta
    if (kind === 'content' && pendingCurrentRoundDurationMs == null && options.roundDurationMs != null) {
      pendingCurrentRoundDurationMs = options.roundDurationMs
    }
    if (!pendingCurrentFlushTimer) {
      pendingCurrentFlushTimer = setTimeout(flushCurrentStreamBuffer, 40)
    }
  }

  const handleStreamFailure = async (source, error) => {
    if (streamSettled) return
    streamSettled = true
    console.error(`SSE stream failed [${source}]`, error)
    eventSource.close()
    flushCurrentStreamBuffer()
    const isIllegalRequest = await probeIllegalRequest(url, {
      notify: (message) => ElMessage.error(message)
    })

    const isCurrentSessionOnError = currentSessionId.value === sessionId
    if (isCurrentSessionOnError) {
      finalizeStreamingThought(streamingReasoningList.value, true)
      const finalBlocks = cloneBlocks(streamingReasoningList.value)
      const finalContentBase = extractFinalContentFromBlocks(finalBlocks, streamingContent.value)
      const finalReasoning = finalBlocks.length > 0
        ? JSON.stringify(finalBlocks)
        : (reasoningContent.value || null)

      if (finalContentBase || finalReasoning) {
        const interruptedContent = buildInterruptedContent(finalContentBase, !!finalReasoning)
        const parsedReasoning = finalBlocks.length > 0 ? finalBlocks : (finalReasoning ? parseReasoning(finalReasoning) : [])
        messages.value.push(enrichAssistantMessage({
          role: 'assistant',
          content: interruptedContent,
          reasoning: finalReasoning,
          parsedReasoning: parsedReasoning,
          renderBlocks: buildMessageBlocks(parsedReasoning, interruptedContent),
          showReasoning: false,
          reasoning_duration: reasoningStartTime.value ? Date.now() - reasoningStartTime.value : 0,
          ai_provider: aiConfig.provider,
          ai_model: aiConfig.model,
          time: formatTime(new Date()),
          hasError: true
        }))
      } else {
        if (!isIllegalRequest) {
          ElMessage.error('连接失败，请重试')
        }
      }

      clearCurrentStreamingUi()
      scrollToBottom()
    } else {
      const errorState = getSessionState(sessionId)
      if (errorState?.streamingReasoningList?.length) {
        finalizeStreamingThought(errorState.streamingReasoningList, true)
      }
      resetBackgroundStreamingPhase(errorState)
      console.warn(`后台会话 ${sessionId} SSE 连接中断`)
    }

    updateSessionState(sessionId, {
      eventSource: null,
      thinking: false,
      completed: true,
      streamStatus: 'failed',
      streamingContent: '',
      reasoningContent: '',
      streamingReasoningList: [],
      streamingPhase: 'idle',
      currentRoundStartedAt: 0,
      toolStatus: '',
      toolCallLogs: []
    })
    forceStateRefresh()
  }
  
  eventSource.onmessage = (event) => {
    // 获取该SSE对应的会话状态（直接使用 reactive 对象，流式更新时不触发计数器）
    const thisSessionState = sessionStatesMap[sessionId] || (sessionStatesMap[sessionId] = createDefaultState())
    const isCurrentSession = currentSessionId.value === sessionId

    if (streamSettled) {
      return
    }
    
    if (event.data === '[DONE]') {
      streamSettled = true
      eventSource.close()
      resetBackgroundStreamingPhase(thisSessionState)
      
      // 清理会话状态（强制刷新以立即更新状态显示）
      updateSessionState(sessionId, {
        eventSource: null,
        thinking: false,
        completed: true,
        streamStatus: 'completed',
        streamingPhase: 'idle',
        currentRoundStartedAt: 0
      })
      forceStateRefresh()  // 立即刷新UI移除"输出中"状态
      
      // 只有当前显示的会话才更新UI
      if (isCurrentSession) {
        flushCurrentStreamBuffer()
        currentEventSource.value = null
        resetCurrentStreamingPhase()
        finalizeStreamingThought(streamingReasoningList.value, false)
        const finalBlocks = cloneBlocks(streamingReasoningList.value)
        const finalContent = extractFinalContentFromBlocks(finalBlocks, streamingContent.value)
        
        // 结束时，准备推理内容（优先使用结构化列表）
        let finalReasoning = null
        if (finalBlocks.length > 0) {
          finalReasoning = JSON.stringify(finalBlocks)
        } else if (reasoningContent.value) {
          finalReasoning = reasoningContent.value
        }

        // 将流式内容添加到消息历史
        if (finalContent || finalReasoning) {
          reasoningDuration.value = reasoningStartTime.value ? Date.now() - reasoningStartTime.value : reasoningDuration.value
          
          messages.value.push(enrichAssistantMessage({
            role: 'assistant',
            content: finalContent,
            reasoning: finalReasoning, 
            parsedReasoning: finalBlocks.length > 0 ? finalBlocks : parseReasoning(finalReasoning),
            renderBlocks: finalBlocks.length > 0 ? finalBlocks : buildMessageBlocks(parseReasoning(finalReasoning), finalContent),
            showReasoning: false, // 思考完成后默认折叠
            reasoning_duration: reasoningDuration.value, // 保存思考耗时
            ai_provider: aiConfig.provider,  // 新增：记录模型信息
            ai_model: aiConfig.model,        // 新增：记录模型信息
            time: formatTime(new Date())
          }))
        }
        clearCurrentStreamingUi()
        scrollToBottom()
        // 延迟同步消息 ID（用于后续编辑功能），使用静默补丁避免整列表重渲染
        setTimeout(() => {
          if (currentSessionId.value === sessionId) silentSyncIds(sessionId)
        }, 400)
      } else {
        // 非当前会话完成，标记完成状态
        updateSessionState(sessionId, { completed: true })
      }
      
      fetchSessions()  // 无论哪个会话完成都刷新列表

      if (sessionStatesMap[sessionId]?.titlePending) {
        scheduleTitlePendingRefresh(sessionId)
      }
      return
    }

    
    try {
      const chunk = JSON.parse(event.data)
      // 检查是否是当前显示的会话
      const isCurrentSession = currentSessionId.value === sessionId
      
      // 流式内容只更新当前显示的会话
      if (chunk.type === 'content') {
        if (chunk.delta) {
          if (isCurrentSession) {
            const roundDurationMs = beginCurrentContentPhase()
            enqueueCurrentStreamDelta('content', chunk.delta, { roundDurationMs })
          }
          if (!isCurrentSession) {
            thisSessionState.streamingReasoningList = thisSessionState.streamingReasoningList || []
            finalizeStreamingThought(thisSessionState.streamingReasoningList || [], false)
            const backgroundRoundDurationMs = beginBackgroundContentPhase(thisSessionState)
            thisSessionState.streamingContent = mergeStreamingText(thisSessionState.streamingContent || '', chunk.delta)
            appendStreamingContentBlock(thisSessionState.streamingReasoningList, chunk.delta, { roundDurationMs: backgroundRoundDurationMs })
            thisSessionState.streamStatus = 'streaming'
            throttleStateRefresh()
          }
        }
      } else if (chunk.type === 'reasoning') {
        const delta = chunk.delta
        if (isCurrentSession) {
          // 更新UI
          beginCurrentStreamingPhase('reasoning')
          enqueueCurrentStreamDelta('reasoning', delta)
        }
        if (!isCurrentSession) {
          // 保存到后台会话状态
          beginBackgroundStreamingPhase(thisSessionState, 'reasoning')
          thisSessionState.reasoningContent = mergeStreamingText(thisSessionState.reasoningContent || '', delta)
          thisSessionState.streamingReasoningList = thisSessionState.streamingReasoningList || []
          appendStreamingReasoningBlock(thisSessionState.streamingReasoningList, delta)
          thisSessionState.streamStatus = 'streaming'
          throttleStateRefresh()  // 节流刷新
        }
      } else if (chunk.type === 'tool_status') {
        if (isCurrentSession) {
          toolStatus.value = chunk.message
        }
        
        if (chunk.action === 'start') {
          if (isCurrentSession) {
            flushCurrentStreamBuffer()
            showStreamingReasoning.value = true
            streamingThinkingExpanded.value = true
            finalizeStreamingThought(streamingReasoningList.value, false)
            beginCurrentStreamingPhase('tool')
          }
          if (!isCurrentSession) {
            thisSessionState.streamingReasoningList = thisSessionState.streamingReasoningList || []
            finalizeStreamingThought(thisSessionState.streamingReasoningList, false)
            beginBackgroundStreamingPhase(thisSessionState, 'tool')
          }
          const toolItem = {
            type: 'tool',
            id: chunk.tool_call_id,
            name: chunk.tool_name,
            arguments: chunk.arguments || {},
            status: 'loading',
            message: chunk.message,
            result: null,
            resultSummary: '',
            expanded: false
          }
          if (isCurrentSession) {
            streamingReasoningList.value.push(toolItem)
            syncCurrentSessionSnapshot({ toolStatus: chunk.message, streamStatus: 'streaming' })
            // 【修复】工具调用卡片添加时，同时滚动思考容器和主消息列表
            throttleScrollReasoning() // 滚动思考容器内部
            throttleScroll() // 滚动主消息列表（因为整个消息块变高了）
          }
          if (!isCurrentSession) {
            thisSessionState.streamingReasoningList.push({...toolItem})
            thisSessionState.toolStatus = chunk.message
            thisSessionState.streamStatus = 'streaming'
            throttleStateRefresh()
          }
        } else if (chunk.action === 'end') {
          // 更新UI
          if (isCurrentSession) {
            flushCurrentStreamBuffer()
            const item = streamingReasoningList.value.find(i => i.id === chunk.tool_call_id)
            if (item) {
              item.status = chunk.success ? 'success' : 'error'
              item.message = chunk.message
              item.result = chunk.result
              item.resultSummary = chunk.data_count ? (typeof chunk.data_count === 'string' ? chunk.data_count : `${chunk.data_count} 条数据`) : (chunk.success ? '调用成功' : '调用失败')
              item.expanded = !chunk.success
            }
            syncCurrentSessionSnapshot({ toolStatus: chunk.message, streamStatus: 'streaming' })
            // 【修复】工具调用结果更新时，同时滚动思考容器和主消息列表
            throttleScrollReasoning() // 滚动思考容器内部
            throttleScroll() // 滚动主消息列表
          }
          if (isCurrentSession) {
          }
          // 更新会话状态
          if (!isCurrentSession && thisSessionState.streamingReasoningList) {
            const item = thisSessionState.streamingReasoningList.find(i => i.id === chunk.tool_call_id)
            if (item) {
              item.status = chunk.success ? 'success' : 'error'
              item.message = chunk.message
              item.result = chunk.result
              item.resultSummary = chunk.data_count ? (typeof chunk.data_count === 'string' ? chunk.data_count : `${chunk.data_count} 条数据`) : (chunk.success ? '调用成功' : '调用失败')
              item.expanded = !chunk.success
            }
            thisSessionState.toolStatus = chunk.message
            thisSessionState.streamStatus = 'streaming'
            throttleStateRefresh()
          }
        }
        
        if (isCurrentSession) {
          throttleScroll()
        }
      } else if (chunk.type === 'error') {
        ElMessage.error(chunk.message)
        if (isCurrentSession) {
          flushCurrentStreamBuffer()
          finalizeStreamingThought(streamingReasoningList.value, true)
          resetCurrentStreamingPhase()
          streamingContent.value = mergeStreamingText(streamingContent.value, `\n\n> ⚠️ **系统错误**: ${chunk.message}`)
          appendStreamingContentBlock(streamingReasoningList.value, `\n\n> ⚠️ **系统错误**: ${chunk.message}`)
          syncCurrentSessionSnapshot({ streamStatus: 'degraded' })
        }
        if (!isCurrentSession) {
          thisSessionState.streamingReasoningList = thisSessionState.streamingReasoningList || []
          finalizeStreamingThought(thisSessionState.streamingReasoningList, true)
          resetBackgroundStreamingPhase(thisSessionState)
          const errorDelta = `\n\n> ⚠️ **系统错误**: ${chunk.message}`
          thisSessionState.streamingContent = mergeStreamingText(thisSessionState.streamingContent || '', errorDelta)
          appendStreamingContentBlock(thisSessionState.streamingReasoningList, errorDelta)
          thisSessionState.streamStatus = 'degraded'
          throttleStateRefresh()
        }
      } else if (chunk.type === 'session_created') {
           // 【修复】只有当发起SSE的会话仍是当前显示会话时才更新 currentSessionId
           // 防止旧会话的SSE劫持当前会话
           if (isCurrentSession || !currentSessionId.value) {
             currentSessionId.value = chunk.session_id
             // 静默更新 URL（不触发路由导航，避免中断流式响应）
             window.history.replaceState({}, '', `/ai/${chunk.session_id}`)
           }
           // 无论是否为当前会话，都要更新会话列表
           // 把临时标题缓存到本地 map，防止 fetchSessions 返回 null 时丢失
           if (chunk.title) localTempTitles[chunk.session_id] = chunk.title
           if (!sessions.value.find(s => s.session_id === chunk.session_id)) {
             sessions.value.unshift({
              session_id: chunk.session_id,
              title: chunk.title,
              start_time: new Date().toISOString(),
              last_time: new Date().toISOString(),
              msg_count: 1
             })
           }
        } else if (chunk.type === 'meta') {
           // 【修复】只有当发起SSE的会话仍是当前显示会话时才更新
           if (chunk.session_id && isCurrentSession) {
             currentSessionId.value = chunk.session_id
             // 静默更新 URL（不触发路由导航，避免中断流式响应）
             window.history.replaceState({}, '', `/ai/${chunk.session_id}`)
           }
        } else if (chunk.type === 'model_info' || chunk.type === 'model_meta') {
           // 更新模型信息（动态切换）
           if (chunk.provider && chunk.model) {
             aiConfig.provider = chunk.provider
             aiConfig.model = chunk.model
             if (!aiConfig.manualSelectEnabled) {
               aiConfig.selectedModel = chunk.model
               aiConfig.selectedMode = chunk.thinking_mode || aiConfig.selectedMode
             }
             if (chunk.reason === 'auto_switch') {
               // 显示切换提示（可选）
               console.log(`模型自动切换: ${chunk.provider} · ${chunk.model}`)
             }
           }
        } else if (chunk.type === 'heartbeat') {
           // 心跳事件：多轮工具调用之间的 keep-alive 信号
           console.log(`工具调用心跳: 第${chunk.iteration || '-'}轮${chunk.waiting ? ' (等待用户确认)' : ''}${chunk.ssl_retry ? ` SSL重试#${chunk.ssl_retry}` : ''}${chunk.source ? ` source=${chunk.source}` : ''}${chunk.idle_seconds ? ` idle=${chunk.idle_seconds}s` : ''}`)
        } else if (chunk.type === 'confirm_continue') {
           // 🔧 达到工具调用上限，显示继续按钮
           if (isCurrentSession) {
             showContinueButton.value = true
             continueIteration.value = chunk.iteration
             continueSessionId.value = chunk.session_id || currentSessionId.value
             continueLoading.value = false
             scrollToBottom()
           }
        } else if (chunk.type === 'continue_confirmed') {
           // 🔧 后端已确认继续，隐藏按钮
           if (isCurrentSession) {
             showContinueButton.value = false
             continueLoading.value = false
             ElMessage.success({ message: chunk.message, duration: 3000 })
           }
        } else if (chunk.type === 'continue_timeout') {
           // 🔧 等待超时，隐藏按钮
           if (isCurrentSession) {
             showContinueButton.value = false
             continueLoading.value = false
           }
        } else if (chunk.type === 'context_stats') {
           // 更新上下文使用统计（仅当前会话）
           if (chunk.stats && isCurrentSession) {
             contextStats.value = normalizeContextStats({ ...chunk.stats, is_estimate: false })
           }
        } else if (chunk.type === 'title_pending') {
           // 标题正在生成中
           updateSessionState(chunk.session_id || currentSessionId.value, { titlePending: true })
        } else if (chunk.type === 'title') {
           // 标题生成完成，立即更新会话列表
           const targetSessionId = chunk.session_id || currentSessionId.value
           const session = sessions.value.find(s => s.session_id === targetSessionId)
           if (session && chunk.title) {
             session.title = chunk.title
           }
           if (chunk.title) {
             delete localTempTitles[targetSessionId]
           }
           clearTitleRefreshTimer(targetSessionId)
           updateSessionState(targetSessionId, { titlePending: false })
        } else if (chunk.type === 'title_error') {
           // 标题生成失败
           const targetSessionId = chunk.session_id || currentSessionId.value
           clearTitleRefreshTimer(targetSessionId)
           updateSessionState(targetSessionId, { titlePending: false })
           console.warn('标题生成失败:', chunk.message)
        }
    } catch (e) {
      console.error('Parse SSE error:', e)
    }
  }

  eventSource.onerror = (error) => { void handleStreamFailure('eventsource', error) }
}

// 同步发送消息 (原有方式)
const sendMessageSync = async (text) => {
  thinking.value = true
  try {
    const item = selectedModelInfo.value
    const payload = {
      message: text,
      session_id: currentSessionId.value,
      web_search: currentSessionWebSearchEnabled.value ? 1 : 0
    }
    if (aiConfig.manualSelectEnabled && aiConfig.selectedModel && item) {
      payload.provider = item.provider
      payload.model = item.model
      payload.thinking_mode = aiConfig.selectedMode || 'auto'
    }
    const res = await api.post('/ai/chat', {
      ...payload
    })
    if (res.code === 200) {
      messages.value.push(enrichAssistantMessage({
        role: 'assistant',
        content: res.data.content,
        time: formatTime(new Date())
      }))
      fetchSessions()
    }
  } catch (error) {
    messages.value.push(enrichAssistantMessage({
      role: 'assistant',
      content: '抱歉，我遇到了一些问题，请稍后再试。',
      time: formatTime(new Date())
    }))
  } finally {
    thinking.value = false
    scrollToBottom(true)
  }
}

// 快速提问（只填充输入框并聚焦，不自动发送）
const sendQuickQuestion = (question) => {
  inputText.value = question
  nextTick(() => {
    inputRef.value?.focus()
  })
}

// 滚动到底部
const scrollToBottom = (force = false) => {
  // 如果页面不可见且非强制滚动，标记待处理并延迟执行
  if (!isPageVisible.value && !force) {
    pendingScrollRequest.value = true
    return
  }
  
  nextTick(() => {
    // 滚动主消息列表
    if (messageListRef.value) {
      const el = messageListRef.value
      const currentlyAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
      
      // 逻辑：用户意图（isAtBottom）优先，实时位置（currentlyAtBottom）辅助
      // - isAtBottom=true（用户没主动向上滚）→ 总是滚动
      // - isAtBottom=false（用户主动向上滚了）→ 只有滚回底部才恢复滚动
      if (!force && !isAtBottom.value && !currentlyAtBottom) {
        return // 用户主动向上滚了，且还没滚回来，不打扰
      }
      
      el.scrollTop = el.scrollHeight
      isAtBottom.value = true
    }
    
    // 滚动流式推理容器（同样逻辑）
    if (streamingReasoningBodyRef.value) {
      const el = streamingReasoningBodyRef.value
      const currentlyAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
      
      if (!force && !isReasoningAtBottom.value && !currentlyAtBottom) {
        return
      }
      el.scrollTop = el.scrollHeight
      isReasoningAtBottom.value = true
    }
  })
}

// 当从其他标签页切换回来时（keep-alive 激活）
onActivated(() => {
  // 如果正在流式输出或有内容，滚动到底部
  nextTick(() => {
    if (thinking.value || streamingContent.value) {
      scrollToBottom(true)
    }
  })
})

const baseRenderMarkdown = createAiMarkdownRenderer({
  enableMermaid: true,
  preprocessText(text, { escapeHtml: sharedEscapeHtml, stashTrustedHtml }) {
    const buildAiPhotoHtml = (photoType, photoUrl, altText) => {
      const safeType = photoType === 'avatar' ? 'avatar' : 'id_photo'
      const safeAlt = sharedEscapeHtml(altText || (safeType === 'avatar' ? '头像' : '证件照'))
      const safeSrc = sharedEscapeHtml(photoUrl)
      const labelText = safeType === 'avatar' ? '头像' : '证件照'
      const safeLabel = sharedEscapeHtml(labelText)

      return `<span class="ai-photo-wrap ${safeType}"><img src="${safeSrc}" alt="${safeAlt}" class="ai-photo-image ${safeType}" data-photo-type="${safeType}" loading="lazy" /><span class="ai-photo-label">${safeLabel}</span></span>`
    }

    const buildAiPhotoPlaceholderHtml = (photoType, studentId, altText) => {
      const safeType = photoType === 'avatar' ? 'avatar' : 'id_photo'
      const safeAlt = sharedEscapeHtml(altText || (safeType === 'avatar' ? '头像' : '证件照'))
      const safeStudentId = sharedEscapeHtml(String(studentId || ''))
      const labelText = safeType === 'avatar' ? '头像' : '证件照'
      const safeLabel = sharedEscapeHtml(labelText)

      return `<span class="ai-photo-wrap ${safeType} is-pending" data-ai-photo-pending="1" data-photo-type="${safeType}" data-student-id="${safeStudentId}"><span class="ai-photo-placeholder ${safeType}" aria-label="${safeAlt}"></span><span class="ai-photo-label">${safeLabel}</span></span>`
    }

    let nextText = text

    nextText = nextText.replace(AI_PHOTO_IMAGE_MD_REGEX, (match, alt, _ref, type, studentId) => {
      const cachedUrl = getCachedPhotoUrl(type, studentId)
      if (cachedUrl) {
        return stashTrustedHtml(buildAiPhotoHtml(type, cachedUrl, alt))
      }

      return stashTrustedHtml(buildAiPhotoPlaceholderHtml(type, studentId, alt))
    })

    nextText = nextText.replace(AI_PHOTO_REF_REGEX, (match, type, studentId) => {
      const cachedUrl = getCachedPhotoUrl(type, studentId)
      if (cachedUrl) {
        return stashTrustedHtml(buildAiPhotoHtml(type, cachedUrl, type === 'id_photo' ? '证件照' : '头像'))
      }

      return stashTrustedHtml(buildAiPhotoPlaceholderHtml(type, studentId, type === 'id_photo' ? '证件照' : '头像'))
    })

    return nextText
  }
})

// 初始化 mermaid
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'strict',
})

const sanitizeMermaidSvg = (html) => DOMPurify.sanitize(html, {
  USE_PROFILES: { svg: true, html: true },
  ALLOWED_ATTR: [
    'class', 'style', 'viewBox', 'xmlns', 'width', 'height', 'd', 'fill', 'stroke', 'stroke-width',
    'transform', 'x', 'y', 'cx', 'cy', 'r', 'rx', 'ry', 'points', 'x1', 'y1', 'x2', 'y2',
    'font-size', 'text-anchor', 'dominant-baseline', 'preserveAspectRatio', 'role', 'aria-hidden',
    'focusable'
  ],
  FORBID_TAGS: ['script', 'foreignObject', 'iframe', 'object', 'embed'],
  FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
})

// Mermail 渲染处理
const renderMermaid = async () => {
  await nextTick()
  const graphs = document.querySelectorAll('.mermaid')
  
  graphs.forEach(async (graph, index) => {
    // 避免重复渲染
    if (graph.getAttribute('data-processed')) return
    
    // 暂不渲染流式传输中的内容（避免闪烁和报错）
    if (graph.closest('.streaming-message')) return

    // 获取源码
    let content = graph.textContent
    if (!content) return

    // 生成唯一ID
    const id = `mermaid-${Date.now()}-${index}-${Math.random().toString(36).substr(2, 9)}`
    
    try {
      // 1. 尝试直接解析
      await mermaid.parse(content)
    } catch (parseErr) {
      console.warn('Initial Mermaid parse failed, attempting recovery...', parseErr)
      
      // 2. 自动纠正/降级处理
      // 去除 classDef, subgraph, direction 等复杂语法
      let recovered = content
        .replace(/classDef\s+\w+\s+[^\n;]+[;\n]/g, '') // 去除 classDef（包括换行符）
        .replace(/:::\w+/g, '')                  // 去除 :::class 引用
        .replace(/class\s+[A-Z0-9,]+\s+\w+/g, '') // 去除 class 应用语句
        .replace(/subgraph\s+([^\n]+)/g, '')     // 去除 subgraph 声明
        .replace(/end\s*($|\n)/g, '')            // 去除 end
        .replace(/direction\s+\w+/g, '')         // 去除 direction
        .replace(/^\s*[\r\n]/gm, '')             // 去除空行
      
      // 尝试对未加引号的中文节点加引号 (简单启发式)
      recovered = recovered.replace(/([A-Z0-9]+)\[([^"\]]+)\]/g, '$1["$2"]')
      
      try {
        await mermaid.parse(recovered)
        content = recovered // 如果修复后成功，更新内容
      } catch (finalErr) {
        console.error('Mermaid recovery failed:', finalErr)
        // 维持原状抛出错误
        throw parseErr 
      }
    }

    try {
      // 渲染
      const { svg } = await mermaid.render(id, content)
      const safeSvg = sanitizeMermaidSvg(svg)
      graph.innerHTML = safeSvg
      graph.setAttribute('data-processed', 'true')
      
      // 添加点击放大功能
      graph.style.cursor = 'zoom-in'
      graph.title = '点击放大查看'
      graph.onclick = () => {
        previewContent.value = safeSvg
        previewVisible.value = true
      }
    } catch (e) {
      console.warn('Mermaid render error:', e)
      // 显示源码和简略错误，避免大段报错影响观感
      const safeContent = escapeHtml(content)
      const safeErrorMessage = escapeHtml((e.message || '').split('\n')[0])
      graph.innerHTML = `
        <div class="mermaid-error">
          <div class="error-title">⚠️ 流程图渲染失败</div>
          <pre class="error-code">${safeContent}</pre>
          <div class="error-msg">错误: ${safeErrorMessage}</div>
        </div>
      `
      graph.setAttribute('data-processed', 'true') // 标记为已处理，避免反复尝试报错
    }
  })
}

// 监听消息变化，触发渲染
watch(messages, () => {
  renderMermaid()
  scheduleObserveAiPhotoPlaceholders()
}, { deep: true })

watch(
  () => [streamingContent.value, streamingReasoningList.value.length, photoRenderTick.value, currentSessionId.value],
  () => {
    scheduleObserveAiPhotoPlaceholders()
  },
  { flush: 'post' }
)

const renderMarkdown = (text) => {
  if (!text) return ''
  photoRenderTick.value
  const html = baseRenderMarkdown(text)
  nextTick(() => {
    renderMermaid()
  })
  
  return html
}

// 时间格式化
const formatTime = (time) => {
  if (!time) return '--:--'
  // 兼容 MySQL 日期格式 "Y-m-d H:i:s"（空格分隔），转为 ISO 8601 再解析
  const normalized = typeof time === 'string' ? time.replace(' ', 'T') : time
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return '--:--'
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

watch(thinking, (isThinkingNow) => {
  if (!isThinkingNow) {
    streamingThinkingExpanded.value = false
  }
})

// 格式化Token提示
const formatTokenTooltip = (session) => {
  const title = session.title || '新对话'
  const tokens = session.total_tokens || 0
  if (tokens > 0) {
    return `${title}\n消耗Token: ${tokens.toLocaleString()}`
  }
  return title
}

// 格式化会话时间
const formatSessionTime = (time) => {
  if (!time) return '--'
  const now = Date.now()
  // 兼容 MySQL 日期格式 "Y-m-d H:i:s"（空格分隔），转为 ISO 8601 再解析
  const normalized = typeof time === 'string' ? time.replace(' ', 'T') : time
  const timestamp = new Date(normalized).getTime()
  if (isNaN(timestamp)) return '--'
  const diff = now - timestamp
  
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  
  if (days > 0) return `${days}天前`
  if (hours > 0) return `${hours}小时前`
  if (minutes > 0) return `${minutes}分钟前`
  return '刚刚'
}

let localMessageRenderSeed = 0
const localMessageRenderKeys = new WeakMap()
const getMessageRenderKey = (msg, index = 0) => {
  if (!msg) return `message-${index}`
  if (msg.id) return `message-${msg.id}`
  if (msg.taskId) return `task-${msg.taskId}`
  if (!localMessageRenderKeys.has(msg)) {
    localMessageRenderKeys.set(msg, `local-${Date.now()}-${localMessageRenderSeed++}`)
  }
  return localMessageRenderKeys.get(msg)
}

const getStreamingTimelineKey = () => `streaming-${thinking.value ? 'live' : 'idle'}`

// HTML转义函数
const escapeHtml = (str) => {
  if (!str) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

// 获取工具调用结果摘要（用于云端代理任务的历史显示）
const getToolResultSummary = (result) => {
  if (!result) return '无结果'
  if (result.error) return `失败: ${result.error}`
  if (result.message) return result.message
  if (result.count !== undefined) return `找到 ${result.count} 条记录`
  if (Array.isArray(result)) return `返回 ${result.length} 条数据`
  if (typeof result === 'object') {
    const keys = Object.keys(result)
    if (keys.length === 0) return '空对象'
    if (keys.length <= 3) return keys.join(', ')
    return `${keys.length} 个字段`
  }
  return String(result).substring(0, 50)
}

const toggleToolDetail = (item) => {
  item.expanded = !item.expanded
}



const userStore = useUserStore()
const verifyDialogRef = ref(null)
const pendingSensitiveRequest = ref(null)

watch(
  () => userStore.user?.id || 'guest',
  () => {
    draftWebSearchEnabled.value = loadWebSearchPreference(aiConfig.webSearchDefault)
  }
)

// 用户头像
const userAvatar = computed(() => {
  const url = userStore.avatar
  if (!url) return ''
  // 检查 OSS URL 是否包含签名
  if (url.includes('oss') && !url.includes('OSSAccessKeyId')) {
    return '' // OSS URL 需要有签名才有效
  }
  return url
})

const handleVerifySuccess = (token, expiresIn) => {
  // 设置验证状态（token 已由后端设置到 HttpOnly Cookie）
  userStore.setSensitiveVerified(expiresIn || 3600)
  
  // 如果有待处理的请求，再次尝试
  if (pendingSensitiveRequest.value) {
    const { el, type, id } = pendingSensitiveRequest.value
    pendingSensitiveRequest.value = null
    viewSensitiveDataWithToken(el, type, id)
  }
}

// 带验证查看敏感数据（token 由后端从 Cookie 获取）
const viewSensitiveDataWithToken = async (el, type, id) => {
  if (!el || el.dataset.loading === 'true') return
  
  try {
    el.dataset.loading = 'true'
    const maskedHtml = el.querySelector('.val')?.textContent || el.textContent
    el.textContent = '加载中...'
    
    const res = await api.post('/student/view-sensitive-data', {
      id: id,
      field: type
    })
    
    if (res.code === 200) {
      const rawValue = res.data.value
      // 仅保留脱敏值；明文只存在于当前文本节点中。
      el.dataset.maskedValue = maskedHtml
      // 揭示状态：显示明文 + 眼睛按钮（可收回）
      const valueNode = document.createElement('span')
      valueNode.className = 'val revealed-val'
      valueNode.textContent = rawValue
      const hideButton = document.createElement('button')
      hideButton.className = 'sensitive-eye-btn'
      hideButton.title = '点击重新隐藏'
      hideButton.dataset.action = 'hide'
      hideButton.textContent = '隐藏'
      el.replaceChildren(valueNode, hideButton)
      el.removeAttribute('onclick')
      el.style.cursor = 'text'
      el.title = '已显示原文，可直接复制'
      el.classList.remove('clickable')
      el.classList.add('revealed')
    } else {
      const valueNode = document.createElement('span')
      valueNode.className = 'val'
      valueNode.textContent = maskedHtml
      el.replaceChildren(valueNode)
    }
  } catch (e) {
    console.error(e)
    if (!e.isBusinessError && !e.response) {
      ElMessage.error('请求失败')
    }
  } finally {
    el.dataset.loading = 'false'
  }
}

// 处理敏感标签区域的所有点击
const handleSensitiveClick = async (event) => {
  // 0. 图片点击放大（聊天内容）
  const clickedImage = event.target.closest('.message-bubble img')
  if (clickedImage) {
    const imageSrc = clickedImage.getAttribute('src') || ''
    openImagePreview(imageSrc)
    return
  }

  // 1. 眼睛按钮：切换显示/隐藏
  const eyeBtn = event.target.closest('.sensitive-eye-btn')
  if (eyeBtn) {
    event.stopPropagation()
    const el = eyeBtn.closest('.sensitive-tag')
    if (!el) return
    const action = eyeBtn.dataset.action
    if (action === 'hide') {
      // 收回明文，恢复脱敏标签可点击状态
      const maskedVal = el.dataset.maskedValue || '***'
      const valueNode = document.createElement('span')
      valueNode.className = 'val'
      valueNode.textContent = maskedVal
      el.replaceChildren(valueNode)
      el.style.cursor = 'pointer'
      el.title = '点击查看完整信息'
      el.classList.add('clickable')
      el.classList.remove('revealed')
    }
    return
  }

  // 2. 普通点击：查找可点击的敏感标签
  const el = event.target.closest('.sensitive-tag.clickable')
  if (!el) return
  
  const type = el.dataset.sensitiveType
  const id = el.dataset.sensitiveId
  if (!type || !id) return
  
  if (!userStore.isSensitiveVerified()) {
    pendingSensitiveRequest.value = { el, type, id }
    verifyDialogRef.value.open({ targetUserId: parseInt(id) || 0 })
    return
  }
  
  viewSensitiveDataWithToken(el, type, id)
}

onMounted(() => {
  fetchSessions()
  
  // 保留全局函数以兼容旧代码（如果有其他地方调用）
  window.viewSensitiveData = async (el, type, id) => {
    // 检查验证状态
    if (!userStore.isSensitiveVerified()) {
      // 未验证或已过期，弹出验证对话框，绑定目标学生
      pendingSensitiveRequest.value = { el, type, id }
      verifyDialogRef.value.open({ targetUserId: parseInt(id) || 0 })
      return
    }
    
    // 已验证，直接请求（token 由后端从 Cookie 获取）
    viewSensitiveDataWithToken(el, type, id)
  }
})

onUnmounted(() => {
  window.viewSensitiveData = null
})
</script>

<style scoped>
.ai-chat {
  height: 100%;
  max-height: 100%;
  min-height: 0;
  box-sizing: border-box;
}

.chat-container {
  display: flex;
  height: 100%;
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}

/* 会话列表 */
.session-list {
  width: 240px;
  background: var(--el-fill-color-lighter);
  border-right: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.session-search {
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.session-search :deep(.el-input__wrapper) {
  border-radius: 16px;
}

.session-items {
  flex: 1;
  overflow-y: auto;
}

.load-more {
  padding: 12px 16px;
  text-align: center;
  border-top: 1px solid var(--el-border-color-lighter);
}

.load-earlier-history {
  padding: 8px 0;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  &.no-more {
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }
}

.no-more {
  padding: 12px 16px;
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 移动端抽屉内部布局 */
:deep(.el-drawer__body) {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

:deep(.el-drawer__body) .session-header {
  flex-shrink: 0;
}

:deep(.el-drawer__body) .session-search {
  flex-shrink: 0;
}

:deep(.el-drawer__body) .session-items {
  flex: 1;
  overflow-y: auto;
}

/* ==================== 优化后的会话列表样式 ==================== */
.session-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  cursor: pointer;
  border-radius: 4px;
  margin: 2px 6px;
  transition: all 0.2s ease;
  color: var(--el-text-color-regular);
  gap: 10px;
}

.session-item:hover {
  background: var(--el-fill-color);
}

.session-item.active {
  background: var(--el-color-primary-light-9);
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}

.session-item.active .session-title {
  color: var(--el-color-primary);
  font-weight: 500;
}

/* 各种状态的背景 */
.session-item.is-streaming {
  background: linear-gradient(90deg, var(--el-color-success-light-9) 0%, transparent 100%);
}

.session-item.is-processing {
  background: linear-gradient(90deg, var(--el-color-warning-light-9) 0%, transparent 100%);
}

.session-item.is-pending {
  background: linear-gradient(90deg, var(--el-color-info-light-9) 0%, transparent 100%);
}

/* 任务完成待查看 - 绿色闪烁 */
.session-item.is-task-completed {
  background: linear-gradient(90deg, var(--el-color-success-light-9) 0%, transparent 100%);
  animation: task-completed-flash 1s ease-in-out infinite;
}

@keyframes task-completed-flash {
  0%, 100% { 
    background: linear-gradient(90deg, var(--el-color-success-light-9) 0%, transparent 100%);
  }
  50% { 
    background: linear-gradient(90deg, var(--el-color-success-light-7) 0%, var(--el-color-success-light-9) 50%, transparent 100%);
  }
}

/* 暗黑模式 */
html.dark .session-item.active {
  background: var(--el-color-primary-light-7);
}

html.dark .session-item.active .session-title {
  color: #fff;
}

/* 图标包装器 */
.session-icon-wrapper {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: var(--el-fill-color);
  transition: all 0.2s;
}

.session-item.active .session-icon-wrapper {
  background: var(--el-color-primary-light-8);
}

.session-icon {
  font-size: 16px;
  color: var(--el-text-color-secondary);
}

.session-item.active .session-icon {
  color: var(--el-color-primary);
}

/* 流式输出状态 - 绿色脉冲 */
.session-icon.streaming {
  color: var(--el-color-success);
  animation: pulse-green 1.5s ease-in-out infinite, spin 2s linear infinite;
}

/* 处理中状态 - 橙色旋转 */
.session-icon.processing {
  color: var(--el-color-warning);
  animation: spin 1.5s linear infinite;
}

/* 等待中状态 */
.session-icon.pending {
  color: var(--el-color-info);
  opacity: 0.8;
}

/* 标题生成中 */
.session-icon.generating {
  color: var(--el-color-primary);
  animation: spin 2s linear infinite;
  opacity: 0.6;
}

/* 任务完成待查看 - 绿色闪烁 */
.session-icon.task-completed {
  color: var(--el-color-success);
  animation: icon-flash-green 0.8s ease-in-out infinite;
}

@keyframes icon-flash-green {
  0%, 100% { 
    opacity: 1;
    transform: scale(1);
  }
  50% { 
    opacity: 0.5;
    transform: scale(1.1);
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse-green {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 会话信息区域 */
.session-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.session-title {
  flex: 1;
  font-size: 13px;
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s;
}

/* 临时标题样式 - 斜体 + 较淡颜色 */
.session-title.is-temp {
  font-style: italic;
  color: var(--el-text-color-secondary);
}

/* 正在生成标题 - 骨架屏效果 */
.session-title.is-generating {
  background: linear-gradient(90deg, var(--el-fill-color) 25%, var(--el-fill-color-light) 50%, var(--el-fill-color) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 2px;
  color: transparent;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* 状态圆点 */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.streaming {
  background: var(--el-color-success);
  animation: pulse-dot 1s ease-in-out infinite;
}

.status-dot.processing {
  background: var(--el-color-warning);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.status-dot.pending {
  background: var(--el-color-info);
  opacity: 0.6;
}

.status-dot.task-completed {
  background: var(--el-color-success);
  animation: dot-flash-green 0.8s ease-in-out infinite;
}

@keyframes dot-flash-green {
  0%, 100% { 
    transform: scale(1); 
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(103, 194, 58, 0.7);
  }
  50% { 
    transform: scale(1.3); 
    opacity: 0.8;
    box-shadow: 0 0 8px 2px rgba(103, 194, 58, 0.5);
  }
}

@keyframes pulse-dot {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: 0.7; }
}

/* 元信息行 */
.session-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.session-time {
  opacity: 0.8;
}

.session-count {
  padding: 0 4px;
  background: var(--el-fill-color);
  border-radius: 2px;
}

/* 状态文字 */
.session-status {
  flex-shrink: 0;
}

.status-text {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 2px;
  font-weight: 500;
}

.status-text.streaming {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}

.status-text.processing {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.status-text.pending {
  color: var(--el-color-info);
  background: var(--el-color-info-light-9);
}

/* 空状态 */
.empty-sessions {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--el-text-color-secondary);
}

.empty-sessions .empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-sessions p {
  margin: 8px 0 16px;
  font-size: 14px;
}

/* 加载更多和没有更多 */
.load-more, .no-more {
  text-align: center;
  padding: 12px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* 流程图预览 */
.preview-toolbar {
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.zoom-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.mermaid-preview-viewport {
  height: 60vh;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  cursor: grab;
  position: relative;
}

.mermaid-preview-viewport:active {
  cursor: grabbing;
}

.mermaid-preview-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  transform-origin: center center;
}

:deep(.mermaid-preview-container svg) {
  max-width: none !important;
  max-height: none !important;
}

/* 聊天主区域 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0; /* 防止 flex 子元素撑开容器 */
  overflow: hidden;
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden; /* 防止水平溢出 */
  padding: 20px;
  background: var(--el-bg-color);
}

.welcome-tip {
  text-align: center;
  padding: 60px 20px;
  color: var(--el-text-color-regular);
}

.welcome-icon {
  font-size: 64px;
  color: var(--el-color-primary);
  margin-bottom: 20px;
}

.welcome-tip h3 {
  margin-bottom: 10px;
}

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 30px;
}

.quick-questions span {
  padding: 8px 16px;
  background: var(--el-fill-color-light);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid var(--el-border-color-lighter);
}

.quick-questions span:hover {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

/* 消息项 - 适配 Period.vue 视觉 */
.message-item {
  display: flex;
  margin-bottom: 24px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  box-sizing: border-box;
  contain: layout paint;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
  margin: 0 16px;
}

.message-item:not(.user) .message-avatar {
  margin-left: 4px;
}

.message-item.user .message-avatar {
  margin-right: 4px;
}

/* 头像样式增强 */
.message-avatar :deep(.el-avatar) {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.message-item:not(.user) .message-avatar :deep(.el-avatar) {
  background: linear-gradient(135deg, #409eff 0%, #00d2ff 100%) !important; /* Blue gradient */
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.3);
  color: #fff;
}

.message-item.user .message-avatar :deep(.el-avatar) {
  background: var(--el-fill-color-light) !important;
  color: var(--el-text-color-secondary) !important;
  border: 1px solid var(--el-border-color-lighter);
}

.message-content {
  max-width: 78%; /* Matched to Period.vue */
  display: flex;
  flex-direction: column;
  min-width: 0;
  margin: 0;
  overflow: hidden; /* 防止内容溢出 */
  box-sizing: border-box;
  width: 100%; /* 确保flex子元素不会撑开 */
}

.streaming-message {
  position: relative;
  transform-origin: left top;
}

.streaming-message .message-content {
  gap: 10px;
}

.streaming-message .message-avatar :deep(.el-avatar) {
  transition: transform 0.32s ease, box-shadow 0.32s ease, filter 0.32s ease;
}

.streaming-message.is-thinking .message-avatar :deep(.el-avatar) {
  box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.12), 0 10px 24px rgba(79, 140, 255, 0.16);
  animation: streaming-avatar-breathe 2.8s ease-in-out infinite;
}

.streaming-message.has-live-content .message-avatar :deep(.el-avatar) {
  filter: saturate(1.05);
}

.streaming-turn-enter-active,
.streaming-turn-leave-active {
  transition: opacity 0.36s ease, transform 0.36s cubic-bezier(0.22, 1, 0.36, 1), filter 0.36s ease;
}

.streaming-turn-enter-from,
.streaming-turn-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.985);
  filter: blur(2px);
}

@keyframes streaming-avatar-breathe {
  0%, 100% {
    transform: translateY(0);
    box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.1), 0 8px 20px rgba(79, 140, 255, 0.14);
  }
  50% {
    transform: translateY(-1px);
    box-shadow: 0 0 0 6px rgba(79, 140, 255, 0.08), 0 14px 28px rgba(79, 140, 255, 0.18);
  }
}

/* 旧的 message-bubble 定义已移除，使用下方 1:1 Period.vue 的定义 */

.message-bubble :deep(code) {
  background: var(--el-fill-color-darker);
  color: var(--el-color-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  word-break: break-all;
  overflow-wrap: break-word;
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
}

.message-time {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}

.message-disclaimer {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.message-model-tag {
  margin-top: 8px;
  display: inline-block;
}

.message-model-tag .el-tag {
  font-size: 11px;
  padding: 0 6px;
  height: 20px;
  line-height: 18px;
}

.message-item.user .message-time {
  text-align: right;
}

/* 思考动画 */
.thinking {
  display: flex;
  gap: 4px;
  padding: 16px 20px;
}

/* 推理过程增强样式 */



.message-bubble :deep(.table-wrapper) {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch; /* iOS 平滑滚动 */
  margin: 12px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  box-sizing: border-box;
}

.message-bubble :deep(table) {
  width: 100%;
  min-width: max-content; /* 确保表格内容完整显示 */
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.5;
  margin: 0; /* Remove default margin as wrapper handles it */
  border: none; /* Remove table border as wrapper handles it */
  border-radius: 0;
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

.reasoning-bubble {
  background: var(--el-fill-color-light);
  border-left: 3px solid #909399;
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.reasoning-content {
  line-height: 1.6;
  white-space: pre-wrap;
  opacity: 0.9;
}

/* 工具调用状态 */
.tool-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary);
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.tool-status .el-icon {
  font-size: 14px;
  color: var(--el-color-primary);
}

.thinking .dot {
  width: 8px;
  height: 8px;
  background: #909399;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}

.thinking .dot:nth-child(1) { animation-delay: -0.32s; }
.thinking .dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 工具调用状态 */
.tool-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary);
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.tool-status .el-icon {
  font-size: 14px;
  color: var(--el-color-primary);
}

/* 输入区 */
.input-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.input-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-actions {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

.input-area .el-textarea {
  flex: 1;
}

.input-area .el-button {
  height: auto;
  align-self: flex-end;
}

.chat-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.input-option-toggles {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-left: auto;
}

.model-selector {
  display: flex;
  gap: 8px;
  flex: 1 1 320px;
  min-width: min(100%, 320px);
}

.model-selector .el-select {
  flex: 1;
  min-width: 0;
}

.web-search-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.web-search-label {
  white-space: nowrap;
}

.agent-stream {
  margin-top: 8px;
}

.agent-stream-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px 2px;
  padding: 4px 10px;
  border-radius: 999px;
  color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.10);
  border: 1px solid rgba(64, 158, 255, 0.22);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
}

.agent-stream .message-bubble {
  border-left: 3px solid rgba(64, 158, 255, 0.45);
}

.streaming-stage-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px 2px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
}

.streaming-content-wrap.intermediate .streaming-stage-label {
  color: #4f8cff;
  background: rgba(79, 140, 255, 0.12);
  border-color: rgba(79, 140, 255, 0.32);
}

html.dark .streaming-content-wrap.intermediate .message-bubble {
  background: linear-gradient(135deg, rgba(79, 140, 255, 0.16), rgba(79, 140, 255, 0.08));
  border-color: rgba(79, 140, 255, 0.3);
}

/* 上下文状态显示 */
/* 输入选项区域 */
.input-options {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.mobile-composer-toolbar {
  display: none;
}

.mobile-toolbar-scroll {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mobile-model-selector {
  flex: 0 0 auto;
}

.ai-chat {
  --ai-composer-bg: linear-gradient(180deg, #fbfcff, #f2f5fb);
  --ai-composer-surface: rgba(255, 255, 255, 0.96);
  --ai-composer-pill-bg: rgba(255, 255, 255, 0.94);
  --ai-composer-border: rgba(31, 35, 41, 0.12);
  --ai-composer-pill-border: rgba(31, 35, 41, 0.12);
  --ai-composer-ink: #2f3440;
  --ai-composer-muted: #6b7280;
  --ai-composer-placeholder: rgba(107, 114, 128, 0.9);
  --ai-composer-ring-center: #ffffff;
}

html.dark .ai-chat {
  --ai-composer-bg: linear-gradient(180deg, rgba(18, 18, 18, 0.96), rgba(22, 22, 22, 0.98));
  --ai-composer-surface: rgba(48, 48, 48, 0.98);
  --ai-composer-pill-bg: rgba(44, 44, 44, 0.96);
  --ai-composer-border: rgba(255, 255, 255, 0.05);
  --ai-composer-pill-border: rgba(255, 255, 255, 0.08);
  --ai-composer-ink: #f2f2f2;
  --ai-composer-muted: #d3d7df;
  --ai-composer-placeholder: rgba(255, 255, 255, 0.46);
  --ai-composer-ring-center: #1d2128;
}

.context-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  margin-right: auto;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.context-indicator {
  min-height: 30px;
  padding: 4px 10px 4px 8px;
  border-radius: 999px;
  background: var(--ai-composer-pill-bg);
  border: 1px solid var(--ai-composer-pill-border);
  color: var(--el-color-primary);
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.context-indicator:hover {
  background: color-mix(in srgb, var(--ai-composer-pill-bg) 90%, var(--el-color-primary) 10%);
  border-color: rgba(79, 140, 255, 0.28);
}

.context-indicator.is-warning {
  border-color: rgba(79, 140, 255, 0.28);
}

.context-indicator.is-danger {
  border-color: rgba(245, 108, 108, 0.34);
}

.context-ring {
  --context-usage-angle: 0deg;
  position: relative;
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  border-radius: 50%;
  background:
    conic-gradient(#4f8cff 0deg, #4f8cff var(--context-usage-angle), rgba(255, 255, 255, 0.14) var(--context-usage-angle), rgba(255, 255, 255, 0.14) 360deg);
}

.context-indicator.is-warning .context-ring {
  background:
    conic-gradient(#4f8cff 0deg, #4f8cff var(--context-usage-angle), rgba(255, 255, 255, 0.14) var(--context-usage-angle), rgba(255, 255, 255, 0.14) 360deg);
}

.context-indicator.is-danger .context-ring {
  background:
    conic-gradient(#f56c6c 0deg, #f56c6c var(--context-usage-angle), rgba(255, 255, 255, 0.14) var(--context-usage-angle), rgba(255, 255, 255, 0.14) 360deg);
}

.context-ring-core {
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: var(--ai-composer-ring-center);
  box-shadow: inset 0 0 0 1px var(--ai-composer-pill-border);
}

.context-indicator-text {
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.context-usage-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.context-usage-flag {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(79, 140, 255, 0.12);
  color: #8eb8ff;
  font-size: 11px;
  line-height: 1.2;
}

.context-usage-flag.is-estimate {
  background: rgba(79, 140, 255, 0.12);
  color: #8eb8ff;
}

/* 云端代理模式开关 - 始终在右侧 */
.cloud-proxy-toggle {
  flex-shrink: 0;
}

.cloud-proxy-control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.option-select-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 10px;
  border: 1px solid var(--ai-composer-pill-border);
  border-radius: 999px;
  background: var(--ai-composer-pill-bg);
  color: var(--ai-composer-ink);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.option-select-chip:hover {
  border-color: rgba(79, 140, 255, 0.28);
}

.option-select-chip.is-active {
  background: rgba(79, 140, 255, 0.12);
  border-color: rgba(79, 140, 255, 0.34);
  color: var(--el-color-primary);
  box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.08);
}

.option-select-chip.is-disabled {
  opacity: 0.58;
  cursor: not-allowed;
}

.option-select-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  color: rgba(148, 163, 184, 0.95);
  background: rgba(148, 163, 184, 0.14);
  transition: color 0.18s ease, background 0.18s ease, transform 0.18s ease;
  font-size: 12px;
}

.option-select-chip.is-active .option-select-indicator {
  color: #4f8cff;
  background: rgba(79, 140, 255, 0.16);
  transform: scale(1.02);
}

html.dark .option-select-chip.is-active {
  background: rgba(79, 140, 255, 0.16);
}

html.dark .option-select-indicator {
  color: rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.08);
}

.task-badge :deep(.el-badge__content) {
  font-size: 10px;
}

/* 远端队列弹窗样式（与会话列表保持一致） */
.task-queue-dialog .tq-list {
  display: flex;
  flex-direction: column;
  max-height: 400px;
  overflow-y: auto;
}

.task-queue-dialog .tq-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 4px;
  margin: 2px 0;
  transition: all 0.2s ease;
  color: var(--el-text-color-regular);
  gap: 10px;
}

.task-queue-dialog .tq-item:hover {
  background: var(--el-fill-color);
}

.task-queue-dialog .tq-item.is-processing {
  background: linear-gradient(90deg, var(--el-color-warning-light-9) 0%, transparent 100%);
}

.task-queue-dialog .tq-item.is-pending {
  background: linear-gradient(90deg, var(--el-color-info-light-9) 0%, transparent 100%);
}

.task-queue-dialog .tq-icon-wrapper {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: var(--el-fill-color);
}

.task-queue-dialog .tq-icon {
  font-size: 16px;
  color: var(--el-text-color-secondary);
}

.task-queue-dialog .tq-icon.processing {
  color: var(--el-color-warning);
  animation: spin 1.5s linear infinite;
}

.task-queue-dialog .tq-icon.pending {
  color: var(--el-color-info);
  opacity: 0.8;
}

.task-queue-dialog .tq-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-queue-dialog .tq-title {
  font-size: 13px;
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}

.task-queue-dialog .tq-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.task-queue-dialog .tq-status {
  font-weight: 500;
}

.task-queue-dialog .tq-item.is-processing .tq-status {
  color: var(--el-color-warning);
}

.task-queue-dialog .tq-item.is-pending .tq-status {
  color: var(--el-color-info);
}

.task-queue-dialog .tq-time {
  opacity: 0.8;
}

.task-queue-dialog .tq-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--el-text-color-placeholder);
}

.task-queue-dialog .tq-empty p {
  margin-top: 12px;
  font-size: 13px;
}

/* 后台处理占位消息样式 */
.message-item.assistant .message-bubble.placeholder {
  background: var(--el-fill-color-light);
  border: 1px dashed var(--el-border-color);
  color: var(--el-text-color-secondary);
  font-style: italic;
}

.context-progress-wrapper {
  flex: 1;
  height: 6px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  overflow: hidden;
  max-width: 200px;
  min-width: 80px;
}

.context-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #67c23a, #85ce61);
  border-radius: 3px;
  transition: width 0.3s ease, background 0.3s ease;
  min-width: 2px;
}

.context-progress-bar.warning {
  background: linear-gradient(90deg, #e6a23c, #f0c78a);
}

.context-progress-bar.danger {
  background: linear-gradient(90deg, #f56c6c, #fab6b6);
}

.context-text {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  letter-spacing: -0.3px;
}

.estimate-badge {
  font-size: 10px;
  color: #e6a23c;
  margin-left: 2px;
  cursor: default;
}

/* 暗黑模式适配 */
html.dark .context-progress-wrapper {
  background: #363637;
}

html.dark .context-text {
  color: #909399;
}

/* 移动端适配 */
.mobile-chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.current-session-title {
  flex: 1;
  text-align: center;
  font-weight: 600;
  font-size: 15px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 10px;
}

@media screen and (max-width: 768px) {
  .ai-chat {
    height: 100%;
    max-height: 100%;
    min-height: 0;
    overflow: hidden;
  }
  
  .chat-container {
    width: 100%;
    max-width: 100vw;
    overflow: hidden;
  }
  
  .chat-main {
    max-width: 100%;
    overflow: hidden;
  }
  
  .message-list {
    padding: 12px 8px; /* 左右各8px，保持对称 */
    overflow-x: hidden; /* 防止水平溢出 */
  }

  .message-content {
    max-width: calc(100% - 8px); /* 留出少量边距防止贴边 */
    width: 100%;
    overflow: hidden;
  }
  
  .message-bubble {
    max-width: 100%;
    overflow-x: auto; /* 允许内部内容横向滚动 */
    font-size: 15px; /* 移动端稍小字体 */
  }
  
  .reasoning-container {
    max-width: 100%;
    overflow: hidden;
  }
  
  .reasoning-body {
    max-height: 200px; /* 移动端限制思考区域高度 */
    overflow-x: hidden;
  }
  
  .tool-card {
    max-width: 100%;
    overflow: hidden;
  }
  
  .tool-body {
    max-height: 150px;
    overflow-x: auto;
  }
  
  .tool-result-pre pre {
    max-width: 100%;
    overflow-x: auto;
  }

  .welcome-tip {
    padding: 30px 15px;
  }

  .quick-questions span {
    font-size: 13px;
  }

  .input-area {
    padding: 6px 10px 8px;
    gap: 5px;
    background: var(--ai-composer-bg);
  }
  
  .mobile-composer-toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  .mobile-toolbar-scroll {
    flex: 1;
    overflow-x: auto;
    padding-bottom: 1px;
    scrollbar-width: none;
  }

  .mobile-toolbar-scroll::-webkit-scrollbar {
    display: none;
  }

  .input-row {
    gap: 8px;
    align-items: center;
    padding: 5px 7px 5px 10px;
    border-radius: 16px;
    background: var(--ai-composer-surface);
    border: 1px solid var(--ai-composer-border);
  }
  
  .input-options {
    display: none;
  }
  
  .chat-controls {
    display: none;
  }

  .mobile-context-status {
    flex: 0 0 auto;
    margin-right: 0;
    padding: 4px 8px 4px 6px;
    min-height: 26px;
  }
  
  .web-search-toggle,
  .cloud-proxy-toggle {
    flex: 0 0 auto;
    min-width: fit-content;
    box-sizing: border-box;
  }

  .cloud-proxy-control {
    gap: 6px;
  }
  
  .context-text {
    font-size: 10px;
    white-space: nowrap;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .option-select-chip {
    min-height: 28px;
    padding: 3px 9px;
    border-radius: 14px;
  }

  .option-select-indicator {
    width: 15px;
    height: 15px;
    font-size: 11px;
  }

  .mobile-model-selector {
    width: max-content;
    display: flex;
    flex-wrap: nowrap;
    gap: 6px;
  }

  .mobile-model-selector .el-select:first-child {
    width: min(38vw, 152px);
    flex: 0 0 auto;
  }

  .mobile-model-selector .el-select:last-child {
    width: 86px;
    flex: 0 0 auto;
  }

  .mobile-model-selector :deep(.el-select__wrapper) {
    min-height: 28px;
    border-radius: 14px;
    background: var(--ai-composer-pill-bg);
    box-shadow: inset 0 0 0 1px var(--ai-composer-pill-border);
  }

  .input-row :deep(.el-textarea) {
    flex: 1;
  }

  .input-row :deep(.el-textarea__inner) {
    padding: 4px 0;
    min-height: 20px !important;
    max-height: 84px;
    border: 0;
    background: transparent;
    box-shadow: none;
    color: var(--ai-composer-ink);
    font-size: 13px;
    line-height: 1.35;
  }

  .input-row :deep(.el-textarea__inner::placeholder) {
    color: var(--ai-composer-placeholder);
  }
  
  .input-actions {
    align-self: center;
    flex-shrink: 0;
  }

  .input-actions .el-button,
  .mobile-send-button {
    min-width: 36px;
    width: 36px;
    height: 36px;
    border-radius: 12px;
    padding: 0;
  }

  .mobile-send-button .el-icon {
    margin-right: 0;
  }

  /* 移动端隐藏头像，利用气泡颜色区分，最大化内容宽度 */
  .message-avatar {
    display: none;
  }

  .message-item {
    padding: 0;
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }

  /* 移动端隐藏滚动条 */
  .message-list::-webkit-scrollbar,
  .reasoning-body::-webkit-scrollbar {
    display: none;
  }
  
  /* 移动端表格处理 */
  .message-bubble :deep(.table-wrapper) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    max-width: 100%;
  }
  
  .message-bubble :deep(table) {
    font-size: 12px;
  }
}

@media screen and (max-width: 380px) {
  .mobile-context-status {
    padding-inline: 8px;
  }

  .mobile-model-selector .el-select:first-child {
    width: min(42vw, 138px);
  }

  .mobile-model-selector .el-select:last-child {
    width: 80px;
  }
}

/* ---------------------------------- */
/* 新增样式：仿主流AI的思维链与UI优化 */
/* ---------------------------------- */

.assistant-turn-container {
  width: 100%;
}

.thinking-summary-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  user-select: none;
  margin: 2px 0 6px;
  padding: 0;
}

.thinking-summary-action {
  font-size: 12px;
  color: var(--el-color-primary);
}

.thinking-detail-lines {
  margin: 0 0 8px;
  padding: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.thinking-text-line {
  margin: 0;
  padding: 4px 0 4px 8px;
  border-left: 2px solid var(--el-border-color-lighter);
}

.thinking-tool-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin: 4px 0;
  padding: 4px 0;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.tool-inline-link {
  color: var(--el-color-primary);
  text-decoration: none;
  white-space: nowrap;
  font-size: 12px;
}

.tool-inline-link:hover {
  text-decoration: underline;
}

.tool-inline-detail {
  margin: 2px 0 6px;
}

.tool-inline-detail pre {
  margin: 0;
  padding: 6px 8px;
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.thinking-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 10px;
}

.thinking-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color);
  overflow: hidden;
}

.thinking-card.is-active {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.08);
}

.thinking-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-blank);
}

.thinking-card-header:hover {
  background: var(--el-fill-color-light);
}

.thinking-card-header-main,
.thinking-card-header-side {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.thinking-card-header-side {
  flex-shrink: 0;
}

.thinking-card-label {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.thinking-card-title {
  min-width: 0;
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.thinking-card-status,
.thinking-card-action {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.thinking-card-action {
  color: var(--el-color-primary);
}

.thinking-card-body {
  padding: 0 12px 12px;
}

.thought-detail-body,
.tool-detail-body {
  overflow-y: auto;
  overflow-x: hidden;
}

.thought-detail-body {
  max-height: 220px;
}

.tool-detail-body {
  max-height: 260px;
}

.thinking-text-content {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
  white-space: normal;
  word-break: break-word;
}

.tool-card-item .thinking-card-label {
  color: var(--el-color-primary);
}

.tool-card-item .thinking-card-title,
.tool-card-item .thinking-card-status {
  font-family: 'Consolas', 'Monaco', monospace;
}

.thinking-card-body::-webkit-scrollbar {
  width: 5px;
}

.thinking-card-body::-webkit-scrollbar-thumb {
  background: var(--el-border-color-darker);
  border-radius: 999px;
}

@media (max-width: 768px) {
  .thinking-card-header {
    padding: 9px 10px;
    align-items: flex-start;
  }

  .thinking-card-header,
  .thinking-card-header-main,
  .thinking-card-header-side {
    gap: 6px;
  }

  .thinking-card-header {
    flex-direction: column;
  }

  .thinking-card-header-main,
  .thinking-card-header-side {
    width: 100%;
    justify-content: space-between;
  }

  .thought-detail-body {
    max-height: 170px;
  }

  .tool-detail-body {
    max-height: 190px;
  }
}

.reasoning-container {
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px dashed var(--el-border-color-lighter);
  margin-bottom: 0;
  margin-top: 4px;
  overflow: hidden;
  width: 100%;
  max-width: 100%; /* 限制最大宽度 */
  box-sizing: border-box;
  min-width: 0; /* 允许flex子元素收缩 */
}

/* 消除相邻卡片的垂直间隙，形成拼接效果 */
.reasoning-container + .reasoning-container,
.reasoning-container + .tool-card,
.tool-card + .reasoning-container,
.tool-card + .tool-card {
  margin-top: -1px;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}

.reasoning-container:has(+ .reasoning-container),
.reasoning-container:has(+ .tool-card),
.tool-card:has(+ .reasoning-container),
.tool-card:has(+ .tool-card) {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  margin-bottom: 0;
}

.reasoning-header {
  padding: 6px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-light);
  font-size: 12px;
  color: var(--el-color-primary);
  transition: background 0.2s;
}

.reasoning-header:hover {
  background: var(--el-fill-color);
}

.reasoning-header .header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.reasoning-header .is-active {
  animation: rotate 2s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.expand-icon {
  transition: transform 0.3s;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.expand-icon.is-expanded {
  transform: rotate(90deg);
}

.reasoning-body-wrapper {
  position: relative;
  border-top: none; 
}

.reasoning-body {
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
  background: transparent;
  max-height: 400px; /* PC端增大以提供更好的阅读体验 */
  overflow-y: auto;
  overflow-x: hidden; /* 防止水平溢出 */
  transition: max-height 0.3s ease;
  scroll-behavior: smooth;
  word-break: break-word; /* 防止长文本撑开容器 */
  overflow-wrap: break-word;
  box-sizing: border-box;
  min-width: 0;
}

/* 移动端适当限制高度 */
@media (max-width: 768px) {
  .reasoning-body {
    max-height: 250px;
  }
}

/* 工具调用行样式 */
.reasoning-body :deep(.tool-call-line) {
  color: #409eff;
  font-family: 'Consolas', 'Monaco', monospace;
  padding: 4px 0;
  font-weight: 500;
  white-space: pre-wrap;
  word-break: break-all; /* 强制工具调用行断行 */
}

html.dark .reasoning-body :deep(.tool-call-line) {
  color: #79bbff;
}

/* 滚动条美化 */
.reasoning-body::-webkit-scrollbar {
  width: 4px;
}
.reasoning-body::-webkit-scrollbar-thumb {
  background: var(--el-border-color-darker);
  border-radius: 2px;
}

/* 暗色模式适配 */
html.dark .reasoning-container {
  background: #1d1e1f;
  border-color: #363637;
}
html.dark .reasoning-header {
  background: #262727;
  color: #79bbff;
}
html.dark .reasoning-header:hover {
  background: #303133;
}
html.dark .reasoning-body {
  background: transparent;
  color: #cfd3dc;
  border-top: none;
}

/* 消息气泡优化 - 1:1 Period.vue */
.message-bubble {
  padding: 12px 16px;
  border-radius: 4px;
  font-size: 16px; /* 加大字体 */
  line-height: 1.6;
  position: relative;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.03);
  border: 1px solid var(--el-border-color-lighter);
  word-break: break-word; /* 防止长文本溢出 */
  overflow-wrap: break-word;
  min-width: 0;
  max-width: 100%; /* 限制最大宽度 */
  overflow: hidden; /* 防止内容溢出 */
  box-sizing: border-box;
}

/* 消息气泡内部元素溢出控制 */
.message-bubble :deep(*) {
  max-width: 100%;
  box-sizing: border-box;
}

.message-bubble :deep(pre) {
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-width: 100%;
}

.message-bubble :deep(img) {
  max-width: 100%;
  height: auto;
}

.message-bubble :deep(.ai-photo-wrap) {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px;
  margin: 8px 0;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-lighter);
}

.message-bubble :deep(.ai-photo-image) {
  display: block;
  border-radius: 8px;
  cursor: zoom-in;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color-page);
}

.message-bubble :deep(.ai-photo-placeholder) {
  display: block;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background:
    linear-gradient(110deg, rgba(240, 244, 250, 0.95) 8%, rgba(226, 233, 244, 0.9) 18%, rgba(240, 244, 250, 0.95) 33%);
  background-size: 200% 100%;
  animation: ai-photo-placeholder-shimmer 1.4s linear infinite;
}

.message-bubble :deep(.ai-photo-placeholder.avatar) {
  width: 96px;
  height: 96px;
}

.message-bubble :deep(.ai-photo-placeholder.id_photo) {
  width: min(220px, 100%);
  max-width: 220px;
  aspect-ratio: 220 / 300;
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
  border-radius: 999px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
}

.message-bubble :deep(.ai-photo-wrap.avatar .ai-photo-label) {
  background: #ecf8ef;
  color: #2d8a4b;
  border-color: #b7ebc3;
}

.message-bubble :deep(.ai-photo-wrap.id_photo .ai-photo-label) {
  background: #eef4ff;
  color: #2f63c4;
  border-color: #c8d8ff;
}

html.dark .message-bubble :deep(.ai-photo-wrap) {
  background: #242629;
  border-color: #3a3d42;
}

html.dark .message-bubble :deep(.ai-photo-image) {
  border-color: #3a3d42;
  background: #1a1b1d;
}

html.dark .message-bubble :deep(.ai-photo-placeholder) {
  border-color: #3a3d42;
  background:
    linear-gradient(110deg, rgba(47, 50, 56, 0.95) 8%, rgba(61, 65, 72, 0.92) 18%, rgba(47, 50, 56, 0.95) 33%);
  background-size: 200% 100%;
}

html.dark .message-bubble :deep(.ai-photo-wrap.avatar .ai-photo-label) {
  background: rgba(58, 156, 110, 0.18);
  color: #8fe0b9;
  border-color: rgba(95, 204, 149, 0.45);
}

html.dark .message-bubble :deep(.ai-photo-wrap.id_photo .ai-photo-label) {
  background: rgba(74, 132, 235, 0.22);
  color: #a7c7ff;
  border-color: rgba(105, 157, 244, 0.5);
}

@keyframes ai-photo-placeholder-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.message-item.assistant .message-bubble {
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  border-top-left-radius: 0;
}

.message-item.user .message-bubble {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
  border-top-right-radius: 2px;
}

html.dark .message-item.assistant .message-bubble {
  background: #1d1e1f;
  border-color: #363637;
  color: #cfd3dc;
}

html.dark .message-item.user .message-bubble {
  background: #1e2535;
  border-color: #2a3655;
  color: #a0cfff;
}

/* 🔧 继续按钮提示样式 */
.continue-prompt {
  margin-top: 12px;
  padding: 0;
  animation: continue-prompt-rise 0.36s cubic-bezier(0.22, 1, 0.36, 1);
}

.continue-prompt-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 8px;
  box-shadow: 0 10px 24px rgba(79, 140, 255, 0.08);
  animation: pulse-border 2.8s ease-in-out infinite;
}
.continue-text {
  flex: 1;
  font-size: 13px;
  color: var(--el-color-primary);
  line-height: 1.4;
}
@keyframes pulse-border {
  0%, 100% { border-color: var(--el-color-primary-light-7); }
  50% { border-color: var(--el-color-primary); }
}

@keyframes continue-prompt-rise {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ... (sensitive tag styles omitted for brevity, keeping existing) ... */

/* 工具调用卡片样式 - 使用变量适配暗黑模式 */
.tool-card {
  margin: 4px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background-color: var(--el-bg-color);
  overflow: hidden;
  font-size: 12px;
  transition: all 0.3s;
  max-width: 100%;
}

.tool-card:hover {
  border-color: var(--el-text-color-secondary);
}

.tool-card.loading {
  border-color: var(--el-color-primary-light-5);
  background-color: var(--el-color-primary-light-9);
}

.tool-card.error {
  border-color: var(--el-color-danger-light-5);
  background-color: var(--el-color-danger-light-9);
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  cursor: pointer;
  background-color: var(--el-fill-color-light);
  user-select: none;
  min-height: 28px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.tool-card.loading .tool-header {
  background-color: var(--el-color-primary-light-9);
}

.th-left {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.th-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.tool-body {
  padding: 6px 8px;
  border-top: none; /* header has border-bottom */
  background-color: var(--el-bg-color);
  font-family: monospace;
  font-size: 11px;
  color: var(--el-text-color-regular);
  max-height: 300px;
  overflow-y: auto;
}

:deep(.tool-card) {
  margin: 6px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  font-size: 13px;
  background-color: var(--el-bg-color);
}
:deep(.tool-card .tool-header) {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  background-color: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-primary);
}
:deep(.tool-card .tool-body) {
  padding: 8px 10px;
  font-family: monospace;
  font-size: 12px;
  background: var(--el-bg-color);
  border-top: none;
  color: var(--el-text-color-regular);
}

/* 历史记录/暗黑模式强制适配 */
html.dark .tool-card,
html.dark :deep(.tool-card) {
  background-color: #1d1e1f !important;
  border-color: #363637 !important;
}

html.dark .tool-header, 
html.dark :deep(.tool-card .tool-header) {
  background-color: #262727 !important;
  border-bottom-color: #363637 !important;
  color: #cfd3dc !important;
}

html.dark .tool-body,
html.dark :deep(.tool-card .tool-body) {
  background-color: #1d1e1f !important;
  color: #a3a6ad !important;
}

.message-item.assistant .message-bubble {
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  border-top-left-radius: 0;
}

.message-item.user .message-bubble {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
  border-top-right-radius: 2px;
}

html.dark .message-item.assistant .message-bubble {
  background: #1d1e1f;
  border-color: #363637;
  color: #cfd3dc;
}

html.dark .message-item.assistant .message-bubble :deep(p),
html.dark .message-item.assistant .message-bubble :deep(div),
html.dark .message-item.assistant .message-bubble :deep(span),
html.dark .message-item.assistant .message-bubble :deep(li) {
  color: #cfd3dc;
}

html.dark .message-item.assistant .message-bubble :deep(h1),
html.dark .message-item.assistant .message-bubble :deep(h2),
html.dark .message-item.assistant .message-bubble :deep(h3),
html.dark .message-item.assistant .message-bubble :deep(h4),
html.dark .message-item.assistant .message-bubble :deep(h5),
html.dark .message-item.assistant .message-bubble :deep(h6) {
  color: #e4e7ed;
}

html.dark .message-item.user .message-bubble {
  background: #1e2535;
  border-color: #2a3655;
  color: #a0cfff;
}

/* 敏感数据标签 */
.message-bubble :deep(.sensitive-tag) {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
  padding: 2px 8px;
  background: rgba(245, 108, 108, 0.08);
  color: #f56c6c;
  border-radius: 6px;
  font-size: 0.9em;
  font-family: inherit;
  margin: 0 2px;
  cursor: help;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  gap: 4px;
}

.message-bubble :deep(.sensitive-tag:hover) {
  background: rgba(245, 108, 108, 0.15);
}

/* 可点击的敏感标签 */
.message-bubble :deep(.sensitive-tag.clickable) {
  cursor: pointer;
}

.message-bubble :deep(.sensitive-tag.clickable:hover) {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(245, 108, 108, 0.15);
}

.message-bubble :deep(.sensitive-tag.clickable:active) {
  transform: translateY(0);
  box-shadow: none;
}

.message-bubble :deep(.sensitive-tag.phone) {
  background: rgba(64, 158, 255, 0.08);
  color: #409eff;
}

.message-bubble :deep(.sensitive-tag.phone .val) {
  font-weight: 500;
}

.message-bubble :deep(.sensitive-tag.phone:hover) {
  background: rgba(64, 158, 255, 0.15);
}

.message-bubble :deep(.sensitive-tag.phone.clickable:hover) {
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
}

/* 已揭示的敏感标签：绿色边框，光标默认（可复制），不再可点击 */
.message-bubble :deep(.sensitive-tag.revealed) {
  background: rgba(103, 194, 58, 0.08);
  color: #4a9c2a;
  border: 1px solid rgba(103, 194, 58, 0.3);
  cursor: text;
  user-select: text;
  gap: 4px;
}

.message-bubble :deep(.sensitive-tag.revealed:hover) {
  background: rgba(103, 194, 58, 0.12);
  transform: none;
  box-shadow: none;
}

.message-bubble :deep(.sensitive-tag.revealed .revealed-val) {
  user-select: text;
  font-weight: 500;
  letter-spacing: 0.02em;
}

/* 眼睛按钮：收起明文 */
.message-bubble :deep(.sensitive-eye-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  padding: 0 2px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  opacity: 0.45;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.message-bubble :deep(.sensitive-eye-btn:hover) {
  opacity: 0.9;
}

/* 暗色模式 */
html.dark .message-bubble :deep(.sensitive-tag) {
  background: rgba(245, 108, 108, 0.15);
  color: #f89898;
}

html.dark .message-bubble :deep(.sensitive-tag:hover) {
  background: rgba(245, 108, 108, 0.25);
}

html.dark .message-bubble :deep(.sensitive-tag.phone) {
  background: rgba(64, 158, 255, 0.15);
  color: #79bbff;
}

html.dark .message-bubble :deep(.sensitive-tag.phone:hover) {
  background: rgba(64, 158, 255, 0.25);
}

html.dark .message-bubble :deep(.sensitive-tag.revealed) {
  background: rgba(103, 194, 58, 0.12);
  color: #85ce61;
  border-color: rgba(103, 194, 58, 0.25);
}

/* Mermaid 错误提示样式与暗黑模式适配 */
.mermaid-error {
  background: #fff0f0;
  border: 1px solid #ffcccc;
  padding: 10px;
  border-radius: 4px;
}

.error-title {
  color: #f56c6c;
  font-weight: bold;
  margin-bottom: 5px;
}

.error-code {
  background: #f8f9fa;
  padding: 5px;
  overflow: auto;
  font-size: 12px;
  color: #333;
  border-radius: 2px;
}

.error-msg {
  font-size: 12px;
  color: #999;
  margin-top: 5px;
}

/* Mermaid Error Dark Mode */
html.dark .mermaid-error {
  background: rgba(245, 108, 108, 0.1);
  border-color: rgba(245, 108, 108, 0.2);
}

html.dark .error-code {
  background: #1d1e1f;
  color: #cfd3dc;
  border: 1px solid #363637;
}

html.dark .error-msg {
  color: #909399;
}

.mermaid-preview-container {
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: auto;
  min-height: 300px;
  background: white; /* 保持白色背景确保图表清晰 */
  padding: 20px;
  border-radius: 4px;
}

html.dark .mermaid-preview-container {
  background: #1e1e20; /* 暗黑模式背景 */
}

/* 工具调用卡片样式 */
.tool-card {
  margin: 6px 0; /* 减小上下间距 */
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background-color: #fff;
  overflow: hidden;
  font-size: 13px;
  transition: all 0.3s;
}

.tool-card:hover {
  border-color: #c0c4cc;
}

.tool-card.loading {
  border-color: #409EFF;
  background-color: #ecf5ff;
}

.tool-card.error {
  border-color: #fde2e2;
  background-color: #fef0f0;
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px; /* 减小内边距 */
  cursor: pointer;
  background-color: #f9fafc;
  user-select: none;
  min-height: 32px; /* 限制高度 */
}

.tool-card.loading .tool-header {
  background-color: #ecf5ff;
}

.th-left {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  color: #303133;
}

.th-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.status-text {
  display: flex;
  align-items: center;
  gap: 4px;
}

.status-text.loading {
  color: #409EFF;
}

.status-text.success {
  color: #67C23A;
}

.status-text.error {
  color: #F56C6C;
}

.tool-body {
  padding: 8px 10px; /* 减小内边距 */
  border-top: 1px solid #ebeef5;
  background-color: #fff;
  font-family: monospace;
  font-size: 12px;
  color: #555;
  max-height: 300px;
  overflow-y: auto;
}

.tool-result-pre pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-width: 100%;
  overflow-x: auto;
  box-sizing: border-box;
}

.arrow-icon {
  transition: transform 0.3s;
}
.arrow-icon.is-expanded {
  transform: rotate(90deg);
}

/* 历史记录中的静态工具卡片样式 */
:deep(.tool-card) {
  margin: 6px 0;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
  font-size: 13px;
  background-color: #fff;
}
:deep(.tool-card .tool-header) {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  background-color: #f9fafc;
  border-bottom: 1px solid #ebeef5;
}
:deep(.tool-card .tool-icon) {
  margin-right: 6px;
}
:deep(.tool-card .tool-status-icon) {
  margin-left: auto;
}
:deep(.tool-card.success .tool-status-icon) {
  color: #67C23A;
}
:deep(.tool-card.error .tool-status-icon) {
  color: #F56C6C;
}
:deep(.tool-card .tool-body) {
  padding: 8px 10px;
  font-family: monospace;
  font-size: 12px;
  background: #fff;
  border-top: none; /* 历史记录已在header有border-bottom */
  color: #606266;
}


/* 暗色模式适配 */
html.dark .tool-card {
  background-color: #1d1e1f !important;
  border-color: #363637 !important;
}

html.dark .tool-card:hover {
  border-color: #4c4d4f !important;
}

html.dark .tool-header {
  background-color: #262727 !important;
  color: #cfd3dc !important;
}

html.dark .th-left {
  color: #cfd3dc !important;
}

html.dark .tool-body {
  background-color: #1d1e1f !important;
  border-top-color: #363637 !important;
  color: #a3a6ad !important;
}

html.dark .tool-card.loading {
  background-color: rgba(64, 158, 255, 0.1) !important;
  border-color: rgba(64, 158, 255, 0.2) !important;
}

html.dark .tool-card.loading .tool-header {
  background-color: rgba(64, 158, 255, 0.15) !important;
}

html.dark .tool-card.error {
  background-color: rgba(245, 108, 108, 0.1) !important;
  border-color: rgba(245, 108, 108, 0.2) !important;
}

/* 历史记录暗黑模式 */
html.dark :deep(.tool-card) {
  background-color: #1d1e1f !important;
  border-color: #363637 !important;
}
html.dark :deep(.tool-card .tool-header) {
  background-color: #262727 !important;
  border-bottom-color: #363637 !important;
  color: #cfd3dc !important;
}
html.dark :deep(.tool-card .tool-body) {
  background-color: #1d1e1f !important;
  color: #a3a6ad !important;
}
</style>

<!-- 全局样式覆盖 (解决 v-html 内容样式穿透问题) -->
<style>
.context-usage-popover.el-popover.el-popper {
  padding: 0 !important;
  border: 1px solid rgba(31, 35, 41, 0.12) !important;
  background: #ffffff !important;
  box-shadow: 0 16px 40px rgba(31, 35, 41, 0.12) !important;
  color: #2f3440 !important;
  overflow: hidden;
}

.context-usage-panel {
  padding: 14px 14px 12px;
  color: #2f3440;
}

.context-usage-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.context-usage-header-main {
  min-width: 0;
}

.context-usage-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 6px;
}

.context-usage-summary {
  font-size: 13px;
  color: rgba(47, 52, 64, 0.8);
}

.context-usage-percent {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(79, 140, 255, 0.16);
  color: #9ec0ff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}

.context-usage-percent.is-warning {
  background: rgba(79, 140, 255, 0.16);
  color: #4f8cff;
}

.context-usage-percent.is-danger {
  background: rgba(245, 108, 108, 0.16);
  color: #ff9f9f;
}

.context-usage-section + .context-usage-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(31, 35, 41, 0.08);
}

.context-usage-section-title {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  color: rgba(47, 52, 64, 0.52);
  letter-spacing: 0.02em;
}

.context-usage-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  font-size: 13px;
  line-height: 1.45;
  color: rgba(47, 52, 64, 0.92);
}

.context-usage-row + .context-usage-row {
  margin-top: 6px;
}

.context-usage-row span:last-child {
  color: rgba(47, 52, 64, 0.72);
  text-align: right;
}

html.dark .context-usage-popover.el-popover.el-popper {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: #1f2228 !important;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.34) !important;
  color: #e7ebf3 !important;
}

html.dark .context-usage-panel {
  color: #e7ebf3;
}

html.dark .context-usage-title {
  color: #f3f6fb;
}

html.dark .context-usage-summary {
  color: rgba(231, 235, 243, 0.88);
}

html.dark .context-usage-section + .context-usage-section {
  border-top-color: rgba(255, 255, 255, 0.08);
}

html.dark .context-usage-section-title {
  color: rgba(255, 255, 255, 0.54);
}

html.dark .context-usage-row {
  color: rgba(231, 235, 243, 0.92);
}

html.dark .context-usage-row span:last-child {
  color: rgba(231, 235, 243, 0.76);
}

html.dark .ai-chat .tool-card {
  background-color: #1d1e1f !important;
  border-color: #363637 !important;
}
html.dark .ai-chat .tool-card .tool-header {
  background-color: #262727 !important;
  border-bottom-color: #363637 !important;
  color: #cfd3dc !important;
}
html.dark .ai-chat .tool-card .tool-body,
html.dark .ai-chat .tool-card .tool-result-summary,
html.dark .ai-chat .tool-card .tool-result-pre {
  background-color: #1d1e1f !important;
  color: #a3a6ad !important;
  border-top-color: #363637 !important;
}
html.dark .ai-chat .tool-card .th-left {
  color: #cfd3dc !important;
}
html.dark .ai-chat .tool-card.loading {
  background-color: rgba(64, 158, 255, 0.1) !important;
  border-color: rgba(64, 158, 255, 0.2) !important;
}
html.dark .ai-chat .tool-card.loading .tool-header {
  background-color: rgba(64, 158, 255, 0.15) !important;
}
html.dark .ai-chat .tool-card.error {
  background-color: rgba(245, 108, 108, 0.1) !important;
  border-color: rgba(245, 108, 108, 0.2) !important;
}

/* 基础布局样式 - 确保 v-html 内容与 Vue 模板一致 */
.ai-chat .tool-card {
  margin: 6px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background-color: var(--el-bg-color);
  overflow: hidden;
  font-size: 13px;
}

.ai-chat .tool-card .tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background-color: var(--el-fill-color-light);
  cursor: pointer;
  min-height: 40px;
}

.ai-chat .tool-card .th-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.ai-chat .tool-card .th-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.ai-chat .tool-card .status-text {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ai-chat .tool-card .status-text.success {
  color: #67C23A;
}

.ai-chat .tool-card .status-text.error {
  color: #F56C6C;
}

.ai-chat .tool-card .status-text.loading {
  color: #409EFF;
}

.ai-chat .tool-card.success {
  border-color: rgba(103, 194, 58, 0.3);
}

.ai-chat .tool-card.error {
  border-color: rgba(245, 108, 108, 0.3);
}

.ai-chat .tool-card.loading {
  border-color: rgba(64, 158, 255, 0.3);
}

/* 展开箭头 */
.ai-chat .tool-card .arrow-icon {
  font-size: 14px;
  transition: transform 0.3s;
  color: var(--el-text-color-secondary);
}

.ai-chat .tool-card .arrow-icon.is-expanded {
  transform: rotate(90deg);
}

/* 工具结果区域 */
.ai-chat .tool-card .tool-body {
  padding: 10px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  background-color: var(--el-bg-color);
}

.ai-chat .tool-card .tool-result-pre {
  background-color: var(--el-fill-color-lighter);
  border-radius: 4px;
  padding: 8px;
  overflow-x: auto;
}

.ai-chat .tool-card .tool-result-pre pre {
  margin: 0;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  max-width: 100%;
  overflow-y: auto;
  overflow-x: auto;
  box-sizing: border-box;
}

.ai-chat .tool-card .tool-error {
  color: #F56C6C;
  font-size: 13px;
}

.ai-chat .tool-card .empty-result {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  font-style: italic;
}

/* 图标渲染 - 使用伪元素模拟 Element Plus 图标风格 */
.tool-icon.icon-operation::before {
  content: "⚙";
  font-size: 14px;
  display: inline-block;
}

.status-icon.icon-success::before {
  content: "✓";
  font-weight: bold;
  color: #67C23A;
}

.status-icon.icon-error::before {
  content: "✗";
  font-weight: bold;
  color: #F56C6C;
}

.status-icon.icon-loading::before {
  content: "⟳";
  display: inline-block;
  color: #409EFF;
  animation: icon-rotate 1.5s linear infinite;
}

@keyframes icon-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
