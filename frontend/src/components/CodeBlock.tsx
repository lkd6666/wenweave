import { lazy, memo, Suspense } from 'react'
import type { SyntaxHighlightedCodeProps } from './SyntaxHighlightedCode'
import { AiCodeBlock } from './AiOutput'

const SyntaxHighlightedCode = lazy(() => import('./SyntaxHighlightedCode'))
// Prism expands source into many token nodes. Keep large and growing blocks
// as complete plain text rather than rebuilding that tree on every delta.
const MAX_HIGHLIGHT_CHARACTERS = 20_000

interface CodeBlockProps extends Omit<SyntaxHighlightedCodeProps, 'language' | 'showLineNumbers'> {
  language?: string
  showLineNumbers?: boolean
  highlight?: boolean
}

/** Agent code remains fully readable and copyable, even without token colors. */
export default memo(function CodeBlock({ code, language = 'text', showLineNumbers = false, className, highlight = true }: CodeBlockProps) {
  const plainCode = <pre className={className} style={{ margin: 0, padding: '1em', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><code>{code}</code></pre>
  return (
    <AiCodeBlock language={language} code={code}>
      {highlight && code.length <= MAX_HIGHLIGHT_CHARACTERS ? <Suspense fallback={plainCode}>
        <SyntaxHighlightedCode
          code={code}
          language={language}
          showLineNumbers={showLineNumbers}
          className={className}
        />
      </Suspense> : plainCode}
    </AiCodeBlock>
  )
})
