import { useState, useEffect } from 'react'
import { listAccounts } from '../api/accounts'
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

  return (
    <div className="h-14 border-b border-[#1E1E28] flex items-center justify-between px-6 shrink-0">
      <div>
        <span className="text-xs text-[#6B6B7B] mr-2">账户</span>
        <select
          value={selectedAccountId ?? ''}
          onChange={(e) => onAccountChange(e.target.value ? Number(e.target.value) : null)}
          className="bg-[#14141A] border border-[#1E1E28] rounded-md px-3 py-1.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
        >
          <option value="">全部账户</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.trade_mode})
            </option>
          ))}
        </select>
      </div>
      <div className="text-xs text-[#6B6B7B]">
        数据实时刷新中
      </div>
    </div>
  )
}
