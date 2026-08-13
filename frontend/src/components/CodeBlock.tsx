import { lazy, Suspense } from 'react'
import type { SyntaxHighlightedCodeProps } from './SyntaxHighlightedCode'
import { AiCodeBlock } from './AiOutput'

const SyntaxHighlightedCode = lazy(() => import('./SyntaxHighlightedCode'))

interface CodeBlockProps extends Omit<SyntaxHighlightedCodeProps, 'language' | 'showLineNumbers'> {
  language?: string
  showLineNumbers?: boolean
}

/** 统一渲染 Agent 输出中的 HTML、JSON 和 diff 代码，避免工具面板使用裸文本。 */
export default function CodeBlock({ code, language = 'text', showLineNumbers = false, className }: CodeBlockProps) {
  return (
    <AiCodeBlock language={language} code={code}>
      <Suspense fallback={<pre className={className}><code>{code}</code></pre>}>
        <SyntaxHighlightedCode
          code={code}
          language={language}
          showLineNumbers={showLineNumbers}
          className={className}
        />
      </Suspense>
    </AiCodeBlock>
  )
}
