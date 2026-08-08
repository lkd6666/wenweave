import { describe, expect, it } from 'vitest'
import { readDirectImportAssetReferences, replaceDirectImportAssetReferences } from './directImportAssetReferences'

describe('direct import asset references', () => {
  const html = [
    '<img src="direct-import://asset/word-source-1" />',
    '<img src="direct-import://asset/word-source-10" />',
    '<img src="direct-import://asset/word-source-11" />',
  ].join('')

  it('reads complete client IDs when one is another ID prefix', () => {
    expect(readDirectImportAssetReferences(html)).toEqual([
      'word-source-1',
      'word-source-10',
      'word-source-11',
    ])
  })

  it('replaces only complete asset tokens', () => {
    const replaced = replaceDirectImportAssetReferences(html, new Map([
      ['word-source-1', 'blob:http://localhost:5173/image-1'],
      ['word-source-10', 'blob:http://localhost:5173/image-10'],
      ['word-source-11', 'blob:http://localhost:5173/image-11'],
    ]))

    expect(replaced).toBe([
      '<img src="blob:http://localhost:5173/image-1" />',
      '<img src="blob:http://localhost:5173/image-10" />',
      '<img src="blob:http://localhost:5173/image-11" />',
    ].join(''))
  })
})
