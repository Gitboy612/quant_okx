import { type RefObject } from 'react'
import { Lock, Search } from 'lucide-react'
import Modal from '../Modal'
import Dropdown from '../Dropdown'
import OrderQtyInput, { type SzFields } from '../OrderQtyInput'
import NumberInput from './NumberInput'
import { INST_ID_LABEL, isContractPair } from '../../utils/instId'
import type { Account, StrategyTemplate } from '../../types'
import type { RenderParamField } from '../../types/strategies'

interface InstanceFormModalProps {
  open: boolean
  onClose: () => void
  templates: StrategyTemplate[]
  activeAccounts: Account[]
  selectedTemplateId: number | null
  setSelectedTemplateId: (id: number | null) => void
  selectedAccountForCreate: number | null
  setSelectedAccountForCreate: (id: number | null) => void
  instanceName: string
  setInstanceName: (v: string) => void
  selectedMarketType: string
  setSelectedMarketType: (v: string) => void
  customParams: Record<string, unknown>
  setCustomParams: (updater: (prev: Record<string, unknown>) => Record<string, unknown>) => void
  selectedTemplate: StrategyTemplate | undefined
  lockedBaseSymbol: string
  paramSchema: Record<string, RenderParamField>
  symbolSearch: string
  setSymbolSearch: (v: string) => void
  showSymbolDropdown: boolean
  setShowSymbolDropdown: (v: boolean) => void
  symbolDropdownRef: RefObject<HTMLDivElement>
  filteredSymbols: string[]
  contractSymbols: string[]
  spotSymbols: string[]
  creating: boolean
  handleCreate: () => void
}

export default function InstanceFormModal({
  open,
  onClose,
  templates,
  activeAccounts,
  selectedTemplateId,
  setSelectedTemplateId,
  selectedAccountForCreate,
  setSelectedAccountForCreate,
  instanceName,
  setInstanceName,
  selectedMarketType,
  setSelectedMarketType,
  customParams,
  setCustomParams,
  selectedTemplate,
  lockedBaseSymbol,
  paramSchema,
  symbolSearch,
  setSymbolSearch,
  showSymbolDropdown,
  setShowSymbolDropdown,
  symbolDropdownRef,
  filteredSymbols,
  contractSymbols,
  spotSymbols,
  creating,
  handleCreate,
}: InstanceFormModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="新建策略" wide>
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
  )
}
