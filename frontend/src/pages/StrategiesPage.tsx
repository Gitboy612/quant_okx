import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus, Play, Pause, Square, ChevronDown, Trash2, RefreshCw, FileText, X, CheckCircle, XCircle, Loader2, AlertTriangle, Search, Blocks, Lock, Edit2, Settings } from 'lucide-react'
import Dropdown from '../components/Dropdown'
import {
  listInstances,
  listTemplates,
  createInstance,
  createTemplate,
  deleteTemplate,
  startInstance,
  pauseInstance,
  resumeInstance,
  stopInstance,
  deleteInstance,
  updateInstance,
  checkFeasibility,
} from '../api/strategies'
import { listAccounts } from '../api/accounts'
import { getStrategyEvents } from '../api/monitoring'
import { formatInstId, isContractPair, INST_ID_LABEL } from '../utils/instId'
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'
import DslEditor from '../components/DslEditor'
import OrderQtyInput, { type SzFields } from '../components/OrderQtyInput'
import type { StrategyInstance, StrategyTemplate, Account, ParamSchemaField, StrategyEvent } from '../types'

// 参数字段（兼容 ParamSchemaField 与 QS-Model ParamDefinition）
type RenderParamField = {
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

// NumberInput — 草稿字符串数字输入（保留输入中间态，如 "0." 不被吞）
function NumberInput({ value, onChange, step, min, max, placeholder, className }: {
  value: number | undefined | null
  onChange: (val: number | undefined) => void
  step?: string | number
  min?: number
  max?: number
  placeholder?: string
  className?: string
}) {
  const [draft, setDraft] = useState<string>(value != null ? String(value) : '')
  const lastValid = useRef<number | undefined>(value ?? undefined)

  // Sync external value changes (e.g., when loading a template)
  useEffect(() => {
    if (value != null && String(value) !== draft) {
      setDraft(String(value))
      lastValid.current = value
    }
  }, [value])

  const handleBlur = () => {
    const num = Number(draft)
    if (draft === '' || isNaN(num)) {
      // Revert to last valid value
      setDraft(lastValid.current != null ? String(lastValid.current) : '')
      onChange(lastValid.current)
    } else {
      let clamped = num
      if (min != null) clamped = Math.max(min, clamped)
      if (max != null) clamped = Math.min(max, clamped)
      setDraft(String(clamped))
      lastValid.current = clamped
      onChange(clamped)
    }
  }

  return (
    <input
      type="number"
      value={draft}
      step={step}
      min={min}
      max={max}
      placeholder={placeholder}
      className={className}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={handleBlur}
    />
  )
}

export default function StrategiesPage() {
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [templates, setTemplates] = useState<StrategyTemplate[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showNewTemplate, setShowNewTemplate] = useState(false)
  const [showDslEditor, setShowDslEditor] = useState(false)
  const [showTemplateMgmt, setShowTemplateMgmt] = useState(false)
  const [editingTemplateId, setEditingTemplateId] = useState<number | null>(null)
  const [deletingTemplateId, setDeletingTemplateId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null)
  const [customParams, setCustomParams] = useState<Record<string, unknown>>({})
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [savingParams, setSavingParams] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  // symbol dropdown in create modal
  const [symbolSearch, setSymbolSearch] = useState('')
  const [showSymbolDropdown, setShowSymbolDropdown] = useState(false)
  const symbolDropdownRef = useRef<HTMLDivElement>(null)

  // order failure alerts
  const [instanceEvents, setInstanceEvents] = useState<Record<number, StrategyEvent[]>>({})
  const eventPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const presetSymbols = Object.keys(INST_ID_LABEL)

  const filteredSymbols = symbolSearch
    ? presetSymbols.filter((s) =>
        s.toLowerCase().includes(symbolSearch.toLowerCase()) ||
        (INST_ID_LABEL[s] && INST_ID_LABEL[s].toLowerCase().includes(symbolSearch.toLowerCase()))
      )
    : presetSymbols

  const contractSymbols = filteredSymbols.filter((s) => isContractPair(s))
  const spotSymbols = filteredSymbols.filter((s) => !isContractPair(s))

  const loadData = () => {
    setLoading(true)
    Promise.all([
      listInstances().then((res) => setInstances(res.data)).catch(() => {}),
      listTemplates().then((res) => setTemplates(res.data)).catch(() => {}),
      listAccounts().then((res) => setAccounts(res.data)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }

  useEffect(() => { loadData() }, [])

  // poll events for expanded strategy
  useEffect(() => {
    if (eventPollRef.current) {
      clearInterval(eventPollRef.current)
      eventPollRef.current = null
    }
    if (expandedId !== null) {
      const pollEvents = () => {
        getStrategyEvents(expandedId, 5).then((res) => {
          setInstanceEvents((prev) => ({ ...prev, [expandedId]: res.data.items || [] }))
        }).catch(() => {})
      }
      pollEvents()
      eventPollRef.current = setInterval(pollEvents, 15000)
    }
    return () => {
      if (eventPollRef.current) clearInterval(eventPollRef.current)
    }
  }, [expandedId])

  // close symbol dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (symbolDropdownRef.current && !symbolDropdownRef.current.contains(e.target as Node)) {
        setShowSymbolDropdown(false)
      }
    }
    if (showSymbolDropdown) {
      document.addEventListener('mousedown', handler)
    }
    return () => document.removeEventListener('mousedown', handler)
  }, [showSymbolDropdown])

  const activeAccounts = accounts.filter((a) => a.is_active)

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId)
  // QS-Model 币对锁定：模板 meta.base_symbol 非空时，新建实例 symbol 锁定为该值
  const lockedBaseSymbol = selectedTemplate?.qs_model_config?.meta?.base_symbol?.trim() || ''
  // 参数 schema 取值：优先 param_schema；为空（null/undefined/{}）时从 qs_model_config.params 构建
  const paramSchema: Record<string, RenderParamField> = (() => {
    const ps = selectedTemplate?.param_schema
    if (ps && Object.keys(ps).length > 0) {
      return ps as Record<string, RenderParamField>
    }
    const qsParams = selectedTemplate?.qs_model_config?.params
    const built: Record<string, RenderParamField> = {}
    if (qsParams) {
      for (const [key, def] of Object.entries(qsParams)) {
        built[key] = {
          label: def.label,
          type: def.type,
          default: def.value,
          min: def.range?.[0],
          max: def.range?.[1],
          hint: def.description,
          options: def.options as string[] | undefined,
          option_labels: def.option_labels,
          unit: def.unit,
        }
      }
    }
    return built
  })()

  useEffect(() => {
    if (selectedTemplate) {
      const defaults: Record<string, unknown> = {}
      for (const [key, field] of Object.entries(paramSchema)) {
        defaults[key] = field.default
      }
      setCustomParams(defaults)
    }
  }, [selectedTemplateId])

  // 模板币对锁定：selectedTemplate 含非空 meta.base_symbol 时，强制 symbol 输入为该值
  useEffect(() => {
    if (lockedBaseSymbol) {
      setSymbolSearch(lockedBaseSymbol)
      setCustomParams((prev) => ({ ...prev, symbol: lockedBaseSymbol }))
      setShowSymbolDropdown(false)
    }
  }, [lockedBaseSymbol])

  const [feasibilityMsg, setFeasibilityMsg] = useState<string | null>(null)
  const [startingId, setStartingId] = useState<number | null>(null)

  const showToast = (type: 'success' | 'error', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const handleStart = async (id: number) => {
    setActionLoading(id)
    setFeasibilityMsg(null)
    try {
      const feas = await checkFeasibility(id)
      if (!feas.data.ok) {
        setFeasibilityMsg(feas.data.reason)
        setActionLoading(null)
        return
      }
      setFeasibilityMsg(feas.data.reason)
      await startInstance(id)
      showToast('success', '策略已启动')
      setFeasibilityMsg(null)
      loadData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '启动失败')
      setFeasibilityMsg(detail || '启动失败')
    }
    setActionLoading(null)
  }
  const handlePause = async (id: number) => {
    setActionLoading(id)
    try { await pauseInstance(id); showToast('success', '策略已暂停'); loadData() }
    catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '暂停失败')
    }
    setActionLoading(null)
  }
  const handleResume = async (id: number) => {
    setActionLoading(id)
    try { await resumeInstance(id); showToast('success', '策略已恢复'); loadData() }
    catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '恢复失败')
    }
    setActionLoading(null)
  }
  const handleStop = async (id: number) => {
    setActionLoading(id)
    try { await stopInstance(id); showToast('success', '策略已停止'); loadData() }
    catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '停止失败')
    }
    setActionLoading(null)
  }
  const handleDelete = async (id: number) => {
    setActionLoading(id)
    try { await deleteInstance(id); showToast('success', '策略已删除'); loadData() }
    catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '删除失败')
    }
    setActionLoading(null)
  }

  const handleDeleteTemplate = async (id: number) => {
    if (!window.confirm('确定删除该模板？此操作不可撤销。')) return
    setDeletingTemplateId(id)
    try {
      await deleteTemplate(id)
      showToast('success', '模板已删除')
      loadData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '删除模板失败')
    }
    setDeletingTemplateId(null)
  }

  const handleEditTemplate = (id: number) => {
    setEditingTemplateId(id)
    setShowTemplateMgmt(false)
    setShowDslEditor(true)
  }

  const handleOpenNewDslEditor = () => {
    setEditingTemplateId(null)
    setShowDslEditor(true)
  }

  const handleCloseDslEditor = () => {
    setShowDslEditor(false)
    setEditingTemplateId(null)
  }

  const handleCreate = async () => {
    if (!selectedTemplateId || !selectedAccountForCreate) return
    setCreating(true)
    try {
      await createInstance({
        template_id: selectedTemplateId,
        account_id: selectedAccountForCreate,
        name: instanceName || selectedTemplate?.name || '',
        symbol: (customParams.symbol as string) || '',
        market_type: selectedMarketType,
        params: customParams,
      })
      setShowCreate(false)
      resetCreateForm()
      loadData()
    } catch { /* ignore */ }
    finally { setCreating(false) }
  }

  const [instanceName, setInstanceName] = useState('')
  const [selectedAccountForCreate, setSelectedAccountForCreate] = useState<number | null>(null)
  const [selectedMarketType, setSelectedMarketType] = useState('swap')

  const openCreateModal = () => {
    setShowCreate(true)
    if (templates.length > 0) {
      setSelectedTemplateId(templates[0].id)
    }
    setSelectedAccountForCreate(activeAccounts.length > 0 ? activeAccounts[0].id : null)
    setInstanceName('')
    setSelectedMarketType('swap')
  }

  const resetCreateForm = () => {
    setSelectedTemplateId(null)
    setCustomParams({})
    setInstanceName('')
    setSelectedAccountForCreate(null)
    setSelectedMarketType('swap')
  }

  const handleParamSave = async (id: number) => {
    const inst = instances.find((i) => i.id === id)
    if (!inst) return
    setSavingParams(id)
    try {
      await updateInstance(id, { params: inst.params })
      showToast('success', '参数已保存')
      loadData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast('error', detail || '保存失败')
    }
    setSavingParams(null)
  }

  const getInstanceSchema = (inst: StrategyInstance) => {
    const tpl = templates.find((t) => t.id === inst.template_id)
    const ps = tpl?.param_schema
    if (ps && Object.keys(ps).length > 0) {
      return ps as Record<string, ParamSchemaField>
    }
    // QS-Model 模板：从 qs_model_config.params 动态构建 schema
    const qsParams = tpl?.qs_model_config?.params
    const built: Record<string, RenderParamField> = {}
    if (qsParams) {
      for (const [key, def] of Object.entries(qsParams)) {
        built[key] = {
          label: def.label,
          type: def.type,
          default: def.value,
          min: def.range?.[0],
          max: def.range?.[1],
          step: def.type === 'int' ? 1 : undefined,
          hint: def.description,
          options: def.options as string[] | undefined,
          option_labels: def.option_labels,
          unit: def.unit,
        }
      }
    }
    return built
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">策略列表</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowNewTemplate(true)}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <FileText className="w-4 h-4" /> 自定义模板
          </button>
          <button
            onClick={() => setShowTemplateMgmt(true)}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <Settings className="w-4 h-4" /> 模板管理
          </button>
          <button
            onClick={handleOpenNewDslEditor}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <Blocks className="w-4 h-4" /> QS-Model 策略构建
          </button>
          <button
            onClick={openCreateModal}
            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-4 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors"
          >
            <Plus className="w-4 h-4" /> 新建策略
          </button>
        </div>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className={`flex items-center gap-2 text-sm p-3 rounded-md border ${
              toast.type === 'success'
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
            }`}
          >
            {toast.type === 'success' ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
        {feasibilityMsg && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`text-xs p-3 rounded-md border ${
              feasibilityMsg.startsWith('当前价') || feasibilityMsg.startsWith('约需')
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
            }`}
          >
            {feasibilityMsg}
            <button onClick={() => setFeasibilityMsg(null)} className="ml-3 underline">关闭</button>
          </motion.div>
        )}
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-6 animate-pulse">
                <div className="h-4 bg-[#1E1E28] rounded w-1/3 mb-3" />
                <div className="h-3 bg-[#1E1E28] rounded w-1/4 mb-2" />
                <div className="h-3 bg-[#1E1E28] rounded w-2/3" />
              </div>
            ))}
          </div>
        ) : instances.length === 0 ? (
          <div className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-12 text-center text-[#6B6B7B] text-sm">
            暂无策略实例，点击上方按钮创建
          </div>
        ) : (
          instances.map((inst, i) => {
            const schema = getInstanceSchema(inst)
            return (
              <motion.div
                key={inst.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="bg-[#14141A] rounded-lg border border-[#1E1E28] overflow-hidden"
              >
                <div
                  onClick={() => setExpandedId(expandedId === inst.id ? null : inst.id)}
                  className="flex items-center gap-4 p-4 cursor-pointer hover:bg-[#1A1A24]/50 transition-colors"
                >
                  <ChevronDown
                    className={`w-4 h-4 text-[#6B6B7B] transition-transform ${expandedId === inst.id ? 'rotate-180' : ''}`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium">{inst.name}</span>
                      <StatusBadge status={inst.status} />
                    </div>
                    <div className="text-xs text-[#6B6B7B] mt-0.5">
                      {inst.template_name} · {formatInstId(inst.symbol)} · {inst.market_type === 'swap' ? '永续合约' : inst.market_type === 'spot' ? '现货' : inst.market_type}
                    </div>
                  </div>
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    {actionLoading === inst.id ? (
                      <span className="p-1.5"><Loader2 className="w-4 h-4 animate-spin text-[#6B6B7B]" /></span>
                    ) : (
                      <>
                        {inst.status === 'stopped' || inst.status === 'paused' ? (
                          <button onClick={() => inst.status === 'paused' ? handleResume(inst.id) : handleStart(inst.id)} className="p-1.5 rounded-md hover:bg-[#00D4AA]/10 text-[#00D4AA] transition-colors" title="启动">
                            <Play className="w-4 h-4" />
                          </button>
                        ) : null}
                        {inst.status === 'running' && (
                          <button onClick={() => handlePause(inst.id)} className="p-1.5 rounded-md hover:bg-[#F0A500]/10 text-[#F0A500] transition-colors" title="暂停">
                            <Pause className="w-4 h-4" />
                          </button>
                        )}
                        {(inst.status === 'running' || inst.status === 'paused') && (
                          <button onClick={() => handleStop(inst.id)} className="p-1.5 rounded-md hover:bg-[#FF4757]/10 text-[#FF4757] transition-colors" title="停止">
                            <Square className="w-4 h-4" />
                          </button>
                        )}
                        <button onClick={() => handleDelete(inst.id)} className="p-1.5 rounded-md hover:bg-[#FF4757]/10 text-[#6B6B7B] hover:text-[#FF4757] transition-colors" title="删除">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <AnimatePresence>
                  {expandedId === inst.id && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-4 border-t border-[#1E1E28] pt-4">
                        {/* order failure alert */}
                        {(() => {
                          const events = instanceEvents[inst.id]
                          const failedEvents = events?.filter((e) => e.event_type === 'order_failed')
                          if (failedEvents && failedEvents.length > 0) {
                            return (
                              <motion.div
                                initial={{ opacity: 0, y: -5 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="mb-3 flex items-center gap-2 bg-[#FF4757]/10 border border-[#FF4757]/20 rounded-md px-3 py-2 text-xs text-[#FF4757]"
                              >
                                <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                                <div className="flex-1 min-w-0">
                                  <span className="font-medium">策略下单失败</span>
                                  <span className="ml-2 text-[#FF4757]/70">{failedEvents[0].message}</span>
                                  {failedEvents.length > 1 && (
                                    <span className="ml-1 text-[#FF4757]/50">等 {failedEvents.length} 条</span>
                                  )}
                                </div>
                              </motion.div>
                            )
                          }
                          return null
                        })()}
                        <div className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">策略参数</div>
                        <div className="grid grid-cols-2 gap-3">
                          {Object.entries(inst.params).filter(([key]) => key !== 'sz_fields').map(([key, value]) => {
                            const field = schema[key]
                            const label = field?.label ?? key
                            const hint = field?.hint ?? ''
                            const isOrderQtyField = key === 'order_qty' || key === 'sz'
                            const useOrderQty = isOrderQtyField && isContractPair(inst.symbol)
                            return (
                              <div key={key} className={useOrderQty ? 'col-span-2' : ''}>
                                <label className="text-xs text-[#6B6B7B]" title={hint}>
                                  {label}
                                  {hint ? <span className="ml-1 opacity-50">({hint})</span> : null}
                                </label>
                                {field?.type === 'select' && field.options ? (
                                  <Dropdown
                                    options={field.options.map((opt: string) => ({ value: opt, label: opt }))}
                                    value={String(value)}
                                    onChange={(v) => {
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: isNaN(Number(v)) ? v : Number(v) } }
                                            : pi,
                                        ),
                                      )
                                    }}
                                    className="mt-1 w-full"
                                  />
                                ) : useOrderQty && (field?.type === 'number' || field?.type === 'int' || field?.type === 'float') ? (
                                  <OrderQtyInput
                                    symbol={inst.symbol}
                                    value={typeof value === 'number' ? value : undefined}
                                    szFields={(inst.params.sz_fields as SzFields) ?? null}
                                    onChange={(sz, fields) => {
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: sz ?? 0, sz_fields: fields } }
                                            : pi,
                                        ),
                                      )
                                    }}
                                    step={field?.step ?? (field?.type === 'int' || field?.type === 'integer' ? 1 : 'any')}
                                    min={field?.min}
                                    max={field?.max}
                                    className="mt-1"
                                  />
                                ) : field?.type === 'number' ? (
                                  <NumberInput
                                    value={typeof value === 'number' ? value : undefined}
                                    onChange={(v) => {
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: v } }
                                            : pi,
                                        ),
                                      )
                                    }}
                                    step={field?.step ?? (field?.type === 'int' || field?.type === 'integer' ? 1 : 'any')}
                                    min={field?.min}
                                    max={field?.max}
                                    className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] mt-1 font-mono"
                                  />
                                ) : (
                                  <input
                                    type="text"
                                    value={String(value)}
                                    onChange={(e) => {
                                      const raw = e.target.value
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: raw } }
                                            : pi,
                                        ),
                                      )
                                    }}
                                    className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] mt-1 font-mono"
                                  />
                                )}
                              </div>
                            )
                          })}
                        </div>
                        <div className="mt-4 flex gap-2">
                          <button
                            onClick={() => handleParamSave(inst.id)}
                            disabled={savingParams === inst.id}
                            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-md px-4 py-1.5 text-xs font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
                          >
                            {savingParams === inst.id ? (
                              <><Loader2 className="w-3 h-3 animate-spin" /> 保存中...</>
                            ) : (
                              <><RefreshCw className="w-3 h-3" /> 保存参数</>
                            )}
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )
          })
        )}
      </motion.div>

      <Modal open={showCreate} onClose={() => { setShowCreate(false); resetCreateForm() }} title="新建策略" wide>
        {activeAccounts.length === 0 ? (
          <div className="text-sm text-[#6B6B7B] text-center py-4">请先在「账户管理」中添加 OKX 账户</div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[#6B6B7B]">策略模板</label>
                <Dropdown
                  options={templates.map((t) => ({ value: t.id, label: `${t.name} ${t.is_custom ? '(自定义)' : ''}` }))}
                  value={selectedTemplateId ?? ''}
                  onChange={(v) => setSelectedTemplateId(Number(v))}
                  className="mt-1 w-full"
                />
                {selectedTemplate?.description && (
                  <p className="text-xs text-[#6B6B7B] mt-1 leading-relaxed">{selectedTemplate.description}</p>
                )}
              </div>
              <div>
                <label className="text-xs text-[#6B6B7B]">绑定账户</label>
                <Dropdown
                  options={activeAccounts.map((a) => ({ value: a.id, label: `${a.name} (${a.trade_mode === 'live' ? '真实' : '模拟'})` }))}
                  value={selectedAccountForCreate ?? ''}
                  onChange={(v) => setSelectedAccountForCreate(Number(v))}
                  className="mt-1 w-full"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[#6B6B7B]">策略名称</label>
                <input
                  value={instanceName}
                  onChange={(e) => setInstanceName(e.target.value)}
                  placeholder={selectedTemplate?.name ?? '自定义名称'}
                  className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
                />
              </div>
              <div>
                <label className="text-xs text-[#6B6B7B]">市场类型</label>
                <Dropdown
                  options={[{ value: 'spot', label: '现货' }, { value: 'swap', label: '永续合约' }]}
                  value={selectedMarketType}
                  onChange={(v) => setSelectedMarketType(String(v))}
                  className="mt-1 w-full"
                />
              </div>
            </div>

            <div>
              <label className="text-xs text-[#6B6B7B]">
                交易对
                {lockedBaseSymbol && (
                  <span className="ml-2 text-[10px] text-[#F0A500] border border-[#F0A500]/30 rounded px-1.5 py-0.5">已锁定</span>
                )}
              </label>
              <div className="relative" ref={symbolDropdownRef}>
                <div className="relative">
                  <input
                    value={lockedBaseSymbol || symbolSearch}
                    onChange={(e) => {
                      if (lockedBaseSymbol) return
                      setSymbolSearch(e.target.value)
                      setCustomParams((prev) => ({ ...prev, symbol: e.target.value }))
                      setShowSymbolDropdown(true)
                    }}
                    onFocus={() => { if (!lockedBaseSymbol) setShowSymbolDropdown(true) }}
                    readOnly={Boolean(lockedBaseSymbol)}
                    placeholder="搜索或输入交易对，如 BTC-USDT-SWAP"
                    className={`w-full border border-[#1E1E28] rounded-md px-3 py-2 text-sm mt-1 focus:outline-none font-mono ${
                      lockedBaseSymbol
                        ? 'bg-[#1A1A24] text-[#6B6B7B] cursor-not-allowed'
                        : 'bg-[#0C0C14] text-[#E8E8ED] focus:border-[#00D4AA]'
                    }`}
                  />
                  {lockedBaseSymbol ? (
                    <Lock className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#F0A500]" />
                  ) : (
                    <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6B6B7B]" />
                  )}
                </div>
                {showSymbolDropdown && !lockedBaseSymbol && (
                  <div className="absolute z-10 mt-1 w-full bg-[#14141A] border border-[#1E1E28] rounded-md shadow-lg max-h-60 overflow-y-auto">
                    {contractSymbols.length > 0 && (
                      <>
                        <div className="text-[10px] text-[#F0A500] px-3 py-1.5 border-b border-[#1E1E28]/50">合约</div>
                        {contractSymbols.map((s) => (
                          <button
                            key={s}
                            type="button"
                            onClick={() => {
                              setSymbolSearch(s)
                              setCustomParams((prev) => ({ ...prev, symbol: s }))
                              setShowSymbolDropdown(false)
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-[#E8E8ED] hover:bg-[#1A1A24] font-mono flex items-center gap-2"
                          >
                            <span className="text-[#F0A500] text-[10px] font-medium">合约</span>
                            {INST_ID_LABEL[s] || s}
                          </button>
                        ))}
                      </>
                    )}
                    {spotSymbols.length > 0 && (
                      <>
                        <div className="text-[10px] text-[#00D4AA] px-3 py-1.5 border-b border-[#1E1E28]/50">现货</div>
                        {spotSymbols.map((s) => (
                          <button
                            key={s}
                            type="button"
                            onClick={() => {
                              setSymbolSearch(s)
                              setCustomParams((prev) => ({ ...prev, symbol: s }))
                              setShowSymbolDropdown(false)
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-[#E8E8ED] hover:bg-[#1A1A24] font-mono flex items-center gap-2"
                          >
                            <span className="text-[#00D4AA] text-[10px] font-medium">现货</span>
                            {INST_ID_LABEL[s] || s}
                          </button>
                        ))}
                      </>
                    )}
                    {filteredSymbols.length === 0 && (
                      <div className="text-xs text-[#6B6B7B] px-3 py-3 text-center">无匹配交易对</div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="border-t border-[#1E1E28] pt-3">
              <div className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">参数配置</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Object.entries(paramSchema).map(([key, field]) => {
                  const ftype = field.type
                  const isInt = ftype === 'int'
                  const isNumeric = ftype === 'int' || ftype === 'float' || ftype === 'number'
                  const isBool = ftype === 'bool' || ftype === 'boolean'
                  const isSelect = ftype === 'select'
                  const optionLabels = field.option_labels
                  const step = field.step ?? (isInt ? 1 : 'any')
                  const currentSymbol = String(customParams.symbol || '')
                  const isOrderQtyField = key === 'order_qty' || key === 'sz'
                  const useOrderQtyInput = isOrderQtyField && isNumeric && isContractPair(currentSymbol)
                  return (
                    <div key={key} className={useOrderQtyInput ? 'sm:col-span-2' : ''}>
                      <label className="text-xs text-[#6B6B7B]" title={field.hint}>
                        {field.label}
                      </label>
                      {field.unit ? (
                        <span className="text-xs text-[#6B6B7B]/50 ml-1">({field.unit})</span>
                      ) : field.hint ? (
                        <span className="text-xs text-[#6B6B7B]/50 ml-1">({field.hint})</span>
                      ) : null}
                      {isSelect && field.options ? (
                        <Dropdown
                          options={field.options.map((opt: string, idx: number) => ({
                            value: opt,
                            label: optionLabels?.[idx] ?? opt,
                          }))}
                          value={String(customParams[key] ?? field.default ?? '')}
                          onChange={(v) => {
                            setCustomParams((prev) => ({
                              ...prev,
                              [key]: isNaN(Number(v)) ? v : Number(v),
                            }))
                          }}
                          className="mt-1 w-full"
                        />
                      ) : isBool ? (
                        <div className="mt-1 flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={Boolean(customParams[key] ?? field.default)}
                            onChange={(e) => {
                              setCustomParams((prev) => ({ ...prev, [key]: e.target.checked }))
                            }}
                            className="w-4 h-4 accent-[#00D4AA]"
                          />
                          <span className="text-xs text-[#6B6B7B]">
                            {Boolean(customParams[key] ?? field.default) ? '开启' : '关闭'}
                          </span>
                        </div>
                      ) : useOrderQtyInput ? (
                        <OrderQtyInput
                          symbol={currentSymbol}
                          value={typeof customParams[key] === 'number' ? (customParams[key] as number) : (typeof field.default === 'number' ? field.default : undefined)}
                          szFields={(customParams.sz_fields as SzFields) ?? null}
                          onChange={(sz, fields) => {
                            setCustomParams((prev) => ({
                              ...prev,
                              [key]: sz,
                              sz_fields: fields,
                            }))
                          }}
                          step={step}
                          min={field.min}
                          max={field.max}
                          className="mt-1"
                        />
                      ) : isNumeric ? (
                        <NumberInput
                          value={typeof customParams[key] === 'number' ? (customParams[key] as number) : (typeof field.default === 'number' ? field.default : undefined)}
                          onChange={(v) => {
                            setCustomParams((prev) => ({
                              ...prev,
                              [key]: v,
                            }))
                          }}
                          step={step}
                          min={field.min}
                          max={field.max}
                          className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      ) : (
                        <input
                          type="text"
                          value={String(customParams[key] ?? field.default ?? '')}
                          onChange={(e) => {
                            const raw = e.target.value
                            setCustomParams((prev) => ({
                              ...prev,
                              [key]: raw,
                            }))
                          }}
                          className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            <button
              onClick={handleCreate}
              disabled={creating || !selectedTemplateId || !selectedAccountForCreate}
              className="w-full bg-[#00D4AA] text-[#0A0A0F] rounded-md py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
            >
              {creating ? '创建中...' : '创建策略实例'}
            </button>
          </div>
        )}
      </Modal>

      <NewTemplateModal
        open={showNewTemplate}
        onClose={() => setShowNewTemplate(false)}
        onCreated={loadData}
      />
      <DslEditor
        open={showDslEditor}
        onClose={handleCloseDslEditor}
        onSaved={loadData}
        editingTemplateId={editingTemplateId}
        templates={templates}
      />
      <TemplateMgmtModal
        open={showTemplateMgmt}
        onClose={() => setShowTemplateMgmt(false)}
        templates={templates}
        onEdit={handleEditTemplate}
        onDelete={handleDeleteTemplate}
        deletingTemplateId={deletingTemplateId}
      />
    </div>
  )
}

function NewTemplateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [fields, setFields] = useState<{ key: string; label: string; type: string; default: string; step: string; min: string; max: string; hint: string }[]>([])
  const [saving, setSaving] = useState(false)

  const addField = () => {
    setFields([...fields, { key: '', label: '', type: 'number', default: '0', step: '0.01', min: '', max: '', hint: '' }])
  }

  const removeField = (idx: number) => {
    setFields(fields.filter((_, i) => i !== idx))
  }

  const updateField = (idx: number, prop: string, value: string) => {
    setFields(fields.map((f, i) => (i === idx ? { ...f, [prop]: value } : f)))
  }

  const handleSave = async () => {
    if (!name.trim()) return
    const defaultParams: Record<string, unknown> = {}
    const paramSchema: Record<string, unknown> = {}
    for (const f of fields) {
      if (!f.key.trim()) continue
      const v = f.type === 'number' ? Number(f.default) : f.default
      defaultParams[f.key] = v
      paramSchema[f.key] = {
        label: f.label || f.key,
        type: f.type,
        default: v,
        step: f.type === 'number' ? Number(f.step) || 1 : undefined,
        min: f.min ? Number(f.min) : undefined,
        max: f.max ? Number(f.max) : undefined,
        hint: f.hint || undefined,
      }
    }

    setSaving(true)
    try {
      await createTemplate({
        name: name.trim(),
        strategy_type: name.trim().toLowerCase().replace(/\s+/g, '_'),
        description: desc || undefined,
        default_params: defaultParams,
        param_schema: paramSchema,
      })
      setName('')
      setDesc('')
      setFields([])
      onClose()
      onCreated()
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  return (
    <Modal open={open} onClose={onClose} title="创建自定义策略模板" wide scrollable={false}>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-[#6B6B7B]">模板名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="我的自定义策略"
            className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
          />
        </div>
        <div>
          <label className="text-xs text-[#6B6B7B]">策略描述</label>
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="描述策略逻辑"
            className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
          />
        </div>

        <div className="border-t border-[#1E1E28] pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-[#6B6B7B] uppercase tracking-wide">参数定义</span>
            <button
              onClick={addField}
              className="text-xs text-[#00D4AA] hover:underline"
            >
              + 添加参数
            </button>
          </div>

          <div className="space-y-3">
            {fields.map((f, idx) => (
              <div key={idx} className="bg-[#0C0C14] border border-[#1E1E28] rounded-lg p-3 relative">
                <button onClick={() => removeField(idx)} className="absolute top-2 right-2 text-[#6B6B7B] hover:text-[#FF4757]">
                  <X className="w-3.5 h-3.5" />
                </button>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">参数名</label>
                    <input
                      value={f.key}
                      onChange={(e) => updateField(idx, 'key', e.target.value)}
                      placeholder="e.g. upper_price"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">显示名</label>
                    <input
                      value={f.label}
                      onChange={(e) => updateField(idx, 'label', e.target.value)}
                      placeholder="e.g. 价格上限"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">类型</label>
                    <Dropdown
                      options={[{ value: 'number', label: '数字' }, { value: 'string', label: '文本' }, { value: 'select', label: '下拉' }]}
                      value={f.type}
                      onChange={(v) => updateField(idx, 'type', String(v))}
                      className="mt-0.5 w-full"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">默认值</label>
                    <input
                      value={f.default}
                      onChange={(e) => updateField(idx, 'default', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  {f.type === 'number' && (
                    <>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">最小值</label>
                        <input
                          value={f.min}
                          onChange={(e) => updateField(idx, 'min', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">最大值</label>
                        <input
                          value={f.max}
                          onChange={(e) => updateField(idx, 'max', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">步长</label>
                        <input
                          value={f.step}
                          onChange={(e) => updateField(idx, 'step', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                    </>
                  )}
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">提示说明</label>
                    <input
                      value={f.hint}
                      onChange={(e) => updateField(idx, 'hint', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="w-full bg-[#00D4AA] text-[#0A0A0F] rounded-md py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
        >
          {saving ? '保存中...' : '保存自定义模板'}
        </button>
      </div>
    </Modal>
  )
}

function TemplateMgmtModal({
  open,
  onClose,
  templates,
  onEdit,
  onDelete,
  deletingTemplateId,
}: {
  open: boolean
  onClose: () => void
  templates: StrategyTemplate[]
  onEdit: (id: number) => void
  onDelete: (id: number) => Promise<void>
  deletingTemplateId: number | null
}) {
  // 只展示自定义模板（过滤掉内置硬编码策略模板）
  const customTemplates = templates.filter((t) => !t.is_builtin)

  return (
    <Modal open={open} onClose={onClose} title="模板管理" wide>
      <div className="space-y-2">
        {customTemplates.length === 0 ? (
          <div className="text-sm text-[#6B6B7B] text-center py-8">暂无自定义模板</div>
        ) : (
          customTemplates.map((t) => {
            const isQsModel = t.qs_model_config != null
            const hashShort = t.logic_hash ? t.logic_hash.slice(0, 8) : null
            const isDeleting = deletingTemplateId === t.id
            return (
              <div
                key={t.id}
                className="flex items-center gap-3 bg-[#0C0C14] border border-[#1E1E28] rounded-md p-3"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-[#E8E8ED] font-medium truncate">{t.name}</div>
                  <div className="text-xs text-[#6B6B7B] mt-0.5 flex items-center gap-2 flex-wrap">
                    <span className="font-mono">{t.strategy_type}</span>
                    {hashShort && (
                      <span className="font-mono text-[#6B6B7B]/70">#{hashShort}</span>
                    )}
                    {isQsModel ? (
                      <span className="text-[#00D4AA] border border-[#00D4AA]/20 rounded px-1 py-0.5 text-[10px]">QS-Model</span>
                    ) : (
                      <span className="text-[#6B6B7B] border border-[#1E1E28] rounded px-1 py-0.5 text-[10px]">参数定义</span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onEdit(t.id)}
                  disabled={!isQsModel}
                  title={isQsModel ? '编辑模板' : '非 QS-Model 模板不支持编辑'}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md border border-[#1E1E28] text-[#E8E8ED] hover:bg-[#1A1A24] disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  <Edit2 className="w-3.5 h-3.5" /> 编辑
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(t.id)}
                  disabled={isDeleting}
                  title="删除模板"
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md border border-[#1E1E28] text-[#FF4757] hover:bg-[#FF4757]/10 disabled:opacity-50 transition-colors shrink-0"
                >
                  {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                  删除
                </button>
              </div>
            )
          })
        )}
      </div>
    </Modal>
  )
}
