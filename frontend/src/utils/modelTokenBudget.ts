const TOKENS_PER_K = 1_000
const MIN_CONTEXT_TOKENS = 8_192
const MAX_CONTEXT_TOKENS = 2_000_000
const MAX_OUTPUT_TOKENS = 1_000_000

export interface ModelTokenBudget {
  context_window_tokens: number
  context_compaction_threshold_tokens: number
  max_output_tokens: number
  tool_result_max_tokens: number
}

function asWholeKTokens(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function deriveModelTokenBudget(inputKTokens: unknown, outputKTokens: unknown): ModelTokenBudget | null {
  const inputK = asWholeKTokens(inputKTokens)
  const outputK = asWholeKTokens(outputKTokens)
  if (inputK === null || outputK === null) return null

  const contextCompactionThresholdTokens = inputK * TOKENS_PER_K
  const maxOutputTokens = outputK * TOKENS_PER_K
  const contextWindowTokens = contextCompactionThresholdTokens + maxOutputTokens
  if (
    contextWindowTokens < MIN_CONTEXT_TOKENS
    || contextWindowTokens > MAX_CONTEXT_TOKENS
    || maxOutputTokens > MAX_OUTPUT_TOKENS
  ) {
    return null
  }

  return {
    context_window_tokens: contextWindowTokens,
    context_compaction_threshold_tokens: contextCompactionThresholdTokens,
    max_output_tokens: maxOutputTokens,
    tool_result_max_tokens: Math.min(
      contextCompactionThresholdTokens,
      contextCompactionThresholdTokens < 65_536
        ? 10_000
        : contextCompactionThresholdTokens <= 262_144
          ? 12_288
          : 16_384,
    ),
  }
}

export function tokensToWholeK(tokens: number): number {
  return Math.max(1, Math.floor(tokens / TOKENS_PER_K))
}

export function formatKTokens(tokens: number): string {
  return `${tokensToWholeK(tokens)}K`
}
