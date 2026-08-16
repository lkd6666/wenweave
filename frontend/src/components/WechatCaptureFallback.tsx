import { useState } from 'react'
import { Alert, Button, Segmented, Spin } from 'antd'
import {
  CheckOutlined,
  CopyOutlined,
  DownloadOutlined,
  ExportOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import type { LayoutCaptureStatus, WechatVerificationDetail } from '../utils/layoutCaptureBridge'
import { LAYOUT_CAPTURE_EXTENSION_DOWNLOAD_URL } from '../utils/layoutCaptureExtension'

export type CaptureUiState =
  | 'idle'
  | 'checking'
  | 'missing'
  | 'upgrade_required'
  | 'ready'
  | LayoutCaptureStatus
  | 'error'

type CaptureBrowser = 'chrome' | 'edge'
type CapturePurpose = 'layout_reference' | 'web_article_import'

function preferredCaptureBrowser(): CaptureBrowser {
  return typeof navigator !== 'undefined' && navigator.userAgent.includes('Edg/') ? 'edge' : 'chrome'
}

export function LayoutCaptureInstallGuide({
  onDetect,
  upgradeRequired = false,
}: {
  onDetect: () => void
  upgradeRequired?: boolean
}) {
  const [browser, setBrowser] = useState<CaptureBrowser>(preferredCaptureBrowser)
  const [copied, setCopied] = useState(false)
  const browserName = browser === 'edge' ? 'Edge' : 'Chrome'
  const extensionsPage = browser === 'edge' ? 'edge://extensions' : 'chrome://extensions'
  const loadUnpackedLabel = browser === 'edge' ? '加载解压缩的扩展' : '加载已解压的扩展程序'

  const copyExtensionsPage = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(extensionsPage)
      setCopied(true)
    } catch {
      window.prompt('复制扩展管理页地址', extensionsPage)
    }
  }

  return (
    <section className="layout-capture-install-guide" aria-labelledby="layout-capture-install-title">
      <div className="layout-capture-install-title">
        <strong id="layout-capture-install-title">{upgradeRequired ? '更新排版采集助手' : '安装排版采集助手'}</strong>
        <span>约 2 分钟</span>
      </div>
      <ol className="layout-capture-install-steps">
        <li>
          <span className="layout-capture-install-step-number">1</span>
          <div className="layout-capture-install-step-copy">
            <strong>下载扩展安装包</strong>
            <p>点击下方按钮，将最新版扩展 ZIP 下载到电脑。</p>
            <Button type="primary" icon={<DownloadOutlined />} href={LAYOUT_CAPTURE_EXTENSION_DOWNLOAD_URL} download>
              下载扩展 ZIP
            </Button>
          </div>
        </li>
        <li>
          <span className="layout-capture-install-step-number">2</span>
          <div className="layout-capture-install-step-copy">
            <strong>解压 ZIP 文件</strong>
            <p>在下载列表中找到 ZIP，右键选择“全部解压”。打开解压后的文件夹，确认可以直接看到 <code>manifest.json</code>。</p>
          </div>
        </li>
        <li>
          <span className="layout-capture-install-step-number">3</span>
          <div className="layout-capture-install-step-copy">
            <strong>打开扩展管理页</strong>
            <p>选择当前使用的浏览器，复制地址，在新标签页的地址栏中粘贴并按回车。</p>
            <div className="layout-capture-install-browser-row">
              <Segmented<CaptureBrowser>
                size="small"
                value={browser}
                options={[{ label: 'Chrome', value: 'chrome' }, { label: 'Edge', value: 'edge' }]}
                onChange={(value) => {
                  setBrowser(value)
                  setCopied(false)
                }}
              />
              <code>{extensionsPage}</code>
              <Button size="small" icon={copied ? <CheckOutlined /> : <CopyOutlined />} onClick={() => { void copyExtensionsPage() }}>
                {copied ? '已复制' : '复制地址'}
              </Button>
            </div>
          </div>
        </li>
        <li>
          <span className="layout-capture-install-step-number">4</span>
          <div className="layout-capture-install-step-copy">
            <strong>{upgradeRequired ? '替换并重新加载扩展' : '加载已解压的扩展'}</strong>
            <p>在 {browserName} 扩展管理页开启右上角“开发者模式”，点击“{loadUnpackedLabel}”，选择第 2 步中直接包含 <code>manifest.json</code> 的文件夹。</p>
            <p>如果列表中已有旧版“排版采集助手”，请先移除旧版，或用新文件覆盖原目录后点击扩展卡片上的“重新加载”。</p>
          </div>
        </li>
        <li>
          <span className="layout-capture-install-step-number">5</span>
          <div className="layout-capture-install-step-copy">
            <strong>返回并检测</strong>
            <p>确认扩展已启用，然后刷新本页面并点击“重新检测”。</p>
            <Button icon={<ReloadOutlined />} onClick={onDetect}>重新检测</Button>
          </div>
        </li>
      </ol>
      <p className="layout-capture-install-managed-note">
        <InfoCircleOutlined /> 如果“开发者模式”被单位策略锁定，请联系管理员通过 Chrome/Edge 企业策略安装扩展。
      </p>
    </section>
  )
}

function statusText(state: LayoutCaptureStatus, purpose: CapturePurpose): string {
  if (state === 'opening') return '正在打开关联的微信文章页…'
  if (state === 'awaiting_verification') return '文章页已打开。完成微信验证后，在文章页的采集面板中点击“开始抓取”。'
  if (state === 'capturing') return '扩展正在读取正文结构和可访问图片…'
  return purpose === 'web_article_import'
    ? '采集完成，正在上传并生成文章导入预览…'
    : '采集完成，正在上传并生成排版预览…'
}

export function WechatCaptureFallback({
  verification,
  state,
  error,
  purpose,
  onDetect,
  onStart,
}: {
  verification: WechatVerificationDetail
  state: CaptureUiState
  error: string | null
  purpose: CapturePurpose
  onDetect: () => void
  onStart: () => void
}) {
  const actionLabel = purpose === 'web_article_import' ? '在浏览器中验证并导入' : '在浏览器中验证并抓取'
  return (
    <div className="layout-capture-fallback" aria-live="polite">
      <Alert
        type="warning"
        showIcon
        icon={<SafetyCertificateOutlined />}
        message="微信要求在浏览器中完成验证"
        description={verification.message}
      />
      {state === 'checking' && <div className="layout-capture-status"><Spin size="small" /> 正在检测排版采集助手…</div>}
      {(state === 'missing' || state === 'upgrade_required') && (
        <>
          <Alert
            type="error"
            showIcon
            message={state === 'upgrade_required' ? '排版采集助手版本过旧' : '未检测到排版采集助手'}
            description={state === 'upgrade_required'
              ? '当前版本不支持文章链接导入，请按下面步骤更新扩展。'
              : '请按下面的步骤完成安装。安装后无需重新解析文章。'}
          />
          <LayoutCaptureInstallGuide onDetect={onDetect} upgradeRequired={state === 'upgrade_required'} />
        </>
      )}
      {state === 'ready' && <div className="layout-capture-status">排版采集助手已连接，可以打开文章并完成验证。</div>}
      {['opening', 'awaiting_verification', 'capturing', 'uploading'].includes(state) && (
        <div className="layout-capture-status">
          {(state === 'capturing' || state === 'uploading') && <Spin size="small" />}
          {statusText(state as LayoutCaptureStatus, purpose)}
        </div>
      )}
      {state === 'error' && error && <Alert type="error" showIcon message={error} />}
      {!['missing', 'upgrade_required', 'checking'].includes(state) && (
        <div className="layout-capture-actions">
          <Button icon={<ExportOutlined />} href={verification.url} target="_blank" rel="noreferrer">打开微信文章</Button>
          {(state === 'ready' || state === 'error') && (
            <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={onStart}>{actionLabel}</Button>
          )}
        </div>
      )}
    </div>
  )
}
