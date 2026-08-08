import { ApiError, api, apiEventStream } from './client'
import type { DocumentDetail, DocumentShareRecord, DocumentShareVisitList, DocumentSummary, DocumentVersionDetail, DocumentVersionSummary, VisibilitySettings, VisibilityTargets, WeChatArticleMetadata, WeChatDraftRecord, WeChatDraftTarget } from '../types'
import { useAuthStore } from '../store/authStore'

export interface DirectUploadTarget {
  object_key: string
  content_type: string
  upload_url: string
  upload_method: 'PUT' | 'POST'
  upload_headers: Record<string, string>
  upload_fields: Record<string, string>
  file_field_name: string
  expires_in_seconds: number
}

export interface DirectImportStartResult {
  id: string
  source_type: 'pdf' | 'word' | 'markdown'
  upload_mode: 'oss' | 'server'
  source_upload: DirectUploadTarget | null
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
  upload: DirectUploadTarget | null
}

export interface DirectImportStatus {
  id: string
  status: 'pending' | 'completed' | 'expired'
  upload_mode: 'oss' | 'server'
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

export interface WebArticleImportPreview {
  id: string
  title: string
  preview_html: string
  cover_preview_url: string | null
  cover_requires_crops: boolean
  image_count: number
  imported_image_count: number
  external_image_count: number
  warnings: string[]
  expires_at: string
}

export interface DocumentHtmlPatch {
  base_checksum: string
  prefix_length: number
  suffix_length: number
  replacement: string
}

export interface DocumentImageLocalizationResult {
  html: string
  localized_count: number
}

export interface WeChatDraftPushProgressEvent {
  stage: 'validating' | 'metadata' | 'token' | 'body-images' | 'cover' | 'draft' | 'history' | 'completed'
  percent: number
  detail: string
}

export type DocumentVersionCopyPayload = {
  title: string
  group_id: number | null
} & VisibilitySettings

export function uploadToOss(
  target: DirectUploadTarget,
  body: Blob,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const abort = () => request.abort()
    request.open(target.upload_method, target.upload_url)
    Object.entries(target.upload_headers).forEach(([name, value]) => request.setRequestHeader(name, value))
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
    }
    request.onload = () => {
      signal?.removeEventListener('abort', abort)
      if (request.status >= 200 && request.status < 300) resolve()
      else reject(new Error(`对象存储上传失败（HTTP ${request.status || '未知'}）`))
    }
    request.onerror = () => {
      signal?.removeEventListener('abort', abort)
      reject(new Error('无法连接到对象存储，请检查 Bucket CORS 配置'))
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
    if (target.upload_method === 'POST') {
      const formData = new FormData()
      Object.entries(target.upload_fields).forEach(([name, value]) => formData.append(name, value))
      formData.append(target.file_field_name || 'file', body, target.object_key.split('/').pop() || 'upload')
      request.send(formData)
    } else {
      request.send(body)
    }
  })
}

export function uploadToServer(
  path: string,
  body: Blob,
  filename: string,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const abort = () => request.abort()
    const formData = new FormData()
    formData.append('file', body, filename)
    request.open('POST', `/api${path}`)
    const token = useAuthStore.getState().token
    if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
    }
    request.onload = () => {
      signal?.removeEventListener('abort', abort)
      if (request.status >= 200 && request.status < 300) {
        resolve()
        return
      }
      try {
        const response = JSON.parse(request.responseText) as { detail?: unknown }
        reject(new Error(typeof response.detail === 'string' ? response.detail : `服务器上传失败（HTTP ${request.status}）`))
      } catch {
        reject(new Error(`服务器上传失败（HTTP ${request.status || '未知'}）`))
      }
    }
    request.onerror = () => {
      signal?.removeEventListener('abort', abort)
      reject(new Error('无法连接到应用服务器'))
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
    request.send(formData)
  })
}

export const documentsApi = {
  list: () => api.get<DocumentSummary[]>('/documents'),
  aiEditingStatus: () => api.get<{ active_document_ids: number[] }>('/documents/ai-editing-status'),
  visibilityTargets: () => api.get<VisibilityTargets>('/documents/visibility-targets'),
  create: (title: string, group_id: number | null = null) => api.post<DocumentDetail>('/documents', { title, group_id }),
  get: (id: number) => api.get<DocumentDetail>(`/documents/${id}`),
  update: (id: number, payload: { title?: string; current_html?: string; group_id?: number | null; wechat_metadata?: WeChatArticleMetadata } & Partial<VisibilitySettings>) =>
    api.patch<DocumentDetail>(`/documents/${id}`, payload),
  patchContent: (id: number, payload: DocumentHtmlPatch) =>
    api.patch<void>(`/documents/${id}/content`, payload),
  revertLastAiChange: (id: number) => api.post<DocumentDetail>(`/documents/${id}/revert-last-ai-change`),
  revertToMessage: (id: number, messageId: number) =>
    api.post<DocumentDetail>(`/documents/${id}/revert-to-message`, { message_id: messageId }),
  uploadImage: (id: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload<{ url: string }>(`/documents/${id}/images`, formData)
  },
  fetchCropSource: (source: string, signal?: AbortSignal) =>
    api.blob(`/documents/crop-source?url=${encodeURIComponent(source)}`, { signal }),
  materializeTemplateImages: (documentId: number, templateId: number) =>
    api.post<DocumentImageLocalizationResult>(`/documents/${documentId}/templates/${templateId}/materialize-images`, {}),
  localizeExternalImages: (documentId: number) =>
    api.post<DocumentImageLocalizationResult>(`/documents/${documentId}/images/localize-external`, {}),
  uploadWeChatCover: (id: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload<{ url: string }>(`/documents/${id}/wechat-cover`, formData)
  },
  listWeChatDrafts: (id: number) => api.get<WeChatDraftRecord[]>(`/documents/${id}/wechat-drafts`),
  listWeChatDraftTargets: (id: number, accountId: number) =>
    api.get<WeChatDraftTarget[]>(`/documents/${id}/wechat-drafts/targets?account_id=${encodeURIComponent(accountId)}`),
  createWeChatDraft: (id: number, payload: { accountId: number; syncMode: 'auto' | 'create' | 'update'; targetMediaId?: string }) =>
    api.post<WeChatDraftRecord>(`/documents/${id}/wechat-drafts`, {
      account_id: payload.accountId,
      sync_mode: payload.syncMode,
      target_media_id: payload.targetMediaId ?? '',
    }),
  streamWeChatDraft: async (
    id: number,
    payload: { accountId: number; syncMode: 'auto' | 'create' | 'update'; targetMediaId?: string },
    onProgress: (event: WeChatDraftPushProgressEvent) => void,
  ): Promise<WeChatDraftRecord> => {
    let result: WeChatDraftRecord | null = null
    let streamError: ApiError | null = null
    await apiEventStream(`/documents/${id}/wechat-drafts/stream`, {
      body: {
        account_id: payload.accountId,
        sync_mode: payload.syncMode,
        target_media_id: payload.targetMediaId ?? '',
      },
      onEvent: (event, data) => {
        if (event === 'progress') {
          onProgress(data as WeChatDraftPushProgressEvent)
          return
        }
        if (event === 'result') {
          result = data as WeChatDraftRecord
          return
        }
        if (event === 'error') {
          const error = data as { status?: number; detail?: unknown }
          streamError = new ApiError(error.status ?? 502, error.detail ?? '创建公众号草稿失败')
        }
      },
    })
    if (streamError) throw streamError
    if (!result) throw new ApiError(502, '推送进度连接已结束，但未收到草稿结果')
    return result
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
  previewWebArticleImport: (url: string) =>
    api.post<WebArticleImportPreview>('/documents/link-imports/preview', { url }),
  completeWebArticleImport: (importId: string) =>
    api.post<DocumentDetail>(`/documents/link-imports/${importId}/complete`, {}),
  cancelWebArticleImport: (importId: string) => api.delete<void>(`/documents/link-imports/${importId}`),
  sourceAccess: (id: number) => api.get<DocumentSourceAccess>(`/documents/${id}/source-access`),
  listVersions: (id: number) => api.get<DocumentVersionSummary[]>(`/documents/${id}/versions`),
  getVersion: (id: number, versionId: number) =>
    api.get<DocumentVersionDetail>(`/documents/${id}/versions/${versionId}`),
  restoreVersion: (id: number, versionId: number) =>
    api.post<DocumentDetail>(`/documents/${id}/versions/${versionId}/restore`),
  copyVersion: (id: number, versionId: number, payload: DocumentVersionCopyPayload) =>
    api.post<DocumentDetail>(`/documents/${id}/versions/${versionId}/copy`, payload),
  listShares: (id: number) => api.get<DocumentShareRecord[]>(`/documents/${id}/shares`),
  createShare: (id: number, expiresAt: string) => api.post<DocumentShareRecord>(`/documents/${id}/shares`, { expires_at: expiresAt }),
  updateShare: (id: number, shareId: number, expiresAt: string) =>
    api.patch<DocumentShareRecord>(`/documents/${id}/shares/${shareId}`, { expires_at: expiresAt }),
  revokeShare: (id: number, shareId: number) => api.post<DocumentShareRecord>(`/documents/${id}/shares/${shareId}/revoke`),
  listShareVisits: (id: number, shareId: number, page = 1, pageSize = 30) =>
    api.get<DocumentShareVisitList>(`/documents/${id}/shares/${shareId}/visits?page=${page}&page_size=${pageSize}`),
  remove: (id: number) => api.delete<void>(`/documents/${id}`),
}
