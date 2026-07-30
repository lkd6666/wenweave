import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import WorkboardPage from './pages/WorkboardPage'
import EditorPage from './pages/EditorPage'
import AdminModelsPage from './pages/admin/AdminModelsPage'
import AdminStoragePage from './pages/admin/AdminStoragePage'
import AdminUsersPage from './pages/admin/AdminUsersPage'
import AdminUserGroupsPage from './pages/admin/AdminUserGroupsPage'
import AdminWeChatAccountsPage from './pages/admin/AdminWeChatAccountsPage'
import AdminOperationLogsPage from './pages/admin/AdminOperationLogsPage'
import AdminBrandingPage from './pages/admin/AdminBrandingPage'
import PublicSharePage from './pages/PublicSharePage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/share/:token" element={<PublicSharePage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<WorkboardPage />} />
          <Route path="workbench" element={<DashboardPage />} />
          <Route path="editor/:documentId" element={<EditorPage />} />
          <Route
            path="admin/models"
            element={
              <ProtectedRoute adminOnly>
                <AdminModelsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/storage"
            element={
              <ProtectedRoute adminOnly>
                <AdminStoragePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/users"
            element={
              <ProtectedRoute adminOnly>
                <AdminUsersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/user-groups"
            element={
              <ProtectedRoute adminOnly>
                <AdminUserGroupsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/wechat-accounts"
            element={
              <ProtectedRoute adminOnly>
                <AdminWeChatAccountsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/branding"
            element={
              <ProtectedRoute adminOnly>
                <AdminBrandingPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/operation-logs"
            element={
              <ProtectedRoute adminOnly>
                <AdminOperationLogsPage />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
