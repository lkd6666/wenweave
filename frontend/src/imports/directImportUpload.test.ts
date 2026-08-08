import { describe, expect, it } from 'vitest'
import { selectReferencedImportAssets } from './directImportUpload'
import type { ParsedImportAsset } from './types'

const asset = (clientId: string): ParsedImportAsset => ({
  clientId,
  filename: `${clientId}.png`,
  contentType: 'image/png',
  blob: new Blob(['image'], { type: 'image/png' }),
})

describe('selectReferencedImportAssets', () => {
  it('keeps only assets referenced by the final HTML in parsed order', () => {
    const source = asset('word-source-1')
    const unused = asset('word-source-2')
    const crop = asset('word-crop-1')

    const selected = selectReferencedImportAssets(
      '<img src="direct-import://asset/word-crop-1" data-crop-source="direct-import://asset/word-source-1" />' +
        '<img src="direct-import://asset/word-crop-1" />',
      [source, unused, crop],
    )

    expect(selected).toEqual([source, crop])
  })

  it('rejects an HTML placeholder with no parsed image', () => {
    expect(() => selectReferencedImportAssets(
      '<img src="direct-import://asset/missing-image" />',
      [asset('word-source-1')],
    )).toThrow('正文引用的图片资源不存在：missing-image')
  })
})
