import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface CodeBlockProps {
  code: string
  language?: string
  showLineNumbers?: boolean
  className?: string
}

/** 统一渲染 Agent 输出中的 HTML、JSON 和 diff 代码，避免工具面板使用裸文本。 */
export default function CodeBlock({ code, language = 'text', showLineNumbers = false, className }: CodeBlockProps) {
  return (
    <SyntaxHighlighter
      className={className}
      language={language}
      style={oneLight}
      showLineNumbers={showLineNumbers}
      wrapLongLines
      customStyle={{ margin: 0, borderRadius: 4, fontSize: 12, lineHeight: 1.55 }}
    >
      {code}
    </SyntaxHighlighter>
  )
}
