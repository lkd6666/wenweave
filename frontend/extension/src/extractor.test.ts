// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createCaptureDraft, finalizeCaptureDraft } from './extractor'

const articleUrl = 'https://mp.weixin.qq.com/s/test-article'

beforeEach(() => {
  document.head.innerHTML = '<title>页面标题</title>'
  document.body.innerHTML = ''
})

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
})
