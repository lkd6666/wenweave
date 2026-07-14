import { api } from './client'
import type { User, UserRole } from '../types'

export interface CreateUserPayload {
  username: string
  display_name: string
  password: string
  role: UserRole
}

export interface UpdateUserPayload {
  display_name?: string
  password?: string
  role?: UserRole
  is_active?: boolean
}

export const usersApi = {
  list: () => api.get<User[]>('/users'),
  create: (payload: CreateUserPayload) => api.post<User>('/users', payload),
  update: (id: number, payload: UpdateUserPayload) => api.patch<User>(`/users/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/users/${id}`),
  changeMyPassword: (old_password: string, new_password: string) =>
    api.post<User>('/users/me/change-password', { old_password, new_password }),
}
