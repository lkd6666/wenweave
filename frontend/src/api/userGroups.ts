import { api } from './client'
import type { UserGroup } from '../types'

export interface UserGroupPayload {
  name: string
  user_ids: number[]
}

export const userGroupsApi = {
  list: () => api.get<UserGroup[]>('/user-groups'),
  create: (payload: UserGroupPayload) => api.post<UserGroup>('/user-groups', payload),
  update: (id: number, payload: Partial<UserGroupPayload>) => api.patch<UserGroup>(`/user-groups/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/user-groups/${id}`),
}
