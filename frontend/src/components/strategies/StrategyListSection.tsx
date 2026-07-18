import { type Dispatch, type SetStateAction } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Pause, Square, ChevronDown, Trash2, RefreshCw, Loader2 } from 'lucide-react'
import { formatInstId, isContractPair } from '../../utils/instId'
import StatusBadge from '../StatusBadge'
import Dropdown from '../Dropdown'
import OrderQtyInput, { type SzFields } from '../OrderQtyInput'
import NumberInput from './NumberInput'
import EventViewerModal from './EventViewerModal'
import type { StrategyInstance, StrategyEvent } from '../../types'
import type { RenderParamField } from '../../types/strategies'

interface StrategyListSectionProps {
  instances: StrategyInstance[]
  loading: boolean
  expandedId: number | null
  setExpandedId: (id: number | null) => void
  actionLoading: number | null
  savingParams: number | null
  instanceEvents: Record<number, StrategyEvent[]>
  feasibilityMsg: string | null
  setFeasibilityMsg: (msg: string | null) => void
  getInstanceSchema: (inst: StrategyInstance) => Record<string, RenderParamField>
  handleStart: (id: number) => void
  handlePause: (id: number) => void
  handleResume: (id: number) => void
  handleStop: (id: number) => void
  handleDelete: (id: number) => void
  handleParamSave: (id: number) => void
  setInstances: Dispatch<SetStateAction<StrategyInstance[]>>
}

export default function StrategyListSection({
  instances,
  loading,
  expandedId,
  setExpandedId,
  actionLoading,
  savingParams,
  instanceEvents,
  feasibilityMsg,
  setFeasibilityMsg,
  getInstanceSchema,
  handleStart,
  handlePause,
  handleResume,
  handleStop,
  handleDelete,
  handleParamSave,
  setInstances,
}: StrategyListSectionProps) {
  return (
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
                      <EventViewerModal events={instanceEvents[inst.id]} />
                      <div className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">策略参数</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {Object.entries(inst.params).filter(([key]) => key !== 'sz_fields').map(([key, value]) => {
                          const field = schema[key]
                          const label = field?.label ?? key
                          const hint = field?.hint ?? ''
                          const isOrderQtyField = key === 'order_qty' || key === 'sz'
                          const useOrderQty = isOrderQtyField && isContractPair(inst.symbol)
                          const isNumericField = ['number', 'int', 'integer', 'float'].includes(field?.type ?? '')
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
                              ) : useOrderQty && isNumericField ? (
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
                              ) : isNumericField ? (
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
  )
}
