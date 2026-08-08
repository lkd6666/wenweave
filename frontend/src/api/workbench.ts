import { api } from './client'
import type { DocumentGroup, DocumentSummary } from '../types'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface WorkbenchDocument extends DocumentSummary {
  group_name: string | null
}

export interface WorkbenchGroupItem {
  group: DocumentGroup
  document_total: number
  documents: Page<DocumentSummary>
}

export interface WorkbenchGroupedPage {
  groups: Page<WorkbenchGroupItem>
  ungrouped: Page<DocumentSummary>
}

function queryString(values: Record<string, string | number | undefined>) {
  const query = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value))
  })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

export const workbenchApi = {
  groups: (page = 1, pageSize = 10, documentPageSize = 5) =>
    api.get<WorkbenchGroupedPage>(`/workbench/groups${queryString({ page, page_size: pageSize, document_page_size: documentPageSize })}`),
  groupDocuments: (groupId: number, page = 1, pageSize = 5) =>
    api.get<Page<DocumentSummary>>(`/workbench/groups/${groupId}/documents${queryString({ page, page_size: pageSize })}`),
  ungroupedDocuments: (page = 1, pageSize = 5) =>
    api.get<Page<DocumentSummary>>(`/workbench/ungrouped/documents${queryString({ page, page_size: pageSize })}`),
  documents: (page = 1, pageSize = 20, query = '') =>
    api.get<Page<WorkbenchDocument>>(`/workbench/documents${queryString({ page, page_size: pageSize, query })}`),
}
