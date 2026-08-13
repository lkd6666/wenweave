import { describe, expect, it } from 'vitest'
import { prepareWeChatBodyImage, WECHAT_PERMANENT_IMAGE_MAX_BYTES } from './wechatBodyImage'

function imageFile(type: string, size: number, name = 'image'): File {
  return { type, size, name } as File
}

describe('prepareWeChatBodyImage', () => {
  it('keeps an animated GIF as the original file', async () => {
    const gif = imageFile('image/gif', 2 * 1024 * 1024, 'animation.gif')

    const prepared = await prepareWeChatBodyImage(gif)

    expect(prepared.file).toBe(gif)
    expect(prepared.wasCompressed).toBe(false)
    expect(prepared.originalSize).toBe(gif.size)
  })

  it('keeps a CMYK JPEG as the original file', async () => {
    const jpeg = imageFile('image/jpeg', 512 * 1024, 'cmyk-photo.jpg')

    const prepared = await prepareWeChatBodyImage(jpeg)

    expect(prepared.file).toBe(jpeg)
  })

  it('rejects oversized images instead of converting them', async () => {
    const image = imageFile('image/jpeg', WECHAT_PERMANENT_IMAGE_MAX_BYTES + 1, 'large.jpg')

    await expect(prepareWeChatBodyImage(image)).rejects.toThrow('不会自动压缩或转换')
  })
})
