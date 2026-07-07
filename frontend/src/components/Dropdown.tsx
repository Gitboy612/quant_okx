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
        className="flex items-center gap-2 bg-[#14141A] border border-[#1E1E28] rounded-lg px-3 py-2 text-sm text-[#E8E8ED] hover:border-[#2A2A3A] transition-colors min-w-[120px] justify-between"
      >
        <span className={selected ? 'text-[#E8E8ED]' : 'text-[#6B6B7B]'}>
          {selected ? selected.label : (placeholder || '请选择')}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#6B6B7B] transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#1A1A24] border border-[#2A2A3A] rounded-lg shadow-lg shadow-black/40 overflow-hidden py-1">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                onChange(opt.value)
                setOpen(false)
              }}
              className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                opt.value === value
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA]'
                  : 'text-[#E8E8ED] hover:bg-[#14141A]'
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