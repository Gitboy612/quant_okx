import { useEffect, useState, useMemo, useRef, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus, Trash2, ChevronDown, CheckCircle, XCircle, Play, Loader2,
  AlertTriangle, X, Settings, Zap, Save, Sliders, Shield, Info, Link2,
} from 'lucide-react'
import Modal from './Modal'
import Dropdown from './Dropdown'
import SymbolPicker from './SymbolPicker'
import { getBlocks, validateDsl, dryRunDsl } from '../api/dsl'
import { createTemplate } from '../api/strategies'
import type {
  BlockCatalog, BlockMeta, BlockRef, Trigger, Rule, DslConfig,
  ValidationResult, DryRunResult, QSModelConfig, QSModelMeta,
  ParamDefinition, RiskFilter,
} from '../types/dsl'

// ============================================================
// QS-Model 策略构建器
// 四段式编辑：META / PARAMS / LOGIC / RISK_FILTER
// ============================================================

// ============================================================
// param_schema 格式归一化（保留 label / option_labels / unit / step）
// ============================================================

interface NormalizedParam {
  type: 'string' | 'number' | 'bool' | 'select' | 'object' | 'array'
  required: boolean
  default?: unknown
  min?: number
  max?: number
  step?: number
  description?: string
  label?: string
  unit?: string
  options?: string[]
  option_labels?: string[]
}

function normalizeParamDef(def: Record<string, unknown>, required: boolean): NormalizedParam {
  const rawType = String(def.type ?? 'string').toLowerCase()
  let type: NormalizedParam['type']
  switch (rawType) {
    case 'string': case 'str': type = 'string'; break
    case 'number': case 'integer': case 'int': case 'float': case 'double': type = 'number'; break
    case 'bool': case 'boolean': type = 'bool'; break
    case 'select': type = 'select'; break
    case 'object': type = 'object'; break
    case 'array': type = 'array'; break
    default: type = 'string'
  }
  return {
    type,
    required,
    default: def.default,
    min: typeof def.min === 'number' ? def.min : undefined,
    max: typeof def.max === 'number' ? def.max : undefined,
    step: typeof def.step === 'number' ? def.step : undefined,
    description: typeof def.description === 'string' ? def.description : undefined,
    label: typeof def.label === 'string' ? def.label : undefined,
    unit: typeof def.unit === 'string' ? def.unit : undefined,
    options: Array.isArray(def.options) ? (def.options as string[]) : undefined,
    option_labels: Array.isArray(def.option_labels) ? (def.option_labels as string[]) : undefined,
  }
}

/**
 * 将后端两种 param_schema 格式统一归一化为扁平 {param_name: NormalizedParam}。
 *
 * - 扁平格式（indicators/conditions/events/bases）：{param_name: {type, required, ...}}
 * - JSON Schema 嵌套格式（actions）：{type: "object", properties: {...}, required: [...]}
 */
function normalizeParamSchema(raw: unknown): Record<string, NormalizedParam> {
  if (!raw || typeof raw !== 'object') return {}
  const obj = raw as Record<string, unknown>

  // JSON Schema 嵌套格式
  if (obj.type === 'object' && obj.properties && typeof obj.properties === 'object') {
    const requiredArr = Array.isArray(obj.required) ? (obj.required as string[]) : []
    const requiredSet = new Set(requiredArr)
    const props = obj.properties as Record<string, unknown>
    const result: Record<string, NormalizedParam> = {}
    for (const [name, def] of Object.entries(props)) {
      if (def && typeof def === 'object') {
        result[name] = normalizeParamDef(def as Record<string, unknown>, requiredSet.has(name))
      }
    }
    return result
  }

  // 扁平格式
  const result: Record<string, NormalizedParam> = {}
  for (const [name, def] of Object.entries(obj)) {
    if (def && typeof def === 'object') {
      const d = def as Record<string, unknown>
      result[name] = normalizeParamDef(d, Boolean(d.required))
    }
  }
  return result
}

/** 从归一化 schema 提取默认参数值（跳过 object/array 复杂类型）。 */
function getDefaultArgs(schema: Record<string, NormalizedParam>): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const [name, param] of Object.entries(schema)) {
    if (param.type === 'object' || param.type === 'array') continue
    if (param.default !== undefined) {
      args[name] = param.default
    }
  }
  return args
}

/** 积木中文显示名：label 优先，回退到 kind。 */
function blockLabel(b: BlockMeta | undefined | null): string {
  if (!b) return ''
  return b.label || b.kind
}

/** 逻辑组合条件 kind 集合（含嵌套 conditions/condition）。 */
const LOGIC_CONDITIONS = new Set(['and', 'or', 'not'])

/** 简单比较条件 kind → 中文运算符。 */
const SIMPLE_CONDITIONS: { value: string; label: string }[] = [
  { value: 'gt', label: '大于' },
  { value: 'lt', label: '小于' },
  { value: 'abs_gt', label: '绝对值大于' },
  { value: 'abs_lt', label: '绝对值小于' },
]
const SIMPLE_KIND_SET = new Set(SIMPLE_CONDITIONS.map((c) => c.value))

/** 安全的模板字符串替换（兼容低 target）。 */
function fillTemplate(tpl: string, vars: Record<string, string>): string {
  let result = tpl
  for (const [k, v] of Object.entries(vars)) {
    result = result.split(`{${k}}`).join(v)
  }
  return result
}

/** 用 display_template 渲染条件人类可读摘要。 */
function renderConditionSummary(condition: BlockRef, catalog: BlockCatalog): string {
  const block = catalog.conditions.find((b) => b.kind === condition.kind)
  if (!block) return condition.kind || '未设置'
  const tpl = block.display_template
  if (!tpl) return blockLabel(block)
  const vars: Record<string, string> = {}
  const indRef = condition.args.indicator as BlockRef | undefined
  if (indRef) {
    const indBlock = catalog.indicators.find((b) => b.kind === indRef.kind)
    vars.indicator = indBlock ? blockLabel(indBlock) : (indRef.kind || '?')
  }
  if (condition.args.threshold !== undefined && condition.args.threshold !== null) {
    vars.threshold = String(condition.args.threshold)
  }
  const conds = condition.args.conditions
  if (Array.isArray(conds)) {
    vars.conditions = `${conds.length} 个条件`
  }
  const cond = condition.args.condition as BlockRef | undefined
  if (cond) {
    const cBlock = catalog.conditions.find((b) => b.kind === cond.kind)
    vars.condition = cBlock ? blockLabel(cBlock) : (cond.kind || '?')
  }
  return fillTemplate(tpl, vars)
}

// ============================================================
// BlockPicker — 积木选择下拉（按 category 分组，中文化 label）
// ============================================================

interface BlockPickerProps {
  blocks: BlockMeta[]
  value: string | null
  onChange: (kind: string | null) => void
  placeholder?: string
}

function BlockPicker({ blocks, value, onChange, placeholder = '选择积木' }: BlockPickerProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const grouped = useMemo(() => {
    const map = new Map<string, BlockMeta[]>()
    for (const b of blocks) {
      if (!map.has(b.category)) map.set(b.category, [])
      map.get(b.category)!.push(b)
    }
    return Array.from(map.entries())
  }, [blocks])

  const selected = blocks.find((b) => b.kind === value)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] hover:border-[#00D4AA]/30 transition-all w-full justify-between focus:outline-none focus:border-[#00D4AA]"
      >
        <span className={selected ? 'text-[#E8E8ED]' : 'text-[#6B6B7B]'}>
          {selected ? blockLabel(selected) : placeholder}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#6B6B7B] transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#14141A] border border-[#1E1E28] rounded-md shadow-[0_0_30px_rgba(0,0,0,0.5)] max-h-60 overflow-y-auto py-1">
          {grouped.map(([category, items]) => (
            <div key={category}>
              <div className="text-[10px] text-[#6B6B7B] px-3 py-1 uppercase tracking-wide border-b border-[#1E1E28]/50">{category}</div>
              {items.map((b) => (
                <button
                  key={b.kind}
                  type="button"
                  onClick={() => { onChange(b.kind); setOpen(false) }}
                  className={`w-full text-left px-3 py-1.5 text-sm transition-all ${
                    b.kind === value
                      ? 'bg-[#00D4AA]/10 text-[#00D4AA]'
                      : 'text-[#E8E8ED] hover:bg-[#1A1A24]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span>{blockLabel(b)}</span>
                    {b.label && b.label !== b.kind && (
                      <span className="text-[10px] text-[#6B6B7B] font-mono">{b.kind}</span>
                    )}
                  </div>
                  {b.description && <div className="text-xs text-[#6B6B7B] mt-0.5">{b.description}</div>}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// RefPicker — 参数引用选择（$params.xxx / $meta.base_symbol）
// ============================================================

interface RefPickerProps {
  references: string[]
  current: unknown
  onPick: (ref: string) => void
}

/** 在参数输入旁渲染“引用”下拉，可选择已定义的 params 或 meta.base_symbol。 */
function RefPicker({ references, current, onPick }: RefPickerProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const isRef = typeof current === 'string' && current.startsWith('$')

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (references.length === 0) return null

  const options = references.map((r) => ({ value: r, label: r }))

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        title="引用变量"
        className={`flex items-center gap-1 px-2 py-1.5 text-xs rounded-md border transition-all ${
          isRef
            ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/30'
            : 'bg-[#0C0C14] text-[#6B6B7B] border-[#1E1E28] hover:text-[#E8E8ED]'
        }`}
      >
        <Link2 className="w-3 h-3" />
        {isRef ? <span className="font-mono">{current as string}</span> : '引用'}
      </button>
      {open && (
        <div className="absolute z-50 right-0 mt-1 min-w-[10rem] bg-[#14141A] border border-[#1E1E28] rounded-md shadow-[0_0_30px_rgba(0,0,0,0.5)] py-1">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => { onPick(o.value); setOpen(false) }}
              className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors ${
                o.value === current ? 'bg-[#00D4AA]/10 text-[#00D4AA]' : 'text-[#E8E8ED] hover:bg-[#1A1A24]'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// BlockArgsForm — 积木参数动态表单（按类型渲染，symbol 继承）
// ============================================================

interface BlockArgsFormProps {
  block: BlockMeta | null
  args: Record<string, unknown>
  onChange: (args: Record<string, unknown>) => void
  /** 传入则 symbol 参数自动继承该值并隐藏编辑控件（规则级继承）。 */
  inheritSymbol?: string
  /** 引用变量候选（基础策略参数引用 $params.xxx / $meta.base_symbol）。 */
  references?: string[]
}

function BlockArgsForm({ block, args, onChange, inheritSymbol, references }: BlockArgsFormProps) {
  const schema = useMemo(() => {
    if (!block) return {}
    return normalizeParamSchema(block.param_schema)
  }, [block])

  if (!block) return null

  const entries = Object.entries(schema)
  if (entries.length === 0) {
    return <div className="text-xs text-[#6B6B7B] italic">该积木无需参数</div>
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {entries.map(([name, param]) => {
        if (param.type === 'object' || param.type === 'array') {
          return (
            <div key={name} className="col-span-full text-xs text-[#6B6B7B] italic">
              参数「{param.label || name}」为复杂类型（{param.type}），由专用编辑器处理
            </div>
          )
        }
        // symbol 继承：规则级 symbol 自动取基础策略交易对
        if (name === 'symbol' && inheritSymbol !== undefined) {
          return (
            <div key={name} className="col-span-full">
              <label className="text-[10px] text-[#6B6B7B]">
                {param.label || name}
                <span className="ml-1 text-[#00D4AA]/70">（继承基础策略交易对）</span>
              </label>
              <div className="mt-0.5 px-3 py-1.5 text-sm text-[#00D4AA] bg-[#00D4AA]/5 border border-[#00D4AA]/20 rounded-md font-mono">
                {inheritSymbol}
              </div>
            </div>
          )
        }

        const val = args[name]
        const label = param.label || name
        const showUnit = Boolean(param.unit)

        return (
          <div key={name} className={name === 'symbol' ? 'col-span-full' : ''}>
            <label className="text-[10px] text-[#6B6B7B] flex items-center gap-1">
              {label}
              {param.unit && <span className="text-[#00D4AA]/60">（{param.unit}）</span>}
              {param.required && <span className="text-[#FF4757]">*</span>}
            </label>

            {param.type === 'bool' ? (
              <button
                type="button"
                onClick={() => onChange({ ...args, [name]: !val })}
                className={`mt-0.5 w-full px-3 py-1.5 text-sm rounded-md border transition-all ${
                  val
                    ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/30'
                    : 'bg-[#0C0C14] text-[#6B6B7B] border-[#1E1E28]'
                }`}
              >
                {val ? '开启' : '关闭'}
              </button>
            ) : param.type === 'select' && param.options ? (
              <div className="mt-0.5">
                <Dropdown
                  options={param.options.map((opt, i) => ({
                    value: opt,
                    label: param.option_labels?.[i] || opt,
                  }))}
                  value={val !== undefined && val !== null ? String(val) : ''}
                  onChange={(v) => onChange({ ...args, [name]: v })}
                  placeholder="请选择"
                />
              </div>
            ) : name === 'symbol' ? (
              // 基础策略区的 symbol 参数用 SymbolPicker
              <div className="mt-0.5">
                <SymbolPicker
                  value={val !== undefined && val !== null ? String(val) : ''}
                  onChange={(v) => onChange({ ...args, [name]: v })}
                />
              </div>
            ) : param.type === 'number' ? (
              <div className="mt-0.5 flex items-center gap-1">
                <input
                  type="number"
                  step={param.step ?? 'any'}
                  min={param.min}
                  max={param.max}
                  value={val !== undefined && val !== null ? String(val) : ''}
                  onChange={(e) => {
                    const raw = e.target.value
                    onChange({ ...args, [name]: raw === '' ? '' : Number(raw) })
                  }}
                  className="flex-1 min-w-0 bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
                />
                {references && references.length > 0 && (
                  <RefPicker
                    references={references}
                    current={val}
                    onPick={(r) => onChange({ ...args, [name]: r })}
                  />
                )}
              </div>
            ) : (
              <div className="mt-0.5 flex items-center gap-1">
                <input
                  type="text"
                  value={val !== undefined && val !== null ? String(val) : ''}
                  placeholder={param.description}
                  onChange={(e) => onChange({ ...args, [name]: e.target.value })}
                  className="flex-1 min-w-0 bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
                />
                {references && references.length > 0 && (
                  <RefPicker
                    references={references}
                    current={val}
                    onPick={(r) => onChange({ ...args, [name]: r })}
                  />
                )}
              </div>
            )}
            {param.min !== undefined && param.max !== undefined && param.type === 'number' && (
              <div className="text-[10px] text-[#6B6B7B] mt-0.5">范围：{param.min} ~ {param.max}{showUnit ? ` ${param.unit}` : ''}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// IndicatorRefEditor — 嵌套指标引用编辑器（条件 args.indicator）
// ============================================================

interface IndicatorRefEditorProps {
  indicatorRef: BlockRef | null
  onChange: (ref: BlockRef | null) => void
  catalog: BlockCatalog
  baseSymbol?: string
}

function IndicatorRefEditor({ indicatorRef, onChange, catalog, baseSymbol }: IndicatorRefEditorProps) {
  const selectedIndicator = catalog.indicators.find((b) => b.kind === indicatorRef?.kind) ?? null

  return (
    <div className="border border-[#1E1E28] rounded-md p-2 bg-[#0C0C14]/50">
      <div className="text-[10px] text-[#00D4AA] mb-1.5 uppercase tracking-wide">指标引用</div>
      <div className="space-y-2">
        <BlockPicker
          blocks={catalog.indicators}
          value={indicatorRef?.kind ?? null}
          onChange={(kind) => {
            if (!kind) { onChange(null); return }
            const block = catalog.indicators.find((b) => b.kind === kind)
            const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
            onChange({ kind, args: defaultArgs })
          }}
          placeholder="选择指标"
        />
        {selectedIndicator && indicatorRef && (
          <BlockArgsForm
            block={selectedIndicator}
            args={indicatorRef.args}
            onChange={(newArgs) => onChange({ ...indicatorRef, args: newArgs })}
            inheritSymbol={baseSymbol}
          />
        )}
      </div>
    </div>
  )
}

// ============================================================
// SimpleConditionEditor — 简单条件水平布局
// [指标label下拉] [运算符中文下拉] [阈值输入]
// ============================================================

interface SimpleConditionEditorProps {
  condition: BlockRef
  onChange: (condition: BlockRef) => void
  catalog: BlockCatalog
  baseSymbol?: string
}

function SimpleConditionEditor({ condition, onChange, catalog, baseSymbol }: SimpleConditionEditorProps) {
  const indRef = (condition.args.indicator as BlockRef | undefined) ?? null
  const threshold = condition.args.threshold

  return (
    <div className="flex flex-wrap items-end gap-2">
      {/* 指标选择 */}
      <div className="flex-1 min-w-[140px]">
        <label className="text-[10px] text-[#6B6B7B]">指标</label>
        <div className="mt-0.5">
          <BlockPicker
            blocks={catalog.indicators}
            value={indRef?.kind ?? null}
            onChange={(kind) => {
              if (!kind) { onChange({ ...condition, args: { ...condition.args, indicator: undefined } }); return }
              const block = catalog.indicators.find((b) => b.kind === kind)
              const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
              onChange({ ...condition, args: { ...condition.args, indicator: { kind, args: defaultArgs } } })
            }}
            placeholder="选择指标"
          />
        </div>
      </div>

      {/* 运算符下拉 */}
      <div className="w-[120px]">
        <label className="text-[10px] text-[#6B6B7B]">运算符</label>
        <div className="mt-0.5">
          <Dropdown
            options={SIMPLE_CONDITIONS}
            value={condition.kind}
            onChange={(v) => onChange({ ...condition, kind: String(v) })}
          />
        </div>
      </div>

      {/* 阈值输入 */}
      <div className="w-[110px]">
        <label className="text-[10px] text-[#6B6B7B]">阈值</label>
        <input
          type="number"
          step="any"
          value={threshold !== undefined && threshold !== null ? String(threshold) : ''}
          onChange={(e) => {
            const raw = e.target.value
            onChange({ ...condition, args: { ...condition.args, threshold: raw === '' ? '' : Number(raw) } })
          }}
          placeholder="如 70"
          className="w-full mt-0.5 bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
        />
      </div>

      <button
        type="button"
        onClick={() => onChange({ kind: '', args: {} })}
        title="切换条件类型"
        className="text-[#6B6B7B] hover:text-[#E8E8ED] p-1.5 shrink-0"
      >
        <Settings className="w-3.5 h-3.5" />
      </button>

      {/* 指标参数（展开） */}
      {indRef && indRef.kind && (
        <div className="w-full">
          <IndicatorRefEditor
            indicatorRef={indRef}
            onChange={(ref) => onChange({ ...condition, args: { ...condition.args, indicator: ref ?? undefined } })}
            catalog={catalog}
            baseSymbol={baseSymbol}
          />
        </div>
      )}
    </div>
  )
}

// ============================================================
// LogicConditionEditor — 嵌套 and/or/not 可视化
// ============================================================

interface LogicConditionEditorProps {
  condition: BlockRef
  onChange: (condition: BlockRef) => void
  catalog: BlockCatalog
  baseSymbol?: string
  depth?: number
}

function LogicConditionEditor({ condition, onChange, catalog, baseSymbol, depth = 0 }: LogicConditionEditorProps) {
  const block = catalog.conditions.find((b) => b.kind === condition.kind)

  if (condition.kind === 'not') {
    const child = (condition.args.condition as BlockRef | undefined) ?? null
    return (
      <div className="space-y-2 border border-[#1E1E28] rounded-md p-2 bg-[#0C0C14]/40">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-[#F0A500] uppercase tracking-wide">取反（NOT）</span>
          <button
            type="button"
            onClick={() => onChange({ kind: '', args: {} })}
            className="text-[#6B6B7B] hover:text-[#E8E8ED] p-0.5"
            title="切换条件类型"
          >
            <Settings className="w-3 h-3" />
          </button>
        </div>
        {child ? (
          <ConditionEditor
            condition={child}
            onChange={(c) => onChange({ ...condition, args: { ...condition.args, condition: c } })}
            catalog={catalog}
            baseSymbol={baseSymbol}
            depth={depth + 1}
          />
        ) : (
          <button
            type="button"
            onClick={() => onChange({ ...condition, args: { ...condition.args, condition: { kind: '', args: {} } } })}
            className="text-xs text-[#00D4AA] hover:underline"
          >
            + 添加子条件
          </button>
        )}
      </div>
    )
  }

  // and / or
  const children = Array.isArray(condition.args.conditions)
    ? (condition.args.conditions as BlockRef[])
    : []
  const summary = block ? blockLabel(block) : condition.kind

  return (
    <div className="space-y-2 border border-[#1E1E28] rounded-md p-2 bg-[#0C0C14]/40">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#00D4AA] uppercase tracking-wide">
          {summary}（{children.length} 个子条件）
        </span>
        <button
          type="button"
          onClick={() => onChange({ kind: '', args: {} })}
          className="text-[#6B6B7B] hover:text-[#E8E8ED] p-0.5"
          title="切换条件类型"
        >
          <Settings className="w-3 h-3" />
        </button>
      </div>
      {children.length === 0 && (
        <div className="text-xs text-[#6B6B7B] italic">暂无子条件</div>
      )}
      <div className="space-y-2">
        {children.map((child, idx) => (
          <div key={idx} className="flex items-start gap-2">
            <span className="text-[10px] text-[#6B6B7B] font-mono shrink-0 mt-2">#{idx + 1}</span>
            <div className="flex-1 min-w-0">
              <ConditionEditor
                condition={child}
                onChange={(c) => {
                  const next = [...children]
                  next[idx] = c
                  onChange({ ...condition, args: { ...condition.args, conditions: next } })
                }}
                catalog={catalog}
                baseSymbol={baseSymbol}
                depth={depth + 1}
              />
            </div>
            <button
              type="button"
              onClick={() => {
                const next = children.filter((_, i) => i !== idx)
                onChange({ ...condition, args: { ...condition.args, conditions: next } })
              }}
              className="text-[#6B6B7B] hover:text-[#FF4757] p-1 mt-1 shrink-0"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => onChange({
          ...condition,
          args: { ...condition.args, conditions: [...children, { kind: '', args: {} }] },
        })}
        className="text-xs text-[#00D4AA] hover:underline"
      >
        + 添加子条件
      </button>
    </div>
  )
}

// ============================================================
// ConditionEditor — 单个条件编辑（分发简单/逻辑/未选）
// ============================================================

interface ConditionEditorProps {
  condition: BlockRef
  onChange: (condition: BlockRef) => void
  catalog: BlockCatalog
  baseSymbol?: string
  depth?: number
}

function ConditionEditor({ condition, onChange, catalog, baseSymbol, depth = 0 }: ConditionEditorProps) {
  const selectedBlock = catalog.conditions.find((b) => b.kind === condition.kind) ?? null
  const isLogic = selectedBlock ? LOGIC_CONDITIONS.has(selectedBlock.kind) : false
  const isSimple = selectedBlock ? SIMPLE_KIND_SET.has(selectedBlock.kind) : false

  // 未选择 → BlockPicker
  if (!condition.kind || !selectedBlock) {
    return (
      <BlockPicker
        blocks={catalog.conditions}
        value={condition.kind || null}
        onChange={(kind) => {
          if (!kind) { onChange({ kind: '', args: {} }); return }
          const block = catalog.conditions.find((b) => b.kind === kind)
          const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
          const sch = normalizeParamSchema(block?.param_schema)
          if ('indicator' in sch && sch.indicator?.type === 'object') {
            defaultArgs.indicator = { kind: '', args: {} }
          }
          if ('conditions' in sch && sch.conditions?.type === 'array') {
            defaultArgs.conditions = []
          }
          if ('condition' in sch && sch.condition?.type === 'object') {
            defaultArgs.condition = { kind: '', args: {} }
          }
          onChange({ kind, args: defaultArgs })
        }}
        placeholder="选择条件"
      />
    )
  }

  // 简单比较条件 → 水平布局
  if (isSimple) {
    return (
      <SimpleConditionEditor
        condition={condition}
        onChange={onChange}
        catalog={catalog}
        baseSymbol={baseSymbol}
      />
    )
  }

  // 逻辑组合条件 → 嵌套可视化
  if (isLogic) {
    return (
      <LogicConditionEditor
        condition={condition}
        onChange={onChange}
        catalog={catalog}
        baseSymbol={baseSymbol}
        depth={depth}
      />
    )
  }

  // 其他条件类型 → 通用表单 + indicator 嵌套
  const schema = normalizeParamSchema(selectedBlock.param_schema)
  const hasIndicatorParam = 'indicator' in schema && schema.indicator?.type === 'object'
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <BlockPicker
            blocks={catalog.conditions}
            value={condition.kind || null}
            onChange={(kind) => {
              if (!kind) { onChange({ kind: '', args: {} }); return }
              const block = catalog.conditions.find((b) => b.kind === kind)
              const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
              onChange({ kind, args: defaultArgs })
            }}
            placeholder="选择条件"
          />
        </div>
        <button
          type="button"
          onClick={() => onChange({ kind: '', args: {} })}
          className="text-[#6B6B7B] hover:text-[#E8E8ED] p-1.5 shrink-0"
          title="切换条件类型"
        >
          <Settings className="w-3.5 h-3.5" />
        </button>
      </div>
      {hasIndicatorParam ? (
        <div className="space-y-2">
          <BlockArgsForm
            block={selectedBlock}
            args={condition.args}
            onChange={(newArgs) => onChange({ ...condition, args: newArgs })}
            inheritSymbol={baseSymbol}
          />
          <IndicatorRefEditor
            indicatorRef={(condition.args.indicator as BlockRef) ?? null}
            onChange={(ref) => onChange({ ...condition, args: { ...condition.args, indicator: ref } })}
            catalog={catalog}
            baseSymbol={baseSymbol}
          />
        </div>
      ) : (
        <BlockArgsForm
          block={selectedBlock}
          args={condition.args}
          onChange={(newArgs) => onChange({ ...condition, args: newArgs })}
          inheritSymbol={baseSymbol}
        />
      )}
    </div>
  )
}

// ============================================================
// TriggerEditor — 触发器编辑（mode 切换 condition/event + extra_condition）
// ============================================================

interface TriggerEditorProps {
  trigger: Trigger
  onChange: (trigger: Trigger) => void
  catalog: BlockCatalog
  label: string
  baseSymbol?: string
}

function TriggerEditor({ trigger, onChange, catalog, label, baseSymbol }: TriggerEditorProps) {
  const selectedEvent = trigger.mode === 'event'
    ? catalog.events.find((b) => b.kind === trigger.event?.kind) ?? null
    : null

  const hasMainTrigger = trigger.mode === 'condition'
    ? Boolean(trigger.condition)
    : Boolean(trigger.event)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-[#6B6B7B] uppercase tracking-wide min-w-[90px]">{label}</span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => onChange({
              ...trigger,
              mode: 'condition',
              event: null,
              condition: trigger.condition ?? { kind: '', args: {} },
            })}
            className={`px-2 py-0.5 text-xs rounded transition-all ${
              trigger.mode === 'condition'
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border border-[#00D4AA]/30'
                : 'text-[#6B6B7B] border border-[#1E1E28] hover:text-[#E8E8ED]'
            }`}
          >
            条件
          </button>
          <button
            type="button"
            onClick={() => onChange({
              ...trigger,
              mode: 'event',
              condition: null,
              event: trigger.event ?? { kind: '', args: {} },
            })}
            className={`px-2 py-0.5 text-xs rounded transition-all ${
              trigger.mode === 'event'
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border border-[#00D4AA]/30'
                : 'text-[#6B6B7B] border border-[#1E1E28] hover:text-[#E8E8ED]'
            }`}
          >
            事件
          </button>
        </div>
      </div>

      {trigger.mode === 'condition' && (
        <div className="space-y-2 pl-3 border-l border-[#1E1E28]">
          {trigger.condition ? (
            <ConditionEditor
              condition={trigger.condition}
              onChange={(condition) => onChange({ ...trigger, condition })}
              catalog={catalog}
              baseSymbol={baseSymbol}
            />
          ) : (
            <button
              type="button"
              onClick={() => onChange({ ...trigger, condition: { kind: '', args: {} } })}
              className="text-xs text-[#00D4AA] hover:underline"
            >
              + 添加条件
            </button>
          )}
        </div>
      )}

      {trigger.mode === 'event' && (
        <div className="space-y-2 pl-3 border-l border-[#1E1E28]">
          {trigger.event ? (
            <>
              <BlockPicker
                blocks={catalog.events}
                value={trigger.event.kind || null}
                onChange={(kind) => {
                  if (!kind) { onChange({ ...trigger, event: null }); return }
                  const block = catalog.events.find((b) => b.kind === kind)
                  const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
                  onChange({ ...trigger, event: { kind, args: defaultArgs } })
                }}
                placeholder="选择事件"
              />
              {selectedEvent && trigger.event && (
                <BlockArgsForm
                  block={selectedEvent}
                  args={trigger.event.args}
                  onChange={(newArgs) => onChange({ ...trigger, event: { ...trigger.event!, args: newArgs } })}
                  inheritSymbol={baseSymbol}
                />
              )}
            </>
          ) : (
            <button
              type="button"
              onClick={() => onChange({ ...trigger, event: { kind: '', args: {} } })}
              className="text-xs text-[#00D4AA] hover:underline"
            >
              + 添加事件
            </button>
          )}
        </div>
      )}

      {/* 额外条件（可选，AND 关系） */}
      {hasMainTrigger && (
        <div className="pl-3">
          {trigger.extra_condition ? (
            <div className="space-y-2 border-l border-[#1E1E28] pl-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#F0A500] uppercase tracking-wide">额外条件 (AND)</span>
                <button
                  type="button"
                  onClick={() => onChange({ ...trigger, extra_condition: null })}
                  className="text-[#6B6B7B] hover:text-[#FF4757] p-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
              <ConditionEditor
                condition={trigger.extra_condition}
                onChange={(extra) => onChange({ ...trigger, extra_condition: extra })}
                catalog={catalog}
                baseSymbol={baseSymbol}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => onChange({ ...trigger, extra_condition: { kind: '', args: {} } })}
              className="text-xs text-[#6B6B7B] hover:text-[#00D4AA] transition-colors"
            >
              + 添加额外条件
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ============================================================
// ActionListEditor — 动作列表编辑（symbol 自动继承）
// ============================================================

interface ActionListEditorProps {
  actions: BlockRef[]
  onChange: (actions: BlockRef[]) => void
  catalog: BlockCatalog
  label: string
  baseSymbol?: string
}

function ActionListEditor({ actions, onChange, catalog, label, baseSymbol }: ActionListEditorProps) {
  return (
    <div className="space-y-2">
      <span className="text-[10px] text-[#6B6B7B] uppercase tracking-wide">{label}</span>
      {actions.length === 0 && (
        <div className="text-xs text-[#6B6B7B] italic">暂无动作</div>
      )}
      {actions.map((action, idx) => {
        const selectedBlock = catalog.actions.find((b) => b.kind === action.kind) ?? null
        return (
          <div key={idx} className="border border-[#1E1E28] rounded-md p-2 bg-[#0C0C14]/50 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#6B6B7B] font-mono shrink-0">#{idx + 1}</span>
              <div className="flex-1 min-w-0">
                <BlockPicker
                  blocks={catalog.actions}
                  value={action.kind || null}
                  onChange={(kind) => {
                    if (!kind) return
                    const block = catalog.actions.find((b) => b.kind === kind)
                    const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
                    const newActions = [...actions]
                    newActions[idx] = { kind, args: defaultArgs }
                    onChange(newActions)
                  }}
                  placeholder="选择动作"
                />
              </div>
              <button
                type="button"
                onClick={() => onChange(actions.filter((_, i) => i !== idx))}
                className="text-[#6B6B7B] hover:text-[#FF4757] p-1 shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            {selectedBlock && (
              <BlockArgsForm
                block={selectedBlock}
                args={action.args}
                onChange={(newArgs) => {
                  const newActions = [...actions]
                  newActions[idx] = { ...action, args: newArgs }
                  onChange(newActions)
                }}
                inheritSymbol={baseSymbol}
              />
            )}
          </div>
        )
      })}
      <button
        type="button"
        onClick={() => onChange([...actions, { kind: '', args: {} }])}
        className="text-xs text-[#00D4AA] hover:underline"
      >
        + 添加动作
      </button>
    </div>
  )
}

// ============================================================
// RuleCard — 规则卡片（可折叠，display_template 摘要头部）
// ============================================================

interface RuleCardProps {
  rule: Rule
  onChange: (rule: Rule) => void
  onDelete: () => void
  catalog: BlockCatalog
  baseSymbol?: string
}

function RuleCard({ rule, onChange, onDelete, catalog, baseSymbol }: RuleCardProps) {
  const [expanded, setExpanded] = useState(true)
  const [showRecover, setShowRecover] = useState(
    Boolean(rule.recover_when || (rule.recover_then && rule.recover_then.length > 0)),
  )

  // 用 display_template 渲染 WHEN 摘要
  const whenSummary = useMemo(() => {
    const cond = rule.when.condition
    if (rule.when.mode === 'condition' && cond) {
      return renderConditionSummary(cond, catalog)
    }
    if (rule.when.mode === 'event' && rule.when.event) {
      const blk = catalog.events.find((b) => b.kind === rule.when.event!.kind)
      return blk ? blockLabel(blk) : (rule.when.event.kind || '未设置')
    }
    return '未设置'
  }, [rule, catalog])

  const thenCount = rule.then.length

  return (
    <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-lg overflow-hidden">
      {/* 卡片头部 */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer hover:bg-[#1A1A24]/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <ChevronDown className={`w-4 h-4 text-[#6B6B7B] transition-transform shrink-0 ${expanded ? 'rotate-180' : ''}`} />
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-[#E8E8ED]">{rule.name || '未命名规则'}</span>
          <div className="mt-0.5 text-xs text-[#6B6B7B] truncate">
            <span className="text-[#6B6B7B]">当 </span>
            <span className="text-[#00D4AA]/80">{whenSummary}</span>
            <span className="text-[#6B6B7B]"> 时执行 {thenCount} 个动作</span>
          </div>
        </div>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          className="text-[#6B6B7B] hover:text-[#FF4757] p-1 shrink-0"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* 卡片内容 */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-[#1E1E28] pt-3 space-y-3">
              {/* 规则名 */}
              <div>
                <label className="text-[10px] text-[#6B6B7B] uppercase tracking-wide">规则名称</label>
                <input
                  value={rule.name}
                  onChange={(e) => onChange({ ...rule, name: e.target.value })}
                  placeholder="如：单边上涨暂停"
                  className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                />
              </div>

              {/* WHEN */}
              <TriggerEditor
                trigger={rule.when}
                onChange={(when) => onChange({ ...rule, when })}
                catalog={catalog}
                label="WHEN"
                baseSymbol={baseSymbol}
              />

              {/* THEN */}
              <ActionListEditor
                actions={rule.then}
                onChange={(then) => onChange({ ...rule, then })}
                catalog={catalog}
                label="THEN"
                baseSymbol={baseSymbol}
              />

              {/* 恢复逻辑 */}
              {showRecover ? (
                <div className="space-y-3 border-t border-[#1E1E28] pt-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[#F0A500] uppercase tracking-wide">恢复逻辑</span>
                    <button
                      type="button"
                      onClick={() => {
                        setShowRecover(false)
                        onChange({ ...rule, recover_when: null, recover_then: [] })
                      }}
                      className="text-[#6B6B7B] hover:text-[#FF4757] text-xs"
                    >
                      <X className="w-3 h-3 inline" /> 移除恢复
                    </button>
                  </div>
                  <TriggerEditor
                    trigger={rule.recover_when ?? { mode: 'condition', condition: null, event: null, extra_condition: null }}
                    onChange={(recover_when) => onChange({ ...rule, recover_when })}
                    catalog={catalog}
                    label="RECOVER_WHEN"
                    baseSymbol={baseSymbol}
                  />
                  <ActionListEditor
                    actions={rule.recover_then ?? []}
                    onChange={(recover_then) => onChange({ ...rule, recover_then })}
                    catalog={catalog}
                    label="RECOVER_THEN"
                    baseSymbol={baseSymbol}
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowRecover(true)}
                  className="text-xs text-[#F0A500] hover:underline"
                >
                  + 添加恢复条件
                </button>
              )}

              {/* 冷却时间 */}
              <div>
                <label className="text-[10px] text-[#6B6B7B] uppercase tracking-wide">冷却时间（秒）</label>
                <input
                  type="number"
                  min={0}
                  value={String(rule.cool_down_seconds ?? 0)}
                  onChange={(e) => onChange({ ...rule, cool_down_seconds: Number(e.target.value) })}
                  className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ============================================================
// CollapsibleSection — 可折叠分区
// ============================================================

interface SectionProps {
  title: string
  icon: ReactNode
  children: ReactNode
  defaultCollapsed?: boolean
  accent?: string
}

function CollapsibleSection({ title, icon, children, defaultCollapsed = false, accent = '#00D4AA' }: SectionProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  return (
    <div className="border border-[#1E1E28] rounded-lg bg-[#14141A]/50">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 w-full px-3 py-2.5 text-left"
      >
        <span style={{ color: accent }}>{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: accent }}>{title}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#6B6B7B] transition-transform ml-auto ${collapsed ? '' : 'rotate-180'}`} />
      </button>
      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-[#1E1E28] pt-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ============================================================
// ParamsEditor — PARAMS 区可变参数定义列表
// ============================================================

interface ParamsEditorProps {
  params: Record<string, ParamDefinition>
  onChange: (params: Record<string, ParamDefinition>) => void
}

const PARAM_TYPES: { value: string; label: string }[] = [
  { value: 'int', label: '整数' },
  { value: 'float', label: '浮点' },
  { value: 'string', label: '字符串' },
  { value: 'bool', label: '布尔' },
  { value: 'select', label: '枚举' },
]

function ParamsEditor({ params, onChange }: ParamsEditorProps) {
  const entries = Object.entries(params)

  function update(key: string, patch: Partial<ParamDefinition>) {
    const next = { ...params }
    next[key] = { ...next[key], ...patch }
    onChange(next)
  }
  function updateKey(oldKey: string, newKey: string) {
    if (oldKey === newKey || params[newKey]) return
    const next: Record<string, ParamDefinition> = {}
    for (const [k, v] of Object.entries(params)) {
      next[k === oldKey ? newKey : k] = v
    }
    onChange(next)
  }
  function remove(key: string) {
    const next = { ...params }
    delete next[key]
    onChange(next)
  }
  function add() {
    let idx = 1
    while (params[`param_${idx}`]) idx++
    onChange({ ...params, [`param_${idx}`]: { label: `参数 ${idx}`, value: 0, type: 'float' } })
  }

  return (
    <div className="space-y-2">
      {entries.length === 0 && (
        <div className="text-xs text-[#6B6B7B] italic">暂无可变参数，可在 LOGIC 区通过 $params.xxx 引用</div>
      )}
      {entries.map(([key, def]) => (
        <div key={key} className="grid grid-cols-12 gap-1.5 items-center bg-[#0C0C14] border border-[#1E1E28] rounded-md p-2">
          <input
            value={key}
            onChange={(e) => updateKey(key, e.target.value)}
            placeholder="参数名"
            className="col-span-3 bg-transparent border border-[#1E1E28] rounded px-2 py-1 text-xs text-[#00D4AA] focus:outline-none focus:border-[#00D4AA] font-mono"
          />
          <input
            value={def.label}
            onChange={(e) => update(key, { label: e.target.value })}
            placeholder="标签"
            className="col-span-3 bg-transparent border border-[#1E1E28] rounded px-2 py-1 text-xs text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
          />
          <div className="col-span-2">
            <Dropdown
              options={PARAM_TYPES}
              value={def.type}
              onChange={(v) => update(key, { type: v as ParamDefinition['type'] })}
            />
          </div>
          <input
            type={def.type === 'int' || def.type === 'float' ? 'number' : 'text'}
            value={def.value === undefined || def.value === null ? '' : String(def.value)}
            onChange={(e) => {
              const raw = e.target.value
              const v = def.type === 'int' || def.type === 'float' ? (raw === '' ? '' : Number(raw)) : raw
              update(key, { value: v })
            }}
            placeholder="默认值"
            className="col-span-2 bg-transparent border border-[#1E1E28] rounded px-2 py-1 text-xs text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
          />
          <div className="col-span-1 flex items-center justify-center">
            <button
              type="button"
              onClick={() => remove(key)}
              className="text-[#6B6B7B] hover:text-[#FF4757] p-0.5"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
          {(def.type === 'int' || def.type === 'float') && (
            <div className="col-span-12 flex items-center gap-1 text-[10px] text-[#6B6B7B]">
              <span>范围</span>
              <input
                type="number"
                value={def.range ? String(def.range[0]) : ''}
                onChange={(e) => {
                  const lo = e.target.value === '' ? undefined : Number(e.target.value)
                  const hi = def.range?.[1]
                  update(key, { range: lo !== undefined || hi !== undefined ? [lo ?? 0, hi ?? 0] : undefined })
                }}
                placeholder="下限"
                className="w-16 bg-transparent border border-[#1E1E28] rounded px-1 py-0.5 text-[10px] text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
              />
              <span>~</span>
              <input
                type="number"
                value={def.range ? String(def.range[1]) : ''}
                onChange={(e) => {
                  const hi = e.target.value === '' ? undefined : Number(e.target.value)
                  const lo = def.range?.[0]
                  update(key, { range: lo !== undefined || hi !== undefined ? [lo ?? 0, hi ?? 0] : undefined })
                }}
                placeholder="上限"
                className="w-16 bg-transparent border border-[#1E1E28] rounded px-1 py-0.5 text-[10px] text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
              />
            </div>
          )}
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="w-full flex items-center justify-center gap-1 text-xs text-[#00D4AA] border border-dashed border-[#1E1E28] rounded-md py-1.5 hover:border-[#00D4AA]/30 transition-colors"
      >
        <Plus className="w-3.5 h-3.5" /> 添加参数
      </button>
    </div>
  )
}

// ============================================================
// DslEditor — QS-Model 主组件（四段式布局）
// ============================================================

interface DslEditorProps {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

function initialConfig(): DslConfig {
  return {
    version: '1.0',
    base_strategy: { kind: 'grid', params: {} },
    rules: [],
  }
}

function emptyTrigger(): Trigger {
  return { mode: 'condition', condition: null, event: null, extra_condition: null }
}

function initialMeta(): QSModelMeta {
  return {
    name: '',
    version: '1.0',
    author: '',
    description: '',
    asset_class: 'crypto',
    frequency: '1H',
    base_symbol: 'BTC-USDT',
  }
}

export default function DslEditor({ open, onClose, onSaved }: DslEditorProps) {
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null)
  const [dslConfig, setDslConfig] = useState<DslConfig>(initialConfig)
  const [meta, setMeta] = useState<QSModelMeta>(initialMeta)
  const [params, setParams] = useState<Record<string, ParamDefinition>>({})
  const [riskFilter, setRiskFilter] = useState<RiskFilter>({
    max_position_ratio: 0.5,
    daily_max_loss: 0.05,
    min_trade_size: 0,
  })
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [dryRunning, setDryRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showDryRunDetail, setShowDryRunDetail] = useState(false)
  const [dupConfirm, setDupConfirm] = useState<string | null>(null)

  useEffect(() => {
    if (open && !catalog) {
      getBlocks().then((res) => setCatalog(res.data)).catch(() => {})
    }
  }, [open, catalog])

  const baseStrategyBlock = catalog?.base_strategies.find((b) => b.kind === dslConfig.base_strategy.kind) ?? null

  // 基础交易对：meta.base_symbol 为唯一来源，与基础策略 symbol 双向同步
  const baseSymbol = useMemo(() => {
    const fromStrategy = dslConfig.base_strategy.params.symbol
    return (meta.base_symbol || (typeof fromStrategy === 'string' ? fromStrategy : '') || 'BTC-USDT')
  }, [meta.base_symbol, dslConfig.base_strategy.params.symbol])

  function handleBaseSymbolChange(sym: string) {
    setMeta((m) => ({ ...m, base_symbol: sym }))
    setDslConfig((c) => ({
      ...c,
      base_strategy: {
        ...c.base_strategy,
        params: { ...c.base_strategy.params, symbol: sym },
      },
    }))
  }

  // 引用变量候选（供基础策略参数引用 $params.xxx / $meta.base_symbol）
  const referenceOptions = useMemo(() => {
    const refs: string[] = ['$meta.base_symbol']
    for (const key of Object.keys(params)) refs.push(`$params.${key}`)
    return refs
  }, [params])

  async function handleValidate() {
    setValidating(true)
    try {
      const res = await validateDsl(dslConfig)
      setValidation(res.data)
    } catch {
      setValidation({
        valid: false,
        errors: [{ layer: 'request', code: 'NETWORK', message: '校验请求失败', path: '' }],
      })
    }
    setValidating(false)
  }

  async function handleDryRun() {
    setDryRunning(true)
    try {
      const res = await dryRunDsl({ config: dslConfig, symbol: baseSymbol, bar: '1H', limit: 50 })
      setDryRunResult(res.data)
    } catch {
      setDryRunResult(null)
    }
    setDryRunning(false)
  }

  // 将 rules 中所有指标/动作的 symbol 参数强制同步为基础交易对
  function syncRulesSymbol(config: DslConfig, sym: string): DslConfig {
    if (!catalog) return config
    const allBlocks = [
      ...catalog.indicators,
      ...catalog.actions,
      ...catalog.events,
    ]
    const blockMap = new Map(allBlocks.map((b) => [b.kind, b]))
    const syncRef = (ref: BlockRef): BlockRef => {
      const blk = blockMap.get(ref.kind)
      if (!blk) return ref
      const sch = normalizeParamSchema(blk.param_schema)
      if ('symbol' in sch && sch.symbol) {
        return { ...ref, args: { ...ref.args, symbol: sym } }
      }
      return ref
    }
    const syncCondition = (cond: BlockRef | null | undefined): BlockRef | null => {
      if (!cond) return cond ?? null
      let nextArgs = { ...cond.args }
      if (nextArgs.indicator) {
        nextArgs.indicator = syncRef(nextArgs.indicator as BlockRef)
      }
      if (Array.isArray(nextArgs.conditions)) {
        nextArgs.conditions = (nextArgs.conditions as BlockRef[]).map(syncCondition)
      }
      if (nextArgs.condition) {
        nextArgs.condition = syncCondition(nextArgs.condition as BlockRef)
      }
      return { ...cond, args: nextArgs }
    }
    const syncTrigger = (t: Trigger | null | undefined): Trigger | null => {
      if (!t) return t ?? null
      return {
        ...t,
        condition: syncCondition(t.condition),
        event: t.event ? syncRef(t.event) : null,
        extra_condition: syncCondition(t.extra_condition),
      }
    }
    return {
      ...config,
      rules: config.rules.map((r) => ({
        ...r,
        when: syncTrigger(r.when) ?? r.when,
        then: r.then.map(syncRef),
        recover_when: syncTrigger(r.recover_when),
        recover_then: r.recover_then?.map(syncRef),
      })),
    }
  }

  // 组装 QSModelConfig
  function buildQsModelConfig(forceConfig?: DslConfig): QSModelConfig {
    const logic = forceConfig ?? dslConfig
    return {
      qs_model_version: '1.0',
      meta: { ...meta, name: meta.name.trim(), base_symbol: baseSymbol },
      params,
      logic,
      risk_filter: riskFilter,
    }
  }

  async function doCreate(force: boolean) {
    const syncedConfig = syncRulesSymbol(dslConfig, baseSymbol)
    const qsModel = buildQsModelConfig(syncedConfig)
    const res = await createTemplate({
      name: meta.name.trim(),
      strategy_type: 'composable',
      description: meta.description,
      default_params: { symbol: baseSymbol },
      param_schema: null,
      dsl_config: syncedConfig as unknown as Record<string, unknown>,
      qs_model_config: qsModel,
      force,
    })
    return res.data
  }

  async function handleSave() {
    if (!meta.name.trim()) return
    if (!validation?.valid) {
      await handleValidate()
      return
    }
    setSaving(true)
    try {
      const created = await doCreate(false)
      // 检测哈希去重提示
      if (created?.duplicate_hint) {
        setDupConfirm(created.duplicate_hint)
        setSaving(false)
        return
      }
      onSaved()
      onClose()
      handleClose()
    } catch {
      /* ignore */
    }
    setSaving(false)
  }

  async function handleForceCreate() {
    setDupConfirm(null)
    setSaving(true)
    try {
      await doCreate(true)
      onSaved()
      onClose()
      handleClose()
    } catch {
      /* ignore */
    }
    setSaving(false)
  }

  function handleClose() {
    setDslConfig(initialConfig())
    setMeta(initialMeta())
    setParams({})
    setRiskFilter({ max_position_ratio: 0.5, daily_max_loss: 0.05, min_trade_size: 0 })
    setValidation(null)
    setDryRunResult(null)
    setDupConfirm(null)
  }

  function addRule() {
    setDslConfig({
      ...dslConfig,
      rules: [...dslConfig.rules, {
        name: `规则 ${dslConfig.rules.length + 1}`,
        when: emptyTrigger(),
        then: [],
        recover_when: null,
        recover_then: [],
        cool_down_seconds: 0,
      }],
    })
  }

  return (
    <Modal open={open} onClose={onClose} title="QS-Model 策略构建" wide scrollable={false}>
      <div className="space-y-4 max-h-[calc(100vh-12rem)] overflow-y-auto pr-1">
        {/* ============ META 区 ============ */}
        <div className="border border-[#1E1E28] rounded-lg p-3 bg-[#14141A]/50">
          <div className="text-xs text-[#00D4AA] mb-2 uppercase tracking-wide flex items-center gap-1">
            <Info className="w-3 h-3" /> META 元信息
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="sm:col-span-2">
              <label className="text-[10px] text-[#6B6B7B]">策略名称 *</label>
              <input
                value={meta.name}
                onChange={(e) => setMeta({ ...meta, name: e.target.value })}
                placeholder="如：网格-单边暂停策略"
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#6B6B7B]">作者</label>
              <input
                value={meta.author}
                onChange={(e) => setMeta({ ...meta, author: e.target.value })}
                placeholder="作者"
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#6B6B7B]">运行频率</label>
              <div className="mt-0.5">
                <Dropdown
                  options={[
                    { value: '1m', label: '1 分钟' },
                    { value: '5m', label: '5 分钟' },
                    { value: '15m', label: '15 分钟' },
                    { value: '1H', label: '1 小时' },
                    { value: '4H', label: '4 小时' },
                    { value: '1D', label: '1 天' },
                  ]}
                  value={meta.frequency}
                  onChange={(v) => setMeta({ ...meta, frequency: String(v) })}
                />
              </div>
            </div>
            <div className="sm:col-span-2">
              <label className="text-[10px] text-[#6B6B7B]">基准交易对</label>
              <div className="mt-0.5">
                <SymbolPicker
                  value={meta.base_symbol}
                  onChange={handleBaseSymbolChange}
                />
              </div>
            </div>
            <div className="sm:col-span-2">
              <label className="text-[10px] text-[#6B6B7B]">描述</label>
              <textarea
                value={meta.description}
                onChange={(e) => setMeta({ ...meta, description: e.target.value })}
                placeholder="策略逻辑描述"
                rows={2}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] resize-none"
              />
            </div>
          </div>
        </div>

        {/* ============ PARAMS 区（可折叠） ============ */}
        <CollapsibleSection title="PARAMS 可变参数" icon={<Sliders className="w-3 h-3" />} defaultCollapsed>
          <ParamsEditor params={params} onChange={setParams} />
        </CollapsibleSection>

        {/* ============ LOGIC 区 ============ */}
        <div className="border border-[#1E1E28] rounded-lg p-3 bg-[#14141A]/50">
          <div className="text-xs text-[#00D4AA] mb-2 uppercase tracking-wide flex items-center gap-1">
            <Settings className="w-3 h-3" /> LOGIC 策略逻辑
          </div>

          {/* 基础策略 */}
          <div className="space-y-2">
            <div className="text-[10px] text-[#6B6B7B] uppercase tracking-wide">基础策略</div>
            {catalog ? (
              <>
                <BlockPicker
                  blocks={catalog.base_strategies}
                  value={dslConfig.base_strategy.kind || null}
                  onChange={(kind) => {
                    if (!kind) return
                    const block = catalog.base_strategies.find((b) => b.kind === kind)
                    const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
                    defaultArgs.symbol = baseSymbol
                    setDslConfig({ ...dslConfig, base_strategy: { kind, params: defaultArgs } })
                  }}
                  placeholder="选择基础策略"
                />
                {baseStrategyBlock && (
                  <BlockArgsForm
                    block={baseStrategyBlock}
                    args={dslConfig.base_strategy.params}
                    onChange={(p) => setDslConfig({
                      ...dslConfig,
                      base_strategy: { ...dslConfig.base_strategy, params: p },
                    })}
                    references={referenceOptions}
                  />
                )}
              </>
            ) : (
              <div className="text-xs text-[#6B6B7B] flex items-center gap-2">
                <Loader2 className="w-3 h-3 animate-spin" /> 加载积木清单...
              </div>
            )}
          </div>

          {/* 规则列表 */}
          <div className="mt-3 space-y-2">
            <div className="text-[10px] text-[#00D4AA] uppercase tracking-wide flex items-center gap-1">
              <Zap className="w-3 h-3" /> 规则列表 ({dslConfig.rules.length})
            </div>
            {catalog ? (
              <div className="space-y-2">
                {dslConfig.rules.length === 0 && (
                  <div className="text-xs text-[#6B6B7B] italic text-center py-2">暂无规则，点击下方按钮添加</div>
                )}
                {dslConfig.rules.map((rule, idx) => (
                  <RuleCard
                    key={idx}
                    rule={rule}
                    onChange={(newRule) => {
                      const newRules = [...dslConfig.rules]
                      newRules[idx] = newRule
                      setDslConfig({ ...dslConfig, rules: newRules })
                    }}
                    onDelete={() => {
                      setDslConfig({ ...dslConfig, rules: dslConfig.rules.filter((_, i) => i !== idx) })
                    }}
                    catalog={catalog}
                    baseSymbol={baseSymbol}
                  />
                ))}
                <button
                  type="button"
                  onClick={addRule}
                  className="w-full flex items-center justify-center gap-1 text-xs text-[#00D4AA] border border-dashed border-[#1E1E28] rounded-md py-2 hover:border-[#00D4AA]/30 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> 添加规则
                </button>
              </div>
            ) : (
              <div className="text-xs text-[#6B6B7B] flex items-center gap-2">
                <Loader2 className="w-3 h-3 animate-spin" /> 加载积木清单...
              </div>
            )}
          </div>
        </div>

        {/* ============ RISK_FILTER 区（可折叠） ============ */}
        <CollapsibleSection title="RISK_FILTER 风控过滤" icon={<Shield className="w-3 h-3" />} defaultCollapsed accent="#F0A500">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div>
              <label className="text-[10px] text-[#6B6B7B]">最大持仓比例</label>
              <input
                type="number"
                step="0.01"
                min={0}
                max={1}
                value={String(riskFilter.max_position_ratio ?? 0)}
                onChange={(e) => setRiskFilter({ ...riskFilter, max_position_ratio: Number(e.target.value) })}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#6B6B7B]">日内最大亏损</label>
              <input
                type="number"
                step="0.01"
                value={String(riskFilter.daily_max_loss ?? 0)}
                onChange={(e) => setRiskFilter({ ...riskFilter, daily_max_loss: Number(e.target.value) })}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#6B6B7B]">最小交易量</label>
              <input
                type="number"
                step="any"
                value={String(riskFilter.min_trade_size ?? 0)}
                onChange={(e) => setRiskFilter({ ...riskFilter, min_trade_size: Number(e.target.value) })}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
              />
            </div>
          </div>
        </CollapsibleSection>

        {/* 操作按钮区 */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handleValidate}
            disabled={validating || !catalog}
            className="flex items-center gap-1.5 border border-[#1E1E28] text-[#E8E8ED] rounded-md px-3 py-2 text-xs font-medium hover:bg-[#1A1A24] disabled:opacity-50 transition-colors"
          >
            {validating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
            校验配置
          </button>
          <button
            onClick={handleDryRun}
            disabled={dryRunning || !catalog}
            className="flex items-center gap-1.5 border border-[#1E1E28] text-[#E8E8ED] rounded-md px-3 py-2 text-xs font-medium hover:bg-[#1A1A24] disabled:opacity-50 transition-colors"
          >
            {dryRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            Dry-Run 预览
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !meta.name.trim()}
            className="flex items-center gap-1.5 bg-[#00D4AA] text-[#0A0A0F] rounded-md px-3 py-2 text-xs font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors ml-auto"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            保存模板
          </button>
        </div>

        {/* 校验结果 */}
        {validation && (
          <div className={`border rounded-md p-3 ${
            validation.valid
              ? 'bg-[#00D4AA]/5 border-[#00D4AA]/20'
              : 'bg-[#FF4757]/5 border-[#FF4757]/20'
          }`}>
            {validation.valid ? (
              <div className="flex items-center gap-2 text-sm text-[#00D4AA]">
                <CheckCircle className="w-4 h-4" /> 校验通过，可以保存模板
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-sm text-[#FF4757]">
                  <XCircle className="w-4 h-4" /> 校验失败（{validation.errors.length} 个错误）
                </div>
                <div className="space-y-1 mt-2">
                  {validation.errors.map((err, i) => (
                    <div key={i} className="text-xs text-[#FF4757]/80 flex items-start gap-2">
                      <span className="text-[#FF4757] font-mono shrink-0">[{err.layer}]</span>
                      <span className="flex-1">{err.message}</span>
                      {err.path && <span className="text-[#6B6B7B] font-mono shrink-0">{err.path}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Dry-Run 结果 */}
        {dryRunResult && (
          <div className="border border-[#1E1E28] rounded-md p-3 bg-[#14141A]/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-[#00D4AA] uppercase tracking-wide">Dry-Run 结果</span>
              <button
                onClick={() => setShowDryRunDetail(!showDryRunDetail)}
                className="text-xs text-[#6B6B7B] hover:text-[#E8E8ED]"
              >
                {showDryRunDetail ? '收起' : '展开'}
              </button>
            </div>
            <div className="grid grid-cols-4 gap-2 mb-2">
              <div className="bg-[#0C0C14] rounded p-2 text-center">
                <div className="text-lg text-[#E8E8ED] font-mono">{dryRunResult.total_ticks}</div>
                <div className="text-[10px] text-[#6B6B7B]">总步数</div>
              </div>
              <div className="bg-[#0C0C14] rounded p-2 text-center">
                <div className="text-lg text-[#00D4AA] font-mono">{dryRunResult.triggered_count}</div>
                <div className="text-[10px] text-[#6B6B7B]">触发次数</div>
              </div>
              <div className="bg-[#0C0C14] rounded p-2 text-center">
                <div className="text-lg text-[#F0A500] font-mono">{dryRunResult.state_changes}</div>
                <div className="text-[10px] text-[#6B6B7B]">状态转换</div>
              </div>
              <div className="bg-[#0C0C14] rounded p-2 text-center">
                <div className="text-sm text-[#E8E8ED] font-mono truncate">{dryRunResult.final_state}</div>
                <div className="text-[10px] text-[#6B6B7B]">最终状态</div>
              </div>
            </div>
            <AnimatePresence>
              {showDryRunDetail && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className="max-h-60 overflow-y-auto border-t border-[#1E1E28] pt-2">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-[#6B6B7B] text-left">
                          <th className="py-1 pr-2">时间</th>
                          <th className="py-1 pr-2">价格</th>
                          <th className="py-1 pr-2">状态</th>
                          <th className="py-1 pr-2">触发</th>
                          <th className="py-1">动作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dryRunResult.steps.map((step, i) => (
                          <tr key={i} className="text-[#E8E8ED]/80 border-t border-[#1E1E28]/50">
                            <td className="py-1 pr-2 font-mono text-[10px]">{step.timestamp}</td>
                            <td className="py-1 pr-2 font-mono">{step.price.toFixed(2)}</td>
                            <td className="py-1 pr-2 font-mono">{step.state}</td>
                            <td className="py-1 pr-2">
                              {step.triggered
                                ? <span className="text-[#00D4AA]">●</span>
                                : <span className="text-[#6B6B7B]">○</span>}
                              {step.rule_name && (
                                <span className="ml-1 text-[10px] text-[#6B6B7B]">{step.rule_name}</span>
                              )}
                            </td>
                            <td className="py-1 text-[10px] text-[#6B6B7B]">{step.actions.join(', ')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* 哈希去重确认弹窗 */}
      <AnimatePresence>
        {dupConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] grid place-items-center p-4"
          >
            <div className="absolute inset-0 bg-[#050711]/80 backdrop-blur-sm" onClick={() => setDupConfirm(null)} />
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative z-10 w-full max-w-md rounded-2xl border border-[rgba(240,165,0,0.2)] bg-[#14141A] p-5 shadow-[0_0_60px_rgba(240,165,0,0.1)]"
            >
              <div className="flex items-start gap-3">
                <div className="shrink-0 w-10 h-10 rounded-full bg-[#F0A500]/10 grid place-items-center">
                  <AlertTriangle className="w-5 h-5 text-[#F0A500]" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-[#E8E8ED]">检测到重复逻辑</h3>
                  <p className="mt-1 text-xs text-[#6B6B7B] leading-relaxed">{dupConfirm}</p>
                  <p className="mt-2 text-xs text-[#F0A500]/80">是否仍要创建该模板？</p>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => setDupConfirm(null)}
                  className="px-3 py-1.5 text-xs text-[#6B6B7B] hover:text-[#E8E8ED] border border-[#1E1E28] rounded-md transition-colors"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleForceCreate}
                  className="px-3 py-1.5 text-xs font-semibold text-[#0A0A0F] bg-[#F0A500] hover:bg-[#F0A500]/90 rounded-md transition-colors"
                >
                  仍然创建
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Modal>
  )
}
