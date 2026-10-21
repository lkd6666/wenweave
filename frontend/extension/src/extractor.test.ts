// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createCaptureDraft, finalizeCaptureDraft } from './extractor'
import { MAX_CAPTURE_ASSETS } from './shared'

const articleUrl = 'https://mp.weixin.qq.com/s/test-article'

beforeEach(() => {
  document.head.innerHTML = '<title>页面标题</title>'
  document.body.innerHTML = ''
})

afterEach(() => vi.restoreAllMocks())

describe('WeChat layout capture extraction', () => {
  it('rewrites body and inline background images while deduplicating repeated sources', () => {
    document.body.innerHTML = `
      <h1 id="activity-name">采集标题</h1>
      <div id="js_content">
        <img data-src="https://mmbiz.qpic.cn/a/repeated.png">
        <img src="https://mmbiz.qpic.cn/a/repeated.png">
        <section style="background-image: url('https://mmbiz.qpic.cn/a/background.png')"><p>正文</p></section>
      </div>`

    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(draft.assets).toHaveLength(2)
    expect(capture.title).toBe('采集标题')
    expect(capture.activeAssetIds).toHaveLength(2)
    expect(capture.sourceHtml.match(/layout-capture:\/\//g)).toHaveLength(3)
    expect(capture.sourceHtml).not.toContain('mmbiz.qpic.cn')
  })

  it('removes failed images and all assets sharing a failed background declaration', () => {
    document.body.innerHTML = `
      <div id="js_content">
        <img src="https://mmbiz.qpic.cn/a/photo.png">
        <section style="background-image:url(https://mmbiz.qpic.cn/a/one.png),url(https://mmbiz.qpic.cn/a/two.png)">背景</section>
      </div>`

    const draft = createCaptureDraft(document, articleUrl)
    const backgroundAssets = draft.assets.filter((asset) => !asset.url.endsWith('/photo.png'))
    const capture = finalizeCaptureDraft(draft.draftId, [backgroundAssets[0]!.assetId])

    expect(capture.activeAssetIds).toHaveLength(1)
    expect(capture.omittedAssetCount).toBe(2)
    expect(capture.sourceHtml).toContain('layout-capture://')
    expect(capture.sourceHtml).not.toContain('background-image')
  })

  it('removes inaccessible image sources without blocking structure capture', () => {
    document.body.innerHTML = `
      <div id="js_content"><p>保留正文</p><img src="https://example.com/not-wechat.png"></div>`

    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(draft.assets).toEqual([])
    expect(capture.omittedAssetCount).toBe(1)
    expect(capture.sourceHtml).toContain('保留正文')
    expect(capture.sourceHtml).not.toContain('<img')
  })

  it('captures the article cover first and deduplicates it with a body image for link import', () => {
    document.head.innerHTML = '<meta property="og:image" content="https://mmbiz.qpic.cn/a/cover.png">'
    document.body.innerHTML = `
      <h1 id="activity-name">带封面的文章</h1>
      <div id="js_content"><p>正文</p><img src="https://mmbiz.qpic.cn/a/cover.png"></div>`

    const draft = createCaptureDraft(document, articleUrl, 'web_article_import')
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(draft.assets).toHaveLength(1)
    expect(draft.coverAssetId).toBe(draft.assets[0]?.assetId)
    expect(capture.coverAssetId).toBe(draft.coverAssetId)
    expect(capture.activeAssetIds).toEqual([draft.coverAssetId])
  })

  it('drops a failed cover without counting it as an omitted body image', () => {
    document.head.innerHTML = '<meta property="og:image" content="https://mmbiz.qpic.cn/a/cover-only.png">'
    document.body.innerHTML = '<div id="js_content"><p>正文</p></div>'

    const draft = createCaptureDraft(document, articleUrl, 'web_article_import')
    const capture = finalizeCaptureDraft(draft.draftId, [draft.coverAssetId!])

    expect(capture.coverAssetId).toBeNull()
    expect(capture.activeAssetIds).toEqual([])
    expect(capture.omittedAssetCount).toBe(0)
  })

  it('uses the WeChat msg_cdn_url script value when no cover element or metadata exists', () => {
    document.head.innerHTML = '<script>var msg_cdn_url = "https:\\/\\/mmbiz.qpic.cn\\/a\\/script-cover.png";</script>'
    document.body.innerHTML = '<div id="js_content"><p>正文</p></div>'

    const draft = createCaptureDraft(document, articleUrl, 'web_article_import')
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(draft.assets.map((asset) => asset.url)).toEqual(['https://mmbiz.qpic.cn/a/script-cover.png'])
    expect(capture.coverAssetId).toBe(draft.assets[0]?.assetId)
  })

  it('inlines authored class styles without reading computed layout', () => {
    document.head.innerHTML = '<style>.captured-card { color: rgb(12, 34, 56); text-align: center; font-weight: 700; }</style>'
    document.body.innerHTML = '<div id="js_content"><section class="captured-card">保留样式</section></div>'

    const computedStyle = vi.spyOn(window, 'getComputedStyle')
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(capture.sourceHtml).toContain('color: rgb(12, 34, 56)')
    expect(capture.sourceHtml).toContain('text-align: center')
    expect(capture.sourceHtml).toContain('font-weight: 700')
    expect(computedStyle).not.toHaveBeenCalled()
  })

  it('keeps percentages, CSS variables and author colors when the page uses dark media rules', () => {
    document.head.innerHTML = `<style>
      #js_content { --accent: #345678; }
      .card { width: 32%; color: var(--accent); display: flex; }
      @media (prefers-color-scheme: light) { .card { background-color: rgb(255, 255, 255); } }
      @media (prefers-color-scheme: dark) { .card { background-color: rgb(20, 20, 20); color: white !important; } }
    </style>`
    document.body.innerHTML = '<div id="js_content" style="opacity:0.6"><section class="card">正文</section></div>'
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])
    const parsed = new DOMParser().parseFromString(capture.sourceHtml, 'text/html')
    const card = parsed.querySelector<HTMLElement>('.card')!
    expect(card.style.width).toBe('32%')
    expect(card.style.color).toBe('var(--accent)')
    expect(card.style.backgroundColor).toBe('rgb(255, 255, 255)')
    expect(parsed.querySelector<HTMLElement>('#js_content')!.style.getPropertyValue('--accent')).toBe('#345678')
    expect(parsed.querySelector<HTMLElement>('#js_content')!.style.opacity).toBe('0.6')
  })

  it('respects specificity, inline declarations and stylesheet importance for arbitrary selectors', () => {
    document.head.innerHTML = `<style>
      #js_content .card { color: red; width: 75%; }
      :where(#js_content) .card { color: blue; width: 90%; }
      .card { text-align: right !important; color: green; }
    </style>`
    document.body.innerHTML = '<div id="js_content"><section class="card" style="width:32%;text-align:left">正文</section></div>'
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])
    const parsed = new DOMParser().parseFromString(capture.sourceHtml, 'text/html')
    const card = parsed.querySelector<HTMLElement>('.card')!
    expect(card.style.color).toBe('red')
    expect(card.style.width).toBe('32%')
    expect(card.style.textAlign).toBe('right')
    expect(card.style.getPropertyPriority('text-align')).toBe('important')
  })

  it('retains generated author content and its styles', () => {
    document.head.innerHTML = '<style>.quote::before { content:"“"; color: red; display: inline-block; }</style>'
    document.body.innerHTML = '<div id="js_content"><p class="quote">正文</p></div>'
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])
    expect(capture.sourceHtml).toContain('data-layout-capture-generated="before"')
    expect(capture.sourceHtml).toContain('“')
    expect(capture.sourceHtml).toContain('color: red')
  })

  it('localizes SVG pictures and every authored CSS image declaration while retaining fragment references', () => {
    document.body.innerHTML = `<div id="js_content">
      <svg viewBox="0 0 10 10"><defs><filter id="blur" /></defs><image xlink:href="https://mmbiz.qpic.cn/a/vector.png" width="10" height="10"/><path style="filter:url(#blur)" d="M0 0L10 10"/></svg>
      <p style="mask-image:url(https://mmbiz.qpic.cn/a/mask.png);border-image-source:url(https://mmbiz.qpic.cn/a/border.png)">正文</p>
    </div>`
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])
    expect(draft.assets).toHaveLength(3)
    expect(capture.sourceHtml).toContain('<image')
    expect(capture.sourceHtml).toContain('href="layout-capture://')
    expect(capture.sourceHtml).toContain('url(#blur)')
    expect(capture.sourceHtml).not.toContain('mmbiz.qpic.cn')
  })

  it('keeps embedded raster images as downloadable assets', () => {
    const source = 'data:image/png;base64,iVBORw0KGgo='
    document.body.innerHTML = `<div id="js_content"><img src="${source}"></div>`
    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])
    expect(draft.assets[0]?.url).toBe(source)
    expect(capture.omittedAssetCount).toBe(0)
    expect(capture.sourceHtml).toContain('layout-capture://')
  })

  it('keeps all assets from image-heavy articles below the expanded safe limit', () => {
    const imageCount = 81
    document.body.innerHTML = `<div id="js_content">${Array.from(
      { length: imageCount },
      (_, index) => `<img data-src="https://mmbiz.qpic.cn/a/image-${index}.png">`,
    ).join('')}</div>`

    const draft = createCaptureDraft(document, articleUrl)
    const capture = finalizeCaptureDraft(draft.draftId, [])

    expect(imageCount).toBeLessThanOrEqual(MAX_CAPTURE_ASSETS)
    expect(draft.assets).toHaveLength(imageCount)
    expect(capture.activeAssetIds).toHaveLength(imageCount)
    expect(capture.omittedAssetCount).toBe(0)
  })
})
