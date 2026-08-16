import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { LAYOUT_CAPTURE_EXTENSION_DOWNLOAD_URL } from '../utils/layoutCaptureExtension'
import { LayoutCaptureInstallGuide } from './LayoutImitationModal'

describe('LayoutCaptureInstallGuide', () => {
  it('guides the user from download through extension detection', () => {
    const html = renderToStaticMarkup(<LayoutCaptureInstallGuide onDetect={() => undefined} />)

    expect(html).toContain(`href="${LAYOUT_CAPTURE_EXTENSION_DOWNLOAD_URL}"`)
    expect(html).toContain('下载扩展 ZIP')
    expect(html).toContain('manifest.json')
    expect(html).toContain('chrome://extensions')
    expect(html).toContain('开发者模式')
    expect(html).toContain('重新检测')
    expect(html.match(/layout-capture-install-step-number/g)).toHaveLength(5)
  })
})
