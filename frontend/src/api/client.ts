import { useAuthStore } from '../store/authStore'

const API_BASE = '/api'

function apiErrorMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(apiErrorMessage).filter(Boolean).join('\n')
  if (detail && typeof detail === 'object') {
    const fields = detail as Record<string, unknown>
    for (const key of ['message', 'msg', 'detail', 'error', 'reason', 'errors']) {
      if (fields[key] !== undefined && fields[key] !== null) {
        const text = apiErrorMessage(fields[key])
        if (text) return text
      }
    }
    return JSON.stringify(detail)
  }
  return detail == null ? '请求失败' : String(detail)
}

export class ApiError extends Error {
  status: number
  detail: unknown
  headers: Headers

  constructor(status: number, detail: unknown, headers?: HeadersInit) {
    super(apiErrorMessage(detail))
    this.status = status
    this.detail = detail
    this.headers = new Headers(headers)
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  isFormData?: boolean
  signal?: AbortSignal
}

export interface UploadProgress {
  loaded: number
  total: number
}

export interface UploadOptions {
  onProgress?: (progress: UploadProgress) => void
  signal?: AbortSignal
}

interface EventStreamOptions {
  method?: 'POST'
  body?: unknown
  signal?: AbortSignal
  onEvent: (event: string, data: unknown) => void
}

interface TokenResponse {
  access_token: string
  password_change_required?: boolean
}

let refreshPromise: Promise<boolean> | null = null

function requestWithCurrentAccessToken(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = useAuthStore.getState().token
  if (token) headers.set('Authorization', `Bearer ${token}`)
  else headers.delete('Authorization')
  return fetch(input, { ...init, headers })
}

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise

  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'same-origin',
      })
      if (!response.ok) return false
      const payload = await response.json() as TokenResponse
      if (!payload.access_token) return false

      const { user, setAuth } = useAuthStore.getState()
      if (!user) return false
      setAuth(payload.access_token, {
        ...user,
        password_change_required: payload.password_change_required ?? user.password_change_required ?? false,
      })
      return true
    } catch {
      return false
    }
  })()

  try {
    const refreshed = await refreshPromise
    if (!refreshed) useAuthStore.getState().logout()
    return refreshed
  } finally {
    refreshPromise = null
  }
}

export async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const tokenUsedForRequest = useAuthStore.getState().token
  const response = await requestWithCurrentAccessToken(input, init)
  if (response.status !== 401 || !tokenUsedForRequest) return response

  // A concurrent request may have renewed the session while this request was
  // in flight. Reuse that token without issuing a second refresh request.
  if (useAuthStore.getState().token !== tokenUsedForRequest) {
    return requestWithCurrentAccessToken(input, init)
  }
  if (!await refreshAccessToken()) return response
  return requestWithCurrentAccessToken(input, init)
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, isFormData, signal } = options

  const headers: Record<string, string> = {}

  let payload: BodyInit | undefined
  if (body !== undefined) {
    if (isFormData) {
      payload = body as FormData
    } else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
  }

  const res = await authenticatedFetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: payload,
    signal,
  })

  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // 响应体不是 JSON，忽略解析错误
    }
    throw new ApiError(res.status, detail, res.headers)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

function uploadWithCurrentAccessToken(path: string, body: FormData, options: UploadOptions): Promise<Response> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const signal = options.signal
    const onAbort = () => request.abort()
    const cleanup = () => signal?.removeEventListener('abort', onAbort)
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('上传已取消', 'AbortError'))
      return
    }
    request.open('POST', `${API_BASE}${path}`)
    const token = useAuthStore.getState().token
    if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.({ loaded: event.loaded, total: event.total })
    }
    request.upload.onload = () => options.onProgress?.({ loaded: 1, total: 1 })
    request.onload = () => {
      cleanup()
      if (!request.status) {
        reject(new ApiError(0, '上传连接中断，请重试'))
        return
      }
      resolve(new Response(request.status === 204 ? null : request.responseText, {
        status: request.status,
        statusText: request.statusText,
      }))
    }
    request.onerror = () => { cleanup(); reject(new ApiError(0, '上传连接中断，请重试')) }
    request.onabort = () => { cleanup(); reject(signal?.reason ?? new DOMException('上传已取消', 'AbortError')) }
    signal?.addEventListener('abort', onAbort, { once: true })
    try {
      request.send(body)
    } catch (error) {
      cleanup()
      reject(error)
    }
  })
}

export async function apiUpload<T>(path: string, body: FormData, options: UploadOptions = {}): Promise<T> {
  if (!options.onProgress) return apiRequest<T>(path, { method: 'POST', body, isFormData: true, signal: options.signal })
  const tokenUsedForRequest = useAuthStore.getState().token
  let response = await uploadWithCurrentAccessToken(path, body, options)
  if (response.status === 401 && tokenUsedForRequest) {
    const refreshed = useAuthStore.getState().token !== tokenUsedForRequest || await refreshAccessToken()
    if (refreshed) {
      options.onProgress({ loaded: 0, total: 0 })
      response = await uploadWithCurrentAccessToken(path, body, options)
    }
  }
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const data = await response.json()
      detail = data.detail ?? data
    } catch {
      // Reverse proxies may return a non-JSON upload error.
    }
    throw new ApiError(response.status, detail, response.headers)
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

export async function apiBlob(path: string, options: Pick<RequestOptions, 'signal'> = {}): Promise<Blob> {
  const res = await authenticatedFetch(`${API_BASE}${path}`, {
    method: 'GET',
    signal: options.signal,
  })

  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Image proxy failures may return an empty or non-JSON body.
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  return res.blob()
}

export async function apiEventStream(path: string, options: EventStreamOptions): Promise<void> {
  const { method = 'POST', body, signal, onEvent } = options
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await authenticatedFetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const data = await res.json()
      detail = data.detail ?? data
    } catch {
      // Event streams can fail before the response body is established.
    }
    throw new ApiError(res.status, detail, res.headers)
  }
  if (!res.body) throw new ApiError(res.status, '推送进度连接未建立')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consumeEvent = (rawEvent: string) => {
    const lines = rawEvent.split('\n')
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (dataLines.length === 0) return
    try {
      onEvent(event, JSON.parse(dataLines.join('\n')))
    } catch {
      throw new ApiError(res.status, '推送进度数据格式无效')
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let separator = buffer.indexOf('\n\n')
    while (separator >= 0) {
      consumeEvent(buffer.slice(0, separator))
      buffer = buffer.slice(separator + 2)
      separator = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  if (buffer.trim()) consumeEvent(buffer)
}

export const api = {
  get: <T>(path: string) => apiRequest<T>(path),
  blob: (path: string, options?: Pick<RequestOptions, 'signal'>) => apiBlob(path, options),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => apiRequest<T>(path, { method: 'DELETE' }),
  upload: apiUpload,
}
