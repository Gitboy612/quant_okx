import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Plus, Trash2, Eye, EyeOff } from 'lucide-react'
import { listAccounts, createAccount, deleteAccount } from '../api/accounts'
import Modal from '../components/Modal'
import Dropdown from '../components/Dropdown'
import { TableSkeleton } from '../components/Skeleton'
import type { Account } from '../types'

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [createSuccess, setCreateSuccess] = useState('')
  const [showSecret, setShowSecret] = useState<Record<number, boolean>>({})
  const [tradeMode, setTradeMode] = useState('demo')

  useEffect(() => {
    listAccounts().then((res) => setAccounts(res.data)).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleCreate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setCreating(true)
    setCreateError('')
    setCreateSuccess('')
    try {
      const res = await createAccount({
        name: form.get('name') as string,
        api_key: form.get('api_key') as string,
        secret_key: form.get('secret_key') as string,
        passphrase: (form.get('passphrase') as string) || undefined,
        trade_mode: (form.get('trade_mode') as string) || 'demo',
      })
      setCreateSuccess(res.data.message || '账户验证通过，已添加')
      setTimeout(() => setShowCreate(false), 1500)
      listAccounts().then((res) => setAccounts(res.data))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateError(detail || '验证失败')
    }
    finally { setCreating(false) }
  }

  const handleDelete = async (id: number) => {
    await deleteAccount(id)
    listAccounts().then((res) => setAccounts(res.data))
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">账户管理</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-4 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors"
        >
          <Plus className="w-4 h-4" /> 添加账户
        </button>
      </div>

      <div className="space-y-2">
        {loading ? (
          <div className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-6">
            <TableSkeleton rows={3} cols={3} />
          </div>
        ) : accounts.length === 0 ? (
          <div className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-12 text-center text-[#6B6B7B] text-sm">
            暂无OKX账户，点击上方按钮添加
          </div>
        ) : (
          accounts.map((acc, i) => (
            <motion.div
              key={acc.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-4 flex items-center gap-4"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium">{acc.name}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${acc.trade_mode === 'live' ? 'bg-[#FF4757]/10 text-[#FF4757]' : 'bg-[#6B6B7B]/10 text-[#6B6B7B]'}`}>
                    {acc.trade_mode === 'live' ? '真实' : '模拟'}
                  </span>
                  {!acc.is_active && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-[#F0A500]/10 text-[#F0A500]">已停用</span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-[#6B6B7B] font-mono">
                    API Key: {acc.api_key_masked}
                  </span>
                  {showSecret[acc.id] && (
                    <span className="text-xs text-[#6B6B7B] font-mono">
                      (已掩码存储，不可查看原始)
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => setShowSecret((s) => ({ ...s, [acc.id]: !s[acc.id] }))}
                className="p-2 rounded-md hover:bg-[#1A1A24] text-[#6B6B7B] transition-colors"
              >
                {showSecret[acc.id] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
              <button
                onClick={() => handleDelete(acc.id)}
                className="p-2 rounded-md hover:bg-[#FF4757]/10 text-[#6B6B7B] hover:text-[#FF4757] transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </motion.div>
          ))
        )}
      </div>

      <Modal open={showCreate} onClose={() => { setShowCreate(false); setCreateError(''); setCreateSuccess(''); setTradeMode('demo') }} title="添加 OKX 账户">
        <form onSubmit={handleCreate} className="space-y-3">
          {createError && (
            <div className="bg-[#FF4757]/10 text-[#FF4757] text-xs p-3 rounded-md border border-[#FF4757]/20">{createError}</div>
          )}
          {createSuccess && (
            <div className="bg-[#00D4AA]/10 text-[#00D4AA] text-xs p-3 rounded-md border border-[#00D4AA]/20">{createSuccess}</div>
          )}
          <div>
            <label className="text-xs text-[#6B6B7B]">账户名称</label>
            <input name="name" required placeholder="我的OKX账户" className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]" />
          </div>
          <div>
            <label className="text-xs text-[#6B6B7B]">API Key</label>
            <input name="api_key" required placeholder="输入 API Key" className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono" />
          </div>
          <div>
            <label className="text-xs text-[#6B6B7B]">Secret Key</label>
            <input name="secret_key" required type="password" placeholder="输入 Secret Key" className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono" />
          </div>
          <div>
            <label className="text-xs text-[#6B6B7B]">Passphrase (可选)</label>
            <input name="passphrase" type="password" placeholder="输入 Passphrase" className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono" />
          </div>
          <div>
            <label className="text-xs text-[#6B6B7B]">交易模式</label>
            <input type="hidden" name="trade_mode" value={tradeMode} />
            <Dropdown
              options={[{ value: 'demo', label: '模拟交易 (Demo)' }, { value: 'live', label: '真实交易 (Live)' }]}
              value={tradeMode}
              onChange={(v) => setTradeMode(String(v))}
              className="mt-1 w-full"
            />
          </div>
          <p className="text-xs text-[#6B6B7B] leading-relaxed">
            API Key 将使用 AES-256 加密存储，仅用于程序化交易调用。建议创建仅含交易权限的 API Key。
          </p>
          <button
            type="submit"
            disabled={creating}
            className="w-full bg-[#00D4AA] text-[#0A0A0F] rounded-md py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
          >
            {creating ? '添加中...' : '添加账户'}
          </button>
        </form>
      </Modal>
    </motion.div>
  )
}
