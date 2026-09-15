import { useState } from 'react'
import { Button, Form, Input, message, Typography } from 'antd'
import {
  ArrowRightOutlined,
  InfoCircleOutlined,
  LockOutlined,
  UserOutlined,
} from '@ant-design/icons'
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
      <main className="login-shell">
        <section className="login-story" aria-label="品牌信息">
          <div className="login-story-topline">
            <img
              className="login-story-logo"
              src={brandingAssetUrl(branding.logo_url, branding.updated_at) ?? '/favicon.svg'}
              alt=""
            />
            <span>{branding.system_name}</span>
          </div>
          <div className="login-story-copy">
            <Title level={1}>把表达，<br /><em>交给灵感。</em></Title>
          </div>
        </section>

        <section className="login-form-panel" aria-labelledby="login-title">
          <div className="login-form-header">
            <img
              className="login-brand-logo"
              src={brandingAssetUrl(branding.logo_url, branding.updated_at) ?? '/favicon.svg'}
              alt=""
            />
            <Text className="login-form-system-name">{branding.system_name}</Text>
            <Text className="login-form-eyebrow">WELCOME BACK</Text>
            <Title id="login-title" level={2}>欢迎回来</Title>
            <Text className="login-form-subtitle">登录后继续你的创作</Text>
          </div>
          <Form
            layout="vertical"
            onFinish={onFinish}
            autoComplete="on"
            requiredMark={false}
            className="login-form"
          >
            <Form.Item label="账号" name="username" rules={[{ required: true, message: '请输入账号' }]}>
              <Input
                prefix={<UserOutlined />}
                placeholder="请输入账号"
                size="large"
                autoComplete="username"
                autoFocus
              />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                size="large"
                autoComplete="current-password"
              />
            </Form.Item>
            <Form.Item className="login-submit-item">
              <Button
                type="primary"
                htmlType="submit"
                block
                size="large"
                loading={loading}
                icon={<ArrowRightOutlined />}
                iconPosition="end"
              >
                进入工作台
              </Button>
            </Form.Item>
          </Form>
          <div className="login-note">
            <InfoCircleOutlined />
            <Text>首次使用请用默认管理员账号登录，登录后请立即修改密码。</Text>
          </div>
        </section>
      </main>
    </div>
  )
}
