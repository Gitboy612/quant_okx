import client from './client'
import type { StrategyEvent } from '../types'

export const getStrategyEvents = (id: number, limit = 100) =>
  client.get<{ total: number; items: StrategyEvent[] }>(`/monitoring/strategy/${id}/events`, { params: { limit } })

export const deleteStrategyEvents = (id: number) =>
  client.delete(`/monitoring/strategy/${id}/events`)

export const exportStrategyEvents = (id: number) =>
  client.get(`/monitoring/strategy/${id}/events/export`, { responseType: 'text' })

// 仓位冲突检测（Task 7: 改代数和 + 对冲组标注）
export interface PositionConflict {
  strategy_instance_id: number
  symbol: string
  real_pos: number
  net_position: number
  others_occupied: number
  available: number
  usable: number
  is_conflict: boolean
  hedge_group: string | null
}

export interface PositionConflictResult {
  account_id: number
  conflicts: PositionConflict[]
  total: number
}

export const getPositionConflicts = (accountId: number) =>
  client.get<PositionConflictResult>(`/monitoring/position_conflicts`, { params: { account_id: accountId } })

// 仓位隔离对账（SubTask 4.3）：虚拟 vs 真实持仓差异
export interface ReconcileResult {
  account_id: number
  symbol: string
  virtual_total: number
  real_total: number
  diff: number
  tolerance: number
  matched: boolean
}

export const getReconcilePositions = (accountId: number, symbol: string) =>
  client.get<ReconcileResult>(`/monitoring/reconcile`, { params: { account_id: accountId, symbol } })

// 健康指标看板（Task 12）
export interface LatencyStats {
  p50: number
  p95: number
  count: number
}

export interface CapitalInfo {
  investment_amount: number
  position_value: number
  usage_rate: number
}

export interface IsolationInfo {
  diff: number
  matched: boolean
}

export interface StrategyHealth {
  instance_id: number
  symbol: string
  latency: LatencyStats | null
  capital: CapitalInfo
  margin_ratio: number | null
  isolation: IsolationInfo | null
}

export type HealthAlertType = 'margin_warning' | 'position_conflict' | 'order_latency' | 'capital_usage'
export type HealthAlertLevel = 'warning' | 'critical'

export interface HealthAlert {
  level: HealthAlertLevel
  type: HealthAlertType
  message: string
}

export interface HealthMetrics {
  strategies: StrategyHealth[]
  alerts: HealthAlert[]
}

export const getHealthMetrics = (accountId: number) =>
  client.get<HealthMetrics>(`/monitoring/health`, { params: { account_id: accountId } })