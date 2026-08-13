import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  AiCodeBlock,
  AiComparisonTable,
  AiDataTable,
  AiFileDiff,
  AiImageGeneration,
  AiInlineCitation,
  AiOrbs,
  AiStreamingText,
  AiTextResponse,
  AiThinkingReasoning,
  AiThinkingState,
  AiTodoList,
  AiToolCall,
  AiWebSearch,
} from './AiOutput'
import { aiDiffRows } from './aiOutputDiff'

describe('aiDiffRows', () => {
  it('keeps unified-diff line numbers and removes transport metadata', () => {
    expect(aiDiffRows([
      'diff --git a/article.html b/article.html',
      'index 12ab34..56cd78 100644',
      '--- a/article.html',
      '+++ b/article.html',
      '@@ -4,2 +4,3 @@',
      ' unchanged',
      '-old paragraph',
      '+new paragraph',
      '+another line',
      '\\ No newline at end of file',
    ].join('\n'))).toEqual([
      { kind: 'context', oldLine: '4', newLine: '4', text: ' unchanged' },
      { kind: 'remove', oldLine: '5', text: 'old paragraph' },
      { kind: 'add', newLine: '5', text: 'new paragraph' },
      { kind: 'add', newLine: '6', text: 'another line' },
    ])
  })
})

describe('AICSS output components', () => {
  it('renders the output-state component mapping with accessible markers', () => {
    const html = renderToStaticMarkup(
      <>
        <AiThinkingState />
        <AiOrbs label="加载中" />
        <AiThinkingReasoning thinking content="推理内容" />
        <AiStreamingText active showCaret={false}>流式正文</AiStreamingText>
        <AiTextResponse>完成正文</AiTextResponse>
        <AiToolCall icon={<span>t</span>} title="读取 HTML" summary="正在执行" status="running" expanded={false} onToggle={() => undefined}><span>工具详情</span></AiToolCall>
        <AiWebSearch query="排版素材" running sources={[{ label: '来源', href: 'https://example.com' }]} />
        <AiFileDiff file="article.html" rows={aiDiffRows('@@ -1 +1 @@\n-old\n+new')} />
        <AiCodeBlock language="html" code="<p>内容</p>"><pre><code>&lt;p&gt;内容&lt;/p&gt;</code></pre></AiCodeBlock>
        <AiDataTable><table><tbody><tr><td>数据</td></tr></tbody></table></AiDataTable>
        <AiTodoList live items={[{ step: '读取排版块', status: 'done' }, { step: '修改样式', status: 'in_progress' }]} />
        <AiInlineCitation href="https://example.com">参考来源</AiInlineCitation>
        <AiComparisonTable rows={[{ label: '新增行', value: '+2', tone: 'add' }]} />
        <AiImageGeneration status="success" title="图片已应用" detail="候选图已插入正文" />
      </>,
    )

    expect(html).toContain('aicss-thinking-reasoning is-thinking')
    expect(html).toContain('aicss-streaming-text is-active')
    expect(html).not.toContain('aicss-streaming-caret')
    expect(html).toContain('aicss-tool-call is-running')
    expect(html).toContain('aicss-tool-call-collapsible is-collapsed')
    expect(html).toContain('工具详情')
    expect(html).toContain('aicss-web-search is-running')
    expect(html).toContain('aicss-file-diff')
    expect(html).toContain('aicss-code-block')
    expect(html).toContain('aicss-data-table')
    expect(html).toContain('aicss-todo-list is-live')
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('aicss-todo-items')
    expect(html).toContain('aicss-todo-inner')
    expect(html).toContain('aria-label="任务步骤"')
    expect(html).toContain('aicss-todo-progress')
    expect(html).toContain('aicss-todo-state is-visible')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain('aicss-inline-citation')
    expect(html).toContain('aicss-comparison-table')
    expect(html).toContain('aicss-image-generation is-success')
    expect(html).toContain('aicss-code-block-file')
  })

  it('splits streamed reasoning into AICSS animated sentence rows', () => {
    const html = renderToStaticMarkup(
      <AiThinkingReasoning thinking content={'先读取文档。\n再检查所有排版块。'} />,
    )

    expect(html).toContain('aicss-thinking-reasoning-stream')
    expect(html).toContain('aicss-reasoning-sentence')
    expect(html).not.toContain('height:')
  })

  it('keeps completed reasoning collapsed until the user opens it', () => {
    const html = renderToStaticMarkup(
      <AiThinkingReasoning thinking={false} content="已完成的推理" duration="3 秒" />,
    )

    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-hidden="true"')
  })
})
