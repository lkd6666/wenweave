import { api } from './client'
import type { DocumentDetail, DocumentSummary, DocumentVersionDetail, DocumentVersionSummary, VisibilitySettings, VisibilityTargets } from '../types'

export interface DirectUploadTarget {
  object_key: string
  content_type: string
  upload_url: string
  expires_in_seconds: number
}

export interface DirectImportStartResult {
  id: string
  source_type: 'pdf' | 'word'
  source_upload: DirectUploadTarget
  expires_at: string
}

export interface DirectImportAssetInput {
  client_id: string
  filename: string
  content_type: string
  size: number
}

export interface DirectImportAssetUpload {
  client_id: string
  asset_id: string
  upload: DirectUploadTarget
}

export interface DirectImportStatus {
  id: string
  status: 'pending' | 'completed' | 'expired'
  source_upload: DirectUploadTarget | null
  assets: DirectImportAssetUpload[]
  expires_at: string
  document_id: number | null
}

export interface DocumentSourceAccess {
  filename: string
  content_type: string
  size: number
  url: string
  expires_in_seconds: number
}

export function uploadToOss(
  target: DirectUploadTarget,
  body: Blob,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const abort = () => request.abort()
    request.open('PUT', target.upload_url)
    request.setRequestHeader('Content-Type', target.content_type)
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
    }
    request.onload = () => {
      signal?.removeEventListener('abort', abort)
      if (request.status >= 200 && request.status < 300) resolve()
      else reject(new Error(`OSS 上传失败（HTTP ${request.status || '未知'}）`))
    }
    request.onerror = () => {
      signal?.removeEventListener('abort', abort)
      reject(new Error('无法连接到 OSS，请检查 Bucket CORS 配置'))
    }
    request.onabort = () => {
      signal?.removeEventListener('abort', abort)
      reject(new DOMException('上传已取消', 'AbortError'))
    }
    if (signal?.aborted) {
      abort()
      return
    }
    signal?.addEventListener('abort', abort, { once: true })
    request.send(body)
  })
}

export const documentsApi = {
  list: () => api.get<DocumentSummary[]>('/documents'),
  visibilityTargets: () => api.get<VisibilityTargets>('/documents/visibility-targets'),
  create: (title: string, group_id: number | null = null) => api.post<DocumentDetail>('/documents', { title, group_id }),
  get: (id: number) => api.get<DocumentDetail>(`/documents/${id}`),
  update: (id: number, payload: { title?: string; current_html?: string; group_id?: number | null } & Partial<VisibilitySettings>) =>
    api.patch<DocumentDetail>(`/documents/${id}`, payload),
  revertLastAiChange: (id: number) => api.post<DocumentDetail>(`/documents/${id}/revert-last-ai-change`),
  revertToMessage: (id: number, messageId: number) =>
    api.post<DocumentDetail>(`/documents/${id}/revert-to-message`, { message_id: messageId }),
  uploadImage: (id: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload<{ url: string }>(`/documents/${id}/images`, formData)
  },
  startDirectImport: (file: File) =>
    api.post<DirectImportStartResult>('/documents/imports', {
      filename: file.name,
      content_type: file.type || 'application/octet-stream',
      size: file.size,
    }),
  requestDirectImportAssets: (importId: string, assets: DirectImportAssetInput[]) =>
    api.post<{ assets: DirectImportAssetUpload[] }>(`/documents/imports/${importId}/assets`, {
      assets,
    }),
  getDirectImport: (importId: string) => api.get<DirectImportStatus>(`/documents/imports/${importId}`),
  completeDirectImport: (importId: string, payload: { html: string; title?: string; group_id?: number | null }) =>
    api.post<DocumentDetail>(`/documents/imports/${importId}/complete`, payload),
  sourceAccess: (id: number) => api.get<DocumentSourceAccess>(`/documents/${id}/source-access`),
  listVersions: (id: number) => api.get<DocumentVersionSummary[]>(`/documents/${id}/versions`),
  getVersion: (id: number, versionId: number) =>
    api.get<DocumentVersionDetail>(`/documents/${id}/versions/${versionId}`),
  restoreVersion: (id: number, versionId: number) =>
    api.post<DocumentDetail>(`/documents/${id}/versions/${versionId}/restore`),
  remove: (id: number) => api.delete<void>(`/documents/${id}`),
}
