import { api } from './client'
import type { WeChatAccount, WeChatAvailableAccount } from '../types'

export interface WeChatAccountPayload {
  name: string
  app_id: string
  app_secret?: string
  allowed_user_ids: number[]
  allowed_group_ids: number[]
  is_active: boolean
}

export const wechatAccountsApi = {
  list: () => api.get<WeChatAccount[]>('/wechat-accounts'),
  available: () => api.get<WeChatAvailableAccount[]>('/wechat-accounts/available'),
  create: (payload: Required<Pick<WeChatAccountPayload, 'app_secret'>> & WeChatAccountPayload) =>
    api.post<WeChatAccount>('/wechat-accounts', payload),
  update: (id: number, payload: Partial<WeChatAccountPayload>) => api.patch<WeChatAccount>(`/wechat-accounts/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/wechat-accounts/${id}`),
  test: (id: number) => api.post<{ success: boolean; message: string }>(`/wechat-accounts/${id}/test`),
}
