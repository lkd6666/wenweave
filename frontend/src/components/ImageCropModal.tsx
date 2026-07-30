import { useEffect, useMemo, useState } from 'react'
import ReactCrop, { type Crop, type PercentCrop } from 'react-image-crop'
import 'react-image-crop/dist/ReactCrop.css'
import { Button, InputNumber, Modal, Segmented, Space } from 'antd'
import type { CropRect } from '../utils/imageCrop'
import { FULL_CROP_RECT, cropPercentagesToRect, cropRectToPercentages, normalizeCropRect } from '../utils/imageCrop'

type AspectPreset = 'free' | 'square' | 'fourThree' | 'sixteenNine' | 'custom'

interface ImageCropModalProps {
  open: boolean
  source: string
  initialRect: CropRect | null
  saving: boolean
  onCancel: () => void
  onApply: (rect: CropRect) => void
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

  useEffect(() => {
    if (!open) return
    setPreset('free')
    setCrop(percentCrop(normalizedInitial))
  }, [normalizedInitial, open, source])

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
    if (rect) onApply(rect)
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
          <Button type="primary" loading={saving} disabled={crop.width <= 0 || crop.height <= 0} onClick={apply}>应用裁剪</Button>
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
      </div>
      <div className="image-crop-canvas">
        <ReactCrop
          crop={crop as Crop}
          aspect={aspect}
          minWidth={1}
          minHeight={1}
          keepSelection
          ruleOfThirds
          onChange={(_pixelCrop, percent) => setCrop(percent)}
        >
          <img className="image-crop-media" src={source} alt="" />
        </ReactCrop>
      </div>
    </Modal>
  )
}
