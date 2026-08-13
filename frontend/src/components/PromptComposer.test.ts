import { describe, expect, it } from 'vitest'
import type { SelectedElementContext } from '../types'
import { resolveOutgoingReferences } from './PromptComposer'

const reference = (selector: string): SelectedElementContext => ({
  selector,
  tag_name: 'img',
  html: `<img src="${selector}.png">`,
  text: '',
})

describe('resolveOutgoingReferences', () => {
  it('keeps selected anchors when a just-selected token has not reached the composer DOM', () => {
    const selected = [reference('article > img:nth-of-type(1)')]

    expect(resolveOutgoingReferences([], selected)).toEqual(selected)
  })

  it('preserves the explicit composer order only after every selected anchor is represented', () => {
    const first = reference('article > img:nth-of-type(1)')
    const second = reference('article > img:nth-of-type(2)')

    expect(resolveOutgoingReferences([second, first], [first, second])).toEqual([second, first])
  })

  it('does not accept a stale duplicate token in place of a different selected anchor', () => {
    const first = reference('article > img:nth-of-type(1)')
    const second = reference('article > img:nth-of-type(2)')

    expect(resolveOutgoingReferences([first, first], [first, second])).toEqual([first, second])
  })
})
