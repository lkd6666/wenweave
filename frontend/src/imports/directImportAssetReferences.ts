const DIRECT_IMPORT_ASSET_PATTERN = /direct-import:\/\/asset\/([^\s"'<>`]+)/g

/**
 * Replace complete direct-import asset tokens without treating one client ID as
 * the prefix of another (for example, `word-source-1` and `word-source-10`).
 */
export function replaceDirectImportAssetReferences(html: string, replacements: ReadonlyMap<string, string>): string {
  return html.replace(DIRECT_IMPORT_ASSET_PATTERN, (token, clientId: string) => replacements.get(clientId) ?? token)
}

export function readDirectImportAssetReferences(html: string): string[] {
  return Array.from(html.matchAll(DIRECT_IMPORT_ASSET_PATTERN), (match) => match[1])
}
