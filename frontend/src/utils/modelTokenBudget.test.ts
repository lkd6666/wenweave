import { describe, expect, it } from 'vitest'
import { deriveModelTokenBudget, formatKTokens, tokensToWholeK } from './modelTokenBudget'

describe('model token budget', () => {
  it('derives the internal budgets from whole-K input and output limits', () => {
    expect(deriveModelTokenBudget(176, 82)).toEqual({
      context_window_tokens: 258_000,
      context_compaction_threshold_tokens: 176_000,
      max_output_tokens: 82_000,
      tool_result_max_tokens: 12_288,
    })
  })

  it('rejects limits outside the persisted model budget range', () => {
    expect(deriveModelTokenBudget(1, 1)).toBeNull()
    expect(deriveModelTokenBudget(1_500, 600)).toBeNull()
    expect(deriveModelTokenBudget(20, 1_001)).toBeNull()
  })

  it('shows existing token values as conservative whole-K values', () => {
    expect(tokensToWholeK(81_920)).toBe(81)
    expect(formatKTokens(176_080)).toBe('176K')
  })
})
