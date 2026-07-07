import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus, Play, Pause, Square, ChevronDown, Trash2, RefreshCw, FileText, X } from 'lucide-react'
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
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'
import type { StrategyInstance, StrategyTemplate, Account, ParamSchemaField } from '../types'

export default function StrategiesPage() {
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [templates, setTemplates] = useState<StrategyTemplate[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showNewTemplate, setShowNewTemplate] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null)
  const [customParams, setCustomParams] = useState<Record<string, unknown>>({})

  const loadData = () => {
    listInstances().then((res) => setInstances(res.data)).catch(() => {})
    listTemplates().then((res) => setTemplates(res.data)).catch(() => {})
    listAccounts().then((res) => setAccounts(res.data)).catch(() => {})
  }

  useEffect(() => { loadData() }, [])

  const activeAccounts = accounts.filter((a) => a.is_active)

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId)
  const paramSchema = (selectedTemplate?.param_schema ?? {}) as Record<string, ParamSchemaField>

  useEffect(() => {
    if (selectedTemplate) {
      const defaults: Record<string, unknown> = {}
      for (const [key, field] of Object.entries(paramSchema)) {
        defaults[key] = field.default
      }
      setCustomParams(defaults)
    }
  }, [selectedTemplateId])

  const [feasibilityMsg, setFeasibilityMsg] = useState<string | null>(null)
  const [startingId, setStartingId] = useState<number | null>(null)

  const handleStart = async (id: number) => {
    setStartingId(id)
    setFeasibilityMsg(null)
    try {
      const feas = await checkFeasibility(id)
      if (!feas.data.ok) {
        setFeasibilityMsg(feas.data.reason)
        setStartingId(null)
        return
      }
      setFeasibilityMsg(feas.data.reason)
      await startInstance(id)
      setFeasibilityMsg(null)
      loadData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setFeasibilityMsg(detail || '启动失败')
    }
    setStartingId(null)
  }
  const handlePause = async (id: number) => { await pauseInstance(id); loadData() }
  const handleResume = async (id: number) => { await resumeInstance(id); loadData() }
  const handleStop = async (id: number) => { await stopInstance(id); loadData() }
  const handleDelete = async (id: number) => { await deleteInstance(id); loadData() }

  const handleCreate = async () => {
    if (!selectedTemplateId) return
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
    await updateInstance(id, { params: inst.params })
    loadData()
  }

  const getInstanceSchema = (inst: StrategyInstance) => {
    const tpl = templates.find((t) => t.id === inst.template_id)
    return (tpl?.param_schema ?? {}) as Record<string, ParamSchemaField>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">策略管理</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowNewTemplate(true)}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <FileText className="w-4 h-4" /> 自定义模板
          </button>
          <button
            onClick={openCreateModal}
            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-4 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors"
          >
            <Plus className="w-4 h-4" /> 新建策略
          </button>
        </div>
      </div>

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
        {instances.length === 0 ? (
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
                      {inst.template_name} · {inst.symbol} · {inst.market_type === 'swap' ? '永续合约' : inst.market_type === 'spot' ? '现货' : inst.market_type}
                    </div>
                  </div>
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
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
                        <div className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">策略参数</div>
                        <div className="grid grid-cols-2 gap-3">
                          {Object.entries(inst.params).map(([key, value]) => {
                            const field = schema[key]
                            const label = field?.label ?? key
                            const hint = field?.hint ?? ''
                            return (
                              <div key={key}>
                                <label className="text-xs text-[#6B6B7B]" title={hint}>
                                  {label}
                                  {hint ? <span className="ml-1 opacity-50">({hint})</span> : null}
                                </label>
                                {field?.type === 'select' && field.options ? (
                                  <select
                                    value={String(value)}
                                    onChange={(e) => {
                                      const v = e.target.value
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: isNaN(Number(v)) ? v : Number(v) } }
                                            : pi,
                                        ),
                                      )
                                    }}
                                    className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] mt-1 font-mono"
                                  >
                                    {field.options.map((opt) => (
                                      <option key={opt} value={opt}>{opt}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <input
                                    type={field?.type === 'number' ? 'number' : 'text'}
                                    step={field?.step ?? 1}
                                    min={field?.min}
                                    max={field?.max}
                                    value={String(value)}
                                    onChange={(e) => {
                                      const raw = e.target.value
                                      setInstances((prev) =>
                                        prev.map((pi) =>
                                          pi.id === inst.id
                                            ? { ...pi, params: { ...pi.params, [key]: field?.type === 'number' ? Number(raw) : raw } }
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
                            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-md px-4 py-1.5 text-xs font-semibold hover:bg-[#00D4AA]/90 transition-colors"
                          >
                            <RefreshCw className="w-3 h-3" /> 保存参数
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

      <Modal open={showCreate} onClose={() => { setShowCreate(false); resetCreateForm() }} title="新建策略">
        {activeAccounts.length === 0 ? (
          <div className="text-sm text-[#6B6B7B] text-center py-4">请先在「账户管理」中添加 OKX 账户</div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-[#6B6B7B]">策略模板</label>
              <select
                value={selectedTemplateId ?? ''}
                onChange={(e) => setSelectedTemplateId(Number(e.target.value))}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} {t.is_custom ? '(自定义)' : ''}
                  </option>
                ))}
              </select>
              {selectedTemplate?.description && (
                <p className="text-xs text-[#6B6B7B] mt-1 leading-relaxed">{selectedTemplate.description}</p>
              )}
            </div>

            <div>
              <label className="text-xs text-[#6B6B7B]">绑定账户</label>
              <select
                value={selectedAccountForCreate ?? ''}
                onChange={(e) => setSelectedAccountForCreate(Number(e.target.value))}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
              >
                {activeAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.trade_mode === 'live' ? '真实' : '模拟'})</option>
                ))}
              </select>
            </div>

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
              <select
                value={selectedMarketType}
                onChange={(e) => setSelectedMarketType(e.target.value)}
                className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
              >
                <option value="spot">现货</option>
                <option value="swap">永续合约</option>
              </select>
            </div>

            <div className="border-t border-[#1E1E28] pt-3">
              <div className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">参数配置</div>
              <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
                {Object.entries(paramSchema).map(([key, field]) => (
                  <div key={key}>
                    <label className="text-xs text-[#6B6B7B]" title={field.hint}>
                      {field.label}
                    </label>
                    {field.hint && (
                      <span className="text-xs text-[#6B6B7B]/50 ml-1">({field.hint})</span>
                    )}
                    {field.type === 'select' && field.options ? (
                      <select
                        value={String(customParams[key] ?? field.default)}
                        onChange={(e) => {
                          const v = e.target.value
                          setCustomParams((prev) => ({ ...prev, [key]: isNaN(Number(v)) ? v : Number(v) }))
                        }}
                        className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono"
                      >
                        {field.options.map((opt) => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={field.type === 'number' ? 'number' : 'text'}
                        step={field.step ?? 1}
                        min={field.min}
                        max={field.max}
                        value={String(customParams[key] ?? field.default)}
                        onChange={(e) => {
                          const raw = e.target.value
                          setCustomParams((prev) => ({
                            ...prev,
                            [key]: field.type === 'number' ? Number(raw) : raw,
                          }))
                        }}
                        className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono"
                      />
                    )}
                  </div>
                ))}
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
    <Modal open={open} onClose={onClose} title="创建自定义策略模板">
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
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
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-[10px] text-[#6B6B7B]">参数名</label>
                    <input
                      value={f.key}
                      onChange={(e) => updateField(idx, 'key', e.target.value)}
                      placeholder="e.g. upper_price"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6B6B7B]">显示名</label>
                    <input
                      value={f.label}
                      onChange={(e) => updateField(idx, 'label', e.target.value)}
                      placeholder="e.g. 价格上限"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6B6B7B]">类型</label>
                    <select
                      value={f.type}
                      onChange={(e) => updateField(idx, 'type', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                    >
                      <option value="number">数字</option>
                      <option value="string">文本</option>
                      <option value="select">下拉</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6B6B7B]">默认值</label>
                    <input
                      value={f.default}
                      onChange={(e) => updateField(idx, 'default', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  {f.type === 'number' && (
                    <>
                      <div>
                        <label className="text-[10px] text-[#6B6B7B]">最小值</label>
                        <input
                          value={f.min}
                          onChange={(e) => updateField(idx, 'min', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6B6B7B]">最大值</label>
                        <input
                          value={f.max}
                          onChange={(e) => updateField(idx, 'max', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6B6B7B]">步长</label>
                        <input
                          value={f.step}
                          onChange={(e) => updateField(idx, 'step', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                    </>
                  )}
                  <div>
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
