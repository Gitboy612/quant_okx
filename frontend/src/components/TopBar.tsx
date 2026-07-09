import { useState, useEffect } from 'react'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import Dropdown from './Dropdown'
import type { Account } from '../types'
import { Wifi, ChevronRight } from 'lucide-react'

interface TopBarProps {
  selectedAccountId: number | null
  onAccountChange: (id: number | null) => void
}

export default function TopBar({ selectedAccountId, onAccountChange }: TopBarProps) {
  const { accounts } = useSelectedAccount()
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const accountOptions = [
    { value: '', label: '全部账户' },
    ...accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.trade_mode})` })),
  ]

  return (
    <div className="h-12 flex items-center justify-between px-6 shrink-0 relative z-20 border-b border-[rgba(0,212,170,0.06)] bg-[#050711]">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-[#7B86A2]">
          <span className="text-[10px] uppercase tracking-wider">账户</span>
          <ChevronRight className="w-3 h-3 opacity-50" />
          <Dropdown
            options={accountOptions}
            value={selectedAccountId ?? ''}
            onChange={(v) => onAccountChange(v ? Number(v) : null)}
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="text-[12px] font-mono text-[#7B86A2] tabular-nums">
          {time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>

        <div className="flex items-center gap-1.5">
          <Wifi className="w-3 h-3 text-[#00D4AA]/60" />
          <span className="text-[10px] text-[#00D4AA]/60">已连接</span>
          <span className="w-1.5 h-1.5 rounded-full bg-[#00D4AA] animate-pulse" />
        </div>
      </div>
    </div>
  )
}
