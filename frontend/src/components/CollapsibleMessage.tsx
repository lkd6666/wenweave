import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from 'antd'
import { DownOutlined, UpOutlined } from '@ant-design/icons'

export const COLLAPSED_MESSAGE_HEIGHT = 240

export default function CollapsibleMessage({ children }: { children: ReactNode }) {
  const contentId = useId()
  const contentRef = useRef<HTMLDivElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const collapsed = overflowing && !expanded

  useLayoutEffect(() => {
    const content = contentRef.current
    if (!content) return
    const measure = () => setOverflowing(content.scrollHeight > COLLAPSED_MESSAGE_HEIGHT + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(content)
    return () => observer.disconnect()
  }, [children])

  return (
    <div className={`collapsible-message${collapsed ? ' is-collapsed' : ''}`}>
      <div
        id={contentId}
        className="collapsible-message-viewport"
        style={collapsed ? { maxHeight: COLLAPSED_MESSAGE_HEIGHT } : undefined}
      >
        <div ref={contentRef} className="collapsible-message-content">{children}</div>
      </div>
      {overflowing && (
        <Button
          className="collapsible-message-toggle"
          type="text"
          size="small"
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={() => {
            const content = contentRef.current
            if (expanded && content && content.getBoundingClientRect().top < 0) {
              content.scrollIntoView({ block: 'start' })
            }
            setExpanded(!expanded)
          }}
        >
          {expanded ? '收起' : '展开全文'}
        </Button>
      )}
    </div>
  )
}
