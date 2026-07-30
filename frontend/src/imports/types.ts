export interface ParsedImportAsset {
  clientId: string
  filename: string
  contentType: string
  blob: Blob
}

export interface ParsedImport {
  html: string
  assets: ParsedImportAsset[]
  warnings?: string[]
}

export type ImportParseStage = 'reading' | 'parsing' | 'extracting'

export interface ImportParseProgress {
  stage: ImportParseStage
  percent: number
  detail: string
}
