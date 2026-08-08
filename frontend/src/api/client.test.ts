import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { useAuthStore } from '../store/authStore'
import type { User } from '../types'

const user: User = {
  id: 7,
  username: 'editor',
  display_name: '编辑用户',
  role: 'user',
  is_active: true,
  created_at: '2026-08-02T00:00:00Z',
}

afterEach(() => {
  useAuthStore.setState({ token: null, user: null })
  vi.unstubAllGlobals()
})

describe('authenticated API requests', () => {
  it('refreshes an expired access token once and retries the original request', async () => {
    useAuthStore.getState().setAuth('expired-access-token', user)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '未登录或登录已过期' }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'renewed-access-token' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.get<{ ok: boolean }>('/documents/12')).resolves.toEqual({ ok: true })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/documents/12')
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Authorization')).toBe('Bearer expired-access-token')
    expect(fetchMock.mock.calls[1]).toEqual([
      '/api/auth/refresh',
      { method: 'POST', credentials: 'same-origin' },
    ])
    expect(new Headers(fetchMock.mock.calls[2]?.[1]?.headers).get('Authorization')).toBe('Bearer renewed-access-token')
    expect(useAuthStore.getState().token).toBe('renewed-access-token')
  })
})
