interface QueuedChatItem {
  id: string
  content: string
}

export function updateQueuedChatContent<T extends QueuedChatItem>(items: T[], id: string, content: string): T[] {
  let changed = false
  const next = items.map((item) => {
    if (item.id !== id || item.content === content) return item
    changed = true
    return { ...item, content }
  })
  return changed ? next : items
}

export function moveQueuedChatItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (
    fromIndex === toIndex
    || fromIndex < 0
    || toIndex < 0
    || fromIndex >= items.length
    || toIndex >= items.length
  ) return items

  const next = [...items]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return next
}
