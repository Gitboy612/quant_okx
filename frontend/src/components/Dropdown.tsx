import { useState, useRef, useEffect } from 'react'
import { ChevronDown } from 'lucide-react'

interface DropdownOption {
  value: string | number
  label: string
}

interface DropdownProps {
  options: DropdownOption[]
  value: string | number
  onChange: (value: string | number) => void
  className?: string
  placeholder?: string
}

export default function Dropdown({ options, value, onChange, className = '', placeholder }: DropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 bg-[rgba(12,18,38,0.65)] border border-[rgba(0,212,170,0.08)] rounded-lg px-3 py-2 text-sm text-[#EDF0F7] hover:border-[rgba(0,212,170,0.18)] transition-all duration-300 w-full justify-between hover:shadow-[0_0_15px_rgba(0,212,170,0.06)]"
      >
        <span className={selected ? 'text-[#EDF0F7]' : 'text-[#7B86A2]'}>
          {selected ? selected.label : (placeholder || '请选择')}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#7B86A2] transition-transform duration-300 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[rgba(10,15,30,0.85)] border border-[rgba(0,212,170,0.1)] rounded-lg shadow-[0_0_30px_rgba(0,0,0,0.5),0_0_15px_rgba(0,212,170,0.05)] max-h-60 overflow-y-auto py-1">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                onChange(opt.value)
                setOpen(false)
              }}
              className={`w-full text-left px-3 py-2 text-sm transition-all duration-200 ${
                opt.value === value
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA] shadow-[inset_3px_0_0_0_rgba(0,212,170,0.6)]'
                  : 'text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.06)]'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
