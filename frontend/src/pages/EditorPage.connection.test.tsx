// @vitest-environment happy-dom
import { act } from 'react'
import type { ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type ChatPanel from '../components/ChatPanel'
import type PreviewFrame from '../components/PreviewFrame'
import type TemplateLibraryPanel from '../components/TemplateLibraryPanel'
import type { AIModelItem, ChatImageAttachment, ChatSessionItem, DocumentDetail, TemplateItem } from '../types'
import type { AgentRunInfo, SequencedChatStreamEvent } from '../api/chat'
import * as chatModule from '../api/chat'
import { ApiError } from '../api/client'
import { documentsApi } from '../api/documents'
import { modelsApi } from '../api/models'
import { wechatAccountsApi } from '../api/wechatAccounts'
import EditorPage from './EditorPage'

const state = vi.hoisted(() => ({
  documentId: 1,
  chat: null as ComponentProps<typeof ChatPanel> | null,
  preview: null as ComponentProps<typeof PreviewFrame> | null,
  resource: null as ComponentProps<typeof TemplateLibraryPanel> | null,
  navigate: vi.fn(),
}))
vi.mock('react-router', () => ({
  useParams: () => ({ documentId: String(state.documentId) }),
  useNavigate: () => state.navigate,
}))
vi.mock('../components/ChatPanel', () => ({ default: (props: ComponentProps<typeof ChatPanel>) => { state.chat = props; return null } }))
vi.mock('../components/PreviewFrame', () => ({ default: (props: ComponentProps<typeof PreviewFrame>) => { state.preview = props; return null } }))
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
    localStorage.clear()
    state.documentId = 1
    state.chat = null
    state.preview = null
    state.resource = null
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
    await act(async () => state.resource!.onToggleAttach(template))
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
    await act(async () => { state.resource!.onToggleAttach(nextTemplate) })
    await act(async () => { state.resource!.onToggleAttach(nextTemplate) })
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
})
