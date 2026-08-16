import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WechatCaptureFallback } from './WechatCaptureFallback'

const verification = {
  code: 'wechat_verification_required' as const,
  message: '请完成微信验证',
  url: 'https://mp.weixin.qq.com/s/article',
}

describe('WeChat capture fallback UI', () => {
  it('shows an extension update guide when article-import capability is missing', () => {
    const html = renderToStaticMarkup(
      <WechatCaptureFallback
        verification={verification}
        state="upgrade_required"
        error={null}
        purpose="web_article_import"
        onDetect={() => undefined}
        onStart={() => undefined}
      />,
    )

    expect(html).toContain('排版采集助手版本过旧')
    expect(html).toContain('更新排版采集助手')
    expect(html).toContain('下载扩展 ZIP')
  })

  it('uses link-import wording while uploading a browser capture', () => {
    const html = renderToStaticMarkup(
      <WechatCaptureFallback
        verification={verification}
        state="uploading"
        error={null}
        purpose="web_article_import"
        onDetect={() => undefined}
        onStart={() => undefined}
      />,
    )

    expect(html).toContain('生成文章导入预览')
    expect(html).toContain('打开微信文章')
  })
})
