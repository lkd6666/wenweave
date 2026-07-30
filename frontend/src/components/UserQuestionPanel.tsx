import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Checkbox, Input, Modal, Radio, Tooltip, Typography } from 'antd'
import { EyeOutlined, ForwardOutlined, LeftOutlined, MessageOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'
import type { ChatUserQuestion, ChatUserQuestionOption } from '../types'
import ElementRenderPreview from './ElementRenderPreview'

const { Text } = Typography

export type UserQuestionAnswer =
  | { action: 'select'; optionIds: string[] }
  | { action: 'custom'; customRequirement: string }
  | { action: 'skip' }

interface UserQuestionPanelProps {
  question: ChatUserQuestion
  submitting?: boolean
  onAnswer: (answer: UserQuestionAnswer) => void
  onActivity: () => void
  onTimeoutElapsed: () => void
  onStop: () => void
}

function countdownLabel(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function questionDeadlineMs(timeoutAt: string | null | undefined): number {
  if (!timeoutAt) return Number.NaN
  const value = timeoutAt.trim()
  if (!value) return Number.NaN
  // Legacy question events stored UTC timestamps without an offset. Date.parse
  // treats those as browser-local time, making the two-minute deadline appear
  // expired immediately in timezones east or west of UTC.
  const timezoneQualified = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
  return Date.parse(timezoneQualified ? value : `${value}Z`)
}

export default function UserQuestionPanel({
  question,
  submitting = false,
  onAnswer,
  onActivity,
  onTimeoutElapsed,
  onStop,
}: UserQuestionPanelProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [customMode, setCustomMode] = useState(question.options.length === 0)
  const [customRequirement, setCustomRequirement] = useState('')
  const [previewOption, setPreviewOption] = useState<ChatUserQuestionOption | null>(null)
  const inactivitySeconds = Math.max(1, question.inactivity_seconds ?? 120)
  const [displayTimeoutAt, setDisplayTimeoutAt] = useState<string | null>(question.timeout_at ?? null)
  const [now, setNow] = useState(() => Date.now())
  const timeoutElapsedHandlerRef = useRef(onTimeoutElapsed)
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])
  const deadlineMs = questionDeadlineMs(displayTimeoutAt)
  const remainingSeconds = Number.isFinite(deadlineMs)
    ? Math.max(0, Math.ceil((deadlineMs - now) / 1000))
    : inactivitySeconds
  const timedOut = remainingSeconds <= 0
  // The server owns the deadline. Keep the form usable while the browser
  // verifies a locally elapsed timer so a last-moment interaction can still
  // refresh the durable deadline instead of being discarded client-side.
  const interactionsDisabled = submitting

  useEffect(() => {
    timeoutElapsedHandlerRef.current = onTimeoutElapsed
  }, [onTimeoutElapsed])

  useEffect(() => {
    // This is deliberately separate from form state. Activity responses carry
    // a newer timeout_at for the same question; resetting the form here used
    // to clear a choice or typed requirement immediately after the user made it.
    setDisplayTimeoutAt(question.timeout_at ?? new Date(Date.now() + inactivitySeconds * 1000).toISOString())
    setNow(Date.now())
  }, [inactivitySeconds, question.timeout_at])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!timedOut || submitting) return
    timeoutElapsedHandlerRef.current()
    const poll = window.setInterval(() => timeoutElapsedHandlerRef.current(), 3_000)
    return () => window.clearInterval(poll)
  }, [question.id, submitting, timedOut])

  const markActivity = () => {
    if (interactionsDisabled) return
    setDisplayTimeoutAt(new Date(Date.now() + inactivitySeconds * 1000).toISOString())
    setNow(Date.now())
    onActivity()
  }

  const toggleOption = (optionId: string) => {
    if (interactionsDisabled) return
    markActivity()
    setCustomMode(false)
    setCustomRequirement('')
    if (!question.allow_multiple) {
      setSelectedIds([optionId])
      return
    }
    setSelectedIds((items) => items.includes(optionId) ? items.filter((item) => item !== optionId) : [...items, optionId])
  }

  const submitSelection = () => {
    if (!selectedIds.length || interactionsDisabled) return
    onAnswer({ action: 'select', optionIds: selectedIds })
  }

  const submitCustom = () => {
    const requirement = customRequirement.trim()
    if (!requirement || interactionsDisabled) return
    onAnswer({ action: 'custom', customRequirement: requirement })
  }

  return (
    <section
      className="user-question-panel"
      aria-label="排版偏好提问"
    >
      <header className="user-question-panel-head">
        <div className="user-question-panel-kicker">
          <Text type="secondary">排版助手需要确认</Text>
        </div>
        <div className="user-question-panel-status">
          <Text className={timedOut ? 'is-expired' : ''} type="secondary" role="status" aria-live="polite">
            {timedOut ? '正在确认是否超时' : `${countdownLabel(remainingSeconds)} 后自动跳过`}
          </Text>
          <Tooltip title="停止本轮排版">
            <Button aria-label="停止本轮排版" type="text" danger icon={<StopOutlined />} onClick={onStop} disabled={submitting} />
          </Tooltip>
        </div>
        <h3>{question.question}</h3>
      </header>

      {customMode ? (
        <div className="user-question-custom">
          {question.options.length > 0 && (
            <Button type="text" icon={<LeftOutlined />} disabled={interactionsDisabled} onClick={() => {
              markActivity()
              setCustomMode(false)
            }}>
              返回选项
            </Button>
          )}
          <Input.TextArea
            autoFocus
            value={customRequirement}
            maxLength={1200}
            autoSize={{ minRows: 3, maxRows: 7 }}
            placeholder="输入你的新要求"
            disabled={interactionsDisabled}
            onFocus={markActivity}
            onChange={(event) => {
              markActivity()
              setCustomRequirement(event.target.value)
            }}
          />
          <div className="user-question-actions">
            <Button icon={<ForwardOutlined />} disabled={interactionsDisabled} onClick={() => onAnswer({ action: 'skip' })}>跳过</Button>
            <Button type="primary" icon={<SendOutlined />} loading={submitting} disabled={interactionsDisabled || !customRequirement.trim()} onClick={submitCustom}>提交要求</Button>
          </div>
        </div>
      ) : (
        <>
          <div className={`user-question-options${question.allow_multiple ? ' is-multiple' : ''}`}>
            {question.options.map((option) => {
              const selected = selectedSet.has(option.id)
              return (
                <div className={`user-question-option${selected ? ' is-selected' : ''}`} key={option.id}>
                  <button
                    type="button"
                    className="user-question-option-main"
                    disabled={interactionsDisabled}
                    onClick={() => toggleOption(option.id)}
                  >
                    {question.allow_multiple ? <Checkbox checked={selected} /> : <Radio checked={selected} />}
                    <span>
                      <b>{option.label}</b>
                      {option.description && <small>{option.description}</small>}
                    </span>
                  </button>
                  {option.style_html && (
                    <Tooltip title="查看样式">
                      <Button
                        aria-label={`查看 ${option.label} 样式`}
                        type="text"
                        icon={<EyeOutlined />}
                        disabled={interactionsDisabled}
                        onClick={() => {
                          markActivity()
                          setPreviewOption(option)
                        }}
                      >
                        查看样式
                      </Button>
                    </Tooltip>
                  )}
                </div>
              )
            })}
          </div>
          <div className="user-question-actions">
            <span>
              <Button icon={<MessageOutlined />} type="text" disabled={interactionsDisabled} onClick={() => {
                markActivity()
                setSelectedIds([])
                setCustomMode(true)
              }}>
                提出新要求
              </Button>
              <Button icon={<ForwardOutlined />} type="text" disabled={interactionsDisabled} onClick={() => onAnswer({ action: 'skip' })}>跳过</Button>
            </span>
            <Button type="primary" icon={<SendOutlined />} loading={submitting} disabled={interactionsDisabled || !selectedIds.length} onClick={submitSelection}>确认选择</Button>
          </div>
        </>
      )}

      <Modal
        title={previewOption ? `${previewOption.label} 样式` : '样式预览'}
        open={previewOption !== null}
        footer={null}
        width={640}
        destroyOnHidden
        onCancel={() => setPreviewOption(null)}
      >
        {previewOption?.style_html && <div className="user-question-style-preview"><ElementRenderPreview html={previewOption.style_html} /></div>}
      </Modal>
    </section>
  )
}
