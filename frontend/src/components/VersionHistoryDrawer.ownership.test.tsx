// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { documentsApi } from '../api/documents'
import type { DocumentDetail, DocumentVersionSummary } from '../types'
import VersionHistoryDrawer from './VersionHistoryDrawer'

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return { ...actual, Popconfirm: ({ children, onConfirm }: { children: React.ReactNode; onConfirm: () => void }) => (
    <span onClick={() => onConfirm()}>{children}</span>
  ) }
})

let root: Root
let container: HTMLDivElement
const restored = vi.fn()
const version = (documentId: number): DocumentVersionSummary => ({
  id: documentId * 10, version_number: 1, title: `Document ${documentId}`,
  source: 'manual', label: 'saved', created_at: '', created_by: null,
})

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  restored.mockClear()
  vi.spyOn(documentsApi, 'listVersions').mockImplementation(async (id) => [version(id)])
  vi.spyOn(documentsApi, 'getVersion').mockImplementation(async (id) => ({ ...version(id), html: `<p>${id}</p>` }))
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function render(id: number) {
  await act(async () => root.render(<VersionHistoryDrawer
    documentId={id} open refreshToken={0}
    copyDefaults={{ group_id: null, visibility_mode: 'all', allowed_user_ids: [], allowed_group_ids: [] }}
    onClose={() => {}} onRestored={restored} onCopied={() => {}}
  />))
}

it('does not apply a restored version to a document opened while the request was pending', async () => {
  let finish!: (document: DocumentDetail) => void
  const restore = vi.spyOn(documentsApi, 'restoreVersion').mockReturnValue(new Promise((resolve) => { finish = resolve }))
  await render(1)
  await act(async () => document.body.querySelector<HTMLButtonElement>('[aria-label="恢复版本 v1"]')!.click())
  expect(restore).toHaveBeenCalledExactlyOnceWith(1, 10)
  await render(2)
  await act(async () => finish({ id: 1, title: 'old snapshot', current_html: '<p>old</p>' } as DocumentDetail))
  expect(restored).not.toHaveBeenCalled()
  expect(document.body.textContent).not.toContain('old snapshot')
})
