import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { readWordImageOccurrences } from './docxCropMetadata'

describe('readWordImageOccurrences', () => {
  it('keeps image order and converts srcRect values', async () => {
    const zip = new JSZip()
    zip.file('word/document.xml', `
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <w:body><w:p><w:r>
          <w:drawing><pic:pic><pic:blipFill><a:blip r:embed="rId1" /></pic:blipFill></pic:pic></w:drawing>
          <w:drawing><pic:pic><pic:blipFill><a:blip r:embed="rId2" /><a:srcRect l="10000" t="20000" r="30000" b="40000" /></pic:blipFill></pic:pic></w:drawing>
        </w:r></w:p></w:body>
      </w:document>
    `)

    const occurrences = await readWordImageOccurrences(await zip.generateAsync({ type: 'arraybuffer' }))

    expect(occurrences).toEqual([
      { relationshipId: 'rId1', cropRect: null },
      { relationshipId: 'rId2', cropRect: { x: 10000, y: 20000, width: 60000, height: 40000 } },
    ])
  })
})
