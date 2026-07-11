import { useState, useEffect, useRef, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { getInstrumentInfo, getTickerPrice } from '../api/market'

export type QtyUnit = 'contracts' | 'base_ccy' | 'quote_ccy'

export interface SzFields {
  input: number
  unit: QtyUnit
  ct_val: number
  sz: number
}

interface OrderQtyInputProps {
  symbol: string
  value: number | undefined | null
  szFields?: SzFields | null
  onChange: (sz: number | undefined, fields: SzFields | null) => void
  className?: string
  step?: string | number
  min?: number
  max?: number
}

const UNIT_PLACEHOLDER: Record<QtyUnit, string> = {
  contracts: '输入张数',
  base_ccy: '输入目标币数量',
  quote_ccy: '输入稳定币金额',
}

const UNIT_LABEL: Record<QtyUnit, string> = {
  contracts: '张数',
  base_ccy: '目标币',
  quote_ccy: '稳定币',
}

export default function OrderQtyInput({
  symbol,
  value,
  szFields,
  onChange,
  className,
  step,
  min,
  max,
}: OrderQtyInputProps) {
  const [unit, setUnit] = useState<QtyUnit>(szFields?.unit ?? 'contracts')
  const [draft, setDraft] = useState<string>(
    szFields?.input != null ? String(szFields.input) : value != null ? String(value) : '',
  )
  const [ctVal, setCtVal] = useState<number>(szFields?.ct_val ?? 1.0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lastValid = useRef<number | undefined>(value ?? undefined)
  const ctValFetchedFor = useRef<string>('')

  // 外部 value 变化时同步 draft（如切换模板加载默认值）
  useEffect(() => {
    if (szFields?.input != null) {
      if (String(szFields.input) !== draft) {
        setDraft(String(szFields.input))
      }
      setUnit(szFields.unit)
      setCtVal(szFields.ct_val)
    } else if (value != null && String(value) !== draft) {
      setDraft(String(value))
      lastValid.current = value
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, szFields])

  // symbol 变化时重置单位与错误
  useEffect(() => {
    setUnit('contracts')
    setError(null)
    setCtVal(1.0)
    ctValFetchedFor.current = ''
  }, [symbol])

  const ensureCtVal = useCallback(
    async (instId: string): Promise<number> => {
      if (ctValFetchedFor.current === instId && ctVal > 0) {
        return ctVal
      }
      setLoading(true)
      setError(null)
      try {
        const res = await getInstrumentInfo(instId)
        const val = res.data.ctVal || 1.0
        setCtVal(val)
        ctValFetchedFor.current = instId
        return val
      } catch {
        setError('获取合约信息失败，使用默认 ctVal=1')
        return 1.0
      } finally {
        setLoading(false)
      }
    },
    [ctVal],
  )

  const computeAndNotify = useCallback(
    async (inputVal: number | undefined, currentUnit: QtyUnit, overrideCtVal?: number) => {
      if (inputVal == null || isNaN(inputVal)) {
        onChange(undefined, null)
        return
      }

      const usedCtVal = overrideCtVal ?? ctVal

      if (currentUnit === 'contracts') {
        let sz = Math.floor(inputVal)
        if (min != null) sz = Math.max(min, sz)
        onChange(sz, { input: inputVal, unit: currentUnit, ct_val: usedCtVal, sz })
        return
      }

      if (currentUnit === 'base_ccy') {
        if (usedCtVal <= 0) {
          setError('ctVal 无效')
          onChange(undefined, null)
          return
        }
        let sz = Math.floor(inputVal / usedCtVal)
        if (min != null) sz = Math.max(min, sz)
        onChange(sz, { input: inputVal, unit: currentUnit, ct_val: usedCtVal, sz })
        return
      }

      // quote_ccy: 需要实时价格
      setLoading(true)
      setError(null)
      try {
        const res = await getTickerPrice(symbol)
        if (res.data.code !== '0' || !res.data.data) {
          setError('无法获取当前价格，请改用张数或目标币')
          onChange(undefined, null)
          return
        }
        const price = parseFloat(res.data.data.last)
        if (!price || price <= 0) {
          setError('无法获取当前价格，请改用张数或目标币')
          onChange(undefined, null)
          return
        }
        let sz = Math.floor(inputVal / price / usedCtVal)
        if (min != null) sz = Math.max(min, sz)
        onChange(sz, { input: inputVal, unit: currentUnit, ct_val: usedCtVal, sz })
      } catch {
        setError('无法获取当前价格，请改用张数或目标币')
        onChange(undefined, null)
      } finally {
        setLoading(false)
      }
    },
    [ctVal, symbol, min, onChange],
  )

  const handleUnitChange = async (newUnitStr: string) => {
    const newUnit = newUnitStr as QtyUnit
    setUnit(newUnit)
    setError(null)

    const inputVal = draft === '' ? undefined : Number(draft)
    if (inputVal == null || isNaN(inputVal)) return

    if (newUnit === 'base_ccy' || newUnit === 'quote_ccy') {
      const fetchedCtVal = await ensureCtVal(symbol)
      await computeAndNotify(inputVal, newUnit, fetchedCtVal)
    } else {
      await computeAndNotify(inputVal, newUnit)
    }
  }

  const handleBlur = async () => {
    const num = Number(draft)
    if (draft === '' || isNaN(num)) {
      setDraft(lastValid.current != null ? String(lastValid.current) : '')
      onChange(lastValid.current, null)
      return
    }

    let clamped = num
    if (min != null) clamped = Math.max(min, clamped)
    if (max != null) clamped = Math.min(max, clamped)

    if (unit === 'base_ccy' || unit === 'quote_ccy') {
      const fetchedCtVal = await ensureCtVal(symbol)
      await computeAndNotify(clamped, unit, fetchedCtVal)
    } else {
      await computeAndNotify(clamped, unit)
    }
    lastValid.current = clamped
  }

  // 预览换算结果
  const previewSz = (() => {
    const num = Number(draft)
    if (draft === '' || isNaN(num)) return null
    if (unit === 'contracts') return Math.floor(num)
    if (unit === 'base_ccy' && ctVal > 0) return Math.floor(num / ctVal)
    return null
  })()

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2">
        <input
          type="number"
          value={draft}
          step={step}
          min={min}
          max={max}
          placeholder={UNIT_PLACEHOLDER[unit]}
          className={`flex-1 bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono ${className ?? ''}`}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={handleBlur}
        />
        <select
          value={unit}
          onChange={(e) => handleUnitChange(e.target.value)}
          className="bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] cursor-pointer"
        >
          <option value="contracts">{UNIT_LABEL.contracts}</option>
          <option value="base_ccy">{UNIT_LABEL.base_ccy}</option>
          <option value="quote_ccy">{UNIT_LABEL.quote_ccy}</option>
        </select>
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-[#6B6B7B] self-center" />}
      </div>
      {error && <span className="text-[10px] text-[#FF4757]">{error}</span>}
      {!error && previewSz != null && unit !== 'contracts' && (
        <span className="text-[10px] text-[#6B6B7B]">≈ {previewSz} 张</span>
      )}
      {!error && unit === 'quote_ccy' && (
        <span className="text-[10px] text-[#6B6B7B]/70">提交时按实时价格换算</span>
      )}
    </div>
  )
}
