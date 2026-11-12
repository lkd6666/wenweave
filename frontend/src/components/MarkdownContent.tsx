import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkCjkFriendly from 'remark-cjk-friendly/parseOnly'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import CodeBlock from './CodeBlock'
import { AiDataTable, AiTextResponse } from './AiOutput'

interface MarkdownContentProps {
  content: string
  streaming?: boolean
}

const CODE_TOKEN_PATTERN = /```[\s\S]*?```|`[^`\n]*`/g
const EXPLICIT_DISPLAY_MATH_PATTERN = /\\\[([\s\S]*?)\\\]/g
const EXPLICIT_INLINE_MATH_PATTERN = /\\\(([^\n]*?)\\\)/g
const STANDALONE_BRACKET_PATTERN = /(^|\n)([\t ]*)\[([^\]\n]+)\]([\t ]*)(?=\n|$)/g
const PARENTHESISED_EXPRESSION_PATTERN = /\(([^()\n]+)\)/g
const MATH_SIGNAL_PATTERN = /\\[a-zA-Z]+|[A-Za-z]\s*[_^]\s*(?:\{[^}\n]+\}|[A-Za-z0-9]+)/

function isLikelyMath(expression: string): boolean {
  return MATH_SIGNAL_PATTERN.test(expression)
}

/**
 * The Agent is instructed to use `$` delimiters, but older replies often
 * contain `\(...\)` or a standalone `[ ... ]` equation. Convert only
 * recognizable LaTex-like forms and keep code samples literal.
 */
export function normalizeMathMarkdown(content: string): string {
  const codeTokens: string[] = []
  const protectedContent = content.replace(CODE_TOKEN_PATTERN, (match) => {
    const token = `@@YIBAN_CODE_${codeTokens.length}@@`
    codeTokens.push(match)
    return token
  })
  const normalized = protectedContent
    .replace(EXPLICIT_DISPLAY_MATH_PATTERN, (_match, expression: string) => `$$\n${expression.trim()}\n$$`)
    .replace(EXPLICIT_INLINE_MATH_PATTERN, (_match, expression: string) => `$${expression.trim()}$`)
    .replace(STANDALONE_BRACKET_PATTERN, (match, prefix: string, indent: string, expression: string) => (
      isLikelyMath(expression) ? `${prefix}${indent}$$\n${expression.trim()}\n$$` : match
    ))
    .replace(PARENTHESISED_EXPRESSION_PATTERN, (match, expression: string) => (
      isLikelyMath(expression) ? `$${expression.trim()}$` : match
    ))
  return normalized.replace(/@@YIBAN_CODE_(\d+)@@/g, (_match, index: string) => codeTokens[Number(index)] ?? '')
}

function markdownCode(highlight: boolean): NonNullable<Components['code']> {
  return function MarkdownCode({ className, children, ...props }) {
    const code = String(children).replace(/\n$/, '')
    const language = /language-([\w+-]+)/.exec(className ?? '')?.[1]
    const isBlock = Boolean(language) || code.includes('\n')
    if (isBlock) {
      return <CodeBlock code={code} language={language} showLineNumbers={code.includes('\n')} highlight={highlight} />
    }
    return <code className={className} {...props}>{children}</code>
  }
}

const markdownComponents: Components = {
  pre: ({ children }) => <>{children}</>,
  table: ({ children, ...props }) => (
    <AiDataTable><table {...props}>{children}</table></AiDataTable>
  ),
  code: markdownCode(true),
}
const streamingMarkdownComponents: Components = { ...markdownComponents, code: markdownCode(false) }

/** AI 消息使用安全的 Markdown 子集渲染；不启用 raw HTML。 */
export default function MarkdownContent({ content, streaming = false }: MarkdownContentProps) {
  return (
    <AiTextResponse><div className="markdown-content">
      <ReactMarkdown
        // Support CJK punctuation at either emphasis boundary: 前文**“说明”** and **句末。**后文.
        remarkPlugins={[remarkGfm, remarkCjkFriendly, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={streaming ? streamingMarkdownComponents : markdownComponents}
      >
        {normalizeMathMarkdown(content)}
      </ReactMarkdown>
    </div></AiTextResponse>
  )
}
