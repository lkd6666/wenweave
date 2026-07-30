export interface PublicDocumentShare {
  title: string
  html: string
  cover_url: string
  revision: string
  expires_at: string
  asset_refresh_at: string
}

export interface PublicDocumentShareRevision {
  revision: string
  expires_at: string
}

export class PublicShareError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function requestPublicShare<T>(path: string): Promise<T> {
  const response = await fetch(`/api/public/shares${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // Keep the HTTP status text when a proxy returned a non-JSON error.
    }
    throw new PublicShareError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export const publicSharesApi = {
  get: (token: string) => requestPublicShare<PublicDocumentShare>(`/${encodeURIComponent(token)}`),
  revision: (token: string) => requestPublicShare<PublicDocumentShareRevision>(`/${encodeURIComponent(token)}/revision`),
}
