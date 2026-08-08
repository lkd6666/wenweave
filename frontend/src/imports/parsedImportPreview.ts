import type { ParsedImport } from './types'
import { replaceDirectImportAssetReferences } from './directImportAssetReferences'

export interface ParsedImportPreview {
  html: string
  revoke: () => void
}

export function createParsedImportPreview(parsed: ParsedImport): ParsedImportPreview {
  const urls = parsed.assets.map((asset) => ({
    clientId: asset.clientId,
    url: URL.createObjectURL(asset.blob),
  }))
  const html = replaceDirectImportAssetReferences(parsed.html, new Map(
    urls.map((asset) => [asset.clientId, asset.url]),
  ))
  return {
    html,
    revoke: () => urls.forEach((asset) => URL.revokeObjectURL(asset.url)),
  }
}
