import { describe, expect, it } from 'vitest'
import { parsePendingQuestionsSseChunk } from './chatUserQuestions'

describe('parsePendingQuestionsSseChunk', () => {
  it('parses complete snapshots and preserves a partial trailing event', () => {
    const first = JSON.stringify([
      {
        document_id: 12,
        document_title: '示例文档',
        session_id: 3,
        created_at: '2026-08-15T01:00:00Z',
        question: {
          id: 'question-1',
          run_id: 'run-1',
          question: '请选择风格',
          options: [],
          allow_multiple: false,
          include_style: false,
        },
      },
    ])
    const chunk = `event: pending_questions\r\ndata: ${first}\r\n\r\nevent: pending_questions\r\ndata: [`

    const parsed = parsePendingQuestionsSseChunk(chunk)

    expect(parsed.snapshots).toHaveLength(1)
    expect(parsed.snapshots[0][0].question.id).toBe('question-1')
    expect(parsed.rest).toBe('event: pending_questions\r\ndata: [')
  })

  it('accepts an empty snapshot when all questions are resolved', () => {
    const parsed = parsePendingQuestionsSseChunk('event: pending_questions\ndata: []\n\n')

    expect(parsed.snapshots).toEqual([[]])
  })
})
