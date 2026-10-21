import { describe, expect, it, vi } from 'vitest'
import { runImageUploads } from './imageUpload'
import type { ImageUploadProgress } from './imageUpload'
import type { UploadProgress } from '../api/client'

describe('image upload batches', () => {
  it('weights transfer progress by bytes and waits for saving before reaching 100 percent', async () => {
    let transfer!: (progress: UploadProgress) => void
    let finish!: (value: string[]) => void
    const states: ImageUploadProgress[] = []
    const pending = runImageUploads([{ size: 1000, count: 100, run: (onProgress) => {
      transfer = onProgress
      return new Promise<string[]>((resolve) => { finish = resolve })
    } }], (state) => states.push(state))
    transfer({ loaded: 500, total: 1000 })
    expect(states.at(-1)).toEqual({ total: 100, completed: 0, failed: 0, percent: 50, phase: 'uploading' })
    transfer({ loaded: 1000, total: 1000 })
    expect(states.at(-1)).toEqual({ total: 100, completed: 0, failed: 0, percent: 99, phase: 'processing' })
    finish(['saved'])
    await pending
    expect(states.at(-1)).toEqual({ total: 100, completed: 100, failed: 0, percent: 100, phase: 'complete' })
  })

  it('bounds concurrency and returns all one hundred results in selection order', async () => {
    let active = 0
    let peak = 0
    const states: ImageUploadProgress[] = []
    const result = await runImageUploads(Array.from({ length: 100 }, (_, i) => ({ size: 10, run: async () => {
      active += 1
      peak = Math.max(peak, active)
      await new Promise((resolve) => setTimeout(resolve, i % 4))
      active -= 1
      return i
    } })), (state) => states.push(state))
    expect(peak).toBe(4)
    expect(result).toEqual(Array.from({ length: 100 }, (_, value) => ({ status: 'fulfilled', value })))
    expect(states.at(-1)?.completed).toBe(100)
    expect(states.at(-1)?.phase).toBe('complete')
  })

  it('records partial failures and continues the rest of the batch', async () => {
    const onProgress = vi.fn()
    const result = await runImageUploads([
      { size: 10, run: async () => 'first' },
      { size: 90, run: async (progress) => { progress({ loaded: 45, total: 90 }); throw new Error('connection lost') } },
      { size: 10, run: async () => 'last' },
    ], onProgress)
    expect(result.map((item) => item.status)).toEqual(['fulfilled', 'rejected', 'fulfilled'])
    expect(onProgress).toHaveBeenLastCalledWith({ total: 3, completed: 2, failed: 1, percent: 59, phase: 'error' })
  })
})
