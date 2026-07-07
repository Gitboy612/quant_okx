import client from './client'
import type { PaginatedResponse, OperationLog } from '../types'

export function listLogs(params: {
  action?: string
  target_type?: string
  limit?: number
  offset?: number
}) {
  return client.get<PaginatedResponse<OperationLog>>('/logs', { params })
}
