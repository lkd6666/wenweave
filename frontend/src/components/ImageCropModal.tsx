import { useEffect, useMemo, useState } from 'react'
import ReactCrop, { type Crop, type PercentCrop } from 'react-image-crop'
import 'react-image-crop/dist/ReactCrop.css'
import { Button, InputNumber, Modal, Segmented, Space, Spin } from 'antd'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'
import type { CropRect } from '../utils/imageCrop'
import { FULL_CROP_RECT, cropPercentagesToRect, cropRectToPercentages, normalizeCropRect } from '../utils/imageCrop'
import { transformImageBlob } from '../utils/imageTransform'

type AspectPreset = 'free' | 'square' | 'fourThree' | 'sixteenNine' | 'custom'

interface ImageCropModalProps {
  open: boolean
  source: Blob
  initialRect: CropRect | null
  initialRotationDegrees: number
  saving: boolean
  onCancel: () => void
  onApply: (rect: CropRect, rotationDegrees: number) => void
  onReset: (() => void) | null
}

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value))

function percentCrop(rect: CropRect): PercentCrop {
  return { unit: '%', ...cropRectToPercentages(rect) }
}

function aspectForPreset(preset: AspectPreset, customWidth: number, customHeight: number): number | undefined {
  if (preset === 'square') return 1
  if (preset === 'fourThree') return 4 / 3
  if (preset === 'sixteenNine') return 16 / 9
  if (preset === 'custom' && customWidth > 0 && customHeight > 0) return customWidth / customHeight
  return undefined
}

function constrainToAspect(crop: PercentCrop, aspect: number | undefined): PercentCrop {
  if (!aspect || crop.width <= 0 || crop.height <= 0) return crop
  let width = crop.width
  let height = width / aspect
  if (height > 100 - crop.y) {
    height = 100 - crop.y
    width = height * aspect
  }
  if (width > 100 - crop.x) {
    width = 100 - crop.x
    height = width / aspect
  }
  return {
    unit: '%',
    x: clamp(crop.x, 0, 100),
    y: clamp(crop.y, 0, 100),
    width: clamp(width, 0.1, 100),
    height: clamp(height, 0.1, 100),
  }
}

export default function ImageCropModal({
  open,
  source,
  initialRect,
  initialRotationDegrees,
  saving,
  onCancel,
  onApply,
  onReset,
}: ImageCropModalProps) {
  const normalizedInitial = useMemo(() => normalizeCropRect(initialRect) ?? FULL_CROP_RECT, [initialRect])
  const [preset, setPreset] = useState<AspectPreset>('free')
  const [customWidth, setCustomWidth] = useState(4)
  const [customHeight, setCustomHeight] = useState(3)
  const [crop, setCrop] = useState<PercentCrop>(() => percentCrop(normalizedInitial))
  const [rotationDegrees, setRotationDegrees] = useState(initialRotationDegrees)
  const [previewUrl, setPreviewUrl] = useState('')
  const [preparingPreview, setPreparingPreview] = useState(false)
  const [previewError, setPreviewError] = useState('')

  useEffect(() => {
    if (!open) return
    setPreset('free')
    setCrop(percentCrop(normalizedInitial))
    setRotationDegrees(initialRotationDegrees)
  }, [initialRotationDegrees, normalizedInitial, open, source])

  useEffect(() => {
    let cancelled = false
    let url = ''
    setPreparingPreview(true)
    setPreviewUrl('')
    setPreviewError('')
    void (async () => {
      try {
        const preview = rotationDegrees ? await transformImageBlob(source, { rotationDegrees }) : source
        if (cancelled) return
        url = URL.createObjectURL(preview)
        setPreviewUrl(url)
      } catch (error) {
        if (!cancelled) setPreviewError(error instanceof Error ? error.message : '无法生成旋转后的图片预览')
      } finally {
        if (!cancelled) setPreparingPreview(false)
      }
    })()
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [rotationDegrees, source])

  const aspect = aspectForPreset(preset, customWidth, customHeight)
  const setCropPreset = (nextPreset: AspectPreset) => {
    setPreset(nextPreset)
    setCrop((current) => constrainToAspect(current, aspectForPreset(nextPreset, customWidth, customHeight)))
  }
  const updateCustomRatio = (width: number, height: number) => {
    setCustomWidth(width)
    setCustomHeight(height)
    if (preset === 'custom') setCrop((current) => constrainToAspect(current, aspectForPreset('custom', width, height)))
  }
  const apply = () => {
    const rect = cropPercentagesToRect(crop)
    if (rect) onApply(rect, rotationDegrees)
  }
  const rotate = (delta: number) => {
    setRotationDegrees((current) => ((current + delta) % 360 + 360) % 360)
    // Coordinates describe the displayed image. After changing orientation,
    // start with the whole rotated image selected rather than retaining a
    // selection from incompatible axes.
    setCrop(percentCrop(FULL_CROP_RECT))
  }

  return (
    <Modal
      title="裁剪图片"
      open={open}
      width={720}
      className="image-crop-modal"
      destroyOnHidden
      maskClosable={!saving}
      closable={!saving}
      onCancel={onCancel}
      footer={(
        <Space wrap>
          <Button disabled={saving} onClick={onCancel}>取消</Button>
          {onReset && <Button danger disabled={saving} onClick={onReset}>恢复原图</Button>}
          <Button type="primary" loading={saving} disabled={preparingPreview || crop.width <= 0 || crop.height <= 0} onClick={apply}>{rotationDegrees ? '应用裁剪与旋转' : '应用裁剪'}</Button>
        </Space>
      )}
    >
      <div className="image-crop-controls">
        <Segmented
          value={preset}
          options={[
            { label: '自由比例', value: 'free' },
            { label: '1:1', value: 'square' },
            { label: '4:3', value: 'fourThree' },
            { label: '16:9', value: 'sixteenNine' },
            { label: '自定义', value: 'custom' },
          ]}
          onChange={(value) => setCropPreset(value as AspectPreset)}
        />
        {preset === 'custom' && (
          <Space size={6}>
            <InputNumber aria-label="裁剪宽度比例" min={1} max={100} precision={2} value={customWidth} onChange={(value) => updateCustomRatio(typeof value === 'number' ? value : 1, customHeight)} />
            <span>:</span>
            <InputNumber aria-label="裁剪高度比例" min={1} max={100} precision={2} value={customHeight} onChange={(value) => updateCustomRatio(customWidth, typeof value === 'number' ? value : 1)} />
          </Space>
        )}
        <Space size={4} className="image-crop-rotation-controls">
          <Button icon={<UndoOutlined />} disabled={saving || preparingPreview} onClick={() => rotate(-90)}>左转 90°</Button>
          <Button icon={<RedoOutlined />} disabled={saving || preparingPreview} onClick={() => rotate(90)}>右转 90°</Button>
          {rotationDegrees !== 0 && <span>{rotationDegrees}°</span>}
        </Space>
      </div>
      <div className="image-crop-canvas">
        {preparingPreview ? <Spin tip="正在旋转图片…" /> : previewError ? <span className="image-crop-preview-error">{previewError}</span> : !previewUrl ? <Spin tip="正在加载图片…" /> : (
          <ReactCrop
            crop={crop as Crop}
            aspect={aspect}
            minWidth={1}
            minHeight={1}
            keepSelection
            ruleOfThirds
            onChange={(_pixelCrop, percent) => setCrop(percent)}
          >
            <img className="image-crop-media" src={previewUrl} alt="" />
          </ReactCrop>
        )}
      </div>
    </Modal>
  )
}
