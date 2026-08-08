import { afterEach, describe, expect, it, vi } from 'vitest'
import { workbenchApi } from './workbench'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('workbench API', () => {
  it('encodes grouped, ungrouped, and searched pagination requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 20 }), { status: 200 }),
    ))
    vi.stubGlobal('fetch', fetchMock)

    await workbenchApi.groups(2, 10, 50)
    await workbenchApi.groupDocuments(42, 3, 100)
    await workbenchApi.ungroupedDocuments(4, 20)
    await workbenchApi.documents(5, 50, '秋季 活动')

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/workbench/groups?page=2&page_size=10&document_page_size=50',
      '/api/workbench/groups/42/documents?page=3&page_size=100',
      '/api/workbench/ungrouped/documents?page=4&page_size=20',
      '/api/workbench/documents?page=5&page_size=50&query=%E7%A7%8B%E5%AD%A3+%E6%B4%BB%E5%8A%A8',
    ])
  })
})
