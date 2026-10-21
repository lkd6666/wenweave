import type { UploadProgress } from '../api/client'

export interface ImageUploadProgress {
  total: number
  completed: number
  failed: number
  percent: number
  phase: 'uploading' | 'processing' | 'complete' | 'error'
}

interface ImageUploadTask<T> {
  size: number
  count?: number
  run: (onProgress: (progress: UploadProgress) => void) => Promise<T>
}

export async function runImageUploads<T>(
  tasks: ImageUploadTask<T>[],
  onProgress: (progress: ImageUploadProgress) => void,
  concurrency = 4,
): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = new Array(tasks.length)
  const sizes = tasks.map((task) => Math.max(1, task.size))
  const counts = tasks.map((task) => Math.max(1, task.count ?? 1))
  const loaded = tasks.map(() => 0)
  const totalBytes = sizes.reduce((sum, size) => sum + size, 0)
  const total = counts.reduce((sum, count) => sum + count, 0)
  let completed = 0
  let failed = 0
  let next = 0
  const report = () => {
    const bytes = loaded.reduce((sum, size) => sum + size, 0)
    const settled = completed + failed === total
    onProgress({
      total, completed, failed,
      percent: settled && failed === 0 ? 100 : Math.min(99, Math.floor(bytes / Math.max(1, totalBytes) * 100)),
      phase: settled ? failed ? 'error' : 'complete' : bytes >= totalBytes ? 'processing' : 'uploading',
    })
  }
  if (!tasks.length) return results
  report()
  async function worker() {
    while (next < tasks.length) {
      const index = next++
      try {
        const value = await tasks[index]!.run((progress) => {
          loaded[index] = progress.total > 0 ? sizes[index]! * Math.min(1, Math.max(0, progress.loaded / progress.total)) : 0
          report()
        })
        loaded[index] = sizes[index]!
        completed += counts[index]!
        results[index] = { status: 'fulfilled', value }
      } catch (reason) {
        failed += counts[index]!
        results[index] = { status: 'rejected', reason }
      }
      report()
    }
  }
  await Promise.all(Array.from({ length: Math.min(tasks.length, Math.max(1, Math.floor(concurrency))) }, worker))
  return results
}
