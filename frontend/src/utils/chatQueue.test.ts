import { describe, expect, it } from 'vitest'
import { moveQueuedChatItem, updateQueuedChatContent } from './chatQueue'

describe('chat queue helpers', () => {
  const items = [
    { id: 'first', content: '第一项', imageIds: ['image-1'] },
    { id: 'second', content: '第二项', imageIds: [] },
    { id: 'third', content: '第三项', imageIds: [] },
  ]

  it('updates only the queued instruction content', () => {
    const next = updateQueuedChatContent(items, 'first', '更新后的第一项')

    expect(next).toEqual([
      { id: 'first', content: '更新后的第一项', imageIds: ['image-1'] },
      items[1],
      items[2],
    ])
  })

  it('moves a task without mutating its attached data', () => {
    const next = moveQueuedChatItem(items, 2, 0)

    expect(next.map((item) => item.id)).toEqual(['third', 'first', 'second'])
    expect(next[1].imageIds).toEqual(['image-1'])
    expect(moveQueuedChatItem(items, 0, 0)).toBe(items)
    expect(moveQueuedChatItem(items, -1, 1)).toBe(items)
  })
})
