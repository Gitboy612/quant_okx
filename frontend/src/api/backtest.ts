import client from './client'

// ============================================================
// Types
// ============================================================

export interface BacktestConfig {
  symbol: string
  strategy_type: 'grid' | 'trend' | 'arbitrage'
  params: Record<string, unknown>
  start_time: string
  end_time: string
  interval: string
  initial_capital: number
  slippage: number
  fee_rate: number
}

export interface BacktestTrade {
  timestamp: string
  side: 'buy' | 'sell'
  order_type: 'limit' | 'market'
  price: number
  quantity: number
  fee: number
  pnl: number
}

export interface EquityPoint {
  timestamp: string
  equity: number
  cash: number
  position_value: number
}

export interface BacktestMetrics {
  total_return: number
  max_drawdown: number
  sharpe_ratio: number
  win_rate: number
  trade_count: number
  profit_factor: number
  final_equity: number
}

export interface BacktestResult {
  config: BacktestConfig
  trades: BacktestTrade[]
  equity_curve: EquityPoint[]
  metrics: BacktestMetrics
  kline_count: number
  error: string | null
  created_at?: string
}

export interface BacktestHistoryItem {
  data?: BacktestResult[]
  total?: number
}

export interface ExportResult {
  instance_payload: {
    name: string
    symbol: string
    market_type: string
    params: Record<string, unknown>
    strategy_type: string
    notes?: string
    exported_at: string
  }
  message: string
}

// ============================================================
// API functions
// ============================================================

export function runBacktest(config: BacktestConfig) {
  // 回测可能耗时数秒（K线拉取 + 遍历），放宽超时到 120s
  return client.post<BacktestResult>('/backtest/run', config, { timeout: 120000 })
}

export function getBacktestHistory(limit = 20) {
  return client.get<BacktestHistoryItem>('/backtest/history', { params: { limit } })
}

export function exportBacktestToInstance(result: {
  symbol: string
  strategy_type: string
  params: Record<string, unknown>
  name?: string
  notes?: string
}) {
  return client.post<ExportResult>('/backtest/export', result)
}
