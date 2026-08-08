import { documentsApi, uploadToOss, uploadToServer } from '../api/documents'
import { ApiError } from '../api/client'
import type { DocumentDetail } from '../types'
import { prepareWeChatBodyImage } from '../utils/wechatBodyImage'
import { readDirectImportAssetReferences, replaceDirectImportAssetReferences } from './directImportAssetReferences'
import { parseImportFile } from './documentImportParser'
import type { ImportParseProgress, ParsedImport, ParsedImportAsset } from './types'

export interface DirectImportProgress {
  phase: 'parsing' | 'uploading' | 'finalizing'
  percent: number
  detail: string
}

const RETRY_COUNT = 3
const UPLOAD_CONCURRENCY = 3
/** Keep the parsed asset order while discarding extraction artifacts omitted from the final HTML. */
export function selectReferencedImportAssets(html: string, assets: ParsedImportAsset[]): ParsedImportAsset[] {
  const assetsByClientId = new Map<string, ParsedImportAsset>()
  for (const asset of assets) {
    if (assetsByClientId.has(asset.clientId)) {
      throw new Error(`解析图片标识重复：${asset.clientId}`)
    }
    assetsByClientId.set(asset.clientId, asset)
  }

  const referencedClientIds = new Set<string>()
  for (const clientId of readDirectImportAssetReferences(html)) {
    if (!assetsByClientId.has(clientId)) {
      throw new Error(`正文引用的图片资源不存在：${clientId}`)
    }
    referencedClientIds.add(clientId)
  }
  return assets.filter((asset) => referencedClientIds.has(asset.clientId))
}

async function prepareImportAssetsForWeChat(assets: ParsedImportAsset[], signal?: AbortSignal): Promise<ParsedImportAsset[]> {
  return Promise.all(assets.map(async (asset) => {
    if (signal?.aborted) throw new DOMException('导入已取消', 'AbortError')
    const file = new File([asset.blob], asset.filename, { type: asset.contentType })
    const prepared = await prepareWeChatBodyImage(file)
    return {
      ...asset,
      filename: prepared.file.name,
      contentType: prepared.file.type,
      blob: prepared.file,
    }
  }))
}

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
  throw failure instanceof Error ? failure : new Error('对象存储上传失败')
}

async function uploadToServerWithRetry(
  path: string,
  blob: Blob,
  filename: string,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
) {
  let failure: unknown
  for (let attempt = 1; attempt <= RETRY_COUNT; attempt += 1) {
    try {
      await uploadToServer(path, blob, filename, onProgress, signal)
      return
    } catch (error) {
      failure = error
      if (signal?.aborted || attempt === RETRY_COUNT) break
      await waitForRetry(attempt * 450, signal)
    }
  }
  throw failure instanceof Error ? failure : new Error('服务器上传失败')
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
        detail: `对象存储文件正在同步，正在重试 ${attempt}/${RETRY_COUNT - 1}…`,
      })
      await waitForRetry(attempt * 900, signal)
    }
  }
  throw new Error('导入完成校验失败')
}

async function uploadAssets(
  importId: string,
  assets: ParsedImportAsset[],
  uploadMode: 'oss' | 'server',
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
  if (targets.size !== assets.length) throw new Error('对象存储图片上传授权不完整')

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
      const updateProgress = (percent: number) => {
        const bytes = Math.round((asset.blob.size * percent) / 100)
        loadedByAsset.set(asset.clientId, bytes)
        const loaded = [...loadedByAsset.values()].reduce((total, value) => total + value, 0)
        const verb = uploadMode === 'oss' ? '正在直传图片' : '正在上传图片到服务器'
        onProgress(loaded, totalBytes, `${verb} ${loadedByAsset.size}/${assets.length}…`)
      }
      if (uploadMode === 'oss') {
        if (!target.upload) throw new Error('对象存储图片上传授权不完整')
        await uploadWithRetry(target.upload, asset.blob, updateProgress, signal)
      } else {
        await uploadToServerWithRetry(
          `/documents/imports/${importId}/assets/${target.asset_id}/upload`,
          asset.blob,
          asset.filename,
          updateProgress,
          signal,
        )
      }
      loadedByAsset.set(asset.clientId, asset.blob.size)
      const loaded = [...loadedByAsset.values()].reduce((total, value) => total + value, 0)
      const doneVerb = uploadMode === 'oss' ? '已直传图片' : '已上传图片到服务器'
      onProgress(loaded, totalBytes, `${doneVerb} ${loadedByAsset.size}/${assets.length}`)
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
  preparedImport?: ParsedImport,
): Promise<DocumentDetail> {
  const started = await documentsApi.startDirectImport(file)
  const sourceProgress = (percent: number) => {
    const detail = started.upload_mode === 'oss' ? `正在直传原文件…${percent}%` : `正在上传原文件到服务器…${percent}%`
    onProgress({ phase: 'uploading', percent: Math.round(percent * 0.32), detail })
  }
  const sourceUpload = started.upload_mode === 'oss'
    ? (() => {
        if (!started.source_upload) throw new Error('对象存储原文件上传授权不完整')
        return uploadWithRetry(started.source_upload, file, sourceProgress, signal)
      })()
    : uploadToServerWithRetry(`/documents/imports/${started.id}/source/upload`, file, file.name, sourceProgress, signal)
  const parsed = preparedImport ?? await parseImportFile(file, (progress: ImportParseProgress) => {
    onProgress({ phase: 'parsing', percent: Math.min(58, Math.round(8 + progress.percent * 0.5)), detail: progress.detail })
  }, signal)

  onProgress({ phase: 'uploading', percent: 58, detail: '正在准备公众号正文图片…' })
  const referencedAssets = selectReferencedImportAssets(parsed.html, parsed.assets)
  const uploadAssetsForWechat = await prepareImportAssetsForWeChat(referencedAssets, signal)
  const assetIds = await uploadAssets(started.id, uploadAssetsForWechat, started.upload_mode, (uploaded, total, detail) => {
    const ratio = total === 0 ? 1 : uploaded / total
    onProgress({ phase: 'uploading', percent: 58 + Math.round(ratio * 36), detail })
  }, signal)
  await sourceUpload

  const html = replaceDirectImportAssetReferences(parsed.html, new Map(
    Array.from(assetIds, ([clientId, assetId]) => [clientId, `direct-import://asset/${assetId}`]),
  ))
  onProgress({
    phase: 'finalizing',
    percent: 96,
    detail: started.upload_mode === 'oss' ? '正在校验对象存储文件并创建排版稿…' : '正在校验服务器文件并创建排版稿…',
  })
  const document = await completeWithRetry(started.id, html, onProgress, signal)
  onProgress({ phase: 'finalizing', percent: 100, detail: '导入完成' })
  return document
}
