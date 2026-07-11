import { useState, useEffect } from 'react'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import Dropdown from './Dropdown'
import type { Account } from '../types'
import { Wifi, ChevronRight, Gauge, Menu } from 'lucide-react'
import { getRateLimitStatus, type RateLimitStatus } from '../api/settings'

interface TopBarProps {
  selectedAccountId: number | null
  onAccountChange: (id: number | null) => void
  onMenuClick: () => void
}

export default function TopBar({ selectedAccountId, onAccountChange, onMenuClick }: TopBarProps) {
  const { accounts } = useSelectedAccount()
  const [time, setTime] = useState(new Date())
  const [rateLimit, setRateLimit] = useState<RateLimitStatus | null>(null)

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    let cancelled = false
    const fetchRateLimit = () => {
      getRateLimitStatus()
        .then((res) => {
          if (!cancelled) setRateLimit(res.data)
        })
        .catch(() => {})
    }
    fetchRateLimit()
    const interval = setInterval(fetchRateLimit, 10000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const accountOptions = [
    { value: '', label: '全部账户' },
    ...accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.trade_mode})` })),
  ]

  const pct = rateLimit?.percentage
  const isLow = pct !== null && pct !== undefined && pct < 20
  const hasData = pct !== null && pct !== undefined

  return (
    <div className="h-12 flex items-center justify-between px-4 md:px-6 shrink-0 relative z-20 border-b border-[rgba(0,212,170,0.06)] bg-[#050711]">
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          className="md:hidden text-[#7B86A2] hover:text-[#EDF0F7] transition-colors"
          aria-label="打开菜单"
        >
          <Menu className="w-5 h-5" />
        </button>
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

      <div className="flex items-center gap-2 md:gap-4">
        {/* API 限流配额状态 */}
        <div className="flex items-center gap-1.5" title={hasData ? `剩余 ${rateLimit?.remaining} / ${rateLimit?.limit}` : '暂无限流数据'}>
          <Gauge className={`w-3 h-3 ${isLow ? 'text-red-400' : hasData ? 'text-[#00D4AA]/60' : 'text-[#7B86A2]/40'}`} />
          <span className={`text-[10px] tabular-nums ${isLow ? 'text-red-400' : hasData ? 'text-[#00D4AA]/60' : 'text-[#7B86A2]/40'}`}>
            {hasData ? `API ${pct}%` : 'API --'}
          </span>
          {isLow && <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />}
        </div>

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
