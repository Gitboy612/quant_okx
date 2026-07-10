import { useState, useRef, useEffect, useCallback, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
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
  minPanelWidth?: number
  panelWidth?: number
}

export default function Dropdown({
  options,
  value,
  onChange,
  className = '',
  placeholder,
  minPanelWidth,
  panelWidth,
}: DropdownProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({})
  const selected = options.find((o) => o.value === value)

  const computePanelStyle = useCallback(() => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    let width: number
    if (typeof panelWidth === 'number') {
      width = panelWidth
    } else if (typeof minPanelWidth === 'number') {
      width = Math.max(rect.width, minPanelWidth)
    } else {
      width = rect.width
    }
    setPanelStyle({
      position: 'fixed',
      left: rect.left,
      top: rect.bottom + 4,
      width,
      zIndex: 9999,
    })
  }, [panelWidth, minPanelWidth])

  const handleToggle = () => {
    if (!open) {
      computePanelStyle()
    }
    setOpen(!open)
  }

  // 监听 scroll / resize，使面板跟随触发器位置
  useEffect(() => {
    if (!open) return
    computePanelStyle()
    const handle = () => computePanelStyle()
    window.addEventListener('scroll', handle, true)
    window.addEventListener('resize', handle)
    return () => {
      window.removeEventListener('scroll', handle, true)
      window.removeEventListener('resize', handle)
    }
  }, [open, computePanelStyle])

  // 点击外部关闭（兼容 Portal：面板在 body 上，需同时判断 panelRef）
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!open) return
      const target = e.target as Node
      if (containerRef.current && containerRef.current.contains(target)) return
      if (panelRef.current && panelRef.current.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={handleToggle}
        className="flex items-center gap-2 bg-[rgba(12,18,38,0.65)] border border-[rgba(0,212,170,0.08)] rounded-lg px-3 py-2 text-sm text-[#EDF0F7] hover:border-[rgba(0,212,170,0.18)] transition-all duration-300 w-full justify-between hover:shadow-[0_0_15px_rgba(0,212,170,0.06)]"
      >
        <span className={selected ? 'text-[#EDF0F7]' : 'text-[#7B86A2]'}>
          {selected ? selected.label : (placeholder || '请选择')}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#7B86A2] transition-transform duration-300 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open &&
        createPortal(
          <div
            ref={panelRef}
            style={panelStyle}
            className="bg-[rgba(10,15,30,0.85)] border border-[rgba(0,212,170,0.1)] rounded-lg shadow-[0_0_30px_rgba(0,0,0,0.5),0_0_15px_rgba(0,212,170,0.05)] max-h-60 overflow-y-auto py-1"
          >
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
          </div>,
          document.body
        )}
    </div>
  )
}
