export const MAX_TEXT_ATTACHMENT_BYTES = 2 * 1024 * 1024
export const MAX_TEXT_ATTACHMENTS = 8

/** Conservative UTF-8 estimate: keep clipboard data out of a small context too. */
export function shouldAttachPastedText(text: string, maxInlineTokens = 2000): boolean {
  return new TextEncoder().encode(text).length / 3 > Math.max(128, Math.min(2000, maxInlineTokens))
}

export function pastedTextName(): string {
  return `粘贴文本-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
}
