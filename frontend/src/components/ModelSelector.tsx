import { ApiOutlined } from '@ant-design/icons'
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
      labelRender={({ value: selectedValue }) => {
        const selected = models.find((model) => model.id === selectedValue)
        if (!selected) return '选择 AI 模型'
        return (
          <span className="model-select-value">
            <span className="model-select-value-name">{selected.display_name}</span>
            {selected.provider_name && <span className="model-select-value-provider">{selected.provider_name}</span>}
          </span>
        )
      }}
      options={models.map((m) => ({
        value: m.id,
        label: m.display_name,
        description: m.description,
        providerName: m.provider_name,
        isDefault: m.is_default,
        isMultimodal: m.is_multimodal,
      }))}
      optionRender={(option) => (
        <div className="model-select-option">
          <div className="model-select-option-head">
            <span className="model-select-option-name">{option.data.label}</span>
            {option.data.isDefault === true && <span className="model-select-option-default">默认</span>}
          </div>
          <div className="model-select-option-meta">
            {typeof option.data.providerName === 'string' && option.data.providerName.trim() && (
              <span className="model-select-option-provider"><ApiOutlined />{option.data.providerName}</span>
            )}
            {option.data.isMultimodal === true && <span>支持图片</span>}
          </div>
          {typeof option.data.description === 'string' && option.data.description.trim() && (
            <div className="model-select-option-description">{option.data.description}</div>
          )}
        </div>
      )}
      notFoundContent="请先在「AI 模型管理」中配置模型"
    />
  )
}
