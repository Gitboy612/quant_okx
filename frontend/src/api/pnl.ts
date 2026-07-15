import client from './client'
import type { PnlRecord, PnlSummary } from '../types'

export function listPnlRecords(params: {
  account_id?: number
  strategy_instance_id?: number
  start_time?: string
  end_time?: string
  limit?: number
}) {
  const query: Record<string, string | number> = {}
  if (params.account_id !== undefined) query.account_id = params.account_id
  if (params.strategy_instance_id !== undefined) query.strategy_instance_id = params.strategy_instance_id
  if (params.start_time) query.start_time = params.start_time
  if (params.end_time) query.end_time = params.end_time
  if (params.limit !== undefined) query.limit = params.limit
  return client.get<PnlRecord[]>('/pnl', { params: query })
}

export function getPnlSummary(params: { account_id?: number; strategy_instance_id?: number } = {}) {
  return client.get<PnlSummary>('/pnl/summary', { params })
}

export function recomputePnl(strategyId: number) {
  return client.post(`/pnl/recompute/${strategyId}`)
}

export function snapshotPnl() {
  return client.post('/pnl/snapshot')
}
