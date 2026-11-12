import { describe, expect, it } from 'vitest'
import type { TemplateItem } from '../types'
import { orderMessageTemplates, restoreComposerTemplates } from './templateReferences'

const header = { id: 10, name: '排版头', html: '<h1>Header</h1>' } as TemplateItem
const footer = { id: 20, name: '排版尾', html: '<footer>Footer</footer>' } as TemplateItem

describe('message template identity', () => {
  it('makes the explicitly referenced footer component 1 while retaining session resources', () => {
    expect(orderMessageTemplates([header, footer], [footer.id])).toEqual([footer, header])
    expect(orderMessageTemplates([header, footer], [footer.id, header.id])).toEqual([footer, header])
    expect(orderMessageTemplates([header, footer], [])).toEqual([header, footer])
  })

  it('never substitutes a different component for a missing ID', () => {
    expect(() => orderMessageTemplates([header], [footer.id])).toThrow('重新附加')
  })

  it('rehydrates the same reference even after it is removed from session context', () => {
    const restored = restoreComposerTemplates([{ id: footer.id, name: footer.name }])
    expect(restored[0]).toMatchObject({ id: footer.id, name: footer.name, html: '' })
    expect(orderMessageTemplates([...restored, header], [footer.id]).map(item => item.id)).toEqual([20, 10])
  })
})
