import { describe, expect, it } from 'vitest'
import { sanitizeSelectedElement } from './selectedElements'

describe('selected element locator sanitization', () => {
  it('keeps structural locator data and redacts inline image sources', () => {
    const result = sanitizeSelectedElement({
      selector: 'p:nth-of-type(1) > img:nth-of-type(1)',
      tag_name: 'img',
      html: '<img src="data:image/png;base64,AAAA">',
      text: '',
      locator: {
        path: 'p:nth-of-type(1) > img:nth-of-type(1)',
        parent_path: 'p:nth-of-type(1)',
        sibling_index: 1,
        fingerprint: {
          tag_name: 'img',
          stable_attributes: { src: 'data:image/png;base64,AAAA', class: 'ignored' },
          text: '',
        },
      },
    })

    expect(result.locator?.path).toBe('p:nth-of-type(1) > img:nth-of-type(1)')
    expect(result.locator?.sibling_index).toBe(1)
    expect(result.locator?.fingerprint.stable_attributes.src).toMatch(
      /^\[inline image data identity:[a-f0-9]{16}\]$/,
    )
    expect(result.html).not.toContain('data:image')
  })
})
