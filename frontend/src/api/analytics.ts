import client from './client'
import type {
  AttributionBySymbol,
  AttributionByStrategyType,
  AttributionByPeriod,
  DrillDownOrder,
} from '../types'

export function getAttributionBySymbol(params: {
  account_id: number
  start_date: string
  end_date: string
}) {
  return client.get<AttributionBySymbol[]>('/analytics/attribution/by-symbol', { params })
}

export function getAttributionByStrategyType(params: {
  account_id: number
  start_date: string
  end_date: string
}) {
  return client.get<AttributionByStrategyType[]>('/analytics/attribution/by-strategy-type', { params })
}

export function getAttributionByPeriod(params: {
  account_id: number
  start_date: string
  end_date: string
  period: 'daily' | 'weekly' | 'monthly'
}) {
  return client.get<AttributionByPeriod[]>('/analytics/attribution/by-period', { params })
}

export function getDrillDown(params: {
  start_date: string
  end_date: string
  symbol?: string
  strategy_type?: string
  account_id?: number
}) {
  const query: Record<string, string | number> = {
    start_date: params.start_date,
    end_date: params.end_date,
  }
  if (params.symbol) query.symbol = params.symbol
  if (params.strategy_type) query.strategy_type = params.strategy_type
  if (params.account_id !== undefined) query.account_id = params.account_id
  return client.get<DrillDownOrder[]>('/analytics/drill-down', { params: query })
}
