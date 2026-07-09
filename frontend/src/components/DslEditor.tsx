import { useEffect, useState, useMemo, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus, Trash2, ChevronDown, CheckCircle, XCircle, Play, Loader2,
  AlertTriangle, X, Settings, Zap, Save,
} from 'lucide-react'
import Modal from './Modal'
import { getBlocks, validateDsl, dryRunDsl } from '../api/dsl'
import { createTemplate } from '../api/strategies'
import type {
  BlockCatalog, BlockMeta, BlockRef, Trigger, Rule, DslConfig,
  ValidationResult, DryRunResult,
} from '../types/dsl'

// ============================================================
// param_schema 格式归一化
// ============================================================

interface NormalizedParam {
  type: 'string' | 'number' | 'bool' | 'select' | 'object' | 'array'
  required: boolean
  default?: unknown
  min?: number
  max?: number
  description?: string
  options?: string[]
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
    description: typeof def.description === 'string' ? def.description : undefined,
    options: Array.isArray(def.options) ? (def.options as string[]) : undefined,
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

/** 逻辑组合条件 kind 集合（含嵌套 conditions）。 */
const LOGIC_CONDITIONS = new Set(['and', 'or', 'not'])

// ============================================================
// BlockPicker — 积木选择下拉（按 category 分组）
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
        <span className={selected ? 'text-[#E8E8ED] font-mono' : 'text-[#6B6B7B]'}>
          {selected ? selected.kind : placeholder}
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
                  <span className="font-mono">{b.kind}</span>
                  {b.description && <span className="ml-2 text-xs text-[#6B6B7B]">{b.description}</span>}
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
// BlockArgsForm — 积木参数动态表单
// ============================================================

interface BlockArgsFormProps {
  block: BlockMeta | null
  args: Record<string, unknown>
  onChange: (args: Record<string, unknown>) => void
}

function BlockArgsForm({ block, args, onChange }: BlockArgsFormProps) {
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
              参数「{name}」为复杂类型（{param.type}），暂不支持可视化编辑
            </div>
          )
        }
        const val = args[name]
        const label = param.description || name
        return (
          <div key={name}>
            <label className="text-[10px] text-[#6B6B7B]">
              {label}
              {param.required && <span className="text-[#FF4757] ml-0.5">*</span>}
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
                {val ? 'true' : 'false'}
              </button>
            ) : param.type === 'select' && param.options ? (
              <select
                value={String(val ?? '')}
                onChange={(e) => onChange({ ...args, [name]: e.target.value })}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
              >
                <option value="">请选择</option>
                {param.options.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <input
                type={param.type === 'number' ? 'number' : 'text'}
                step={param.type === 'number' ? 'any' : undefined}
                min={param.min}
                max={param.max}
                value={val !== undefined && val !== null ? String(val) : ''}
                onChange={(e) => {
                  const raw = e.target.value
                  const newVal = param.type === 'number' ? (raw === '' ? '' : Number(raw)) : raw
                  onChange({ ...args, [name]: newVal })
                }}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
              />
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
}

function IndicatorRefEditor({ indicatorRef, onChange, catalog }: IndicatorRefEditorProps) {
  const selectedIndicator = catalog.indicators.find((b) => b.kind === indicatorRef?.kind) ?? null

  return (
    <div className="border border-[#1E1E28] rounded-md p-2 bg-[#0C0C14]/50">
      <div className="text-[10px] text-[#00D4AA] mb-1.5 uppercase tracking-wide">指标引用 (indicator)</div>
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
          />
        )}
      </div>
    </div>
  )
}

// ============================================================
// ConditionEditor — 单个条件编辑（含 indicator 嵌套、逻辑组合提示）
// ============================================================

interface ConditionEditorProps {
  condition: BlockRef
  onChange: (condition: BlockRef) => void
  catalog: BlockCatalog
}

function ConditionEditor({ condition, onChange, catalog }: ConditionEditorProps) {
  const selectedBlock = catalog.conditions.find((b) => b.kind === condition.kind) ?? null
  const schema = selectedBlock ? normalizeParamSchema(selectedBlock.param_schema) : {}
  const hasIndicatorParam = 'indicator' in schema && schema.indicator?.type === 'object'
  const isLogicCondition = selectedBlock ? LOGIC_CONDITIONS.has(selectedBlock.kind) : false

  return (
    <div className="space-y-2">
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
          onChange({ kind, args: defaultArgs })
        }}
        placeholder="选择条件"
      />

      {selectedBlock && (
        isLogicCondition ? (
          <div className="text-xs text-[#6B6B7B] italic p-2 bg-[#0C0C14]/50 rounded border border-[#1E1E28]">
            <AlertTriangle className="w-3 h-3 inline mr-1 text-[#F0A500]" />
            嵌套条件编辑（{selectedBlock.kind}）暂不支持可视化编辑
          </div>
        ) : hasIndicatorParam ? (
          <div className="space-y-2">
            <BlockArgsForm
              block={selectedBlock}
              args={condition.args}
              onChange={(newArgs) => onChange({ ...condition, args: newArgs })}
            />
            <IndicatorRefEditor
              indicatorRef={(condition.args.indicator as BlockRef) ?? null}
              onChange={(ref) => onChange({ ...condition, args: { ...condition.args, indicator: ref } })}
              catalog={catalog}
            />
          </div>
        ) : (
          <BlockArgsForm
            block={selectedBlock}
            args={condition.args}
            onChange={(newArgs) => onChange({ ...condition, args: newArgs })}
          />
        )
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
}

function TriggerEditor({ trigger, onChange, catalog, label }: TriggerEditorProps) {
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
            Condition
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
            Event
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
// ActionListEditor — 动作列表编辑
// ============================================================

interface ActionListEditorProps {
  actions: BlockRef[]
  onChange: (actions: BlockRef[]) => void
  catalog: BlockCatalog
  label: string
}

function ActionListEditor({ actions, onChange, catalog, label }: ActionListEditorProps) {
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
// RuleCard — 规则卡片（可折叠）
// ============================================================

interface RuleCardProps {
  rule: Rule
  onChange: (rule: Rule) => void
  onDelete: () => void
  catalog: BlockCatalog
}

function RuleCard({ rule, onChange, onDelete, catalog }: RuleCardProps) {
  const [expanded, setExpanded] = useState(true)
  const [showRecover, setShowRecover] = useState(
    Boolean(rule.recover_when || (rule.recover_then && rule.recover_then.length > 0)),
  )

  const whenSummary = rule.when.mode === 'condition'
    ? rule.when.condition?.kind || '未设置'
    : rule.when.event?.kind || '未设置'
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
          <span className="ml-2 text-xs text-[#6B6B7B]">
            WHEN <span className="font-mono text-[#00D4AA]/70">{whenSummary}</span> THEN {thenCount} action{thenCount !== 1 ? 's' : ''}
          </span>
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
              />

              {/* THEN */}
              <ActionListEditor
                actions={rule.then}
                onChange={(then) => onChange({ ...rule, then })}
                catalog={catalog}
                label="THEN"
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
                  />
                  <ActionListEditor
                    actions={rule.recover_then ?? []}
                    onChange={(recover_then) => onChange({ ...rule, recover_then })}
                    catalog={catalog}
                    label="RECOVER_THEN"
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
// DslEditor — 主组件
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

export default function DslEditor({ open, onClose, onSaved }: DslEditorProps) {
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null)
  const [dslConfig, setDslConfig] = useState<DslConfig>(initialConfig)
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [dryRunning, setDryRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [showDryRunDetail, setShowDryRunDetail] = useState(false)

  useEffect(() => {
    if (open && !catalog) {
      getBlocks().then((res) => setCatalog(res.data)).catch(() => {})
    }
  }, [open, catalog])

  const baseStrategyBlock = catalog?.base_strategies.find((b) => b.kind === dslConfig.base_strategy.kind) ?? null

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
      const symbol = (dslConfig.base_strategy.params.symbol as string) || 'BTC-USDT'
      const res = await dryRunDsl({ config: dslConfig, symbol, bar: '1H', limit: 50 })
      setDryRunResult(res.data)
    } catch {
      setDryRunResult(null)
    }
    setDryRunning(false)
  }

  async function handleSave() {
    if (!templateName.trim()) return
    if (!validation?.valid) {
      await handleValidate()
      return
    }
    setSaving(true)
    try {
      await createTemplate({
        name: templateName.trim(),
        strategy_type: 'composable',
        default_params: { symbol: dslConfig.base_strategy.params.symbol },
        param_schema: null,
        dsl_config: dslConfig as unknown as Record<string, unknown>,
      })
      onSaved()
      onClose()
      setDslConfig(initialConfig())
      setTemplateName('')
      setValidation(null)
      setDryRunResult(null)
    } catch {
      /* ignore */
    }
    setSaving(false)
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
    <Modal open={open} onClose={onClose} title="DSL 拼接策略模板" wide scrollable={false}>
      <div className="space-y-4 max-h-[calc(100vh-12rem)] overflow-y-auto pr-1">
        {/* 模板名称 */}
        <div>
          <label className="text-xs text-[#6B6B7B]">模板名称</label>
          <input
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            placeholder="如：网格-单边暂停策略"
            className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
          />
        </div>

        {/* 基础策略区 */}
        <div className="border border-[#1E1E28] rounded-lg p-3 bg-[#14141A]/50">
          <div className="text-xs text-[#00D4AA] mb-2 uppercase tracking-wide flex items-center gap-1">
            <Settings className="w-3 h-3" /> 基础策略
          </div>
          {catalog ? (
            <div className="space-y-2">
              <BlockPicker
                blocks={catalog.base_strategies}
                value={dslConfig.base_strategy.kind || null}
                onChange={(kind) => {
                  if (!kind) return
                  const block = catalog.base_strategies.find((b) => b.kind === kind)
                  const defaultArgs = block ? getDefaultArgs(normalizeParamSchema(block.param_schema)) : {}
                  setDslConfig({ ...dslConfig, base_strategy: { kind, params: defaultArgs } })
                }}
                placeholder="选择基础策略"
              />
              {baseStrategyBlock && (
                <BlockArgsForm
                  block={baseStrategyBlock}
                  args={dslConfig.base_strategy.params}
                  onChange={(params) => setDslConfig({
                    ...dslConfig,
                    base_strategy: { ...dslConfig.base_strategy, params },
                  })}
                />
              )}
            </div>
          ) : (
            <div className="text-xs text-[#6B6B7B] flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> 加载积木清单...
            </div>
          )}
        </div>

        {/* 规则列表区 */}
        <div className="border border-[#1E1E28] rounded-lg p-3 bg-[#14141A]/50">
          <div className="text-xs text-[#00D4AA] mb-2 uppercase tracking-wide flex items-center gap-1">
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
            disabled={saving || !templateName.trim()}
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
    </Modal>
  )
}
