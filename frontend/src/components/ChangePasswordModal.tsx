import { useState } from 'react'
import { Alert, Form, Input, Modal, message } from 'antd'
import { usersApi } from '../api/users'
import { ApiError } from '../api/client'
import { useAuthStore } from '../store/authStore'

interface ChangePasswordModalProps {
  open: boolean
  required?: boolean
  onClose: () => void
}

export default function ChangePasswordModal({ open, required = false, onClose }: ChangePasswordModalProps) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const logout = useAuthStore((s) => s.logout)

  const handleOk = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      await usersApi.changeMyPassword(values.old_password, values.new_password)
      message.success('密码修改成功，请重新登录')
      form.resetFields()
      onClose()
      logout()
      window.location.href = '/login'
    } catch (err) {
      if (err instanceof ApiError) {
        message.error(String(err.detail))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title={required ? '请先修改密码' : '修改密码'}
      open={open}
      className="change-password-modal"
      closable={!required}
      maskClosable={!required}
      keyboard={!required}
      onCancel={required ? undefined : onClose}
      cancelButtonProps={required ? { style: { display: 'none' } } : undefined}
      onOk={handleOk}
      confirmLoading={loading}
      destroyOnHidden
    >
      {required && (
        <Alert
          type="warning"
          showIcon
          message="当前密码过于简单"
          description="为了保护工作区安全，请设置一个不同于账号且不易猜测的新密码。"
          style={{ marginBottom: 16 }}
        />
      )}
      <Form form={form} layout="vertical">
        <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[{ required: true, min: 6, message: '新密码至少 6 个字符' }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || value === getFieldValue('new_password')) {
                  return Promise.resolve()
                }
                return Promise.reject(new Error('两次输入的新密码不一致'))
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
