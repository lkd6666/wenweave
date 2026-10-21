import { Progress } from 'antd'
import type { ImageUploadProgress as UploadState } from '../utils/imageUpload'

export default function ImageUploadProgress({ progress }: { progress: UploadState }) {
  const label = progress.phase === 'complete' ? '上传完成'
    : progress.phase === 'error' ? '上传结束'
      : progress.phase === 'processing' ? '正在保存' : '正在上传'
  return <div className="image-upload-progress" role="status" aria-live="polite" aria-atomic="true">
    <div className="image-upload-progress-header">
      <span>{label} {progress.completed}/{progress.total} 张{progress.failed > 0 ? `，${progress.failed} 张失败` : ''}</span>
      <span>{progress.percent}%</span>
    </div>
    <Progress percent={progress.percent} size="small" showInfo={false} status={progress.phase === 'error' ? 'exception' : progress.phase === 'complete' ? 'success' : 'active'} />
  </div>
}
