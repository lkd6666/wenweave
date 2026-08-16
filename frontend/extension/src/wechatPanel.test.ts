// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { WechatCapturePanel } from './wechatPanel'

afterEach(() => {
  document.body.replaceChildren()
})

describe('WeChat capture page panel', () => {
  it('opens automatically in the ready state and starts capture from the page', () => {
    const start = vi.fn()
    const panel = new WechatCapturePanel(document)
    panel.show('ready', {
      message: '已检测到文章正文，可以开始抓取。',
      target: 'mp.weixin.qq.com/s/article',
      onStart: start,
    })

    const host = document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!
    const shadow = host.shadowRoot!
    expect(shadow.textContent).toContain('完成验证后开始抓取')
    expect(shadow.textContent).toContain('已检测到文章正文')
    expect(shadow.querySelector('[data-role="target"]')?.textContent).toBe('mp.weixin.qq.com/s/article')
    shadow.querySelector<HTMLButtonElement>('.start')!.click()
    expect(start).toHaveBeenCalledOnce()
  })

  it('shows each processing stage and the final completion state', () => {
    const panel = new WechatCapturePanel(document)
    const host = () => document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!

    panel.show('capturing')
    expect(host().dataset.state).toBe('capturing')
    expect(host().shadowRoot!.textContent).toContain('读取正文结构')

    panel.show('downloading')
    expect(host().shadowRoot!.textContent).toContain('处理图片素材')

    panel.show('uploading')
    expect(host().shadowRoot!.textContent).toContain('生成排版预览')

    panel.show('success')
    expect(host().shadowRoot!.textContent).toContain('预览已经回传')
    expect(host().shadowRoot!.querySelectorAll('.step.is-complete')).toHaveLength(4)
  })

  it('renders a useful capture error', () => {
    const panel = new WechatCapturePanel(document)
    panel.show('error', { message: '微信文章页未准备好，请刷新后重试。' })

    const host = document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!
    expect(host.dataset.state).toBe('error')
    expect(host.shadowRoot!.textContent).toContain('微信文章页未准备好')
  })

  it('uses article-import copy for an import capture session', () => {
    const panel = new WechatCapturePanel(document)

    panel.show('uploading', { purpose: 'web_article_import' })
    let host = document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!
    expect(host.shadowRoot!.textContent).toContain('生成文章导入预览')

    panel.show('success', { purpose: 'web_article_import' })
    host = document.querySelector<HTMLElement>('#yibanpaiban-layout-capture-panel')!
    expect(host.shadowRoot!.textContent).toContain('导入预览已经回传')
    expect(host.shadowRoot!.textContent).toContain('链接导入窗口')
  })
})
