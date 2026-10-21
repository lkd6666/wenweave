import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ToolExecution } from '../types'
import ToolResultView from './ToolResultView'

function tool(overrides: Partial<ToolExecution> = {}): ToolExecution {
  return {
    id: 'tool-1', name: 'search_html', arguments: {}, status: 'success', html_changed: false,
    ...overrides,
  }
}

describe('ToolResultView', () => {
  it('renders source range metadata separately from literal HTML', () => {
    const item = tool({ name: 'read_file', model_input: { state: 'available', content: JSON.stringify({
      path: '/article.html', revision: 'hidden-revision', start: 12, end: 38, start_line: 2, end_line: 3,
      content: '<p>中文🙂</p>\r\n<p>保留</p>', complete: false, next_cursor: 38,
    }) } })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)
    expect(html).toContain('/article.html')
    expect(html).toContain('起始字符')
    expect(html).toContain('起始行')
    expect(html).toContain('&lt;p&gt;中文🙂&lt;/p&gt;\r\n')
    expect(html).not.toContain('hidden-revision')
    expect(html).not.toContain('<p>中文🙂</p>')
  })

  it('renders structured search results as readable rows without a JSON block', () => {
    const item = tool({
      model_input: {
        state: 'available',
        content: JSON.stringify({ match_count: 1, results: [{ text: '完整的章节标题', path: 'section:nth-of-type(1) > section:nth-of-type(2)', tag: 'section' }] }),
      },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)

    expect(html).toContain('完整的章节标题')
    expect(html).toContain('section:nth-of-type(1)')
    expect(html).toContain('匹配数')
    expect(html).not.toContain('模型收到的内容')
    expect(html).not.toContain('&quot;results&quot;')
  })

  it('uses activity targets when a long result was truncated for the model', () => {
    const item = tool({
      model_input: { state: 'available', truncated: true, content: JSON.stringify({ truncated: true, preview: { head: '{"results":[', tail: '}' }, output_id: 'secret-id' }) },
      activity: { kind: 'search', summary: '找到 1 个结果', targets: [{ text: '候选块', path: 'section > p' }] },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)

    expect(html).toContain('候选块')
    expect(html).toContain('结果较长')
    expect(html).not.toContain('secret-id')
    expect(html).not.toContain('preview')
  })

  it('keeps edited block details beside structured validation results', () => {
    const item = tool({
      name: 'apply_html_patch',
      model_input: { state: 'available', content: JSON.stringify({ ok: true, validation: { valid: true } }) },
      activity: { kind: 'edit', summary: '已更新 1 个排版块', targets: [{ path: 'section > p', before: '旧文案', after: '新文案' }] },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)

    expect(html).toContain('目标块')
    expect(html).toContain('旧文案')
    expect(html).toContain('新文案')
    expect(html).toContain('结构检查')
  })

  it('keeps image galleries free of repeated image metadata', () => {
    const item = tool({
      name: 'view_article_images',
      model_input: { state: 'available', content: JSON.stringify({ count: 1, items: [{ title: '首图', preview_url: 'https://example.com/a.png' }] }) },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery />)

    expect(html).toContain('count')
    expect(html).not.toContain('https://example.com/a.png')
    expect(html).not.toContain('首图')
  })

  it('shows a useful summary for older tools without a saved model result', () => {
    const item = tool({ activity: { kind: 'map', summary: '已加载 88 个排版块' } })
    expect(renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)).toContain('已加载 88 个排版块')
  })

  it('explains dimensions-only reads and labels image delivery metadata in Chinese', () => {
    const item = tool({
      name: 'view_article_images',
      model_input: { state: 'available', content: JSON.stringify({
        vision_supported: true, include_image_requested: false, image_content_included: false,
        requested_count: 3, viewed_count: 0,
        notice: '本次调用选择仅读取尺寸，未请求图片画面',
        items: [{ label: '文章图片 2', width: 3600, height: 1500 }],
      }) },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)

    expect(html).toContain('模型支持看图')
    expect(html).toContain('请求图片画面')
    expect(html).toContain('已提供图片画面')
    expect(html).toContain('本次调用选择仅读取尺寸，未请求图片画面')
    expect(html).toContain('3,600')
    expect(html).not.toContain('image content included')
  })

  it('summarizes incomplete paged output instead of displaying its raw JSON fragment', () => {
    const item = tool({
      name: 'read_tool_output',
      model_input: { state: 'available', content: JSON.stringify({ output_id: 'hidden-id', content: '{"blocks":[{"text":"片段', remaining_bytes: 400 }) },
    })
    const html = renderToStaticMarkup(<ToolResultView tool={item} hasImageGallery={false} />)

    expect(html).toContain('结果片段')
    expect(html).not.toContain('hidden-id')
    expect(html).not.toContain('blocks')
  })
})
