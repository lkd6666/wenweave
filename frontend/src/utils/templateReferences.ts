import type { TemplateItem } from '../types'

export type TemplateReference = Pick<TemplateItem, 'id' | 'name'>

/** @组件N follows the token order in this message, independently of session attachment order. */
export function orderMessageTemplates(available: TemplateItem[], referenceIds: number[]): TemplateItem[] {
  const byId = new Map(available.map(template => [template.id, template]))
  const ids = [...new Set([...referenceIds, ...available.map(template => template.id)])]
  return ids.map(id => {
    const template = byId.get(id)
    if (!template) throw new Error('引用的组件已发生变化，请重新附加后发送')
    return template
  })
}

/** Restore identity without storing component source in browser drafts. */
export function restoreComposerTemplates(references: TemplateReference[] = []): TemplateItem[] {
  return references.map(reference => ({ ...reference, html: '', category_id: null,
    source_type: 'source', image_warnings: [], created_at: '', updated_at: '' }))
}
