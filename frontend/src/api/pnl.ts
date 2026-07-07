import client from './client'
import type { PnlRecord, PnlSummary } from '../types'

export function listPnlRecords(params: { account_id?: number; strategy_instance_id?: number; limit?: number }) {
  return client.get<PnlRecord[]>('/pnl', { params })
}

export function getPnlSummary(params: { account_id?: number } = {}) {
  return client.get<PnlSummary>('/pnl/summary', { params })
}
