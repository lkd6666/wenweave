import { capturePurpose, isRecord, type CapturePurpose, type StoredCaptureSession } from './shared'

const taskElement = document.querySelector<HTMLElement>('#task')!
const stateLabelElement = document.querySelector<HTMLElement>('#state-label')!
const taskTitleElement = document.querySelector<HTMLElement>('#task-title')!
const statusElement = document.querySelector<HTMLElement>('#status')!
const targetElement = document.querySelector<HTMLElement>('#target')!
const targetValueElement = document.querySelector<HTMLElement>('#target-value')!
const actionsElement = document.querySelector<HTMLElement>('#actions')!
const startButton = document.querySelector<HTMLButtonElement>('#start')!
const cancelButton = document.querySelector<HTMLButtonElement>('#cancel')!

type PopupState = 'loading' | 'idle' | 'ready' | 'running' | 'error'
let activePurpose: CapturePurpose = 'layout_reference'

function setStatus(state: PopupState, label: string, title: string, message: string): void {
  taskElement.dataset.state = state
  stateLabelElement.textContent = label
  taskTitleElement.textContent = title
  statusElement.textContent = message
}

async function refresh(): Promise<void> {
  try {
    const response = await chrome.runtime.sendMessage({ type: 'layoutCapture:getState' }) as unknown
    if (!isRecord(response) || response.ok !== true || !response.stored) {
      setStatus('idle', '助手已就绪', '等待采集任务', '返回系统，在“模仿排版”或“导入文章链接”中发起浏览器抓取。')
      targetElement.hidden = true
      actionsElement.hidden = true
      startButton.disabled = true
      cancelButton.hidden = true
      return
    }
    const stored = response.stored as StoredCaptureSession
    activePurpose = capturePurpose(stored.session) || 'layout_reference'
    const url = new URL(stored.session.canonical_url)
    targetValueElement.textContent = `${url.hostname}${url.pathname}`
    targetElement.hidden = false
    actionsElement.hidden = false
    const running = response.running === true
    startButton.disabled = running
    startButton.textContent = running ? '采集中…' : '开始采集'
    cancelButton.hidden = false
    if (running) {
      setStatus(
        'running',
        '正在处理',
        activePurpose === 'web_article_import' ? '采集并生成导入预览' : '采集并生成排版预览',
        '任务会在后台继续，可以关闭此窗口。',
      )
    } else {
      setStatus('ready', '文章已关联', '准备开始采集', '确认微信验证已完成且页面显示正文，然后点击开始。')
    }
  } catch {
    setStatus('error', '连接异常', '暂时无法使用', '无法连接扩展后台，请关闭后重新打开此窗口。')
    targetElement.hidden = true
    actionsElement.hidden = true
    startButton.disabled = true
  }
}

startButton.addEventListener('click', async () => {
  startButton.disabled = true
  setStatus('loading', '正在启动', '准备采集文章', '正在检查文章页面和采集会话…')
  try {
    const response = await chrome.runtime.sendMessage({ type: 'layoutCapture:begin' }) as unknown
    if (!isRecord(response) || response.ok !== true) {
      throw new Error(isRecord(response) && typeof response.message === 'string' ? response.message : '无法启动采集')
    }
    setStatus(
      'running',
      '正在处理',
      '采集已启动',
      activePurpose === 'web_article_import'
        ? '结果会自动回传到“导入文章链接”窗口。'
        : '结果会自动回传到“模仿排版”窗口。',
    )
    window.setTimeout(() => window.close(), 500)
  } catch (error) {
    setStatus('error', '启动失败', '无法开始采集', error instanceof Error ? error.message : '无法启动采集')
    startButton.disabled = false
  }
})

cancelButton.addEventListener('click', async () => {
  const response = await chrome.runtime.sendMessage({ type: 'layoutCapture:getState' }) as unknown
  if (isRecord(response) && isRecord(response.stored) && isRecord(response.stored.session)) {
    await chrome.runtime.sendMessage({ type: 'layoutCapture:cancel', sessionId: response.stored.session.id })
  }
  window.close()
})

void refresh()
