import { useEffect, useState, useRef } from 'react'
import {
  listInstances,
  listTemplates,
  createInstance,
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
import { isContractPair, INST_ID_LABEL } from '../utils/instId'
import type { StrategyInstance, StrategyTemplate, Account, ParamSchemaField, StrategyEvent } from '../types'
import type { RenderParamField } from '../types/strategies'

export function useStrategiesState() {
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

  return {
    // data
    instances, setInstances,
    templates,
    accounts, activeAccounts,
    // ui state
    loading, toast, feasibilityMsg, setFeasibilityMsg,
    showCreate, setShowCreate,
    showNewTemplate, setShowNewTemplate,
    showDslEditor, setShowDslEditor,
    showTemplateMgmt, setShowTemplateMgmt,
    editingTemplateId, deletingTemplateId,
    expandedId, setExpandedId,
    creating, actionLoading, savingParams,
    // create form state
    selectedTemplateId, setSelectedTemplateId,
    customParams, setCustomParams,
    selectedTemplate, lockedBaseSymbol, paramSchema,
    symbolSearch, setSymbolSearch,
    showSymbolDropdown, setShowSymbolDropdown,
    symbolDropdownRef,
    filteredSymbols, contractSymbols, spotSymbols,
    instanceName, setInstanceName,
    selectedAccountForCreate, setSelectedAccountForCreate,
    selectedMarketType, setSelectedMarketType,
    instanceEvents,
    startingId, setStartingId,
    // actions
    loadData, showToast,
    handleStart, handlePause, handleResume, handleStop, handleDelete,
    handleDeleteTemplate, handleEditTemplate,
    handleOpenNewDslEditor, handleCloseDslEditor,
    handleCreate, openCreateModal, resetCreateForm, handleParamSave,
    getInstanceSchema,
  }
}
