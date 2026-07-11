import { useEffect, useState, useRef } from 'react'

// NumberInput — 草稿字符串数字输入（保留输入中间态，如 "0." 不被吞）
export default function NumberInput({ value, onChange, step, min, max, placeholder, className }: {
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
