import type { QSModelConfig } from './dsl'

export interface Account {
  id: number
  name: string
  trade_mode: string
  exchange: string
  is_active: boolean
  api_key_masked: string
  created_at: string
}

export interface AssetBalance {
  ccy: string
  avail: number
  frozen: number
  equity: number
}

export interface Position {
  instId: string
  posSide: string
  pos: string
  markPx: string
  upl: string
  avgPx: string
  notionalUsd: string
}

export interface BalanceData {
  total_equity: number
  assets: AssetBalance[]
  asset_count: number
}

export interface ParamSchemaField {
  label: string
  type: 'number' | 'string' | 'select' | 'boolean'
  default: unknown
  min?: number
  max?: number
  step?: number
  hint?: string
  options?: string[]
}

export interface FeasibilityResult {
  ok: boolean
  reason: string
  current_price?: number
  upper_price?: number
  lower_price?: number
  grid_count?: number
  grids_below_price?: number
  required_usdt_min?: number
  required_usdt_approx?: number
  available_usdt?: number
}

export interface ApiCallLogItem {
  id: number
  strategy_instance_id: number | null
  account_name: string | null
  endpoint: string
  method: string
  request_body: string | null
  response_code: string | null
  response_body: string | null
  status: string
  created_at: string
}

export interface StrategyTemplate {
  id: number
  name: string
  strategy_type: string
  description: string
  default_params: Record<string, unknown>
  param_schema: Record<string, ParamSchemaField> | null
  is_builtin: boolean
  is_custom: boolean
  dsl_config: Record<string, unknown> | null
  qs_model_config?: QSModelConfig | null  // QS-Model 配置
  logic_hash?: string | null              // 逻辑哈希（去重标识）
  duplicate_hint?: string | null          // 创建时返回的去重提示
}

export interface StrategyInstance {
  id: number
  template_id: number
  template_name: string
  strategy_type: string
  account_id: number
  name: string
  symbol: string
  market_type: string
  params: Record<string, unknown>
  status: string
  started_at: string | null
  stopped_at: string | null
  created_at: string
  updated_at: string
}

export interface Order {
  id: number
  strategy_instance_id: number | null
  account_id: number
  symbol: string
  order_id: string | null
  cl_ord_id: string | null
  side: string
  order_type: string
  price: number | null
  quantity: number
  filled_quantity: number
  state: string | null
  fill_px: number | null
  fill_sz: number | null
  fee: number | null
  update_time: string | null
  status: string
  created_at: string
  updated_at: string | null
}

export interface PnlRecord {
  id: number
  account_id: number
  strategy_instance_id: number | null
  equity: number
  unrealized_pnl: number
  realized_pnl: number
  total_pnl: number
  recorded_at: string
}

export interface PnlSummary {
  total_realized_pnl: number
  total_unrealized_pnl: number
  total_pnl: number
  latest_equity: number
}

export interface OperationLog {
  id: number
  user_id: number | null
  action: string
  target_type: string | null
  target_id: number | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface PaginatedResponse<T> {
  total: number
  items: T[]
}

export interface User {
  id: number
  username: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface UserSettings {
  refresh_interval: string
}

export interface ConnectivityTarget {
  ok: boolean
  latency_ms: number
  message?: string
}

export interface ConnectivityResult {
  google: ConnectivityTarget
  github: ConnectivityTarget
  okx: ConnectivityTarget
}

export interface ProxyStatus {
  status: string
  port: number
  pid: number | null
  started_at: string | null
  uptime_seconds: number
  connectivity?: ConnectivityResult
}

export interface SampleConfig {
  name: string
  path: string
}

export interface StrategyEvent {
  id: number
  strategy_instance_id: number
  event_type: string
  message: string
  details: string | null
  created_at: string
}
