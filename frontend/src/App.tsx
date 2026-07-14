import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import EditorPage from './pages/EditorPage'
import AdminModelsPage from './pages/admin/AdminModelsPage'
import AdminStoragePage from './pages/admin/AdminStoragePage'
import AdminUsersPage from './pages/admin/AdminUsersPage'
import AdminUserGroupsPage from './pages/admin/AdminUserGroupsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardPage />} />
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
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
