import { useEffect, useState } from 'react'
import { Button, Card, ColorPicker, Form, InputNumber, Space, Typography, message } from 'antd'
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import type { Color } from 'antd/es/color-picker'
import { articleTypographyApi } from '../../api/articleTypography'
import { ApiError } from '../../api/client'
import type { ArticleTypographySettings } from '../../types'

const { Title, Text } = Typography

const DEFAULT_SETTINGS: Omit<ArticleTypographySettings, 'updated_at'> = {
  horizontal_padding_px: 4,
  paragraph_spacing_px: 20,
  font_size_px: 15,
  line_height_em: 2,
  letter_spacing_px: 1,
  text_indent_em: 2,
  text_color: '#000000',
}

type TypographyForm = Omit<ArticleTypographySettings, 'updated_at'>

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? String(error.detail) : fallback
}

export default function AdminArticleTypographyPage() {
  const [form] = Form.useForm<TypographyForm>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    void articleTypographyApi.get()
      .then((settings) => {
        if (!cancelled) form.setFieldsValue(settings)
      })
      .catch((error) => {
        if (!cancelled) message.error(errorMessage(error, '加载正文排版设置失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [form])

  const save = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const saved = await articleTypographyApi.update({ ...values, text_color: values.text_color.toUpperCase() })
      form.setFieldsValue(saved)
      message.success('正文排版设置已保存')
    } catch (error) {
      if (error instanceof ApiError) message.error(String(error.detail))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="admin-page article-typography-settings-page">
      <header className="admin-page-header">
        <div>
          <Title level={3}>正文排版</Title>
          <Text type="secondary">统一设置 AI 生成微信公众号正文时使用的默认段落样式。</Text>
        </div>
      </header>

      <Card className="article-typography-settings-card" loading={loading}>
        <Form form={form} layout="vertical" onFinish={() => void save()} initialValues={DEFAULT_SETTINGS}>
          <div className="article-typography-settings-grid">
            <Form.Item label="正文左右间距" name="horizontal_padding_px" rules={[{ required: true }]}>
              <InputNumber min={0} max={24} step={0.1} precision={1} addonAfter="px" />
            </Form.Item>
            <Form.Item label="段前距" name="paragraph_spacing_px" rules={[{ required: true }]}>
              <InputNumber min={0} max={48} step={0.1} precision={1} addonAfter="px" />
            </Form.Item>
            <Form.Item label="正文大小" name="font_size_px" rules={[{ required: true }]}>
              <InputNumber min={12} max={20} step={0.1} precision={1} addonAfter="px" />
            </Form.Item>
            <Form.Item label="正文行高" name="line_height_em" rules={[{ required: true }]}>
              <InputNumber min={1.2} max={3} step={0.1} precision={1} addonAfter="em" />
            </Form.Item>
            <Form.Item label="正文文字间距" name="letter_spacing_px" rules={[{ required: true }]}>
              <InputNumber min={0} max={4} step={0.1} precision={1} addonAfter="px" />
            </Form.Item>
            <Form.Item label="正文首行缩进" name="text_indent_em" rules={[{ required: true }]}>
              <InputNumber min={0} max={4} step={0.1} precision={1} addonAfter="em" />
            </Form.Item>
            <Form.Item label="正文颜色" name="text_color" rules={[{ required: true }]}>
              <ColorPicker
                format="hex"
                showText={(color: Color) => color.toHexString().toUpperCase()}
                onChangeComplete={(color) => form.setFieldValue('text_color', color.toHexString().toUpperCase())}
              />
            </Form.Item>
          </div>
          <Space wrap>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存设置</Button>
            <Button icon={<ReloadOutlined />} onClick={() => form.setFieldsValue(DEFAULT_SETTINGS)}>恢复系统默认</Button>
          </Space>
        </Form>
      </Card>
    </div>
  )
}
