import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import ProtectedRoute from './components/ProtectedRoute'

const AppLayout = lazy(() => import('./components/AppLayout'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const WorkboardPage = lazy(() => import('./pages/WorkboardPage'))
const EditorPage = lazy(() => import('./pages/EditorPage'))
const AdminModelsPage = lazy(() => import('./pages/admin/AdminModelsPage'))
const AdminStoragePage = lazy(() => import('./pages/admin/AdminStoragePage'))
const AdminUsersPage = lazy(() => import('./pages/admin/AdminUsersPage'))
const AdminUserGroupsPage = lazy(() => import('./pages/admin/AdminUserGroupsPage'))
const AdminWeChatAccountsPage = lazy(() => import('./pages/admin/AdminWeChatAccountsPage'))
const AdminOperationLogsPage = lazy(() => import('./pages/admin/AdminOperationLogsPage'))
const AdminBrandingPage = lazy(() => import('./pages/admin/AdminBrandingPage'))
const PublicSharePage = lazy(() => import('./pages/PublicSharePage'))

function RouteLoadingFallback() {
  return <main className="route-loading" aria-busy="true" aria-label="页面加载中" />
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteLoadingFallback />}>
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
      </Suspense>
    </BrowserRouter>
  )
}
