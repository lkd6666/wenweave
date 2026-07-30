import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { Result } from 'antd'
import { useAuthStore } from '../store/authStore'

interface ProtectedRouteProps {
  children: ReactNode
  adminOnly?: boolean
}

export default function ProtectedRoute({ children, adminOnly }: ProtectedRouteProps) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)

  if (!token || !user) {
    return <Navigate to="/login" replace />
  }

  if (adminOnly && user.role !== 'admin') {
    return <Result status="403" title="403" subTitle="仅管理员可访问此页面" />
  }

  return <>{children}</>
}
