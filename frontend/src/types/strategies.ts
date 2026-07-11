// 参数字段（兼容 ParamSchemaField 与 QS-Model ParamDefinition）
export type RenderParamField = {
  label: string
  type: string  // 'int' | 'float' | 'number' | 'string' | 'bool' | 'select' | 'boolean'
  default?: unknown
  min?: number
  max?: number
  step?: number
  hint?: string
  options?: string[]
  option_labels?: string[]
  unit?: string
}
