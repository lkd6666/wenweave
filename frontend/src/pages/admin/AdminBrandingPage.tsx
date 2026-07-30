import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Space, Typography, Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { DeleteOutlined, FileImageOutlined, SaveOutlined, UploadOutlined } from '@ant-design/icons'
import { brandingApi } from '../../api/branding'
import { ApiError } from '../../api/client'
import { brandingAssetUrl, useAppBranding } from '../../brand/appBranding'

const { Title, Text } = Typography

type BrandingAssetKind = 'logo' | 'favicon'

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? String(error.detail) : fallback
}

export default function AdminBrandingPage() {
  const { branding, refreshBranding } = useAppBranding()
  const [form] = Form.useForm<{ system_name: string }>()
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState<BrandingAssetKind | null>(null)
  const [removing, setRemoving] = useState<BrandingAssetKind | null>(null)

  useEffect(() => {
    form.setFieldsValue({ system_name: branding.system_name })
  }, [branding.system_name, form])

  const saveSystemName = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await brandingApi.update(values.system_name.trim())
      await refreshBranding()
      message.success('系统名称已保存')
    } catch (error) {
      if (error instanceof ApiError) message.error(String(error.detail))
    } finally {
      setSaving(false)
    }
  }

  const uploadAsset = async (kind: BrandingAssetKind, file: File) => {
    setUploading(kind)
    try {
      await brandingApi.upload(kind, file)
      await refreshBranding()
      message.success(kind === 'logo' ? 'Logo 已更新' : '网页图标已更新')
    } catch (error) {
      message.error(errorMessage(error, '图片上传失败'))
    } finally {
      setUploading(null)
    }
  }

  const removeAsset = async (kind: BrandingAssetKind) => {
    setRemoving(kind)
    try {
      await brandingApi.remove(kind)
      await refreshBranding()
      message.success(kind === 'logo' ? 'Logo 已移除' : '网页图标已恢复默认')
    } catch (error) {
      message.error(errorMessage(error, '移除图片失败'))
    } finally {
      setRemoving(null)
    }
  }

  const uploadProps = (kind: BrandingAssetKind): UploadProps => ({
    accept: 'image/png,image/jpeg,image/gif,image/webp,image/avif',
    showUploadList: false,
    beforeUpload: (file) => {
      void uploadAsset(kind, file)
      return Upload.LIST_IGNORE
    },
  })

  const asset = (kind: BrandingAssetKind) => {
    const isLogo = kind === 'logo'
    const url = brandingAssetUrl(isLogo ? branding.logo_url : branding.favicon_url, branding.updated_at)
    const label = isLogo ? '系统 Logo' : '网页图标'
    const loading = uploading === kind
    const removingAsset = removing === kind
    return (
      <section className="branding-asset" aria-label={label}>
        <div className={`branding-asset-preview${isLogo ? ' is-logo' : ' is-favicon'}`}>
          {url ? <img src={url} alt={`${label}预览`} /> : <FileImageOutlined />}
        </div>
        <div className="branding-asset-copy">
          <strong>{label}</strong>
          <Text type="secondary">{isLogo ? '显示在侧栏、移动端标题和登录页。' : '显示在浏览器标签页，建议使用正方形 PNG。'}</Text>
        </div>
        <Space className="branding-asset-actions" size={6}>
          <Upload {...uploadProps(kind)}>
            <Button icon={<UploadOutlined />} loading={loading}>上传</Button>
          </Upload>
          {url && <Button danger icon={<DeleteOutlined />} loading={removingAsset} onClick={() => void removeAsset(kind)}>移除</Button>}
        </Space>
      </section>
    )
  }

  return (
    <div className="admin-page branding-settings-page">
      <header className="admin-page-header">
        <div>
          <Title level={3}>品牌设置</Title>
          <Text type="secondary">统一管理系统名称、Logo 与浏览器网页图标。</Text>
        </div>
      </header>

      <Card className="branding-name-card">
        <Form form={form} layout="vertical" onFinish={() => void saveSystemName()}>
          <Form.Item label="系统名称" name="system_name" rules={[{ required: true, whitespace: true, message: '请输入系统名称' }, { max: 120, message: '系统名称不能超过 120 个字符' }]}>
            <Input maxLength={120} placeholder="例如：公众号 AI 排版系统" />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存系统名称</Button>
        </Form>
      </Card>

      <Card className="branding-assets-card">
        <div className="branding-assets-list">
          {asset('logo')}
          {asset('favicon')}
        </div>
      </Card>
    </div>
  )
}
