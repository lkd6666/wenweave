import { expect, it } from 'vitest'
import { shouldAttachPastedText } from './textAttachments'

it('lowers the inline threshold with available model space while leaving short instructions inline', () => {
  expect(shouldAttachPastedText('短指令', 128)).toBe(false)
  expect(shouldAttachPastedText('中'.repeat(300), 128)).toBe(true)
  expect(shouldAttachPastedText('中'.repeat(300), 2000)).toBe(false)
  expect(shouldAttachPastedText('a'.repeat(20000))).toBe(true)
})
