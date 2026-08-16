import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, FloatButton, Modal, Tooltip, message } from 'antd'
import { BellOutlined, MinusOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import { cancelChatRun, chatApi } from '../api/chat'
import { streamPendingChatUserQuestions } from '../api/chatUserQuestions'
import type { PendingChatUserQuestion } from '../types'
import { shouldShowGlobalQuestionModal } from '../utils/chatQuestionNotifications'
import UserQuestionPanel from './UserQuestionPanel'
import type { UserQuestionAnswer } from './UserQuestionPanel'

const USER_QUESTION_ACTIVITY_THROTTLE_MS = 10_000

function createClientRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `question-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function reconnectDelay(attempt: number, signal: AbortSignal): Promise<void> {
  const delay = Math.min(5_000, 500 * 2 ** Math.min(4, Math.max(0, attempt - 1)))
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', abort)
    const finish = () => {
      cleanup()
      resolve()
    }
    const timer = window.setTimeout(finish, delay)
    const abort = () => {
      window.clearTimeout(timer)
      cleanup()
      reject(new DOMException('提醒连接已关闭', 'AbortError'))
    }
    if (signal.aborted) {
      abort()
      return
    }
    signal.addEventListener('abort', abort, { once: true })
  })
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? String(error.detail) : fallback
}

interface GlobalUserQuestionNotificationsProps {
  systemName: string
  iconUrl: string
}

export default function GlobalUserQuestionNotifications({
  systemName,
  iconUrl,
}: GlobalUserQuestionNotificationsProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [questions, setQuestions] = useState<PendingChatUserQuestion[]>([])
  const [visibilityState, setVisibilityState] = useState<DocumentVisibilityState>(() => document.visibilityState)
  const [submittingQuestionId, setSubmittingQuestionId] = useState<string | null>(null)
  const [minimizedQuestionIds, setMinimizedQuestionIds] = useState<Set<string>>(() => new Set())
  const answerRequestRef = useRef<{
    questionId: string
    answerKey: string
    clientRequestId: string
  } | null>(null)
  const activityRef = useRef<{ questionId: string; lastSentAt: number } | null>(null)
  const reconcilingQuestionIdsRef = useRef(new Set<string>())
  const notifiedQuestionIdsRef = useRef(new Set<string>())
  const nativeNotificationsRef = useRef(new Map<string, Notification>())

  useEffect(() => {
    const updateVisibility = () => setVisibilityState(document.visibilityState)
    document.addEventListener('visibilitychange', updateVisibility)
    return () => document.removeEventListener('visibilitychange', updateVisibility)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      let attempt = 0
      while (!controller.signal.aborted) {
        try {
          for await (const snapshot of streamPendingChatUserQuestions(controller.signal)) {
            attempt = 0
            setQuestions(snapshot)
          }
        } catch (error) {
          if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return
        }
        attempt += 1
        try {
          await reconnectDelay(attempt, controller.signal)
        } catch {
          return
        }
      }
    })()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const pendingIds = new Set(questions.map((item) => item.question.id))
    nativeNotificationsRef.current.forEach((notification, questionId) => {
      if (pendingIds.has(questionId)) return
      notification.close()
      nativeNotificationsRef.current.delete(questionId)
    })

    if (visibilityState === 'visible' || typeof window.Notification === 'undefined') return
    if (window.Notification.permission !== 'granted') return
    questions.forEach((item) => {
      const questionId = item.question.id
      if (notifiedQuestionIdsRef.current.has(questionId)) return
      notifiedQuestionIdsRef.current.add(questionId)
      try {
        const notification = new window.Notification(`${systemName}：排版任务需要确认`, {
          body: `《${item.document_title}》需要确认排版偏好`,
          icon: iconUrl,
          tag: `chat-user-question-${questionId}`,
          requireInteraction: true,
        })
        nativeNotificationsRef.current.set(questionId, notification)
        notification.onclick = () => {
          window.focus()
          navigate(`/editor/${item.document_id}`)
          notification.close()
        }
        notification.onclose = () => {
          if (nativeNotificationsRef.current.get(questionId) === notification) {
            nativeNotificationsRef.current.delete(questionId)
          }
        }
      } catch {
        // Browser policy failures fall back to the in-app modal when the page is visible again.
      }
    })
  }, [iconUrl, navigate, questions, systemName, visibilityState])

  useEffect(() => () => {
    nativeNotificationsRef.current.forEach((notification) => notification.close())
    nativeNotificationsRef.current.clear()
  }, [])

  const visibleQuestions = useMemo(() => questions.filter((item) => (
    shouldShowGlobalQuestionModal(location.pathname, visibilityState, item.document_id)
  )), [location.pathname, questions, visibilityState])
  const minimizedVisibleQuestions = useMemo(() => visibleQuestions.filter((item) => (
    minimizedQuestionIds.has(item.question.id)
  )), [minimizedQuestionIds, visibleQuestions])
  const currentQuestion = visibleQuestions.find((item) => !minimizedQuestionIds.has(item.question.id)) ?? null

  useEffect(() => {
    const pendingIds = new Set(questions.map((item) => item.question.id))
    setMinimizedQuestionIds((previous) => {
      const activeIds = new Set([...previous].filter((questionId) => pendingIds.has(questionId)))
      return activeIds.size === previous.size ? previous : activeIds
    })
  }, [questions])

  const removeQuestion = useCallback((questionId: string) => {
    setQuestions((items) => items.filter((item) => item.question.id !== questionId))
  }, [])

  const reconcileQuestion = useCallback(async (item: PendingChatUserQuestion) => {
    const questionId = item.question.id
    if (reconcilingQuestionIdsRef.current.has(questionId)) return
    reconcilingQuestionIdsRef.current.add(questionId)
    try {
      const run = await chatApi.getRun(item.document_id, item.question.run_id)
      if (run.status === 'waiting_for_input' && run.user_question) {
        setQuestions((items) => items.map((candidate) => candidate.question.id === questionId
          ? {
              ...candidate,
              session_id: run.session_id,
              question: run.user_question!,
            }
          : candidate,
        ))
      } else {
        removeQuestion(questionId)
      }
    } catch {
      // The durable SSE snapshot will retry reconciliation without hiding a possibly valid question.
    } finally {
      reconcilingQuestionIdsRef.current.delete(questionId)
    }
  }, [removeQuestion])

  const answerQuestion = useCallback(async (item: PendingChatUserQuestion, answer: UserQuestionAnswer) => {
    const questionId = item.question.id
    if (submittingQuestionId) return
    const answerKey = JSON.stringify(answer)
    const previousRequest = answerRequestRef.current
    const clientRequestId = previousRequest?.questionId === questionId && previousRequest.answerKey === answerKey
      ? previousRequest.clientRequestId
      : createClientRequestId()
    answerRequestRef.current = { questionId, answerKey, clientRequestId }
    setSubmittingQuestionId(questionId)
    try {
      await chatApi.answerUserQuestion(
        item.document_id,
        item.question.run_id,
        questionId,
        answer,
        clientRequestId,
      )
      removeQuestion(questionId)
      message.success('排版偏好已提交，任务将继续执行')
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await reconcileQuestion(item)
      } else {
        message.error(errorMessage(error, '提交排版偏好失败'))
      }
    } finally {
      setSubmittingQuestionId(null)
    }
  }, [reconcileQuestion, removeQuestion, submittingQuestionId])

  const recordActivity = useCallback((item: PendingChatUserQuestion) => {
    if (submittingQuestionId) return
    const now = Date.now()
    const previous = activityRef.current
    if (previous?.questionId === item.question.id && now - previous.lastSentAt < USER_QUESTION_ACTIVITY_THROTTLE_MS) return
    activityRef.current = { questionId: item.question.id, lastSentAt: now }
    void chatApi.recordUserQuestionActivity(item.document_id, item.question.run_id, item.question.id)
      .catch(() => reconcileQuestion(item))
  }, [reconcileQuestion, submittingQuestionId])

  const stopQuestionRun = useCallback(async (item: PendingChatUserQuestion) => {
    const questionId = item.question.id
    if (submittingQuestionId) return
    setSubmittingQuestionId(questionId)
    try {
      await cancelChatRun(item.document_id, item.question.run_id)
      removeQuestion(questionId)
      message.success('本轮排版任务已停止')
    } catch (error) {
      await reconcileQuestion(item)
      message.error(errorMessage(error, '停止排版任务失败'))
    } finally {
      setSubmittingQuestionId(null)
    }
  }, [reconcileQuestion, removeQuestion, submittingQuestionId])

  const questionCountLabel = visibleQuestions.length > 1
    ? `（1/${visibleQuestions.length}）`
    : ''

  const minimizeQuestions = () => {
    setMinimizedQuestionIds((previous) => {
      const next = new Set(previous)
      visibleQuestions.forEach((item) => next.add(item.question.id))
      return next
    })
  }

  const restoreQuestions = () => {
    setMinimizedQuestionIds((previous) => {
      const next = new Set(previous)
      visibleQuestions.forEach((item) => next.delete(item.question.id))
      return next
    })
  }

  return (
    <>
      <Modal
        title={(
          <div className="global-user-question-modal-title">
            <span>{currentQuestion ? `${currentQuestion.document_title} · 排版助手需要确认${questionCountLabel}` : '排版助手需要确认'}</span>
            <Tooltip title="暂时收起">
              <Button
                type="text"
                size="small"
                shape="circle"
                aria-label="暂时收起待确认弹窗"
                icon={<MinusOutlined />}
                onClick={minimizeQuestions}
              />
            </Tooltip>
          </div>
        )}
        open={currentQuestion !== null}
        footer={null}
        closable={false}
        maskClosable={false}
        keyboard={false}
        width={640}
        destroyOnHidden
        className="global-user-question-modal"
      >
        {currentQuestion && (
          <UserQuestionPanel
            key={currentQuestion.question.id}
            question={currentQuestion.question}
            submitting={submittingQuestionId === currentQuestion.question.id}
            onAnswer={(answer) => { void answerQuestion(currentQuestion, answer) }}
            onActivity={() => recordActivity(currentQuestion)}
            onTimeoutElapsed={() => { void reconcileQuestion(currentQuestion) }}
            onStop={() => { void stopQuestionRun(currentQuestion) }}
          />
        )}
      </Modal>
      {minimizedVisibleQuestions.length > 0 && (
        <FloatButton
          className="global-user-question-float"
          icon={<BellOutlined />}
          badge={{ count: minimizedVisibleQuestions.length }}
          tooltip="恢复待确认弹窗"
          aria-label={`恢复待确认弹窗，共 ${minimizedVisibleQuestions.length} 项`}
          onClick={restoreQuestions}
        />
      )}
    </>
  )
}
