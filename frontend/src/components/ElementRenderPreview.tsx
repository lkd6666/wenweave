import { useEffect, useMemo, useState } from 'react'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

interface ElementRenderPreviewProps {
  html: string
}

function extractImagePreview(html: string): { src: string; alt: string } | null {
  const document = new DOMParser().parseFromString(html, 'text/html')
  const element = document.body.firstElementChild
  if (!element || document.body.children.length !== 1 || element.tagName !== 'IMG') return null
  return {
    src: element.getAttribute('src') ?? '',
    alt: element.getAttribute('alt') ?? '',
  }
}

/** 在 sandbox iframe 中渲染已引用元素，避免预览 HTML 影响应用页面。 */
export default function ElementRenderPreview({ html }: ElementRenderPreviewProps) {
  const imagePreview = useMemo(() => extractImagePreview(html), [html])
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => setImageFailed(false), [imagePreview?.src])

  if (imagePreview) {
    return (
      <div className="element-image-preview">
        {imagePreview.src && !imageFailed ? (
          <img src={imagePreview.src} alt={imagePreview.alt} onError={() => setImageFailed(true)} />
        ) : (
          <span>图片无法预览</span>
        )}
      </div>
    )
  }

  const srcDoc = frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff}body{padding:12px;font:14px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#111;word-break:break-word}img,video,table{max-width:100%;height:auto}*{box-sizing:border-box}</style></head><body>${html}</body></html>`)
  return <iframe title="元素渲染预览" className="element-render-preview" sandbox={SANDBOX_ALLOW_NEW_WINDOW} srcDoc={srcDoc} />
}
