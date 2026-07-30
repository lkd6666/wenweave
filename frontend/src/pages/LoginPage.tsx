import { useState } from 'react'
import { Button, Card, Form, Input, message, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router'
import { api, ApiError } from '../api/client'
import { useAuthStore } from '../store/authStore'
import { brandingAssetUrl, useAppBranding } from '../brand/appBranding'
import type { TokenResponse, User } from '../types'

const { Title, Text } = Typography

export default function LoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const { branding } = useAppBranding()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const token = await api.post<TokenResponse>('/auth/login', values)
      const meResponse = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token.access_token}` },
      })
      const user: User = await meResponse.json()
      setAuth(token.access_token, user)
      navigate('/')
    } catch (err) {
      const detail = err instanceof ApiError ? String(err.detail) : '登录失败，请检查网络连接'
      message.error(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card" variant="borderless">
        <div className="login-brand-header">
          <img className="login-brand-logo" src={brandingAssetUrl(branding.logo_url, branding.updated_at) ?? '/favicon.svg'} alt="" />
          <Title level={3} style={{ marginBottom: 4 }}>
            {branding.system_name}
          </Title>
          <Text type="secondary">登录后开始智能排版</Text>
        </div>
        <Form layout="vertical" onFinish={onFinish} autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserOutlined />} placeholder="账号" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12 }}>
          首次使用请用默认管理员账号登录（详见部署文档），登录后请立即修改密码。
        </Text>
      </Card>
    </div>
  )
}
