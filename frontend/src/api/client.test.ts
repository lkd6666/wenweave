import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'
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

describe('API error messages', () => {
  it('extracts readable messages while preserving structured details', () => {
    const detail = { code: 'context_limit', message: '消息超出上下文限制', stats: { used_tokens: 9000 } }
    const error = new ApiError(400, detail)
    expect(error.message).toBe('消息超出上下文限制')
    expect(error.detail).toBe(detail)
    expect(new ApiError(502, { error: { message: '图片读取失败' } }).message).toBe('图片读取失败')
    expect(new ApiError(422, [{ loc: ['body', 'message'], msg: '消息不能为空' }, { msg: '图片最多 100 张' }]).message)
      .toBe('消息不能为空\n图片最多 100 张')
  })
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

class UploadRequestMock {
  static requests: UploadRequestMock[] = []
  upload = { onprogress: null as ((event: { loaded: number; total: number; lengthComputable: boolean }) => void) | null, onload: null as (() => void) | null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  status = 200
  statusText = 'OK'
  responseText = '{}'
  headers: Record<string, string> = {}
  body?: FormData
  path = ''
  constructor() { UploadRequestMock.requests.push(this) }
  open(_method: string, path: string) { this.path = path }
  setRequestHeader(key: string, value: string) { this.headers[key] = value }
  send(body: FormData) { this.body = body }
  abort() { this.onabort?.() }
  respond(status: number, payload: unknown) {
    this.status = status
    this.responseText = JSON.stringify(payload)
    this.onload?.()
  }
}

describe('authenticated upload progress', () => {
  function setup() {
    UploadRequestMock.requests = []
    vi.stubGlobal('XMLHttpRequest', UploadRequestMock)
    const body = new FormData()
    body.append('file', new Blob(['pixels'], { type: 'image/png' }), 'photo.png')
    return body
  }

  it('sends the original multipart body with authorization and reports actual transfer progress', async () => {
    const body = setup()
    useAuthStore.setState({ token: 'upload-token', user })
    const onProgress = vi.fn()
    const pending = api.upload('/images', body, { onProgress })
    const request = UploadRequestMock.requests[0]!
    expect(request.path).toBe('/api/images')
    expect(request.headers).toEqual({ Authorization: 'Bearer upload-token' })
    expect(request.body).toBe(body)
    request.upload.onprogress?.({ loaded: 25, total: 100, lengthComputable: true })
    expect(onProgress).toHaveBeenLastCalledWith({ loaded: 25, total: 100 })
    request.upload.onload?.()
    expect(onProgress).toHaveBeenLastCalledWith({ loaded: 1, total: 1 })
    request.respond(201, { id: 'saved' })
    await expect(pending).resolves.toEqual({ id: 'saved' })
  })

  it('refreshes an expired token, resets progress and retries the same files once', async () => {
    const body = setup()
    useAuthStore.setState({ token: 'old-token', user })
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ access_token: 'new-token' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const onProgress = vi.fn()
    const pending = api.upload('/images', body, { onProgress })
    UploadRequestMock.requests[0]!.respond(401, { detail: 'expired' })
    await vi.waitFor(() => expect(UploadRequestMock.requests).toHaveLength(2))
    const retry = UploadRequestMock.requests[1]!
    expect(retry.headers.Authorization).toBe('Bearer new-token')
    expect(retry.body).toBe(body)
    expect(onProgress).toHaveBeenCalledWith({ loaded: 0, total: 0 })
    retry.respond(201, { id: 'saved' })
    await expect(pending).resolves.toEqual({ id: 'saved' })
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
  })

  it('preserves server upload errors and supports cancellation without hanging', async () => {
    const body = setup()
    const pending = api.upload('/images', body, { onProgress: vi.fn() })
    UploadRequestMock.requests[0]!.respond(413, { detail: '单张图片不能超过 10MB' })
    await expect(pending).rejects.toEqual(new ApiError(413, '单张图片不能超过 10MB'))
    const controller = new AbortController()
    const cancelled = api.upload('/images', body, { onProgress: vi.fn(), signal: controller.signal })
    controller.abort()
    await expect(cancelled).rejects.toMatchObject({ name: 'AbortError' })
    const stopped = api.upload('/images', body, { onProgress: vi.fn(), signal: controller.signal })
    await expect(stopped).rejects.toMatchObject({ name: 'AbortError' })
    expect(UploadRequestMock.requests).toHaveLength(3)
  })

  it('reports network failures and keeps legacy uploads on the existing fetch path', async () => {
    const body = setup()
    const pending = api.upload('/images', body, { onProgress: vi.fn() })
    UploadRequestMock.requests[0]!.onerror?.()
    await expect(pending).rejects.toMatchObject({ status: 0 })
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"id":"saved"}', { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.upload('/images', body)).resolves.toEqual({ id: 'saved' })
    expect(fetchMock).toHaveBeenCalledWith('/api/images', expect.objectContaining({ method: 'POST', body }))
    expect(UploadRequestMock.requests).toHaveLength(1)
  })
})
