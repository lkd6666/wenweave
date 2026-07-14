import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from './CodeBlock'

interface MarkdownContentProps {
  content: string
}

const markdownComponents: Components = {
  pre: ({ children }) => <>{children}</>,
  table: ({ children, ...props }) => (
    <div className="markdown-table-scroll">
      <table {...props}>{children}</table>
    </div>
  ),
  code: ({ className, children, ...props }) => {
    const code = String(children).replace(/\n$/, '')
    const language = /language-([\w+-]+)/.exec(className ?? '')?.[1]
    const isBlock = Boolean(language) || code.includes('\n')
    if (isBlock) {
      return <CodeBlock code={code} language={language} showLineNumbers={code.split('\n').length > 1} />
    }
    return <code className={className} {...props}>{children}</code>
  },
}

/** AI 消息使用安全的 Markdown 子集渲染；不启用 raw HTML。 */
export default function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{content}</ReactMarkdown>
    </div>
  )
}
