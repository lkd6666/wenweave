import { documentsApi, uploadToOss } from '../api/documents'
import { ApiError } from '../api/client'
import type { DocumentDetail } from '../types'
import { parseImportFile } from './documentImportParser'
import type { ImportParseProgress, ParsedImportAsset } from './types'

export interface DirectImportProgress {
  phase: 'parsing' | 'uploading' | 'finalizing'
  percent: number
  detail: string
}

const RETRY_COUNT = 3
const UPLOAD_CONCURRENCY = 3

function waitForRetry(delay: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(cleanupAndResolve, delay)
    const abort = () => {
      window.clearTimeout(timer)
      cleanup()
      reject(new DOMException('导入已取消', 'AbortError'))
    }
    const cleanup = () => signal?.removeEventListener('abort', abort)
    function cleanupAndResolve() {
      cleanup()
      resolve()
    }
    if (signal?.aborted) {
      abort()
      return
    }
    signal?.addEventListener('abort', abort, { once: true })
  })
}

async function uploadWithRetry(
  target: Parameters<typeof uploadToOss>[0],
  blob: Blob,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
) {
  let failure: unknown
  for (let attempt = 1; attempt <= RETRY_COUNT; attempt += 1) {
    try {
      await uploadToOss(target, blob, onProgress, signal)
      return
    } catch (error) {
      failure = error
      if (signal?.aborted || attempt === RETRY_COUNT) break
      await waitForRetry(attempt * 450, signal)
    }
  }
  throw failure instanceof Error ? failure : new Error('OSS 上传失败')
}

async function completeWithRetry(
  importId: string,
  html: string,
  onProgress: (progress: DirectImportProgress) => void,
  signal?: AbortSignal,
) {
  for (let attempt = 1; attempt <= RETRY_COUNT; attempt += 1) {
    try {
      return await documentsApi.completeDirectImport(importId, { html })
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409 || attempt === RETRY_COUNT) throw error
      onProgress({
        phase: 'finalizing',
        percent: 96,
        detail: `OSS 文件正在同步，正在重试 ${attempt}/${RETRY_COUNT - 1}…`,
      })
      await waitForRetry(attempt * 900, signal)
    }
  }
  throw new Error('导入完成校验失败')
}

async function uploadAssets(
  importId: string,
  assets: ParsedImportAsset[],
  onProgress: (uploadedBytes: number, totalBytes: number, detail: string) => void,
  signal?: AbortSignal,
) {
  if (assets.length === 0) return new Map<string, string>()
  const result = await documentsApi.requestDirectImportAssets(
    importId,
    assets.map((asset) => ({
      client_id: asset.clientId,
      filename: asset.filename,
      content_type: asset.contentType,
      size: asset.blob.size,
    })),
  )
  const targets = new Map(result.assets.map((asset) => [asset.client_id, asset]))
  if (targets.size !== assets.length) throw new Error('OSS 图片上传授权不完整')

  const totalBytes = assets.reduce((total, asset) => total + asset.blob.size, 0)
  const loadedByAsset = new Map<string, number>()
  const clientToAssetId = new Map<string, string>()
  let cursor = 0
  const worker = async () => {
    while (cursor < assets.length) {
      const asset = assets[cursor]
      cursor += 1
      const target = targets.get(asset.clientId)
      if (!target) throw new Error('找不到图片上传授权')
      await uploadWithRetry(target.upload, asset.blob, (percent) => {
        const bytes = Math.round((asset.blob.size * percent) / 100)
        loadedByAsset.set(asset.clientId, bytes)
        const loaded = [...loadedByAsset.values()].reduce((total, value) => total + value, 0)
        onProgress(loaded, totalBytes, `正在直传图片 ${loadedByAsset.size}/${assets.length}…`)
      }, signal)
      loadedByAsset.set(asset.clientId, asset.blob.size)
      const loaded = [...loadedByAsset.values()].reduce((total, value) => total + value, 0)
      onProgress(loaded, totalBytes, `已直传图片 ${loadedByAsset.size}/${assets.length}`)
      clientToAssetId.set(asset.clientId, target.asset_id)
    }
  }
  await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, assets.length) }, worker))
  return clientToAssetId
}

export async function importDocumentDirectly(
  file: File,
  onProgress: (progress: DirectImportProgress) => void,
  signal?: AbortSignal,
): Promise<DocumentDetail> {
  const started = await documentsApi.startDirectImport(file)
  const sourceUpload = uploadWithRetry(started.source_upload, file, (percent) => {
    onProgress({ phase: 'uploading', percent: Math.round(percent * 0.32), detail: `正在直传原文件…${percent}%` })
  }, signal)
  const parsed = await parseImportFile(file, (progress: ImportParseProgress) => {
    onProgress({ phase: 'parsing', percent: Math.min(58, Math.round(8 + progress.percent * 0.5)), detail: progress.detail })
  }, signal)

  const assetIds = await uploadAssets(started.id, parsed.assets, (uploaded, total, detail) => {
    const ratio = total === 0 ? 1 : uploaded / total
    onProgress({ phase: 'uploading', percent: 58 + Math.round(ratio * 36), detail })
  }, signal)
  await sourceUpload

  let html = parsed.html
  for (const [clientId, assetId] of assetIds) {
    html = html.split(`direct-import://asset/${clientId}`).join(`direct-import://asset/${assetId}`)
  }
  onProgress({ phase: 'finalizing', percent: 96, detail: '正在校验 OSS 文件并创建排版稿…' })
  const document = await completeWithRetry(started.id, html, onProgress, signal)
  onProgress({ phase: 'finalizing', percent: 100, detail: '导入完成' })
  return document
}
