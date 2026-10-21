// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import useImageUploadProgress from './useImageUploadProgress'
import ImageUploadProgress from '../components/ImageUploadProgress'
import type { ImageUploadProgress as UploadState } from '../utils/imageUpload'

describe('completed upload progress', () => {
  let container: HTMLDivElement
  let root: Root
  let update: ReturnType<typeof useImageUploadProgress>[1]
  const complete: UploadState = { total: 1, completed: 1, failed: 0, percent: 100, phase: 'complete' }

  function Harness() {
    const [progress, setProgress] = useImageUploadProgress()
    update = setProgress
    return progress ? <ImageUploadProgress progress={progress} /> : null
  }

  beforeEach(async () => {
    vi.useFakeTimers()
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    await act(async () => root.render(<Harness />))
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows success briefly then removes the progress indicator', async () => {
    await act(async () => update(complete))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('上传完成 1/1 张')
    await act(async () => vi.advanceTimersByTime(1499))
    expect(container.querySelector('[role="status"]')).not.toBeNull()
    await act(async () => vi.advanceTimersByTime(1))
    expect(container.querySelector('[role="status"]')).toBeNull()
  })

  it('does not let the previous completion timer hide a new upload', async () => {
    await act(async () => update(complete))
    await act(async () => vi.advanceTimersByTime(1000))
    await act(async () => update({ ...complete, completed: 0, percent: 20, phase: 'uploading' }))
    await act(async () => vi.advanceTimersByTime(2000))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('正在上传')
    await act(async () => update(complete))
    await act(async () => vi.advanceTimersByTime(1500))
    expect(container.querySelector('[role="status"]')).toBeNull()
  })

  it('keeps failure details visible and clears timers when unmounted', async () => {
    await act(async () => update({ ...complete, completed: 0, failed: 1, phase: 'error' }))
    await act(async () => vi.advanceTimersByTime(3000))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('1 张失败')
    await act(async () => update(complete))
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    await act(async () => root.render(null))
    expect(vi.getTimerCount()).toBe(0)
  })
})
