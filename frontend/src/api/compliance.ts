import { api } from './client'
import type { ComplianceReport } from '../types'

export const complianceApi = {
  check: (html: string) => api.post<ComplianceReport>('/compliance/check', { html }),
}
