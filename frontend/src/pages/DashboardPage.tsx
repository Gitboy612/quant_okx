import { useEffect, useState, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, Clock } from 'lucide-react'
import { getPnlSummary, listPnlRecords } from '../api/pnl'
import { listInstances, listApiCallLogs } from '../api/strategies'
import { listOrders } from '../api/orders'
import { listAccounts, getAccountBalance } from '../api/accounts'
import { getSettings } from '../api/settings'
import KpiCard from '../components/KpiCard'
import PnLChart from '../components/PnLChart'
import StatusBadge from '../components/StatusBadge'
import DataTable from '../components/DataTable'
import type { PnlSummary, PnlRecord, StrategyInstance, Order, AssetBalance, ApiCallLogItem, Account } from '../types'

export default function DashboardPage() {
  const [summary, setSummary] = useState<PnlSummary | null>(null)
  const [pnlRecords, setPnlRecords] = useState<PnlRecord[]>([])
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [assets, setAssets] = useState<AssetBalance[]>([])
  const [totalEquity, setTotalEquity] = useState(0)
  const [apiLogs, setApiLogs] = useState<ApiCallLogItem[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)
  const [assetLoading, setAssetLoading] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)
  const [refreshInterval, setRefreshInterval] = useState<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const selectedAccount = accounts.find((a) => a.id === selectedAccountId)

  const loadBaseData = useCallback(() => {
    getPnlSummary().then((res) => setSummary(res.data)).catch(() => {})
    listPnlRecords({ limit: 200 }).then((res) => setPnlRecords(res.data)).catch(() => {})
    listInstances().then((res) => setInstances(res.data)).catch(() => {})
    listOrders({ limit: 10 }).then((res) => setOrders(res.data)).catch(() => {})
    listApiCallLogs({ limit: 50 }).then((res) => setApiLogs(res.data)).catch(() => {})
  }, [])

  const loadAssets = useCallback((accountId: number) => {
    setAssetLoading(true)
    getAccountBalance(accountId).then((br) => {
      setTotalEquity(br.data.total_equity)
      setAssets(br.data.assets)
      setLastRefresh(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
    }).catch(() => {}).finally(() => setAssetLoading(false))
  }, [])

  useEffect(() => {
    loadBaseData()

    listAccounts().then((res) => {
      const accts: Account[] = res.data
      setAccounts(accts)
      if (accts.length > 0) {
        setSelectedAccountId(accts[0].id)
        loadAssets(accts[0].id)
      }
    }).catch(() => {})

    getSettings().then((res) => {
      const interval = parseInt(res.data.refresh_interval, 10) || 0
      setRefreshInterval(interval)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (refreshInterval > 0 && selectedAccountId) {
      timerRef.current = setInterval(() => {
        loadAssets(selectedAccountId)
        loadBaseData()
      }, refreshInterval * 1000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [refreshInterval, selectedAccountId, loadAssets, loadBaseData])

  const handleAccountChange = (id: number) => {
    setSelectedAccountId(id)
    loadAssets(id)
  }

  const handleRefreshAssets = () => {
    if (selectedAccountId) loadAssets(selectedAccountId)
  }

  const orderColumns = [
    {
      key: 'created_at', header: '时间',
      render: (o: Order) => new Date(o.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    },
    { key: 'symbol', header: '交易对' },
    {
      key: 'side', header: '方向',
      render: (o: Order) => (
        <span className={o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4757]'}>
          {o.side === 'buy' ? '买入' : o.side === 'sell' ? '卖出' : o.side}
        </span>
      ),
    },
    { key: 'price', header: '价格', render: (o: Order) => o.price?.toFixed(4) ?? '-' },
    { key: 'quantity', header: '数量' },
    { key: 'status', header: '状态' },
  ]

  const apiLogColumns = [
    { key: 'created_at', header: '时间', render: (l: ApiCallLogItem) => new Date(l.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) },
    { key: 'method', header: '方法' },
    { key: 'endpoint', header: '端点', render: (l: ApiCallLogItem) => l.endpoint?.split('?')[0] ?? '', className: 'font-mono text-xs max-w-[200px] truncate' },
    { key: 'response_code', header: '响应码' },
    { key: 'status', header: '状态', render: (l: ApiCallLogItem) => (
      <span className={l.status === 'success' ? 'text-[#00D4AA]' : 'text-[#FF4757]'}>{l.status}</span>
    )},
  ]

  return (
    <div className="space-y-6">
      <h2 className="text-sm font-medium text-[#E8E8ED]">仪表盘</h2>

      <motion.div
        initial="hidden"
        animate="visible"
        variants={{ visible: { transition: { staggerChildren: 0.1 } }, hidden: {} }}
        className="grid grid-cols-4 gap-4"
      >
        <KpiCard label="总权益" value={(totalEquity || summary?.latest_equity) ?? 0} prefix="$" accent="neutral" />
        <KpiCard label="未实现盈亏" value={summary?.total_unrealized_pnl ?? 0} prefix="$" accent={summary && summary.total_unrealized_pnl >= 0 ? 'profit' : 'loss'} />
        <KpiCard label="已实现盈亏" value={summary?.total_realized_pnl ?? 0} prefix="$" accent={summary && summary.total_realized_pnl >= 0 ? 'profit' : 'loss'} />
        <KpiCard label="活跃策略" value={instances.filter((i) => i.status === 'running').length} accent="neutral" decimals={0} />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs text-[#6B6B7B] uppercase tracking-wide">账户资产</h3>
          <div className="flex items-center gap-3">
            {accounts.length > 1 && (
              <select
                value={selectedAccountId ?? ''}
                onChange={(e) => handleAccountChange(Number(e.target.value))}
                className="bg-[#0C0C14] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] transition-colors"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            )}
            {selectedAccount && (
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase border ${selectedAccount.trade_mode === 'demo' ? 'text-[#F0A500] border-[#F0A500]/30 bg-[#F0A500]/10' : 'text-[#00D4AA] border-[#00D4AA]/30 bg-[#00D4AA]/10'}`}>
                {selectedAccount.trade_mode === 'demo' ? '模拟盘' : '实盘'}
              </span>
            )}
            {lastRefresh && (
              <span className="text-[10px] text-[#6B6B7B] flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {lastRefresh}
              </span>
            )}
            {refreshInterval > 0 && (
              <span className="text-[10px] text-[#6B6B7B]/60">{refreshInterval}s 自动刷新</span>
            )}
            <button
              onClick={handleRefreshAssets}
              disabled={assetLoading}
              className="flex items-center gap-1 border border-[#1E1E28] text-[#6B6B7B] rounded-md px-2 py-1 text-xs hover:bg-[#1A1A24] hover:text-[#E8E8ED] transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${assetLoading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>

        {accounts.length === 0 ? (
          <p className="text-sm text-[#6B6B7B]">请先添加账户</p>
        ) : assets.length === 0 ? (
          <p className="text-sm text-[#6B6B7B]">{assetLoading ? '加载中...' : '暂无资产数据'}</p>
        ) : (
          <div className="grid grid-cols-5 gap-2">
            {assets.map((a) => (
              <div key={a.ccy} className="bg-[#0C0C14] rounded-md p-3 border border-[#1E1E28]/50">
                <div className="text-xs font-mono text-[#E8E8ED] font-bold">{a.ccy}</div>
                <div className="text-sm font-mono text-[#6B6B7B] mt-1">{a.equity.toFixed(4)}</div>
                <div className="text-[10px] text-[#6B6B7B]/60">
                  可用 {a.avail.toFixed(4)}
                  {a.frozen > 0 ? ` | 冻结 ${a.frozen.toFixed(4)}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </motion.div>

      <div className="flex gap-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="flex-1 bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 h-72"
        >
          <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">盈亏曲线</h3>
          <PnLChart data={pnlRecords} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="w-80 bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
        >
          <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">策略状态</h3>
          <div className="space-y-2">
            {instances.length === 0 ? (
              <p className="text-sm text-[#6B6B7B]">暂无策略实例</p>
            ) : (
              instances.map((inst) => (
                <div key={inst.id} className="flex items-center justify-between py-2 border-b border-[#1E1E28]/50 last:border-0">
                  <div>
                    <div className="text-sm font-medium">{inst.name}</div>
                    <div className="text-xs text-[#6B6B7B]">{inst.symbol}</div>
                  </div>
                  <StatusBadge status={inst.status} />
                </div>
              ))
            )}
          </div>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">最近交易</h3>
        <DataTable columns={orderColumns} data={orders} keyField="id" />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.65 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">OKX API 调用日志</h3>
        <DataTable columns={apiLogColumns} data={apiLogs.slice(0, 20)} keyField="id" />
      </motion.div>
    </div>
  )
}
