// 积木元数据（对应 Registry.list() 返回项）
export interface BlockMeta {
  kind: string
  label?: string          // 中文显示名
  category: string
  description: string
  param_schema: Record<string, BlockParamSchema>
  output_type: string  // "float" / "int" / "dict" / "bool" 等（后端已转为字符串）
  priority: string      // "P0" / "P1" / "P2"
  display_template?: string  // 条件可视化模板
}

export interface BlockParamSchema {
  type: 'string' | 'number' | 'bool' | 'select' | 'integer'
  label?: string           // 中文字段名
  required?: boolean
  default?: unknown
  min?: number
  max?: number
  step?: number
  description?: string
  options?: string[]  // for select type
  option_labels?: string[]  // 选项中文标签
  unit?: string              // 单位
  range?: [number, number]   // 取值范围
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

// ===== QS-Model 配置 =====

// QS-Model 元信息
export interface QSModelMeta {
  name: string
  version: string
  author: string
  description: string
  asset_class: string
  frequency: string
  base_symbol: string
}

// QS-Model 参数定义
export interface ParamDefinition {
  label: string
  value: any
  type: 'int' | 'float' | 'string' | 'bool' | 'select'
  range?: [number, number]
  description?: string
  options?: any[]
  option_labels?: string[]
  unit?: string
}

// 风控过滤
export interface RiskFilter {
  max_position_ratio?: number
  daily_max_loss?: number
  min_trade_size?: number
  blacklist_hours?: string[]
}

// QS-Model 完整配置（logic 字段复用现有 DslConfig 类型）
export interface QSModelConfig {
  qs_model_version: string
  meta: QSModelMeta
  params: Record<string, ParamDefinition>
  logic: DslConfig
  risk_filter?: RiskFilter | null
}
