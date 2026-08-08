import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { applyWordImportFormatting, readWordImportFormatting } from './wordImportFormatting'

async function formattingFromXml(documentXml: string, stylesXml: string) {
  const zip = new JSZip()
  zip.file('word/document.xml', documentXml)
  zip.file('word/styles.xml', stylesXml)
  return readWordImportFormatting(await zip.generateAsync({ type: 'arraybuffer' }))
}

describe('Word import formatting', () => {
  it('keeps paragraph and distinct run styles as inline HTML', async () => {
    const formatting = await formattingFromXml(`
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="40" w:after="80"/></w:pPr>
          <w:r><w:rPr><w:rFonts w:eastAsia="Microsoft YaHei"/><w:color w:val="C00000"/><w:sz w:val="28"/></w:rPr><w:t>红色文字</w:t></w:r>
        </w:p>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>标题</w:t></w:r></w:p>
        <w:p>
          <w:r><w:rPr><w:color w:val="FF0000"/></w:rPr><w:t>红</w:t></w:r>
          <w:r><w:rPr><w:color w:val="0000FF"/></w:rPr><w:t>蓝</w:t></w:r>
        </w:p>
      </w:body></w:document>
    `, `
      <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>
        <w:style w:type="paragraph" w:styleId="Heading1"><w:rPr><w:color w:val="175C7A"/><w:sz w:val="30"/></w:rPr></w:style>
      </w:styles>
    `)

    const html = applyWordImportFormatting('<p>红色文字</p><h1>标题</h1><p><strong>红</strong>蓝</p>', formatting)

    expect(html).toContain('text-align:center')
    expect(html).toContain('margin-top:2pt')
    expect(html).toContain('font-family:\'Microsoft YaHei\'')
    expect(html).toContain('color:#C00000')
    expect(html).toContain('<h1 style="font-size:15pt;color:#175C7A">')
    expect(html).toContain('<strong><span style="font-size:11pt;color:#FF0000">红</span></strong><span style="font-size:11pt;color:#0000FF">蓝</span>')
  })
})
