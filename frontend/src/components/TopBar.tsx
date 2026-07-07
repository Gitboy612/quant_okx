import { useState, useEffect } from 'react'
import { listAccounts } from '../api/accounts'
import Dropdown from './Dropdown'
import type { Account } from '../types'

interface TopBarProps {
  selectedAccountId: number | null
  onAccountChange: (id: number | null) => void
}

export default function TopBar({ selectedAccountId, onAccountChange }: TopBarProps) {
  const [accounts, setAccounts] = useState<Account[]>([])

  useEffect(() => {
    listAccounts().then((res) => setAccounts(res.data)).catch(() => {})
  }, [])

  const accountOptions = [
    { value: '', label: '全部账户' },
    ...accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.trade_mode})` })),
  ]

  return (
    <div className="h-14 border-b border-[#1E1E28] flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[#6B6B7B]">账户</span>
        <Dropdown
          options={accountOptions}
          value={selectedAccountId ?? ''}
          onChange={(v) => onAccountChange(v ? Number(v) : null)}
        />
      </div>
      <div className="text-xs text-[#6B6B7B]">
        数据实时刷新中
      </div>
    </div>
  )
}
