import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Spin } from 'antd'
import { ClockCircleOutlined, CloudServerOutlined, FileUnknownOutlined } from '@ant-design/icons'
import { useParams } from 'react-router'
import { publicSharesApi, PublicShareError, type PublicDocumentShare } from '../api/publicShares'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

const POLL_INTERVAL_MS = 15_000
const ASSET_REFRESH_MARGIN_MS = 30_000

interface CoverCrop {
  x: number
  y: number
  width: number
  height: number
}

type PublicShareErrorKind = 'expired' | 'missing' | 'unavailable'

interface PublicShareLoadError {
  kind: PublicShareErrorKind
  message: string
}

function formatExpiry(value: string): string {
  return new Date(value).toLocaleString()
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] ?? character)
}

function parseCoverCrop(value: string): CoverCrop | null {
  const [x1, y1, x2, y2] = value.split('_').map(Number)
  if (![x1, y1, x2, y2].every(Number.isFinite) || x1 < 0 || y1 < 0 || x2 > 1 || y2 > 1 || x1 >= x2 || y1 >= y2) {
    return null
  }
  return {
    x: x1 * 100,
    y: y1 * 100,
    width: (x2 - x1) * 100,
    height: (y2 - y1) * 100,
  }
}

function coverCropMarkup(source: string, title: string, crop: CoverCrop | null, aspect: number, label: string): string {
  const imageStyle = crop
    ? `width:${10000 / crop.width}%;max-width:none;transform:translate(${-crop.x}%,${-crop.y}%);transform-origin:top left;`
    : ''
  const imageClass = crop ? ' is-cropped' : ''
  return `<figure class="share-cover"><div class="share-cover-frame" style="aspect-ratio:${aspect}"><img class="${imageClass.trim()}" src="${escapeHtml(source)}" alt="${title} ${label} 封面" referrerpolicy="no-referrer" style="${imageStyle}"></div><figcaption>${label}</figcaption></figure>`
}

export default function PublicSharePage() {
  const { token = '' } = useParams()
  const [share, setShare] = useState<PublicDocumentShare | null>(null)
  const [error, setError] = useState<PublicShareLoadError | null>(null)
  const [loading, setLoading] = useState(true)
  const revisionRef = useRef('')
  const assetRefreshAtRef = useRef(0)
  const refreshInFlightRef = useRef(false)

  const loadContent = useCallback(async () => {
    if (!token || refreshInFlightRef.current) return
    refreshInFlightRef.current = true
    try {
      const next = await publicSharesApi.get(token)
      revisionRef.current = next.revision
      assetRefreshAtRef.current = new Date(next.asset_refresh_at).getTime()
      setShare(next)
      setError(null)
      document.title = next.title
    } catch (err) {
      if (err instanceof PublicShareError && err.status === 410) setError({ kind: 'expired', message: '此分享链接已失效' })
      else if (err instanceof PublicShareError && err.status === 404) setError({ kind: 'missing', message: '分享链接不存在' })
      else setError({ kind: 'unavailable', message: '暂时无法加载分享内容' })
    } finally {
      refreshInFlightRef.current = false
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    setLoading(true)
    revisionRef.current = ''
    assetRefreshAtRef.current = 0
    void loadContent()
  }, [loadContent])

  useEffect(() => {
    const robots = document.querySelector('meta[name="robots"]') ?? document.head.appendChild(document.createElement('meta'))
    const previousName = robots.getAttribute('name')
    const previousContent = robots.getAttribute('content')
    robots.setAttribute('name', 'robots')
    robots.setAttribute('content', 'noindex,nofollow,nosnippet')
    return () => {
      if (previousName === null) robots.removeAttribute('name')
      else robots.setAttribute('name', previousName)
      if (previousContent === null) robots.removeAttribute('content')
      else robots.setAttribute('content', previousContent)
    }
  }, [])

  useEffect(() => {
    const root = document.documentElement
    const body = document.body
    root.classList.add('public-share-root')
    body.classList.add('public-share-body')
    return () => {
      root.classList.remove('public-share-root')
      body.classList.remove('public-share-body')
    }
  }, [])

  useEffect(() => {
    if (!token || error) return
    let disposed = false
    const checkForChanges = async () => {
      if (disposed || document.visibilityState !== 'visible' || refreshInFlightRef.current) return
      try {
        const latest = await publicSharesApi.revision(token)
        const needsContent = latest.revision !== revisionRef.current
          || Date.now() >= assetRefreshAtRef.current - ASSET_REFRESH_MARGIN_MS
        if (needsContent) await loadContent()
      } catch (err) {
        if (disposed) return
        if (err instanceof PublicShareError && (err.status === 404 || err.status === 410)) {
          setError(
            err.status === 410
              ? { kind: 'expired', message: '此分享链接已失效' }
              : { kind: 'missing', message: '分享链接不存在' },
          )
        }
      }
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void checkForChanges()
    }
    const timer = window.setInterval(() => void checkForChanges(), POLL_INTERVAL_MS)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      disposed = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [error, loadContent, token])

  const srcDoc = useMemo(() => {
    const title = escapeHtml(share?.title ?? '')
    const expiry = escapeHtml(share ? formatExpiry(share.expires_at) : '')
    const cover = share?.cover_url
      ? `<section class="share-covers" aria-label="文章封面">${coverCropMarkup(share.cover_url, title, parseCoverCrop(share.cover_crop_235_1), 2.35, '2.35 : 1')}${coverCropMarkup(share.cover_url, title, parseCoverCrop(share.cover_crop_1_1), 1, '1 : 1')}</section>`
      : ''
    const body = share?.html ?? ''
    return frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><style>html,body{margin:0;min-height:100%;background:#fff;scrollbar-width:none;-ms-overflow-style:none}html::-webkit-scrollbar,body::-webkit-scrollbar{display:none}body{overflow-wrap:anywhere;font:15px/2 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#171717}.share-header{padding:18px 20px 14px;background:#f4f6f8}.share-header h1{margin:0;color:#15191d;font-size:22px;font-weight:650;line-height:1.35}.share-header time{display:block;margin-top:5px;color:#687480;font-size:12px;line-height:1.5}.share-covers{display:grid;grid-template-columns:minmax(0,2.35fr) minmax(92px,1fr);gap:12px;padding:0 20px 14px;background:#fff}.share-cover{min-width:0;margin:0}.share-cover-frame{position:relative;overflow:hidden;background:#eef1f4}.share-cover-frame img{display:block;width:100%;height:100%;object-fit:cover}.share-cover-frame img.is-cropped{max-width:none;height:auto;object-fit:initial}.share-cover figcaption{margin-top:5px;color:#7a8591;font-size:11px;line-height:1.4}.share-content{box-sizing:border-box;min-height:100%;padding:18px 14px 36px;border-top:1px solid #dfe4e8}img,video,table{max-width:100%;height:auto}table{display:block;overflow-x:auto}a{color:#1677ff}@media (max-width:720px){.share-header{padding:14px 16px 10px}.share-header h1{font-size:19px}.share-covers{gap:8px;padding:0 16px 10px}.share-cover figcaption{margin-top:4px;font-size:10px}}</style></head><body><header class="share-header"><h1>${title}</h1><time>链接有效至 ${expiry}</time></header>${cover}<article class="share-content">${body}</article></body></html>`)
  }, [share?.cover_crop_1_1, share?.cover_crop_235_1, share?.cover_url, share?.expires_at, share?.html, share?.title])

  if (loading) {
    return <main className="public-share-status"><Spin size="large" /></main>
  }
  if (error || !share) {
    const status = error ?? { kind: 'unavailable' as const, message: '分享内容不可用' }
    const content = status.kind === 'expired'
      ? {
          Icon: ClockCircleOutlined,
          title: status.message,
          description: '该链接可能已到期、被分享者停用，或原文档已删除。',
        }
      : status.kind === 'missing'
        ? {
            Icon: FileUnknownOutlined,
            title: status.message,
            description: '请确认链接是否完整，或向分享人重新获取链接。',
          }
        : {
            Icon: CloudServerOutlined,
            title: status.message,
            description: '服务暂时无法响应，请稍后刷新页面重试。',
          }
    return (
      <main className={`public-share-status public-share-status--${status.kind}`}>
        <section className="public-share-status-content" aria-live="polite">
          <content.Icon className="public-share-status-icon" aria-hidden="true" />
          <h1>{content.title}</h1>
          <p>{content.description}</p>
        </section>
      </main>
    )
  }

  return (
    <main className="public-share-page">
      <iframe
        title={share.title}
        className="public-share-frame"
        sandbox={SANDBOX_ALLOW_NEW_WINDOW}
        referrerPolicy="no-referrer"
        srcDoc={srcDoc}
      />
    </main>
  )
}
