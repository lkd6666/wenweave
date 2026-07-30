import { unified } from 'unified'
import rehypeSanitize from 'rehype-sanitize'
import rehypeStringify from 'rehype-stringify'
import remarkGfm from 'remark-gfm'
import remarkParse from 'remark-parse'
import remarkRehype from 'remark-rehype'
import type { ImportParseProgress, ParsedImport } from './types'

const emptyMarkdownHtml = '<p>（Markdown 未提取到正文内容）</p>'

export async function markdownToSafeHtml(markdown: string): Promise<string> {
  const result = await unified()
    .use(remarkParse)
    .use(remarkGfm)
    // Do not pass raw HTML nodes from the source Markdown into the editor.
    .use(remarkRehype)
    .use(rehypeSanitize)
    .use(rehypeStringify)
    .process(markdown)
  return String(result).trim() || emptyMarkdownHtml
}

export async function parseMarkdownFile(
  file: File,
  onProgress: (progress: ImportParseProgress) => void,
  signal?: AbortSignal,
): Promise<ParsedImport> {
  onProgress({ stage: 'reading', percent: 2, detail: '正在读取 Markdown 原文件…' })
  const buffer = await file.arrayBuffer()
  if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')

  let markdown: string
  try {
    markdown = new TextDecoder('utf-8', { fatal: true }).decode(buffer)
  } catch {
    throw new Error('Markdown 文件必须是 UTF-8 编码')
  }
  if (markdown.includes('\0')) throw new Error('Markdown 文件不能包含 NUL 字符')

  onProgress({ stage: 'parsing', percent: 45, detail: '正在转换 Markdown 排版…' })
  const html = await markdownToSafeHtml(markdown)
  if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')
  onProgress({ stage: 'extracting', percent: 92, detail: 'Markdown 解析完成，正在准备上传…' })
  return { html, assets: [] }
}
