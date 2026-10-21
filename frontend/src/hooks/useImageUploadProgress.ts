import { useEffect, useState } from 'react'
import type { ImageUploadProgress } from '../utils/imageUpload'

export default function useImageUploadProgress() {
  const [progress, setProgress] = useState<ImageUploadProgress | null>(null)

  useEffect(() => {
    if (progress?.phase !== 'complete') return
    const timer = window.setTimeout(() => {
      setProgress((current) => current === progress ? null : current)
    }, 1500)
    return () => window.clearTimeout(timer)
  }, [progress])

  return [progress, setProgress] as const
}
