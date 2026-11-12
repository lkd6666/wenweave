import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import type { ChatContextStats, ComplianceReport, ToolExecution } from '../types'
import { complianceReportFromToolActivity, getComplianceButtonStatus, latestComplianceReportFromTools, mergeContextStats } from './EditorPage'

const preparedStats = {
  used_tokens: 20_000,
  compiled_input_tokens: 20_000,
  usable_tokens: 25_000,
  breakdown: {},
} as ChatContextStats

describe('mergeContextStats', () => {
  it('shows the latest tool result budget even after a provider usage report', () => {
    const measured = {
      ...preparedStats,
      runtime_context_state: 'measured',
      runtime_context_tokens: 21_000,
      runtime_context_source: 'provider_reported',
      runtime_context_is_estimate: false,
    }
    const afterTool = {
      ...preparedStats,
      runtime_context_state: 'tool_result_context',
      runtime_context_tokens: 25_000,
      runtime_context_source: 'server_recomputed_after_tool',
      runtime_context_is_estimate: true,
    }

    const merged = mergeContextStats(measured, afterTool)

    expect(merged.runtime_context_tokens).toBe(25_000)
    expect(merged.runtime_context_source).toBe('server_recomputed_after_tool')
    expect(merged.runtime_context_is_estimate).toBe(true)
  })

  it('keeps the latest measured input through following stream telemetry', () => {
    const measured = {
      ...preparedStats,
      runtime_context_state: 'measured',
      runtime_context_tokens: 21_000,
      runtime_context_source: 'provider_reported',
      runtime_context_is_estimate: false,
    }
    const streaming = {
      ...preparedStats,
      runtime_context_state: 'streaming',
      runtime_projected_tokens: 1_500,
    }

    const merged = mergeContextStats(measured, streaming)

    expect(merged.runtime_context_tokens).toBe(21_000)
    expect(merged.runtime_context_source).toBe('provider_reported')
  })

  it('replaces runtime telemetry with the durable snapshot on completion or model change', () => {
    const running = {
      ...preparedStats,
      runtime_context_tokens: 24_000,
      runtime_context_source: 'server_request_budget',
    }
    const persisted = { ...preparedStats, state: 'ready', used_tokens: 18_000, compiled_input_tokens: 18_000 }
    expect(mergeContextStats(running, persisted)).toEqual(persisted)
  })

  it('shows the smaller budget immediately after compaction', () => {
    const running = { ...preparedStats, runtime_context_tokens: 24_000, runtime_context_source: 'server_request_budget' }
    const compacted = {
      ...preparedStats,
      runtime_context_state: 'in_run_compacted',
      runtime_context_tokens: 8_000,
      runtime_context_source: 'server_request_budget',
    }
    expect(mergeContextStats(running, compacted).runtime_context_tokens).toBe(8_000)
  })

  it('retains the matching threshold and multiplier when keeping a live estimate', () => {
    const running = {
      ...preparedStats, model_id: 40, session_id: 3,
      runtime_context_tokens: 30_000, runtime_context_source: 'server_request_budget',
      used_tokens: 30_000, compiled_input_tokens: 30_000,
      active_context_threshold_tokens: 50_000, token_estimate_multiplier: 1.6,
    }
    const persisted = { ...preparedStats, model_id: 40, session_id: 3, state: 'streaming', active_context_threshold_tokens: 80_000 }
    const merged = mergeContextStats(running, persisted)
    expect(merged.compiled_input_tokens).toBe(30_000)
    expect(merged.active_context_threshold_tokens).toBe(50_000)
    expect(merged.token_estimate_multiplier).toBe(1.6)
  })

  it('discards live estimates when a different model or session arrives', () => {
    const running = { ...preparedStats, model_id: 40, session_id: 3, runtime_context_source: 'server_request_budget' }
    for (const next of [{ model_id: 41, session_id: 3 }, { model_id: 40, session_id: 4 }]) {
      const incoming = { ...preparedStats, ...next, state: 'streaming' }
      expect(mergeContextStats(running, incoming)).toEqual(incoming)
    }
  })
})

describe('official compliance report state', () => {
  const report = (overrides: Partial<ComplianceReport> = {}): ComplianceReport => ({
    engine: {
      version: '0.2.28',
      commit: '4a3daa63',
      repository: 'https://github.com/wechatjs/verify-article-structure-spec',
      available: true,
      detail: '',
    },
    isValid: true,
    violations: [],
    warnMsgs: [],
    ...overrides,
  })

  it('does not treat an unavailable official engine as a successful check', () => {
    expect(getComplianceButtonStatus(null, true)).toBe('checking')
    expect(getComplianceButtonStatus(report({
      engine: { ...report().engine, available: false, detail: 'Chromium unavailable' },
      isValid: null,
    }))).toBe('warning')
  })

  it('reports official violations independently from gzhStrict warnings', () => {
    expect(getComplianceButtonStatus(report({
      isValid: false,
      violations: [{ key: 'width', message: '官方规则', items: [] }],
    }))).toBe('error')
    expect(getComplianceButtonStatus(report({
      gzhStrict: { hasError: false, hasWarning: true, errors: [], warnings: ['主题提示'], leafCount: 1 },
    }))).toBe('warning')
  })

  it('uses an official report carried by a compliance tool event', () => {
    const official = report()
    expect(complianceReportFromToolActivity({ kind: 'check', summary: '官方合规检测通过', compliance: official })).toBe(official)
    expect(latestComplianceReportFromTools([
      { id: 'search', name: 'search_html', arguments: {}, status: 'success', html_changed: false },
      { id: 'check', name: 'check_compliance', arguments: {}, status: 'success', html_changed: false, activity: { kind: 'check', summary: '官方合规检测通过', compliance: official } },
    ] as ToolExecution[])).toBe(official)
  })

  it('does not accept incomplete report-like activity data', () => {
    expect(complianceReportFromToolActivity({ kind: 'check', summary: '检测完成' })).toBeNull()
    expect(complianceReportFromToolActivity({ kind: 'check', summary: '检测完成', compliance: { isValid: true } as ComplianceReport })).toBeNull()
  })

  it('never schedules a browser-side compliance API request after editing', () => {
    const source = readFileSync(new URL('./EditorPage.tsx', import.meta.url), 'utf8')

    expect(source).not.toContain('scheduleComplianceCheck')
    expect(source).toContain('invalidateCompliance')
    expect(source).toContain('handleManualComplianceCheck')
    expect(source).toContain('complianceApi.check(snapshot)')
    expect(source.match(/complianceApi\.check/g)).toHaveLength(1)
  })
})

describe('AI editing read-only actions', () => {
  it('keeps read-only panels available while document mutations stay locked', () => {
    const source = readFileSync(new URL('./EditorPage.tsx', import.meta.url), 'utf8')

    expect(source).not.toMatch(/aria-label="打开版本历史"[\s\S]{0,180}disabled=\{streaming\}/)
    expect(source).not.toMatch(/aria-label="打开原文校审"[\s\S]{0,180}disabled=\{streaming\}/)
    expect(source).not.toMatch(/aria-label="分享只读预览"[\s\S]{0,180}disabled=\{streaming \|\| saving\}/)
    expect(source).not.toContain('checkDisabled={streaming}')
    expect(source).toContain('restoreDisabled={documentEditingLocked || saving || draftHtml !== html}')
    expect(source).toContain('disabled={documentEditingLocked || saving || draftHtml === html}')
  })

  it('recovers a durable waiting question when its SSE frame is lost', () => {
    const source = readFileSync(new URL('./EditorPage.tsx', import.meta.url), 'utf8')

    expect(source).toContain("runState.status === 'waiting_for_input' && runState.user_question")
    expect(source).toContain('setPendingUserQuestion(recoveredQuestion)')
  })
})
