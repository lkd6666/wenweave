import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Spin } from 'antd'
import { ClockCircleOutlined, CloudServerOutlined, FileUnknownOutlined } from '@ant-design/icons'
import { useParams } from 'react-router'
import { publicSharesApi, PublicShareError, type PublicDocumentShare } from '../api/publicShares'
import { frameDocumentWithNewWindowLinks, SANDBOX_ALLOW_NEW_WINDOW } from '../utils/frameLinks'

const POLL_INTERVAL_MS = 15_000
const ASSET_REFRESH_MARGIN_MS = 30_000

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
      ? `<figure class="share-cover"><img src="${escapeHtml(share.cover_url)}" alt="${title} 封面" referrerpolicy="no-referrer"></figure>`
      : ''
    const body = share?.html ?? ''
    return frameDocumentWithNewWindowLinks(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><style>html,body{margin:0;min-height:100%;background:#fff;scrollbar-width:none;-ms-overflow-style:none}html::-webkit-scrollbar,body::-webkit-scrollbar{display:none}body{overflow-wrap:anywhere;font:15px/2 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#171717}.share-header{padding:18px 20px 14px;background:#f4f6f8}.share-header h1{margin:0;color:#15191d;font-size:22px;font-weight:650;line-height:1.35}.share-header time{display:block;margin-top:5px;color:#687480;font-size:12px;line-height:1.5}.share-cover{margin:0;padding:0 20px 14px;background:#fff}.share-cover img{display:block;width:100%;max-height:min(36dvh,360px);object-fit:contain;background:#fff}.share-content{box-sizing:border-box;min-height:100%;padding:18px 14px 36px;border-top:1px solid #dfe4e8}img,video,table{max-width:100%;height:auto}table{display:block;overflow-x:auto}a{color:#1677ff}@media (max-width:720px){.share-header{padding:14px 16px 10px}.share-header h1{font-size:19px}.share-cover{padding:0 16px 10px}.share-cover img{max-height:min(32dvh,260px)}}</style></head><body><header class="share-header"><h1>${title}</h1><time>链接有效至 ${expiry}</time></header>${cover}<article class="share-content">${body}</article></body></html>`)
  }, [share?.cover_url, share?.expires_at, share?.html, share?.title])

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
