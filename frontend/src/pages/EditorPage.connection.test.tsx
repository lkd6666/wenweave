// @vitest-environment happy-dom
import { act } from 'react'
import type { ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { message } from 'antd'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type ChatPanel from '../components/ChatPanel'
import type PreviewFrame from '../components/PreviewFrame'
import type CodeViewer from '../components/CodeViewer'
import type TemplateLibraryPanel from '../components/TemplateLibraryPanel'
import type { AIModelItem, ChatImageAttachment, ChatSessionItem, DocumentDetail, TemplateItem } from '../types'
import type { AgentRunInfo, SequencedChatStreamEvent } from '../api/chat'
import * as chatModule from '../api/chat'
import { ApiError } from '../api/client'
import { documentsApi } from '../api/documents'
import { modelsApi } from '../api/models'
import { wechatAccountsApi } from '../api/wechatAccounts'
import EditorPage from './EditorPage'
import { chatTextsApi } from '../api/chatTexts'

const state = vi.hoisted(() => ({
  documentId: 1,
  chat: null as ComponentProps<typeof ChatPanel> | null,
  preview: null as ComponentProps<typeof PreviewFrame> | null,
  code: null as ComponentProps<typeof CodeViewer> | null,
  resource: null as ComponentProps<typeof TemplateLibraryPanel> | null,
  insertTemplate: vi.fn(() => true),
  navigate: vi.fn(),
}))
vi.mock('react-router', () => ({
  useParams: () => ({ documentId: String(state.documentId) }),
  useNavigate: () => state.navigate,
}))
vi.mock('../components/ChatPanel', () => ({ default: (props: ComponentProps<typeof ChatPanel>) => { state.chat = props; return null } }))
vi.mock('../components/PreviewFrame', async () => {
  const { forwardRef, useImperativeHandle } = await import('react')
  return { default: forwardRef((props: ComponentProps<typeof PreviewFrame>, ref) => {
    state.preview = props
    useImperativeHandle(ref, () => ({
      insertTemplateHtml: state.insertTemplate,
      flushPendingChange: () => {},
    }))
    return null
  }) }
})
vi.mock('../components/CodeViewer', () => ({ default: (props: ComponentProps<typeof CodeViewer>) => { state.code = props; return null } }))
vi.mock('../components/TemplateLibraryPanel', () => ({ default: (props: ComponentProps<typeof TemplateLibraryPanel>) => { state.resource = props; return null } }))
vi.mock('../components/ImageLibraryPanel', () => ({ default: () => null }))
vi.mock('../components/CompliancePanel', () => ({ default: () => null }))
vi.mock('../components/VersionHistoryDrawer', () => ({ default: () => null }))
vi.mock('../components/SourceDocumentModal', () => ({ default: () => null }))
vi.mock('../components/ThemeGalleryModal', () => ({ default: () => null }))
vi.mock('../components/LayoutImitationModal', () => ({ default: () => null }))
vi.mock('../components/WeChatDraftModal', () => ({ default: () => null }))
vi.mock('../components/DocumentShareModal', () => ({ default: () => null }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function documentDetail(id: number): DocumentDetail {
  return { id, title: `Document ${id}`, current_html: `<p>Document ${id}</p>`, has_source_file: false,
    visibility_mode: 'all', allowed_user_ids: [], allowed_group_ids: [], group_id: null,
    source_type: 'markdown', wechat_cover_url: '', is_ai_editing: false, created_by: null, last_modified_by: null,
    created_at: '', updated_at: '', wechat_metadata: {} as DocumentDetail['wechat_metadata'] }
}
function runInfo(documentId: number): AgentRunInfo {
  return { run_id: `run-${documentId}`, session_id: documentId * 10, status: 'running', user_message_id: 100 + documentId,
    assistant_message_id: null, error_message: '', event_sequence: 0 }
}
function chatSession(documentId = 1, attached_templates: TemplateItem[] = []): ChatSessionItem {
  return {
    id: documentId * 10, title: 'Chat', is_archived: false, attached_templates,
    context_start_message_id: 0, visible_message_count: 0, hidden_message_count: 0,
    layout_reference: null, theme_context: null, image_model_id: null, created_at: '', updated_at: '',
  }
}
function finalEvent(id: number): SequencedChatStreamEvent {
  return { event: 'final', sequence: 1, eventAgeMs: 0,
    data: { content: 'done', html: `<p>Final ${id}</p>`, html_changed: false, compliance: null, run_status: 'completed' } }
}
const images: ChatImageAttachment[] = Array.from({ length: 100 }, (_, index) => ({
  id: `image-${index}`, filename: `${index}.png`, content_type: 'image/png', size: 10, preview_url: `/images/${index}.png`,
}))

describe('editor connection ownership', () => {
  let root: Root
  let container: HTMLDivElement

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    vi.stubGlobal('fetch', vi.fn(async (input) => { throw new Error(`Unexpected network request: ${String(input)}`) }))
    vi.spyOn(chatTextsApi, 'listDrafts').mockResolvedValue([])
    localStorage.clear()
    sessionStorage.clear()
    state.documentId = 1
    state.chat = null
    state.preview = null
    state.code = null
    state.resource = null
    state.insertTemplate.mockClear()
    vi.spyOn(documentsApi, 'get').mockImplementation(async (id) => documentDetail(id))
    vi.spyOn(documentsApi, 'update').mockImplementation(async (id) => documentDetail(id))
    vi.spyOn(chatModule.chatApi, 'listSessions').mockImplementation(async (id) => [chatSession(id)])
    vi.spyOn(chatModule.chatApi, 'listRecentMessages').mockResolvedValue([])
    vi.spyOn(chatModule.chatApi, 'getActiveRun').mockResolvedValue(null)
    vi.spyOn(chatModule.chatApi, 'previewContext').mockRejectedValue(new Error('Preview unavailable'))
    vi.spyOn(chatModule.chatApi, 'getRunByClientRequest').mockResolvedValue(null)
    vi.spyOn(chatModule.chatApi, 'getRun').mockImplementation(async (id, runId) => ({ ...runInfo(id), run_id: runId }))
    vi.spyOn(chatModule.chatApi, 'deleteImage').mockResolvedValue(undefined)
    vi.spyOn(modelsApi, 'list').mockResolvedValue([{ id: 1, is_default: true, is_multimodal: true, thinking_config: {} } as AIModelItem])
    vi.spyOn(wechatAccountsApi, 'available').mockResolvedValue([])
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    expect(fetch).not.toHaveBeenCalled()
    container.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  async function renderDocument(id = 1) {
    state.documentId = id
    await act(async () => root.render(<EditorPage />))
    await vi.waitFor(() => expect(state.preview?.html).toBe(`<p>Document ${id}</p>`))
  }

  async function openSource() {
    await act(async () => Array.from(container.querySelectorAll('label.ant-segmented-item'))
      .find((item) => item.textContent?.includes('源码编辑'))!.querySelector<HTMLInputElement>('input')!.click())
    await vi.waitFor(() => expect(state.code).not.toBeNull())
  }

  it.each(['onPrepend', 'onAppend', 'onInsertAtCaret'] as const)('ignores late %s results after leaving and returning to the same document', async (action) => {
    const result = deferred<{ html: string; localized_count: number }>()
    vi.spyOn(documentsApi, 'materializeTemplateImages').mockReturnValue(result.promise)
    await renderDocument()
    let pending!: void | Promise<void>
    await act(async () => { pending = state.resource![action]({ id: 1, name: 'template' } as TemplateItem) })
    await renderDocument(2)
    await renderDocument(1)
    await act(async () => {
      result.resolve({ html: '<p>old template</p>', localized_count: 0 })
      await pending
    })
    expect(state.insertTemplate).not.toHaveBeenCalled()
    expect(state.resource!.disabled).toBe(false)
  })

  it.each([['onPrepend', 'prepend'], ['onAppend', 'append']] as const)('inserts materialized template images at %s', async (action, placement) => {
    const html = '<section><img src="/api/documents/1/assets/header.png"><p>Header</p></section>'
    const materialize = vi.spyOn(documentsApi, 'materializeTemplateImages').mockResolvedValue({ html, localized_count: 1 })
    await renderDocument()
    await act(async () => { await state.resource![action]({ id: 1, name: 'template' } as TemplateItem) })
    expect(materialize).toHaveBeenCalledExactlyOnceWith(1, 1)
    expect(state.insertTemplate).toHaveBeenCalledExactlyOnceWith(html, placement)
  })

  it('ignores an old editor callback after navigation', async () => {
    const patch = vi.spyOn(documentsApi, 'patchContent')
    await renderDocument()
    await openSource()
    const staleChange = state.code!.onChange
    await renderDocument(2)
    await act(async () => staleChange('<p>stale formatting</p>'))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(patch).not.toHaveBeenCalled()
  })

  it('shows saved structure errors before sync and clears them after a repair', async () => {
    const warning = vi.spyOn(message, 'warning').mockImplementation(vi.fn())
    const success = vi.spyOn(message, 'success').mockImplementation(vi.fn())
    const destroy = vi.spyOn(message, 'destroy').mockImplementation(vi.fn())
    const invalidHtml = '<svg><text><br></text></svg>'
    const repairedHtml = '<svg><text></text></svg>'
    const patch = vi.spyOn(documentsApi, 'patchContent')
      .mockResolvedValueOnce({ html: invalidHtml, localized_count: 0,
        html_validation: { valid: false, errors: ['第 1 行第 21 列：Element br not allowed in a non-html context'] } })
      .mockResolvedValueOnce({ html: repairedHtml, localized_count: 0,
        html_validation: { valid: true, errors: [], warnings: [] } })
    await renderDocument()
    await openSource()

    await act(async () => { state.code!.onChange(invalidHtml) })
    await act(async () => { await state.code!.onSave() })

    expect(patch).toHaveBeenCalledTimes(1)
    expect(state.preview!.html).toBe(invalidHtml)
    expect(warning).toHaveBeenCalledWith(expect.objectContaining({
      key: 'document-html-validation-1',
      content: expect.stringContaining('Element br not allowed in a non-html context'),
    }))
    expect(success).not.toHaveBeenCalled()

    await act(async () => { state.code!.onChange(repairedHtml) })
    await act(async () => { await state.code!.onSave() })

    expect(patch).toHaveBeenCalledTimes(2)
    expect(state.preview!.html).toBe(repairedHtml)
    expect(destroy).toHaveBeenCalledWith('document-html-validation-1')
    expect(success).toHaveBeenCalledWith('预览修改已保存')
  })

  it('ignores save diagnostics from a document that was left while saving', async () => {
    const warning = vi.spyOn(message, 'warning').mockImplementation(vi.fn())
    const save = deferred<Awaited<ReturnType<typeof documentsApi.patchContent>>>()
    const patch = vi.spyOn(documentsApi, 'patchContent').mockReturnValue(save.promise)
    await renderDocument()
    await openSource()
    await act(async () => { state.code!.onChange('<svg><text><br></text></svg>') })
    await act(async () => { state.code!.onSave() })
    await vi.waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    await renderDocument(2)

    await act(async () => { save.resolve({ html: '<svg><text><br></text></svg>', localized_count: 0,
      html_validation: { valid: false, errors: ['old document error'] } }) })

    expect(warning).not.toHaveBeenCalled()
    expect(state.preview!.html).toBe('<p>Document 2</p>')
  })

  it('ignores an image-localization response after navigation', async () => {
    const result = deferred<{ html: string; localized_count: number }>()
    const localize = vi.spyOn(documentsApi, 'localizeExternalImages').mockReturnValue(result.promise)
    await renderDocument()
    await act(async () => { state.preview!.onExternalImagesPasted() })
    await vi.waitFor(() => expect(localize).toHaveBeenCalledWith(1))
    await renderDocument(2)
    await act(async () => { result.resolve({ html: '<p>old localized article</p>', localized_count: 1 }) })
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.resource!.disabled).toBe(false)
  })

  it('keeps formatting, editing and saving locked from a live question through its answer', async () => {
    const pause = deferred<SequencedChatStreamEvent>()
    const finish = deferred<SequencedChatStreamEvent>()
    const answer = deferred<AgentRunInfo>()
    const patch = vi.spyOn(documentsApi, 'patchContent')
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    vi.spyOn(chatModule.chatApi, 'answerUserQuestion').mockReturnValue(answer.promise)
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents')
      .mockImplementationOnce(async function* () { yield await pause.promise })
      .mockImplementationOnce(async function* () { yield await finish.promise })
    await renderDocument()
    await act(async () => Array.from(container.querySelectorAll('label.ant-segmented-item'))
      .find((item) => item.textContent?.includes('直接编辑'))!.querySelector<HTMLInputElement>('input')!.click())
    await openSource()
    const staleChange = state.code!.onChange
    await act(async () => { state.chat!.onSend('请先询问我的偏好', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(true))
    expect(state.code!.disabled).toBe(true)
    await act(async () => pause.resolve({ event: 'user_question', sequence: 1, eventAgeMs: 0, data: {
      id: 'question-1', run_id: 'run-1', question: '确认风格', options: [], allow_multiple: false, include_style: false,
    } }))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.chat!.pendingUserQuestion?.id).toBe('question-1')
    expect(state.code!.disabled).toBe(true)
    expect(state.preview!.mode).toBe('select')
    expect(state.resource!.disabled).toBe(true)
    await act(async () => {
      staleChange('<p>\n  Document 1\n</p>')
      state.preview!.onHtmlChange?.('<p>Unexpected edit</p>')
      state.code!.onSave()
    })
    expect(state.preview!.html).toBe('<p>Document 1</p>')
    expect(patch).not.toHaveBeenCalled()
    await act(async () => { state.chat!.onAnswerUserQuestion({ action: 'skip' }) })
    expect(state.code!.disabled).toBe(true)
    await act(async () => answer.resolve(runInfo(1)))
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(2))
    expect(state.code!.disabled).toBe(true)
    expect(patch).not.toHaveBeenCalled()
    await act(async () => finish.resolve({ ...finalEvent(1), sequence: 2 }))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.code!.disabled).toBe(false)
    const finalHtml = state.preview!.html
    await act(async () => staleChange('<p>old delayed formatting after unlock</p>'))
    expect(state.preview!.html).toBe(finalHtml)
    expect(patch).not.toHaveBeenCalled()
  })

  it('locks a restored waiting question and unlocks document editing after stopping it', async () => {
    vi.mocked(chatModule.chatApi.getActiveRun).mockResolvedValue({
      ...runInfo(1), status: 'waiting_for_input', user_question: {
        id: 'question-1', run_id: 'run-1', question: '确认', options: [], allow_multiple: false, include_style: false,
      },
    })
    vi.spyOn(chatModule, 'cancelChatRun').mockResolvedValue({ ...runInfo(1), status: 'cancelled' })
    await renderDocument()
    await vi.waitFor(() => expect(state.chat!.pendingUserQuestion?.id).toBe('question-1'))
    await openSource()
    expect(state.code!.disabled).toBe(true)
    vi.mocked(documentsApi.get).mockResolvedValue({ ...documentDetail(1), current_html: '<p>preserved edits</p>' })
    await act(async () => { state.chat!.onStop() })
    await vi.waitFor(() => expect(state.chat!.pendingUserQuestion).toBeNull())
    expect(state.code!.disabled).toBe(false)
    expect(state.preview!.html).toBe('<p>preserved edits</p>')
  })

  it('keeps one compliance card when a replacement ID points at another announced tool', async () => {
    const finish = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      const events: SequencedChatStreamEvent[] = [
        { event: 'tool_call', data: { id: 'read', name: 'read_blocks', arguments: {}, preparing: true } },
        { event: 'tool_call', data: { id: 'check', name: 'check_compliance', arguments: {}, preparing: true } },
        { event: 'tool_call', data: { id: 'read', name: 'read_blocks', arguments: {} } },
        { event: 'tool_call', data: { id: 'check', name: 'check_compliance', arguments: {}, replaces_id: 'read' } },
        { event: 'tool_result', data: { id: 'read', name: 'read_blocks', result: '错误：缺少 block_ids' } },
        { event: 'tool_result', data: { id: 'check', name: 'check_compliance', result: '官方合规检测发现 1 类、14 项违规' } },
      ].map((event, index) => ({ ...event, sequence: index + 1, eventAgeMs: 0 })) as SequencedChatStreamEvent[]
      for (const event of events) yield event
      yield await finish.promise
    })
    await renderDocument()
    await act(async () => { state.chat!.onSend('核对排版', [], []) })
    await vi.waitFor(() => {
      expect(state.chat!.toolActivities).toHaveLength(2)
      expect(state.chat!.toolActivities.every((tool) => tool.status !== 'running')).toBe(true)
    })
    expect(state.chat!.toolActivities.map((tool) => [tool.id, tool.name, tool.status])).toEqual([
      ['read', 'read_blocks', 'error'],
      ['check', 'check_compliance', 'success'],
    ])
    expect(state.chat!.streamBlocks.filter((block) => block.type === 'tool').map((block) => block.tool?.name)).toEqual([
      'read_blocks', 'check_compliance',
    ])
    await act(async () => finish.resolve({ ...finalEvent(1), sequence: 7 }))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
  })

  it('restores all 100 attachments after a rejected start request', async () => {
    vi.spyOn(chatModule, 'startChatRun').mockRejectedValue(new ApiError(400, 'Rejected'))
    await renderDocument()
    await act(async () => { state.chat!.onSend('use these images', [], images) })
    await vi.waitFor(() => expect(state.chat!.imageAttachments.map((image) => image.id)).toEqual(images.map((image) => image.id)))
    expect(state.chat!.messages).toEqual([])
    expect(state.chat!.composerDraft).toBe('use these images')
    expect(state.chat!.streaming).toBe(false)
  })

  it('allows selecting article content and updating template references during a run', async () => {
    const stream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await stream.promise })
    const template = { id: 1, name: 'Footer', html: '<p>Footer</p>' } as TemplateItem
    const replace = vi.spyOn(chatModule.chatApi, 'replaceTemplateAttachments').mockResolvedValue(chatSession(1, [template]))
    const remove = vi.spyOn(chatModule.chatApi, 'removeTemplateAttachment').mockResolvedValue(chatSession())
    await renderDocument()
    await act(async () => Array.from(container.querySelectorAll('label.ant-segmented-item'))
      .find((item) => item.textContent?.includes('直接编辑'))!.querySelector<HTMLInputElement>('input')!.click())
    expect(state.preview!.mode).toBe('edit')
    await act(async () => { state.chat!.onSend('edit article', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(true))
    expect(state.preview!.mode).toBe('select')
    expect(state.resource!.disabled).toBe(true)
    expect(state.resource!.attachmentDisabled).toBe(false)
    await act(async () => state.resource!.onAttachToChat(template))
    expect(replace).toHaveBeenCalledExactlyOnceWith(1, 10, [1])
    expect(state.chat!.composerTemplates).toEqual([template])
    expect(state.chat!.streaming).toBe(true)
    expect(state.preview!.html).toBe('<p>Document 1</p>')
    expect(state.chat!.messages[0]!.template_refs).toEqual([])
    await act(async () => state.chat!.onRemoveAttachedTemplate(1))
    expect(remove).toHaveBeenCalledExactlyOnceWith(1, 10, 1)
    expect(state.chat!.attachedTemplates).toEqual([])
    await act(async () => stream.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.preview!.mode).toBe('edit')
  })

  it.each([1, 6])('reuses attached templates before and after sending without changing a session with %i attachments', async (count) => {
    const templates = Array.from({ length: count }, (_, index) => ({ id: index + 1, name: `Footer ${index + 1}`, html: '<p>Footer</p>' } as TemplateItem))
    const footer = templates.at(-1)!
    vi.mocked(chatModule.chatApi.listSessions).mockResolvedValue([chatSession(1, templates)])
    const replace = vi.spyOn(chatModule.chatApi, 'replaceTemplateAttachments')
    const remove = vi.spyOn(chatModule.chatApi, 'removeTemplateAttachment')
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    const stream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await stream.promise })
    await renderDocument()
    expect(state.chat!.composerTemplates).toEqual([])
    await act(async () => { state.resource!.onAttachToChat(footer) })
    await act(async () => { state.resource!.onAttachToChat(footer) })
    expect(state.chat!.composerTemplates).toEqual([footer])
    await act(async () => { state.chat!.onRemoveComposerTemplate(footer.id) })
    expect(state.chat!.composerTemplates).toEqual([])
    expect(state.chat!.attachedTemplates).toEqual(templates)
    await act(async () => { state.resource!.onAttachToChat(footer) })
    expect(state.chat!.composerTemplates).toEqual([footer])
    await act(async () => { state.chat!.onSend('@组件1 再次使用', [], [], [], [footer.id]) })
    await vi.waitFor(() => expect(start).toHaveBeenCalledOnce())
    expect(start.mock.calls[0]![14]).toEqual([footer.id, ...templates.filter(item => item.id !== footer.id).map(item => item.id)])
    await act(async () => stream.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.chat!.composerTemplates).toEqual([])
    await act(async () => { state.resource!.onAttachToChat(footer) })
    expect(state.chat!.composerTemplates).toEqual([footer])
    expect(state.chat!.attachedTemplates).toEqual(templates)
    expect(replace).not.toHaveBeenCalled()
    expect(remove).not.toHaveBeenCalled()
  })

  it('keeps the referenced footer as component 1 instead of using the first session template', async () => {
    const header = { id: 10, name: '排版头' } as TemplateItem
    const footer = { id: 20, name: '排版尾' } as TemplateItem
    vi.mocked(chatModule.chatApi.listSessions).mockResolvedValue([chatSession(1, [header, footer])])
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    const stream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await stream.promise })
    await renderDocument()
    await act(async () => { state.chat!.onSend('@组件1 不要改动', [], [], [], [footer.id]) })
    await vi.waitFor(() => expect(start).toHaveBeenCalledOnce())
    expect(start.mock.calls[0]![14]).toEqual([footer.id, header.id])
    expect(state.chat!.messages[0]!.template_refs).toEqual([{ id: 20, name: '排版尾' }, { id: 10, name: '排版头' }])
    expect(state.chat!.attachedTemplates).toEqual([header, footer])
    await act(async () => stream.resolve(finalEvent(1)))
  })

  it('preserves the footer identity across a rejected send, draft reload and retry', async () => {
    const header = { id: 10, name: '排版头' } as TemplateItem
    const footer = { id: 20, name: '排版尾' } as TemplateItem
    vi.mocked(chatModule.chatApi.listSessions).mockResolvedValue([chatSession(1, [header, footer])])
    const start = vi.spyOn(chatModule, 'startChatRun').mockRejectedValueOnce(new ApiError(400, 'Fixture rejection'))
      .mockResolvedValue(runInfo(1))
    const stream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await stream.promise })
    await renderDocument()
    await act(async () => { state.chat!.onSend('@组件1 不要改动', [], [], [], [footer.id]) })
    await vi.waitFor(() => expect(state.chat!.submitting).toBe(false))
    expect(state.chat!.composerTemplates.map(item => item.id)).toEqual([footer.id])
    await renderDocument(2)
    await renderDocument(1)
    expect(state.chat!.composerTemplates.map(item => item.id)).toEqual([footer.id])
    await act(async () => { state.chat!.onSend(state.chat!.composerDraft, [], []) })
    await vi.waitFor(() => expect(start).toHaveBeenCalledTimes(2))
    expect(start.mock.calls[1]![14]).toEqual([footer.id, header.id])
    await act(async () => stream.resolve(finalEvent(1)))
  })

  it('snapshots component numbering when a message is queued', async () => {
    const header = { id: 10, name: '排版头' } as TemplateItem
    const footer = { id: 20, name: '排版尾' } as TemplateItem
    vi.mocked(chatModule.chatApi.listSessions).mockResolvedValue([chatSession(1, [header, footer])])
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    const first = deferred<SequencedChatStreamEvent>(), second = deferred<SequencedChatStreamEvent>()
    let count = 0
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      yield await (++count === 1 ? first.promise : second.promise)
    })
    await renderDocument()
    await act(async () => { state.chat!.onSend('先处理正文', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(true))
    await act(async () => { state.chat!.onSend('@组件1 不要改动', [], [], [], [footer.id]) })
    await act(async () => first.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(start).toHaveBeenCalledTimes(2))
    expect(start.mock.calls[1]![14]).toEqual([footer.id, header.id])
    expect(state.chat!.messages.find(item => item.content === '@组件1 不要改动')?.template_refs?.[0])
      .toEqual({ id: footer.id, name: footer.name })
    await act(async () => second.resolve(finalEvent(1)))
  })

  it('waits for pending template changes before advancing queued requests', async () => {
    const firstStream = deferred<SequencedChatStreamEvent>()
    const secondStream = deferred<SequencedChatStreamEvent>()
    const update = deferred<ChatSessionItem>()
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    let streamCalls = 0
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      streamCalls += 1
      yield await (streamCalls === 1 ? firstStream.promise : secondStream.promise)
    })
    const replace = vi.spyOn(chatModule.chatApi, 'replaceTemplateAttachments').mockReturnValue(update.promise)
    const template = { id: 1, name: 'Footer', html: '<p>Footer</p>' } as TemplateItem
    const nextTemplate = { id: 2, name: 'Heading', html: '<p>Heading</p>' } as TemplateItem
    vi.mocked(chatModule.chatApi.listSessions).mockResolvedValue([chatSession(1, [template])])
    await renderDocument()
    await act(async () => { state.chat!.onSend('first request', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(true))
    await act(async () => { state.chat!.onSend('queued request', [], []) })
    await act(async () => { state.resource!.onAttachToChat(nextTemplate) })
    await act(async () => { state.resource!.onAttachToChat(nextTemplate) })
    expect(replace).toHaveBeenCalledOnce()
    expect(state.resource!.attachmentDisabled).toBe(true)
    await act(async () => firstStream.resolve(finalEvent(1)))
    expect(start).toHaveBeenCalledOnce()
    await act(async () => update.resolve(chatSession(1, [template, nextTemplate])))
    await vi.waitFor(() => expect(start).toHaveBeenCalledTimes(2))
    expect(start.mock.calls[1]![14]).toEqual([template.id])
    await vi.waitFor(() => expect(state.chat!.messages.find((item) => item.content === 'queued request')?.template_refs)
      .toEqual([{ id: 1, name: 'Footer' }]))
    expect(state.chat!.attachedTemplates).toEqual([template, nextTemplate])
    await act(async () => secondStream.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
  })

  it('does not let a detached accepted POST overwrite a newer run', async () => {
    const oldStart = deferred<AgentRunInfo>()
    const newStream = deferred<SequencedChatStreamEvent>()
    const start = vi.spyOn(chatModule, 'startChatRun').mockImplementation((id) => id === 1 ? oldStart.promise : Promise.resolve(runInfo(id)))
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await newStream.promise })
    const cancel = vi.spyOn(chatModule, 'cancelChatRun')
    await renderDocument()
    await act(async () => { state.chat!.onSend('old request', [], []) })
    expect(start).toHaveBeenCalledTimes(1)
    await renderDocument(2)
    await act(async () => { state.chat!.onSend('new request', [], []) })
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(1))
    await act(async () => oldStart.resolve({ ...runInfo(1), reask_activation: { archive_id: 1, source_message_id: 1, current_html: '<p>Old activation</p>' } }))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.streaming).toBe(true)
    expect(streams.mock.calls.map((call) => call[0])).toEqual([2])
    expect(cancel).not.toHaveBeenCalled()
    await act(async () => newStream.resolve(finalEvent(2)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
  })

  it('keeps submitted image assets while an in-flight POST survives navigation', async () => {
    const start = deferred<AgentRunInfo>()
    vi.spyOn(chatModule, 'startChatRun').mockReturnValue(start.promise)
    vi.spyOn(chatModule.chatApi, 'uploadImage').mockImplementation(async (_id, file) => images[Number(file.name.split('.')[0])]!)
    await renderDocument()
    await act(async () => {
      state.chat!.onUploadImages(images.map((image) => new File(['pixels'], image.filename, { type: image.content_type })))
    })
    await vi.waitFor(() => expect(state.chat!.imageAttachments).toHaveLength(100))
    await act(async () => { state.chat!.onSend('use these images', [], state.chat!.imageAttachments) })
    expect(state.chat!.imageAttachments).toHaveLength(0)
    await renderDocument(2)
    await act(async () => start.resolve(runInfo(1)))
    expect(chatModule.chatApi.deleteImage).not.toHaveBeenCalled()
    expect(state.chat!.imageAttachments).toHaveLength(0)
    expect(state.chat!.streaming).toBe(false)
  })

  it('ignores a retired stream final event and its cleanup while the new stream runs', async () => {
    const oldStream = deferred<SequencedChatStreamEvent>()
    const newStream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'startChatRun').mockImplementation(async (id) => runInfo(id))
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* (id) {
      yield await (id === 1 ? oldStream.promise : newStream.promise)
    })
    await renderDocument()
    await act(async () => { state.chat!.onSend('old request', [], []) })
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(1))
    await renderDocument(2)
    await act(async () => { state.chat!.onSend('new request', [], []) })
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(2))
    await act(async () => oldStream.resolve(finalEvent(1)))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.streaming).toBe(true)
    expect(state.chat!.messages.every((item) => item.content !== 'done')).toBe(true)
    await act(async () => newStream.resolve(finalEvent(2)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
  })

  it('does not apply a document load that finishes after navigation', async () => {
    const oldLoad = deferred<DocumentDetail>()
    vi.mocked(documentsApi.get).mockImplementation((id) => id === 1 ? oldLoad.promise : Promise.resolve(documentDetail(id)))
    await act(async () => root.render(<EditorPage />))
    await renderDocument(2)
    await act(async () => oldLoad.resolve(documentDetail(1)))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.activeChatSession?.id).toBe(20)
  })

  it('keeps creation visible and prevents a second submission while acceptance is pending', async () => {
    const start = deferred<AgentRunInfo>()
    const create = vi.spyOn(chatModule, 'startChatRun').mockReturnValue(start.promise)
    const stream = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await stream.promise })
    await renderDocument()
    await act(async () => { state.chat!.onSend('long creation', [], []) })
    expect(state.chat!.starting).toBe(true)
    expect(state.chat!.submitting).toBe(true)
    expect(state.chat!.streamNotice).toBeNull()
    await act(async () => { state.chat!.onSend('queued request', [], []) })
    expect(create).toHaveBeenCalledOnce()
    await act(async () => start.resolve(runInfo(1)))
    await vi.waitFor(() => expect(state.chat!.starting).toBe(false))
    expect(state.chat!.streaming).toBe(true)
    expect(state.chat!.submitting).toBe(false)
    // Remove the queued request so completing this run does not start another.
    await act(async () => state.chat!.onRemoveQueuedMessage(state.chat!.queuedMessages[0].id))
    await act(async () => stream.resolve(finalEvent(1)))
  })

  it('honors an explicit stop requested before acceptance even after navigation', async () => {
    const start = deferred<AgentRunInfo>()
    vi.spyOn(chatModule, 'startChatRun').mockReturnValue(start.promise)
    const cancel = vi.spyOn(chatModule, 'cancelChatRun').mockResolvedValue({ ...runInfo(1), status: 'cancelled' })
    await renderDocument()
    await act(async () => { state.chat!.onSend('old request', [], []) })
    await act(async () => { state.chat!.onStop() })
    await renderDocument(2)
    await act(async () => start.resolve({ ...runInfo(1), reask_activation: { archive_id: 1, source_message_id: 1, current_html: '<p>Old activation</p>' } }))
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledWith(1, 'run-1'))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.streaming).toBe(false)
  })

  it('ignores a question-answer response from the previous document', async () => {
    const answer = deferred<AgentRunInfo>()
    vi.mocked(chatModule.chatApi.getActiveRun).mockImplementation(async (id) => id === 1 ? {
      ...runInfo(1), status: 'waiting_for_input', user_question: {
        id: 'question-1', run_id: 'run-1', question: 'Confirm', options: [], allow_multiple: false, include_style: false,
      },
    } : null)
    vi.spyOn(chatModule.chatApi, 'answerUserQuestion').mockReturnValue(answer.promise)
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents')
    await renderDocument()
    await vi.waitFor(() => expect(state.chat!.pendingUserQuestion?.id).toBe('question-1'))
    await act(async () => { state.chat!.onAnswerUserQuestion({ action: 'skip' }) })
    await renderDocument(2)
    await act(async () => answer.resolve(runInfo(1)))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.pendingUserQuestion).toBeNull()
    expect(streams).not.toHaveBeenCalled()
  })

  it('recovers a disconnected stream with the durable event cursor', async () => {
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    let connections = 0
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      connections += 1
      if (connections === 1) {
        yield { event: 'text_delta', data: { text: 'prefix' }, sequence: 7, eventAgeMs: 0 }
        throw new TypeError('Failed to fetch')
      }
      yield { ...finalEvent(1), sequence: 8 }
    })
    await renderDocument()
    await act(async () => { state.chat!.onSend('request', [], []) })
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(2))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(streams.mock.calls[1][2]).toBe(7)
  })

  it('does not reconnect a permanent stream authentication error', async () => {
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      throw new ApiError(403, 'access denied')
    })
    await renderDocument()
    await act(async () => { state.chat!.onSend('request', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(streams).toHaveBeenCalledTimes(1)
  })

  it('does not start a run or apply a pending save after leaving its document', async () => {
    const save = deferred<{ html: string }>()
    const patch = vi.spyOn(documentsApi, 'patchContent').mockImplementation(() => save.promise as ReturnType<typeof documentsApi.patchContent>)
    const start = vi.spyOn(chatModule, 'startChatRun')
    await renderDocument()
    await act(async () => { state.preview!.onHtmlChange?.('<p>Edited old document</p>') })
    await act(async () => { state.chat!.onSend('old request', [], []) })
    await vi.waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    await renderDocument(2)
    await act(async () => save.resolve({ html: '<p>Edited old document</p>' }))
    expect(state.preview!.html).toBe('<p>Document 2</p>')
    expect(state.chat!.streaming).toBe(false)
    expect(start).not.toHaveBeenCalled()
  })
  it('keeps only text IDs in a submitted request and restores attachments after rejection', async () => {
    const text = { id: 'text-1', document_id: 1, session_id: 10, message_id: null, filename: '资料.txt', size: 50000, characters: 20000, lines: 1, sha256: 'abc' }
    vi.spyOn(chatTextsApi, 'upload').mockResolvedValue(text)
    const start = vi.spyOn(chatModule, 'startChatRun').mockRejectedValue(new ApiError(422, 'Rejected'))
    await renderDocument()
    await act(async () => { state.chat!.onPasteText!('PRIVATE_ATTACHMENT_BODY'.repeat(2000)) })
    await vi.waitFor(() => expect(state.chat!.textAttachments?.[0]?.id).toBe('text-1'))
    await act(async () => { state.chat!.onSend('核对资料', [], [], [text]) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(start.mock.calls[0]?.[19]).toEqual(['text-1'])
    expect(JSON.stringify(start.mock.calls)).not.toContain('PRIVATE_ATTACHMENT_BODY')
    expect(state.chat!.textAttachments?.[0]?.id).toBe('text-1')
    expect(JSON.stringify(sessionStorage)).not.toContain('PRIVATE_ATTACHMENT_BODY')
  })

  it('carries uploaded text attachments through a queued request', async () => {
    const text = { id: 'queue-text', document_id: 1, session_id: 10, message_id: null, filename: '队列.txt', size: 50000, characters: 20000, lines: 1, sha256: 'abc' }
    const first = deferred<SequencedChatStreamEvent>(), second = deferred<SequencedChatStreamEvent>()
    vi.spyOn(chatTextsApi, 'upload').mockResolvedValue(text)
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    let calls = 0
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield await (++calls === 1 ? first.promise : second.promise) })
    await renderDocument()
    await act(async () => { state.chat!.onSend('first', [], []) })
    await act(async () => { state.chat!.onPasteText!('正文'.repeat(10000)) })
    await vi.waitFor(() => expect(state.chat!.textAttachments?.[0]?.id).toBe('queue-text'))
    await act(async () => { state.chat!.onSend('queued', [], [], [text]) })
    expect(state.chat!.queuedMessages[0]?.texts?.[0]?.id).toBe('queue-text')
    expect(state.chat!.textAttachments).toHaveLength(0)
    await act(async () => first.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(start).toHaveBeenCalledTimes(2))
    expect(start.mock.calls[1]?.[19]).toEqual(['queue-text'])
    await act(async () => second.resolve(finalEvent(1)))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
  })

  it('shows a recoverable status notice instead of a failed turn when the idle probe disconnects', async () => {
    const probe = vi.mocked(chatModule.chatApi.getActiveRun).mockRejectedValue(new TypeError('Failed to fetch'))
    await renderDocument()
    await vi.waitFor(() => expect(state.chat!.recoveryNotice?.phase).toBe('exhausted'))
    expect(state.chat!.conversationError).toBeNull()
    expect(state.chat!.streaming).toBe(false)
    probe.mockResolvedValue(null)
    await act(async () => { state.chat!.onRetryRecovery!() })
    await vi.waitFor(() => expect(state.chat!.recoveryNotice).toBeNull())
    expect(state.chat!.conversationError).toBeNull()
  })

  it('does not let a late status-probe rejection add an error to another document', async () => {
    let reject!: (error: unknown) => void
    vi.mocked(chatModule.chatApi.getActiveRun).mockImplementation((id) => id === 1
      ? new Promise((_resolve, fail) => { reject = fail }) : Promise.resolve(null))
    await renderDocument()
    await renderDocument(2)
    await act(async () => reject(new TypeError('old disconnected probe')))
    expect(state.chat!.conversationError).toBeNull()
    expect(state.chat!.recoveryNotice).toBeNull()
  })

  it('keeps a completed result and does not restore its request when post-final history refresh fails', async () => {
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () { yield finalEvent(1) })
    await renderDocument()
    vi.mocked(chatModule.chatApi.listRecentMessages).mockRejectedValue(new TypeError('history unavailable'))
    await act(async () => { state.chat!.onContextDraftChange('finish once') })
    await act(async () => { state.chat!.onSend('finish once', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.chat!.conversationError).toBeNull()
    expect(state.chat!.composerDraft).toBe('')
    expect(state.chat!.messages.some(item => item.content === 'done')).toBe(true)
    expect(state.chat!.recoveryNotice?.title).toContain('本轮已结束')
    vi.mocked(chatModule.chatApi.listRecentMessages).mockResolvedValue([])
    await act(async () => { state.chat!.onRetryRecovery!() })
    await vi.waitFor(() => expect(state.chat!.recoveryNotice).toBeNull())
  })

  it('keeps the durable failure and submitted draft when recovering history also fails', async () => {
    const start = vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      yield* []
      throw new TypeError('stream disconnected')
    })
    vi.mocked(chatModule.chatApi.getRun).mockResolvedValue({ ...runInfo(1), status: 'failed', error_message: 'Provider rejected the task' })
    await renderDocument()
    vi.mocked(chatModule.chatApi.listRecentMessages).mockRejectedValue(new TypeError('history unavailable'))
    await act(async () => { state.chat!.onContextDraftChange('failed request') })
    await act(async () => { state.chat!.onSend('failed request', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.chat!.conversationError).toBe('Provider rejected the task')
    expect(state.chat!.composerDraft).toBe('failed request')
    expect(state.chat!.recoveryNotice?.operationId).toBe('history-sync')
    expect(start).toHaveBeenCalledTimes(1)
    expect(streams).toHaveBeenCalledTimes(1)
  })

  it('does not describe a waiting question as a completed run when history sync fails', async () => {
    vi.spyOn(chatModule, 'startChatRun').mockResolvedValue(runInfo(1))
    vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      yield { event: 'user_question', sequence: 1, eventAgeMs: 0, data: {
        id: 'waiting-question', run_id: 'run-1', question: 'Confirm', options: [], allow_multiple: false, include_style: false,
      } }
    })
    await renderDocument()
    vi.mocked(chatModule.chatApi.listRecentMessages).mockRejectedValue(new TypeError('history unavailable'))
    await act(async () => { state.chat!.onSend('request confirmation', [], []) })
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.chat!.pendingUserQuestion?.id).toBe('waiting-question')
    expect(state.chat!.conversationError).toBeNull()
    expect(state.chat!.recoveryNotice?.title).toContain('确认面板已恢复')
  })

  it('allows manual recovery to reconnect a previously resumed run', async () => {
    const probe = vi.mocked(chatModule.chatApi.getActiveRun)
      .mockResolvedValue(runInfo(1))
    const disconnect = deferred<void>()
    let connections = 0
    const streams = vi.spyOn(chatModule, 'streamChatRunEvents').mockImplementation(async function* () {
      if (++connections === 1) {
        await disconnect.promise
        probe.mockRejectedValue(new TypeError('status unavailable'))
        throw new ApiError(403, 'stream access temporarily denied')
      }
      yield finalEvent(1)
    })
    await renderDocument()
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(true))
    await act(async () => disconnect.resolve())
    await vi.waitFor(() => expect(state.chat!.recoveryNotice?.phase).toBe('exhausted'))
    probe.mockResolvedValue(null).mockResolvedValueOnce(runInfo(1))
    await act(async () => { state.chat!.onRetryRecovery!() })
    await vi.waitFor(() => expect(streams).toHaveBeenCalledTimes(2))
    await vi.waitFor(() => expect(state.chat!.streaming).toBe(false))
    expect(state.preview!.html).toBe('<p>Final 1</p>')
    expect(state.chat!.conversationError).toBeNull()
    expect(state.chat!.recoveryNotice).toBeNull()
  })

})
