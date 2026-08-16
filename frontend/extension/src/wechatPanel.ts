import type { CapturePurpose } from './shared'

export type WechatPanelState = 'ready' | 'capturing' | 'downloading' | 'uploading' | 'success' | 'error'

export interface WechatPanelOptions {
  message?: string
  target?: string
  onStart?: () => void
  purpose?: CapturePurpose
}

const PANEL_CSS = String.raw`
  :host {
    all: initial;
    position: fixed;
    top: 18px;
    right: 18px;
    z-index: 2147483647;
    display: block;
    width: min(360px, calc(100vw - 32px));
    color: #111827;
    font: 13px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }

  * { box-sizing: border-box; }
  button { font: inherit; }

  .panel {
    overflow: hidden;
    border: 1px solid #dbe2ea;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 16px 38px rgba(15, 23, 42, 0.18), 0 3px 10px rgba(15, 23, 42, 0.08);
  }

  .header {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 10px;
    padding: 13px 14px 12px;
    border-bottom: 1px solid #e5e7eb;
  }

  .mark {
    display: grid;
    width: 34px;
    height: 34px;
    flex: 0 0 34px;
    place-items: center;
    border-radius: 7px;
    background: #111827;
    box-shadow: inset 0 -3px 0 #2563eb;
    color: #fff;
    font-size: 17px;
    font-weight: 700;
  }

  .brand { min-width: 0; flex: 1; }
  .brand strong { display: block; font-size: 14px; line-height: 1.4; }
  .brand span { display: block; margin-top: 1px; color: #6b7280; font-size: 11px; }

  .close {
    display: grid;
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    place-items: center;
    padding: 0;
    border: 0;
    background: transparent;
    color: #6b7280;
    cursor: pointer;
    font-size: 22px;
    line-height: 1;
  }

  .close:hover { color: #111827; background: #f3f4f6; }
  .content { padding: 14px; }

  .state-line {
    display: flex;
    align-items: center;
    gap: 7px;
    color: #4b5563;
    font-size: 11px;
    font-weight: 600;
  }

  .indicator {
    width: 8px;
    height: 8px;
    flex: 0 0 8px;
    border-radius: 50%;
    background: #2563eb;
  }

  :host([data-state="capturing"]) .indicator,
  :host([data-state="downloading"]) .indicator,
  :host([data-state="uploading"]) .indicator {
    border: 1px solid #2563eb;
    border-top-color: transparent;
    background: transparent;
    animation: spin 800ms linear infinite;
  }

  :host([data-state="success"]) .indicator { background: #16a34a; }
  :host([data-state="error"]) .indicator { background: #dc2626; }

  h2 { margin: 5px 0 0; font-size: 17px; line-height: 1.4; }
  .message { margin: 5px 0 0; color: #4b5563; line-height: 1.65; }

  .target {
    display: block;
    overflow: hidden;
    margin-top: 9px;
    color: #6b7280;
    font: 11px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .steps {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 4px;
    margin: 14px 0 0;
    padding: 0;
    list-style: none;
  }

  .step { min-width: 0; color: #9ca3af; font-size: 10px; text-align: center; }
  .step::before {
    display: block;
    width: 100%;
    height: 3px;
    margin-bottom: 6px;
    border-radius: 2px;
    background: #e5e7eb;
    content: "";
  }
  .step.is-complete { color: #15803d; }
  .step.is-complete::before { background: #22c55e; }
  .step.is-active { color: #1d4ed8; font-weight: 600; }
  .step.is-active::before { background: #2563eb; }

  .actions { display: flex; justify-content: flex-end; margin-top: 14px; }
  .start {
    min-width: 112px;
    min-height: 36px;
    padding: 7px 15px;
    border: 1px solid #2563eb;
    border-radius: 6px;
    background: #2563eb;
    color: #fff;
    cursor: pointer;
    font-weight: 600;
  }
  .start:hover { border-color: #1d4ed8; background: #1d4ed8; }
  .start[hidden], .target[hidden] { display: none; }

  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .indicator { animation: none !important; } }
  @media (max-width: 520px) {
    :host { top: 10px; right: 10px; width: calc(100vw - 20px); }
  }
`

const STATE_COPY: Record<WechatPanelState, { label: string; title: string; message: string; step: number }> = {
  ready: {
    label: '文章已关联',
    title: '完成验证后开始抓取',
    message: '确认页面已经显示公众号正文，然后开始抓取。',
    step: 0,
  },
  capturing: {
    label: '正在采集',
    title: '读取正文结构',
    message: '正在识别段落、标题、装饰与图片位置。',
    step: 1,
  },
  downloading: {
    label: '正在处理',
    title: '处理图片素材',
    message: '正在下载可访问图片，失败素材将自动从预览中移除。',
    step: 2,
  },
  uploading: {
    label: '正在上传',
    title: '生成排版预览',
    message: '正文和素材已采集，正在回传排版页面。',
    step: 3,
  },
  success: {
    label: '采集完成',
    title: '预览已经回传',
    message: '可以返回排版页面选择素材并开始模仿。',
    step: 4,
  },
  error: {
    label: '采集失败',
    title: '未能完成抓取',
    message: '请返回排版页面重新发起抓取。',
    step: -1,
  },
}

export class WechatCapturePanel {
  private readonly doc: Document
  private host: HTMLElement | null = null
  private label: HTMLElement | null = null
  private subtitle: HTMLElement | null = null
  private title: HTMLElement | null = null
  private message: HTMLElement | null = null
  private target: HTMLElement | null = null
  private startButton: HTMLButtonElement | null = null
  private steps: HTMLElement[] = []
  private progressStep = 0

  constructor(doc: Document = document) {
    this.doc = doc
  }

  show(state: WechatPanelState, options: WechatPanelOptions = {}): void {
    this.ensurePanel()
    if (!this.host || !this.label || !this.title || !this.message || !this.target || !this.startButton) return
    const purpose = options.purpose || 'layout_reference'
    const copy = { ...STATE_COPY[state] }
    if (purpose === 'web_article_import') {
      if (state === 'ready') copy.title = '完成验证后导入文章'
      if (state === 'uploading') copy.title = '生成文章导入预览'
      if (state === 'success') {
        copy.title = '导入预览已经回传'
        copy.message = '可以返回链接导入窗口检查内容并确认导入。'
      }
    }
    this.host.dataset.state = state
    this.label.textContent = copy.label
    if (this.subtitle) this.subtitle.textContent = purpose === 'web_article_import' ? '微信公众号文章导入' : '微信公众号文章采集'
    this.title.textContent = copy.title
    this.message.textContent = options.message || copy.message
    this.target.textContent = options.target || ''
    this.target.hidden = !options.target
    this.startButton.hidden = state !== 'ready'
    this.startButton.onclick = state === 'ready' && options.onStart ? options.onStart : null
    if (copy.step >= 0) this.progressStep = copy.step
    this.updateSteps(state)
  }

  close(): void {
    this.host?.remove()
    this.host = null
    this.label = null
    this.subtitle = null
    this.title = null
    this.message = null
    this.target = null
    this.startButton = null
    this.steps = []
  }

  private ensurePanel(): void {
    if (this.host?.isConnected) return
    const host = this.doc.createElement('aside')
    host.id = 'yibanpaiban-layout-capture-panel'
    host.setAttribute('aria-live', 'polite')
    const shadow = host.attachShadow({ mode: 'open' })
    const Stylesheet = this.doc.defaultView?.CSSStyleSheet
    if (Stylesheet && 'replaceSync' in Stylesheet.prototype && 'adoptedStyleSheets' in shadow) {
      const stylesheet = new Stylesheet()
      stylesheet.replaceSync(PANEL_CSS)
      shadow.adoptedStyleSheets = [stylesheet]
    } else {
      const style = this.doc.createElement('style')
      style.textContent = PANEL_CSS
      shadow.append(style)
    }

    const panel = this.doc.createElement('section')
    panel.className = 'panel'
    panel.setAttribute('role', 'dialog')
    panel.setAttribute('aria-label', '排版采集助手')
    panel.innerHTML = `
      <header class="header">
        <span class="mark" aria-hidden="true">排</span>
        <div class="brand"><strong>排版采集助手</strong><span data-role="subtitle">微信公众号文章采集</span></div>
        <button class="close" type="button" title="关闭" aria-label="关闭">&times;</button>
      </header>
      <div class="content">
        <div class="state-line"><span class="indicator" aria-hidden="true"></span><span data-role="label"></span></div>
        <h2 data-role="title"></h2>
        <p class="message" data-role="message"></p>
        <code class="target" data-role="target" hidden></code>
        <ol class="steps" aria-label="采集进度">
          <li class="step">验证</li><li class="step">正文</li><li class="step">图片</li><li class="step">上传</li>
        </ol>
        <div class="actions"><button class="start" type="button">开始抓取</button></div>
      </div>
    `
    shadow.append(panel)
    shadow.querySelector<HTMLButtonElement>('.close')!.onclick = () => this.close()
    this.host = host
    this.label = shadow.querySelector('[data-role="label"]')
    this.subtitle = shadow.querySelector('[data-role="subtitle"]')
    this.title = shadow.querySelector('[data-role="title"]')
    this.message = shadow.querySelector('[data-role="message"]')
    this.target = shadow.querySelector('[data-role="target"]')
    this.startButton = shadow.querySelector('.start')
    this.steps = Array.from(shadow.querySelectorAll<HTMLElement>('.step'))
    ;(this.doc.body || this.doc.documentElement).append(host)
  }

  private updateSteps(state: WechatPanelState): void {
    this.steps.forEach((step, index) => {
      step.classList.toggle('is-complete', state === 'success' || index < this.progressStep)
      step.classList.toggle('is-active', state !== 'success' && state !== 'error' && index === this.progressStep)
    })
  }
}
