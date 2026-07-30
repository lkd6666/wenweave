import { Select } from 'antd'
import type { AIModelItem } from '../types'

interface ModelSelectorProps {
  models: AIModelItem[]
  value: number | null
  onChange: (modelId: number) => void
  loading?: boolean
  disabled?: boolean
}

export default function ModelSelector({ models, value, onChange, loading, disabled }: ModelSelectorProps) {
  return (
    <Select
      style={{ width: '100%' }}
      placeholder="选择 AI 模型"
      loading={loading}
      disabled={disabled || models.length === 0}
      value={value ?? undefined}
      onChange={onChange}
      options={models.map((m) => ({
        value: m.id,
        label: m.is_default ? `${m.display_name}（默认）` : m.display_name,
        description: m.description,
        isMultimodal: m.is_multimodal,
      }))}
      optionRender={(option) => (
        <div className="model-select-option">
          <div className="model-select-option-name">{option.data.label}</div>
          {option.data.isMultimodal === true && <div className="model-select-option-description">支持图片</div>}
          {typeof option.data.description === 'string' && option.data.description.trim() && (
            <div className="model-select-option-description">{option.data.description}</div>
          )}
        </div>
      )}
      notFoundContent="请先在「AI 模型管理」中配置模型"
    />
  )
}
