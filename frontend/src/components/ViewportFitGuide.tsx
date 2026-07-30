import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert } from 'antd'
import { useLocation } from 'react-router'
import { evaluateViewportFit, type ViewportFitIssue } from '../utils/viewportFit'

function issueCopy(issue: Exclude<ViewportFitIssue, null>) {
  if (issue === 'desktop-compact-layout') {
    return {
      message: '当前浏览器显示空间已进入紧凑布局',
      description: '建议按 Ctrl/Cmd + - 缩小浏览器显示比例，或扩大浏览器窗口；恢复桌面布局后自动隐藏。',
    }
  }

  if (issue === 'editor-toolbar-wrapped') {
    return {
      message: '工作台显示空间不足',
      description: '建议按 Ctrl/Cmd + - 缩小浏览器显示比例；工具栏恢复为舒适布局后，此提示会自动消失。',
    }
  }

  return {
    message: '当前页面显示空间不足',
    description: '建议按 Ctrl/Cmd + - 缩小浏览器显示比例；页面恢复正常布局后，此提示会自动消失。',
  }
}

export default function ViewportFitGuide() {
  const location = useLocation()
  const [issue, setIssue] = useState<ViewportFitIssue>(null)
  const [dismissedKey, setDismissedKey] = useState<string | null>(null)
  const frameRef = useRef<number | null>(null)

  const issueKey = issue ? `${location.pathname}:${issue}` : null
  const copy = useMemo(() => issue ? issueCopy(issue) : null, [issue])

  const measure = useCallback(() => {
    const root = document.documentElement
    const layout = document.querySelector<HTMLElement>('.app-layout')
    const toolbar = document.querySelector<HTMLElement>('.editor-toolbar')
    const nextIssue = evaluateViewportFit({
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      maxTouchPoints: navigator.maxTouchPoints,
      viewportWidth: root.clientWidth,
      // Ant Design tooltips/dropdowns are rendered into body portals. Their
      // temporary off-screen positioning must not be treated as application
      // overflow or trigger a global warning and layout shift.
      documentWidth: Math.max(root.clientWidth, layout?.scrollWidth ?? root.clientWidth),
      editorToolbarHeight: toolbar?.getBoundingClientRect().height,
    })
    setIssue((current) => current === nextIssue ? current : nextIssue)
    if (!nextIssue) setDismissedKey(null)
  }, [])

  const scheduleMeasure = useCallback(() => {
    if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current)
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = null
      measure()
    })
  }, [measure])

  useEffect(() => {
    setDismissedKey(null)
    scheduleMeasure()

    const content = document.querySelector<HTMLElement>('.app-content')
    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(scheduleMeasure)
    resizeObserver?.observe(document.documentElement)
    if (content) resizeObserver?.observe(content)

    const mutationObserver = new MutationObserver(scheduleMeasure)
    mutationObserver.observe(content ?? document.body, { childList: true, subtree: true })
    window.addEventListener('resize', scheduleMeasure)
    window.visualViewport?.addEventListener('resize', scheduleMeasure)

    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current)
      resizeObserver?.disconnect()
      mutationObserver.disconnect()
      window.removeEventListener('resize', scheduleMeasure)
      window.visualViewport?.removeEventListener('resize', scheduleMeasure)
    }
  }, [location.pathname, scheduleMeasure])

  if (!issue || !copy || dismissedKey === issueKey) return null

  return (
    <div className="viewport-fit-guide" role="status" aria-live="polite">
      <Alert
        type="warning"
        showIcon
        closable
        message={copy.message}
        description={copy.description}
        onClose={() => setDismissedKey(issueKey)}
      />
    </div>
  )
}
