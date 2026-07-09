import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import { INST_ID_LABEL, isContractPair } from '../utils/instId'

interface SymbolPickerProps {
  value: string
  onChange: (symbol: string) => void
  placeholder?: string
  className?: string
}

/**
 * 交易对下拉搜索组件。
 * - 预设常用交易对（来自 INST_ID_LABEL，与 StrategiesPage 共享同一份清单）
 * - 支持搜索过滤（按 instId 或友好名称匹配）
 * - 沿用项目深色主题风格（#0C0C14 / #14141A 背景，#00D4AA 主色）
 * - 支持直接输入自定义交易对（非预设项也可作为 value）
 */
export default function SymbolPicker({
  value,
  onChange,
  placeholder = '搜索或输入交易对，如 BTC-USDT',
  className = '',
}: SymbolPickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState(value)
  const ref = useRef<HTMLDivElement>(null)

  // 同步外部 value 变化到搜索框（仅在不展开时）
  useEffect(() => {
    if (!open) setSearch(value)
  }, [value, open])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const presetSymbols = useMemo(() => Object.keys(INST_ID_LABEL), [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return presetSymbols
    return presetSymbols.filter(
      (s) =>
        s.toLowerCase().includes(q) ||
        (INST_ID_LABEL[s] && INST_ID_LABEL[s].toLowerCase().includes(q)),
    )
  }, [search, presetSymbols])

  const contractSymbols = filtered.filter((s) => isContractPair(s))
  const spotSymbols = filtered.filter((s) => !isContractPair(s))

  function pick(s: string) {
    setSearch(s)
    onChange(s)
    setOpen(false)
  }

  return (
    <div ref={ref} className={`relative ${className}`}>
      <div className="relative">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            onChange(e.target.value)
            if (!open) setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
        />
        <button
          type="button"
          tabIndex={-1}
          onClick={() => setOpen(!open)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6B6B7B] hover:text-[#00D4AA] transition-colors"
        >
          {search ? <Search className="w-4 h-4" /> : <ChevronDown className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`} />}
        </button>
      </div>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#14141A] border border-[#1E1E28] rounded-md shadow-[0_0_30px_rgba(0,0,0,0.5)] max-h-60 overflow-y-auto py-1">
          {contractSymbols.length > 0 && (
            <>
              <div className="text-[10px] text-[#F0A500] px-3 py-1 border-b border-[#1E1E28]/50 uppercase tracking-wide">合约</div>
              {contractSymbols.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => pick(s)}
                  className={`w-full text-left px-3 py-1.5 text-xs font-mono flex items-center gap-2 transition-colors ${
                    s === value ? 'bg-[#00D4AA]/10 text-[#00D4AA]' : 'text-[#E8E8ED] hover:bg-[#1A1A24]'
                  }`}
                >
                  <span className="text-[#F0A500] text-[10px]">合约</span>
                  {INST_ID_LABEL[s] || s}
                </button>
              ))}
            </>
          )}
          {spotSymbols.length > 0 && (
            <>
              <div className="text-[10px] text-[#00D4AA] px-3 py-1 border-b border-[#1E1E28]/50 uppercase tracking-wide">现货</div>
              {spotSymbols.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => pick(s)}
                  className={`w-full text-left px-3 py-1.5 text-xs font-mono flex items-center gap-2 transition-colors ${
                    s === value ? 'bg-[#00D4AA]/10 text-[#00D4AA]' : 'text-[#E8E8ED] hover:bg-[#1A1A24]'
                  }`}
                >
                  <span className="text-[#00D4AA] text-[10px]">现货</span>
                  {INST_ID_LABEL[s] || s}
                </button>
              ))}
            </>
          )}
          {filtered.length === 0 && (
            <div className="text-xs text-[#6B6B7B] px-3 py-3 text-center">
              无匹配交易对，可直接输入自定义值
            </div>
          )}
        </div>
      )}
    </div>
  )
}
