import type { ParsedImport } from './types'

export interface ParsedImportPreview {
  html: string
  revoke: () => void
}

export function createParsedImportPreview(parsed: ParsedImport): ParsedImportPreview {
  const urls = parsed.assets.map((asset) => ({
    clientId: asset.clientId,
    url: URL.createObjectURL(asset.blob),
  }))
  let html = parsed.html
  for (const asset of urls) {
    html = html.split(`direct-import://asset/${asset.clientId}`).join(asset.url)
  }
  return {
    html,
    revoke: () => urls.forEach((asset) => URL.revokeObjectURL(asset.url)),
  }
}
