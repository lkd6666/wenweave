import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

export interface SyntaxHighlightedCodeProps {
  code: string
  language: string
  showLineNumbers: boolean
  className?: string
}

export default function SyntaxHighlightedCode({
  code,
  language,
  showLineNumbers,
  className,
}: SyntaxHighlightedCodeProps) {
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
