// 积木元数据（对应 Registry.list() 返回项）
export interface BlockMeta {
  kind: string
  category: string
  description: string
  param_schema: Record<string, BlockParamSchema>
  output_type: string  // "float" / "int" / "dict" / "bool" 等（后端已转为字符串）
  priority: string      // "P0" / "P1" / "P2"
}

export interface BlockParamSchema {
  type: 'string' | 'number' | 'bool' | 'select'
  required?: boolean
  default?: unknown
  min?: number
  max?: number
  description?: string
  options?: string[]  // for select type
}

// 积木目录（GET /api/dsl/blocks 响应）
export interface BlockCatalog {
  indicators: BlockMeta[]
  conditions: BlockMeta[]
  actions: BlockMeta[]
  events: BlockMeta[]
  base_strategies: BlockMeta[]
}

// DSL 配置结构（对应后端 StrategyDSL）
export interface BlockRef {
  kind: string
  args: Record<string, unknown>
}

export interface Trigger {
  mode: 'condition' | 'event'
  condition?: BlockRef | null
  event?: BlockRef | null
  extra_condition?: BlockRef | null
}

export interface Rule {
  name: string
  when: Trigger
  then: BlockRef[]
  recover_when?: Trigger | null
  recover_then?: BlockRef[]
  cool_down_seconds?: number
}

export interface BaseStrategyRef {
  kind: string
  params: Record<string, unknown>
}

export interface DslConfig {
  version: '1.0'
  base_strategy: BaseStrategyRef
  rules: Rule[]
}

// 校验结果（POST /api/dsl/validate 响应）
export interface ValidationError {
  layer: string  // "structure" / "reference" / "type" / "semantic" / "resource"
  code: string
  message: string
  path: string
}

export interface ValidationResult {
  valid: boolean
  errors: ValidationError[]
}

// Dry-Run 结果（POST /api/dsl/dry-run 响应）
export interface DryRunStep {
  timestamp: string
  price: number
  state: string
  indicator_values: Record<string, unknown>
  triggered: boolean
  rule_name: string | null
  actions: string[]
  transition: string | null
}

export interface DryRunResult {
  steps: DryRunStep[]
  total_ticks: number
  triggered_count: number
  state_changes: number
  final_state: string
}

// Dry-Run 请求体
export interface DryRunRequest {
  config: DslConfig
  symbol: string
  bar?: string
  limit?: number
}
