// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { originalArticleDocument, readOriginalArticleDocument } from './articleSource'

const articleUrl = 'https://mp.weixin.qq.com/s/article'

beforeEach(() => {
  const settings = (window as unknown as {
    happyDOM: { settings: { disableCSSFileLoading: boolean; handleDisabledFileLoadingAsSuccess: boolean } }
  }).happyDOM.settings
  settings.disableCSSFileLoading = true
  settings.handleDisabledFileLoadingAsSuccess = true
  document.head.innerHTML = '<title>文章</title>'
  document.body.innerHTML = ''
})
afterEach(() => vi.unstubAllGlobals())

describe('original article HTML', () => {
  it('reads original HTML literals without executing scripts or retaining runtime dark colors', async () => {
    document.body.innerHTML = `<div id="js_content" class="js_darkmode__123"><p style="color:white;width:677px">已变色的正文</p></div>`
    const script = document.createElement('script')
    script.textContent = String.raw`window.cgiDataNew = { content_noencode: '\x3cp style=\x22color:#123456;width:32%\x22\x3e原始\u6b63\u6587\x3c/p\x3e' }; throw new Error('must not run');`
    document.head.append(script)
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const source = await readOriginalArticleDocument(document, articleUrl)
    expect(source.querySelector('p')!.textContent).toBe('原始正文')
    expect(source.querySelector<HTMLElement>('p')!.style.width).toBe('32%')
    expect(source.querySelector('#js_content')!.className).not.toContain('js_darkmode')
    expect(document.querySelector<HTMLElement>('p')!.style.width).toBe('677px')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('reads inert response HTML before page scripts change the DOM', async () => {
    document.body.innerHTML = '<div id="js_content"><p>运行时正文</p></div>'
    const response = new Response('<div id="js_content"><p style="width:50%">源代码正文</p></div>')
    Object.defineProperty(response, 'url', { value: articleUrl })
    const fetch = vi.fn().mockResolvedValue(response)
    vi.stubGlobal('fetch', fetch)
    const source = await readOriginalArticleDocument(document, articleUrl)
    expect(source.querySelector('p')!.textContent).toBe('源代码正文')
    expect(source.querySelector<HTMLElement>('p')!.style.width).toBe('50%')
    expect(fetch).toHaveBeenCalledWith(articleUrl, expect.objectContaining({ credentials: 'same-origin', redirect: 'error' }))
  })

  it('falls back to verified HTML and restores stored original colors if source returns a captcha', async () => {
    document.body.innerHTML = '<div id="js_content"><p data-darkmode-original-color-123="#123456" style="color:white">正文</p></div>'
    const response = new Response('<div>请完成验证</div>')
    Object.defineProperty(response, 'url', { value: articleUrl })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const source = await readOriginalArticleDocument(document, articleUrl)
    expect(source.querySelector<HTMLElement>('p')!.style.color).toBe('#123456')
    expect(source.querySelector('p')!.getAttributeNames()).not.toContain('data-darkmode-original-color-123')
  })

  it('treats escaped quotes and line continuations as data', () => {
    document.body.innerHTML = '<div id="js_content"></div>'
    const script = document.createElement('script')
    script.textContent = String.raw`const original = { content_noencode: "<p title=\"author's text\">hello\nworld</p>" };`
    document.head.append(script)
    const source = originalArticleDocument(document)
    expect(source.querySelector('p')!.title).toBe("author's text")
    expect(source.querySelector('p')!.textContent).toBe('hello\nworld')
  })

  it('loads original stylesheets and resolves image URLs relative to the stylesheet', async () => {
    document.head.innerHTML = '<link rel="stylesheet" href="https://res.wx.qq.com/article/styles/theme.css" media="screen">'
    document.body.innerHTML = '<div id="js_content">正文</div>'
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('source temporarily unavailable')))
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, css: '.arbitrary { background:url(../images/picture.png); filter:url(#mask) }' })
    vi.stubGlobal('chrome', { runtime: { sendMessage } })
    const source = await readOriginalArticleDocument(document, articleUrl)
    expect(source.querySelector('style')!.textContent).toContain('https://res.wx.qq.com/article/images/picture.png')
    expect(source.querySelector('style')!.textContent).toContain('url(#mask)')
    expect(source.querySelector('style')!.media).toBe('screen')
    expect(sendMessage).toHaveBeenCalledWith({ type: 'layoutCapture:readStylesheet', url: 'https://res.wx.qq.com/article/styles/theme.css' })
  })
})
