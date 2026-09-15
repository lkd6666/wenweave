import { DownOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons'
import { memo, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode, UIEvent } from 'react'
import type { AiDiffRow } from './aiOutputDiff'
import './ai-output.css'

export type { AiDiffRow } from './aiOutputDiff'

export type AiOutputStatus = 'idle' | 'running' | 'success' | 'error' | 'cancelled'

export interface AiTodoItem {
  step: string
  status: 'pending' | 'in_progress' | 'done'
}

function reasoningSegments(value: string): string[] {
  const normalized = value.replace(/\r\n?/g, '\n').trim()
  if (!normalized) return []
  const lines = normalized.split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.flatMap((line) => {
    if (line.length <= 132) return [line]
    const parts = line.split(/(?<=[。！？!?；;])\s*/).filter(Boolean)
    return parts.length > 1 ? parts : [line]
  })
}

// Long reasoning can contain thousands of sentences. Keep the full transcript
// scrollable without retaining thousands of animated rows.
const ReasoningContent = memo(function ReasoningContent({ text }: { text: string }) {
  const segments = text.length > 8_000 ? null : reasoningSegments(text)
  if (!segments || segments.length > 80) {
    return <div className="aicss-reasoning-text">{text}</div>
  }
  return <div className="aicss-thinking-reasoning-stream">
    {segments.map((segment, index) => <p className="aicss-reasoning-sentence" key={index}>{segment}</p>)}
  </div>
})

function CodeFileIcon() {
  return <svg className="aicss-code-block-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 6-6 6 6 6M16 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function CopyIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.7" /><path d="M5 15a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
}

function SmallCheckIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4.5 12.75 6 6 9-13.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function TodoListIcon() {
  return <svg className="aicss-todo-head-state" viewBox="0 0 24 24" aria-hidden="true"><path d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function TodoDoneIcon({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true"><path fillRule="evenodd" clipRule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12Zm13.36-1.814a.75.75 0 1 0-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.14-.094l3.75-5.25Z" fill="currentColor" /></svg>
}

function TodoChevronIcon() {
  return <svg className="aicss-todo-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m19.5 8.25-7.5 7.5-7.5-7.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function TodoPendingIcon({ className }: { className: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="1.8 3.6" strokeLinecap="round" /></svg>
}

function TodoActiveIcon({ className }: { className: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true"><path d="m12.75 15 3-3m0 0-3-3m3 3h-7.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function TodoItemDoneIcon({ className }: { className: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true"><path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

export function AiThinkingState({ label = '正在思考' }: { label?: string }) {
  return <span className="aicss-thinking-state" role="status">{label}</span>
}

export function AiOrbs({ label = '处理中' }: { label?: string }) {
  return (
    <span className="aicss-orbs" role="status" aria-label={label}>
      <i /><i /><i />
      <span>{label}</span>
    </span>
  )
}

export function AiThinkingReasoning({
  thinking,
  duration,
  content,
  fallback,
  onScroll,
}: {
  thinking: boolean
  duration?: string | null
  content: string
  fallback?: string
  onScroll?: (event: UIEvent<HTMLDivElement>) => void
}) {
  const [open, setOpen] = useState(thinking)

  useEffect(() => setOpen(thinking), [thinking])

  const hasDetail = Boolean(content || fallback)
  const summary = duration ? `思考了 ${duration}` : '思考过程'
  return (
    <section className={`aicss-thinking-reasoning${thinking ? ' is-thinking' : ''}`}>
      <button
        type="button"
        className="aicss-thinking-reasoning-trigger"
        aria-expanded={open}
        aria-label={thinking ? '正在显示思考过程' : '展开或收起思考过程'}
        disabled={thinking || !hasDetail}
        onClick={() => !thinking && hasDetail && setOpen((value) => !value)}
      >
        {thinking ? <AiThinkingState /> : <span className="aicss-thinking-summary">{summary}</span>}
        {!thinking && hasDetail && <DownOutlined className="aicss-disclosure-icon" aria-hidden="true" />}
      </button>
      <div className={`aicss-thinking-reasoning-body${open ? ' is-open' : ''}`} aria-hidden={!open}>
        <div className="aicss-thinking-reasoning-inner">
          <div
            className={`aicss-thinking-reasoning-viewport${thinking ? ' is-live' : ''}`}
            onScroll={onScroll}
          >
            {open && <ReasoningContent text={content || fallback || '模型正在生成推理内容…'} />}
          </div>
        </div>
      </div>
    </section>
  )
}

export function AiTextResponse({ children }: { children: ReactNode }) {
  return <div className="aicss-text-response">{children}</div>
}

export function AiStreamingText({
  children,
  active,
  showCaret = true,
}: {
  children: ReactNode
  active: boolean
  showCaret?: boolean
}) {
  return (
    <div className={`aicss-streaming-text${active ? ' is-active' : ''}`}>
      {children}
      {active && showCaret && <span className="aicss-streaming-caret" aria-hidden="true" />}
    </div>
  )
}

export function AiInlineCitation({ href, children, title }: { href: string; children: ReactNode; title?: string }) {
  return (
    <a className="aicss-inline-citation" href={href} target="_blank" rel="noreferrer" title={title || '打开来源'}>
      {children}<RightOutlined aria-hidden="true" />
    </a>
  )
}

export function AiToolCall({
  icon,
  iconTone,
  title,
  summary,
  status,
  statusDetail,
  expanded,
  onToggle,
  children,
}: {
  icon: ReactNode
  iconTone?: string
  title: string
  summary: string
  status: AiOutputStatus
  statusDetail?: ReactNode
  expanded?: boolean
  onToggle?: () => void
  children?: ReactNode
}) {
  const Head = onToggle ? 'button' : 'div'
  return (
    <div className={`aicss-tool-call is-${status}`}>
      <Head
        {...(onToggle ? { type: 'button' as const, onClick: onToggle, 'aria-expanded': Boolean(expanded) } : {})}
        className="aicss-tool-call-head"
      >
        <span className={'aicss-tool-call-icon' + (iconTone ? ' is-' + iconTone : '')} aria-hidden="true">{icon}</span>
        <span className="aicss-tool-call-copy"><strong>{title}</strong><small>{summary}</small></span>
        {statusDetail || (status === 'running' ? <AiOrbs label="" /> : <span className="aicss-tool-call-status">{statusLabel(status)}</span>)}
        {onToggle && <DownOutlined className={`aicss-disclosure-icon${expanded ? ' is-open' : ''}`} aria-hidden="true" />}
      </Head>
      {children && (
        <div className={`aicss-tool-call-collapsible${onToggle && !expanded ? ' is-collapsed' : ''}`} aria-hidden={Boolean(onToggle && !expanded)}>
          <div className="aicss-tool-call-body">{(!onToggle || expanded) && children}</div>
        </div>
      )}
    </div>
  )
}

export function AiWebSearch({
  query,
  sources = [],
  running = false,
}: {
  query: string
  sources?: Array<{ label: string; href?: string }>
  running?: boolean
}) {
  return (
    <section className={`aicss-web-search${running ? ' is-running' : ''}`} aria-label="搜索结果">
      <div className="aicss-web-search-head"><SearchOutlined aria-hidden="true" /><span>{query || '正在搜索'}</span>{running && <AiOrbs label="" />}</div>
      {sources.length > 0 && <div className="aicss-web-search-sources">
        {sources.slice(0, 4).map((source, index) => source.href
          ? <AiInlineCitation key={`${source.href}-${index}`} href={source.href}>{source.label}</AiInlineCitation>
          : <span className="aicss-search-source" key={`${source.label}-${index}`}>{source.label}</span>)}
      </div>}
    </section>
  )
}

export function AiFileDiff({ file = '变更预览', rows }: { file?: string; rows: AiDiffRow[] }) {
  const additions = rows.filter((row) => row.kind === 'add').length
  const removals = rows.filter((row) => row.kind === 'remove').length
  return (
    <section className="aicss-file-diff" aria-label={file}>
      <div className="aicss-file-diff-head"><span className="aicss-file-diff-file"><CodeFileIcon /><span>{file}</span></span><span><b className="is-add">+{additions}</b><b className="is-remove">-{removals}</b></span></div>
      <div className="aicss-file-diff-body">
        {rows.map((row, index) => <div className={`aicss-file-diff-row is-${row.kind}`} key={`${row.kind}-${index}-${row.text}`}>
          <span>{row.oldLine || ''}</span><span>{row.newLine || ''}</span><i>{row.kind === 'add' ? '+' : row.kind === 'remove' ? '-' : ''}</i><code>{row.text}</code>
        </div>)}
      </div>
    </section>
  )
}

export function AiCodeBlock({ language, code, children }: { language?: string; code: string; children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }
  return (
    <section className="aicss-code-block">
      <header>
        <span className="aicss-code-block-file"><CodeFileIcon /><span>{language || 'text'}</span></span>
        <button type="button" onClick={() => void copy()} aria-label={copied ? '已复制代码' : '复制代码'} title={copied ? '已复制' : '复制代码'}>
          {copied ? <SmallCheckIcon /> : <CopyIcon />}
          <span>{copied ? '已复制' : '复制'}</span>
        </button>
      </header>
      <div className="aicss-code-block-content">{children}</div>
    </section>
  )
}

export function AiTodoList({ items, live = false }: { items: AiTodoItem[]; live?: boolean }) {
  const [open, setOpen] = useState(true)
  const done = items.filter((item) => item.status === 'done').length
  const active = items.find((item) => item.status === 'in_progress')
  const allDone = items.length > 0 && done === items.length
  const progress = items.length ? Math.round((done / items.length) * 100) : 0
  const summary = allDone
    ? '已完成全部任务'
    : active
      ? active.step
      : done > 0
        ? `已完成 ${done} 项`
        : '等待开始'
  return (
    <section className={`aicss-todo-list${live ? ' is-live' : ''}`} aria-label="任务清单" aria-live={live ? 'polite' : 'off'}>
      <button type="button" className="aicss-todo-head" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className={`aicss-todo-head-icon${allDone ? ' is-done' : active ? ' is-active' : ''}`} aria-hidden="true">
          {allDone ? <TodoDoneIcon className="aicss-todo-head-state" /> : active ? (
            <span className="aicss-todo-progress" style={{ '--aicss-todo-progress': `${progress}%` } as CSSProperties}>
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeDasharray="2.2 4.4" strokeLinecap="round" /></svg>
            </span>
          ) : <TodoListIcon />}
          <TodoChevronIcon />
        </span>
        <span className="aicss-todo-title">
          <span className="aicss-todo-title-label" aria-hidden={!open}>任务清单</span>
          <span className={`aicss-todo-head-summary${active ? ' is-active' : allDone ? ' is-done' : ''}`} aria-hidden={open} data-label={summary} title={summary}>{summary}</span>
        </span>
        <span className="aicss-todo-count" aria-label={`${done}/${items.length} 已完成`}>{done}/{items.length}</span>
      </button>
      <div className={`aicss-todo-collapsible${open ? '' : ' is-collapsed'}`}>
        <div className="aicss-todo-inner" tabIndex={0} role="region" aria-label="任务步骤"><ol className="aicss-todo-items">
        {items.map((item, index) => <li className={`is-${item.status}`} key={`${item.step}-${index}`}>
          <span className="aicss-todo-item-icon" aria-hidden="true">
            <TodoPendingIcon className={`aicss-todo-state${item.status === 'pending' ? ' is-visible' : ''}`} />
            <TodoActiveIcon className={`aicss-todo-state aicss-todo-state-strong${item.status === 'in_progress' ? ' is-visible' : ''}`} />
            <TodoItemDoneIcon className={`aicss-todo-state${item.status === 'done' ? ' is-visible' : ''}`} />
          </span>
          <span className="aicss-todo-item-label" data-label={item.step}>{item.step}</span>
        </li>)}
        </ol></div>
      </div>
    </section>
  )
}

export function AiDataTable({ children, comparison = false }: { children: ReactNode; comparison?: boolean }) {
  return <div className={`aicss-data-table${comparison ? ' aicss-comparison-table' : ''}`}>{children}</div>
}

export function AiComparisonTable({ rows }: { rows: Array<{ label: string; value: string; tone?: 'add' | 'remove' | 'neutral' }> }) {
  return <div className="aicss-comparison-table aicss-comparison-summary">{rows.map((row) => <div key={row.label}><span>{row.label}</span><strong className={row.tone ? `is-${row.tone}` : ''}>{row.value}</strong></div>)}</div>
}

export function AiImageGeneration({ status, title, detail, children }: { status: AiOutputStatus; title: string; detail?: string; children?: ReactNode }) {
  return (
    <section className={`aicss-image-generation is-${status}`} role={status === 'error' ? 'alert' : 'status'}>
      <div className="aicss-image-generation-canvas" aria-hidden="true"><span /><span /><span /></div>
      <div><strong>{title}</strong>{detail && <small>{detail}</small>}</div>
      {status === 'running' && <AiOrbs label="" />}
      {children && <div className="aicss-image-generation-body">{children}</div>}
    </section>
  )
}

export function AiAgentInput({ children }: { children: ReactNode }) {
  return <div className="aicss-agent-input">{children}</div>
}

function statusLabel(status: AiOutputStatus): string {
  if (status === 'running') return '执行中'
  if (status === 'success') return '完成'
  if (status === 'error') return '失败'
  if (status === 'cancelled') return '已停止'
  return '待处理'
}
