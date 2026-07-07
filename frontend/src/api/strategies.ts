import client from './client'
import type { StrategyTemplate, StrategyInstance, FeasibilityResult, ApiCallLogItem } from '../types'

export function listInstances() {
  return client.get<StrategyInstance[]>('/strategies/instances')
}

export function listTemplates() {
  return client.get<StrategyTemplate[]>('/strategies/templates')
}

export function checkFeasibility(id: number) {
  return client.get<FeasibilityResult>(`/strategies/instances/${id}/feasibility`)
}

export function listApiCallLogs(params: { strategy_instance_id?: number; limit?: number }) {
  return client.get<ApiCallLogItem[]>('/strategies/api-call-logs', { params })
}

export function createTemplate(data: {
  name: string
  strategy_type: string
  description?: string
  default_params: Record<string, unknown>
  param_schema: Record<string, unknown> | null
}) {
  return client.post<StrategyTemplate>('/strategies/templates', data)
}

export function deleteTemplate(id: number) {
  return client.delete(`/strategies/templates/${id}`)
}

export function createInstance(data: {
  template_id: number
  account_id: number
  name: string
  symbol: string
  market_type: string
  params: Record<string, unknown>
}) {
  return client.post('/strategies/instances', data)
}

export function updateInstance(id: number, data: { name?: string; params?: Record<string, unknown> }) {
  return client.put(`/strategies/instances/${id}`, data)
}

export function deleteInstance(id: number) {
  return client.delete(`/strategies/instances/${id}`)
}

export function startInstance(id: number) {
  return client.post(`/strategies/instances/${id}/start`)
}

export function pauseInstance(id: number) {
  return client.post(`/strategies/instances/${id}/pause`)
}

export function resumeInstance(id: number) {
  return client.post(`/strategies/instances/${id}/resume`)
}

export function stopInstance(id: number) {
  return client.post(`/strategies/instances/${id}/stop`)
}
