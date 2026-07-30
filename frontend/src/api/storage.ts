import { api } from './client'
import type { StorageConfigItem } from '../types'

export interface UpdateStoragePayload {
  provider: StorageConfigItem['provider']
  endpoint: string
  bucket: string
  access_key_id: string
  access_key_secret?: string
  region_or_zone: string
  upload_endpoint: string
  custom_domain: string
}

export interface StorageTestResult {
  success: boolean
  message: string
}

export interface StorageDirectUploadCheck {
  object_key: string
  upload_url: string
  content_type: string
  upload_method: 'PUT' | 'POST'
  upload_headers: Record<string, string>
  upload_fields: Record<string, string>
  file_field_name: string
  expected_size: number
  expires_in_seconds: number
}

export interface StorageImageRepairResult {
  repaired_count: number
  message: string
}

export interface StorageObjectItem {
  key: string
  name: string
  size: number
  last_modified: string | null
  etag: string
  thumbnail_url: string | null
}

export interface StoragePrefixItem {
  key: string
  name: string
}

export interface StorageObjectListResult {
  objects: StorageObjectItem[]
  prefixes: StoragePrefixItem[]
  next_marker: string | null
}

export interface StorageObjectUrlResult {
  url: string
  expires_in_seconds: number
}

export const storageApi = {
  get: () => api.get<StorageConfigItem>('/storage'),
  update: (payload: UpdateStoragePayload) => api.put<StorageConfigItem>('/storage', payload),
  test: () => api.post<StorageTestResult>('/storage/test'),
  startDirectUploadCheck: () => api.post<StorageDirectUploadCheck>('/storage/direct-upload-check'),
  verifyDirectUploadCheck: (objectKey: string) =>
    api.post<StorageTestResult>('/storage/direct-upload-check/verify', { object_key: objectKey }),
  repairImageAccess: () => api.post<StorageImageRepairResult>('/storage/repair-image-access'),
  listObjects: (prefix = '', marker = '') =>
    api.get<StorageObjectListResult>(`/storage/objects?prefix=${encodeURIComponent(prefix)}&marker=${encodeURIComponent(marker)}`),
  previewObject: (objectKey: string) =>
    api.get<StorageObjectUrlResult>(`/storage/objects/${encodeURIComponent(objectKey)}/preview`),
  removeObject: (objectKey: string) => api.delete<void>(`/storage/objects/${encodeURIComponent(objectKey)}`),
  uploadObject: (file: File, prefix = '') => {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload<StorageObjectItem>(`/storage/objects/upload?prefix=${encodeURIComponent(prefix)}`, formData)
  },
}
