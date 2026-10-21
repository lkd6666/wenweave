import type { ReactNode } from 'react'
import type { ToolActivityTarget, ToolExecution } from '../types'

type ResultRecord = Record<string, unknown>

const FIELD_LABELS: Record<string, string> = {
  files: '源码文件', characters: '字符数', lines: '行数', readonly: '只读',
  start: '起始字符', end: '结束字符', before_start: '原起始字符', before_end: '原结束字符', line: '行号', groups: '工具组',
  requested_start: '请求起始字符', requested_end: '请求结束字符', context_start: '上下文起始字符', context_end: '上下文结束字符',
  added_lines: '新增行', after: '修改后', alt: '替代文字', article_type: '文章类型', assets: '图片',
  before: '修改前', block_count: '排版块', block_id: '块编号', blocks: '排版块',
  caption: '图注', character_delta: '字符变化', changes: '变更', code: '规则',
  complete: '已完成', components: '组件', content: '内容', continuity: '定位状态', description: '说明',
  done: '已完成', end_line: '结束行', engine: '来源', error: '错误', errors: '错误',
  hasError: '存在错误', height: '高度', image_count: '图片总数', images: '图片', isValid: '检测结果',
  budget_limited: '上下文限制', include_image_requested: '请求图片画面', image_content_included: '已提供图片画面',
  items: '条目', label: '名称', location_label: '位置', match_count: '匹配数',
  matches: '匹配结果', message: '说明', name: '名称', notice: '说明', operation_count: '修改处数',
  ok: '执行成功', path: '位置', query: '搜索词', remaining_block_count: '剩余块数',
  remaining_image_count: '剩余图片', remaining_match_count: '剩余匹配',
  remaining_version_count: '剩余版本', requested_count: '请求图片数', results: '搜索结果', score: '匹配度',
  section: '章节', slot: '槽位', start_line: '起始行', status: '状态', step: '任务',
  summary: '概要', tag: '标签', target: '应用位置', targets: '目标块', tasks: '任务清单', text: '内容', theme_name: '主题',
  title: '标题', total: '总数', total_changed_blocks: '变更块数',
  total_versions: '历史版本', valid: '结构检查', validation: '结构校验', version: '版本',
  version_number: '版本号', versions: '历史版本', violations: '违规项',
  vision_supported: '模型支持看图', viewed_count: '已提供画面数', warnings: '提示', width: '宽度',
}

const HIDDEN_FIELDS = new Set([
  'activity', 'candidate_ref', 'checksum', 'cursor', 'diff_preview', 'expected_hash',
  'expires_at', 'html', 'html_fragment', 'image_data', 'next_cursor', 'next_step',
  'output_id', 'preview_url', 'revision', 'source_html', 'src', 'srcset',
  'style_html', 'token', 'truncated', 'url',
])

const METADATA_FIELDS = new Set([
  'estimated_original_tokens', 'original_bytes', 'original_lines',
  'remaining_bytes', 'returned_tokens_limit', 'token_redacted',
])

const COLLECTION_FIELDS = new Set([
  'assets', 'blocks', 'changes', 'components', 'errors', 'files', 'images', 'items', 'matches',
  'results', 'targets', 'tasks', 'versions', 'violations', 'warnings',
])

function isRecord(value: unknown): value is ResultRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replaceAll('_', ' ')
}

function visibleEntries(value: ResultRecord): [string, unknown][] {
  return Object.entries(value).filter(([key, item]) =>
    item !== null && item !== undefined && item !== '' && !HIDDEN_FIELDS.has(key) && !METADATA_FIELDS.has(key),
  )
}

function toolResultData(tool: ToolExecution): unknown {
  const content = tool.model_input?.state === 'available' ? tool.model_input.content : null
  if (typeof content === 'string' && content.trim()) {
    try {
      const parsed: unknown = JSON.parse(content)
      if (isRecord(parsed) && parsed.truncated === true && isRecord(parsed.preview)) {
        return tool.activity?.compliance ?? tool.activity?.details ?? tool.activity?.targets ?? null
      }
      if (tool.name === 'read_tool_output' && isRecord(parsed) && typeof parsed.content === 'string') {
        try {
          return JSON.parse(parsed.content) as unknown
        } catch {
          return { ...parsed, content: `已读取 ${parsed.content.length.toLocaleString()} 字符的结果片段` }
        }
      }
      return parsed
    } catch {
      return content
    }
  }
  return tool.activity?.compliance ?? tool.activity?.details ?? tool.activity?.targets ?? null
}

function displayValue(value: string | number | boolean): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return value.toLocaleString()
  return value
}

function itemTitle(value: ResultRecord, index: number, label: string): string {
  for (const key of ['title', 'label', 'name', 'step', 'text', 'location_label', 'path']) {
    if (typeof value[key] === 'string' && value[key].trim()) return value[key].trim()
  }
  if (typeof value.version_number === 'number') return `v${value.version_number}`
  return `${label} ${index + 1}`
}

function ResultFields({ value, depth = 0 }: { value: ResultRecord; depth?: number }) {
  return <dl className="tool-result-fields">
    {visibleEntries(value).map(([key, item]) => {
      if (Array.isArray(item) || isRecord(item)) {
        if (depth >= 3) return null
        return <div className="tool-result-field is-nested" key={key}>
          <dt>{fieldLabel(key)}</dt>
          <dd><ResultValue value={item} label={fieldLabel(key)} depth={depth + 1} /></dd>
        </div>
      }
      return <div className="tool-result-field" key={key}>
        <dt>{fieldLabel(key)}</dt>
        <dd>{key === 'content' && typeof item === 'string' ? <span className="tool-result-text">{item}</span> : displayValue(item as string | number | boolean)}</dd>
      </div>
    })}
  </dl>
}

function ResultValue({ value, label, depth = 0 }: { value: unknown; label: string; depth?: number }): ReactNode {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="tool-result-empty">暂无{label}</span>
    return <div className="tool-result-list">
      {value.map((item, index) => isRecord(item) ? (
        <div className="tool-result-list-item" key={index}>
          <div className="tool-result-item-title">{itemTitle(item, index, label)}</div>
          <ResultFields value={Object.fromEntries(visibleEntries(item).filter(([key, field]) =>
            !['title', 'label', 'name', 'step', 'text', 'location_label', 'path'].includes(key)
              || typeof field !== 'string'
              || field.trim() !== itemTitle(item, index, label),
          ))} depth={depth + 1} />
        </div>
      ) : (
        <div className="tool-result-list-item" key={index}>{Array.isArray(item) ? <ResultValue value={item} label={label} depth={depth + 1} /> : String(item)}</div>
      ))}
    </div>
  }
  if (isRecord(value)) return <ResultFields value={value} depth={depth + 1} />
  if (value === null || value === undefined) return null
  return <span className="tool-result-text">{displayValue(value as string | number | boolean)}</span>
}

function targetsAsData(targets: ToolActivityTarget[]): ResultRecord {
  return { results: targets }
}

export default function ToolResultView({ tool, hasImageGallery }: { tool: ToolExecution; hasImageGallery: boolean }) {
  const raw = toolResultData(tool)
  const data = Array.isArray(raw) ? { items: raw } : isRecord(raw) ? raw : null
  const hasDataCollection = data && Object.entries(data).some(([key, value]) => COLLECTION_FIELDS.has(key) && Array.isArray(value) && value.length > 0)
  const targetData = !hasDataCollection && tool.activity?.targets?.length ? targetsAsData(tool.activity.targets) : null
  const result = data && targetData ? { ...data, targets: targetData.results } : data ?? targetData
  const entries = result ? visibleEntries(result).filter(([key]) => !(hasImageGallery && (key === 'items' || key === 'assets'))) : []
  const sourceContent = tool.name === 'read_file' && typeof data?.content === 'string' ? data.content : null
  const scalars = entries.filter(([key, value]) => !Array.isArray(value) && !isRecord(value) && !(sourceContent !== null && key === 'content'))
  const sections = entries.filter(([, value]) => Array.isArray(value) || isRecord(value))
  const fallback = typeof raw === 'string' ? raw : tool.activity?.summary || tool.result || ''

  return <section className="tool-result-view" aria-label="工具结果">
    {tool.model_input?.truncated && <div className="tool-result-note">结果较长，以下展示已返回的摘要。</div>}
    {scalars.length > 0 && <dl className="tool-result-stats">
      {scalars.map(([key, value]) => <div key={key} className="tool-result-stat">
        <dt>{fieldLabel(key)}</dt><dd>{displayValue(value as string | number | boolean)}</dd>
      </div>)}
    </dl>}
    {sourceContent !== null && <div className="tool-result-section">
      <div className="tool-result-section-title">源码</div>
      <pre className="tool-result-text"><code>{sourceContent}</code></pre>
      {data?.complete === false && <div className="tool-result-note">源码尚未读完，可继续读取。</div>}
    </div>}
    {sections.map(([key, value]) => <div className="tool-result-section" key={key}>
      <div className="tool-result-section-title">{fieldLabel(key)}{Array.isArray(value) ? ` ${value.length}` : ''}</div>
      <ResultValue value={value} label={fieldLabel(key)} />
    </div>)}
    {!entries.length && targetData && <ResultValue value={targetData.results} label="结果" />}
    {!entries.length && !targetData && fallback && <div className="tool-result-text">{fallback}</div>}
    {!entries.length && !targetData && !fallback && <div className="tool-result-empty">{tool.status === 'running' ? '正在获取结果' : '暂无详情'}</div>}
  </section>
}
