import { afterEach, describe, expect, it, vi } from 'vitest'
import { uploadToOss, type DirectUploadTarget } from './documents'

class FakeXmlHttpRequest {
  static instances: FakeXmlHttpRequest[] = []

  method = ''
  url = ''
  status = 204
  sentBody: Document | XMLHttpRequestBodyInit | null = null
  headers: Record<string, string> = {}
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  upload = { onprogress: null as ((event: ProgressEvent<EventTarget>) => void) | null }

  constructor() {
    FakeXmlHttpRequest.instances.push(this)
  }

  open(method: string, url: string) {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }

  send(body: Document | XMLHttpRequestBodyInit | null) {
    this.sentBody = body
    this.onload?.()
  }

  abort() {
    this.onabort?.()
  }
}

const baseTarget: DirectUploadTarget = {
  object_key: 'imports/source.pdf',
  content_type: 'application/pdf',
  upload_url: 'https://upload.example.com/imports/source.pdf',
  upload_method: 'PUT',
  upload_headers: { 'Content-Type': 'application/pdf', 'x-storage-signature': 'signature' },
  upload_fields: {},
  file_field_name: 'file',
  expires_in_seconds: 1800,
}

afterEach(() => {
  FakeXmlHttpRequest.instances = []
  vi.unstubAllGlobals()
})

describe('uploadToOss', () => {
  it('sends signed PUT uploads with the prescribed headers', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXmlHttpRequest)
    const body = new Blob(['pdf'], { type: 'application/pdf' })

    await uploadToOss(baseTarget, body)

    const request = FakeXmlHttpRequest.instances[0]
    expect(request.method).toBe('PUT')
    expect(request.url).toBe(baseTarget.upload_url)
    expect(request.headers).toEqual(baseTarget.upload_headers)
    expect(request.sentBody).toBe(body)
  })

  it('sends Qiniu targets as multipart POST form data without setting a multipart header', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXmlHttpRequest)
    const body = new Blob(['markdown'], { type: 'text/markdown' })
    const target: DirectUploadTarget = {
      ...baseTarget,
      object_key: 'imports/source.md',
      content_type: 'text/markdown',
      upload_url: 'https://up.qiniup.com',
      upload_method: 'POST',
      upload_headers: {},
      upload_fields: { token: 'upload-token', key: 'imports/source.md', mimeType: 'text/markdown' },
    }

    await uploadToOss(target, body)

    const request = FakeXmlHttpRequest.instances[0]
    expect(request.method).toBe('POST')
    expect(request.headers).toEqual({})
    expect(request.sentBody).toBeInstanceOf(FormData)
    const form = request.sentBody as FormData
    expect(form.get('token')).toBe('upload-token')
    expect(form.get('key')).toBe('imports/source.md')
    expect(form.get('mimeType')).toBe('text/markdown')
    expect(form.get('file')).toBeInstanceOf(Blob)
  })
})
