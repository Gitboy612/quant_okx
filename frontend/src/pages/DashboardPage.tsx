import { useEffect, useState, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, Clock } from 'lucide-react'
import { getPnlSummary, listPnlRecords } from '../api/pnl'
import { listInstances, listApiCallLogs } from '../api/strategies'
import { listOrders } from '../api/orders'
import { getAccountBalance, getPositions } from '../api/accounts'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import { getSettings } from '../api/settings'
import { formatInstId } from '../utils/instId'
import KpiCard from '../components/KpiCard'
import PnLChart, { type TimeRange } from '../components/PnLChart'
import StatusBadge from '../components/StatusBadge'
import DataTable from '../components/DataTable'
import type { PnlSummary, PnlRecord, StrategyInstance, Order, AssetBalance, Position, ApiCallLogItem } from '../types'

export default function DashboardPage() {
  const [summary, setSummary] = useState<PnlSummary | null>(null)
  const [pnlRecords, setPnlRecords] = useState<PnlRecord[]>([])
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [liveOrders, setLiveOrders] = useState<Order[]>([])
  const [assets, setAssets] = useState<AssetBalance[]>([])
  const [totalEquity, setTotalEquity] = useState<number | null>(null)
  const [apiLogs, setApiLogs] = useState<ApiCallLogItem[]>([])
  const { accounts, selectedAccountId, selectAccount } = useSelectedAccount()
  const [selectedStrategyId, setSelectedStrategyId] = useState<number>(0)
  const [assetLoading, setAssetLoading] = useState(false)
  const [positions, setPositions] = useState<Position[]>([])
  const [positionsLoading, setPositionsLoading] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)
  const [refreshInterval, setRefreshInterval] = useState<number>(0)
  const [timeRange, setTimeRange] = useState<TimeRange>('all')
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [ordersLoading, setOrdersLoading] = useState(true)
  const [logsLoading, setLogsLoading] = useState(true)
  const [kpiLoading, setKpiLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const selectedAccount = accounts.find((a) => a.id === selectedAccountId)

  const computeStartTime = (range: TimeRange): string | undefined => {
    const now = new Date()
    if (range === '24h') {
      const start = new Date(now.getTime() - 24 * 60 * 60 * 1000)
      return start.toISOString()
    }
    if (range === '7d') {
      const start = new Date(now)
      start.setHours(0, 0, 0, 0)
      start.setDate(start.getDate() - 7)
      return start.toISOString()
    }
    if (range === '30d') {
      const start = new Date(now)
      start.setHours(0, 0, 0, 0)
      start.setDate(start.getDate() - 30)
      return start.toISOString()
    }
    // all: 不传 start_time
    return undefined
  }

  const loadBaseData = useCallback(() => {
    const sid = selectedStrategyId || undefined
    getPnlSummary().then((res) => { setSummary(res.data); setSummaryLoading(false); setKpiLoading(false) }).catch(() => { setSummaryLoading(false); setKpiLoading(false) })
    const startTime = computeStartTime(timeRange)
    listPnlRecords({
      ...(sid ? { strategy_instance_id: sid } : {}),
      ...(startTime ? { start_time: startTime } : {}),
    }).then((res) => setPnlRecords(res.data)).catch(() => {})
    listInstances().then((res) => setInstances(res.data)).catch(() => {})
    listOrders(sid ? { strategy_instance_id: sid, status: 'filled', limit: 10, sort_by: 'updated_at' } : { status: 'filled', limit: 10, sort_by: 'updated_at' }).then((res) => {
      setOrders(res.data)
      setOrdersLoading(false)
    }).catch(() => setOrdersLoading(false))
    listOrders(sid ? { strategy_instance_id: sid, status: 'live', limit: 50 } : { status: 'live', limit: 50 }).then((res) => {
      setLiveOrders(res.data)
    }).catch(() => {})
    listApiCallLogs(sid ? { strategy_instance_id: sid, limit: 50 } : { limit: 50 }).then((res) => { setApiLogs(res.data); setLogsLoading(false) }).catch(() => setLogsLoading(false))
  }, [selectedStrategyId, timeRange])

  const loadAssets = useCallback((accountId: number) => {
    setAssetLoading(true)
    setPositionsLoading(true)
    getAccountBalance(accountId).then((br) => {
      setTotalEquity(br.data.total_equity)
      if (br.data.assets) setAssets(br.data.assets)
      setLastRefresh(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
    }).catch(() => {}).finally(() => setAssetLoading(false))
    getPositions(accountId).then((res) => {
      setPositions(res.data)
    }).catch(() => {}).finally(() => setPositionsLoading(false))
  }, [])

  useEffect(() => {
    loadBaseData()
    getSettings().then((res) => {
      const interval = parseInt(res.data.refresh_interval, 10) || 0
      setRefreshInterval(interval)
    }).catch(() => {})
  }, [])

  const hasRunning = instances.some(inst => inst.status === 'running')
  const effectiveInterval = hasRunning ? (refreshInterval as number) * 2 : (refreshInterval as number)

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (refreshInterval > 0 && selectedAccountId) {
      timerRef.current = setInterval(() => {
        loadAssets(selectedAccountId)
        loadBaseData()
      }, effectiveInterval * 1000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [effectiveInterval, refreshInterval, selectedAccountId, loadAssets, loadBaseData])

  const handleAccountChange = (id: number) => {
    selectAccount(id)
    loadAssets(id)
  }

  useEffect(() => {
    if (selectedAccountId) {
      loadAssets(selectedAccountId)
    }
  }, [selectedAccountId, loadAssets])

  const handleRefreshAssets = () => {
    if (selectedAccountId) loadAssets(selectedAccountId)
  }

  const orderColumns = [
    {
      key: 'created_at', header: '时间',
      render: (o: Order) => new Date(o.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    },
    { key: 'symbol', header: '交易对', render: (o: Order) => formatInstId(o.symbol) },
    {
      key: 'side', header: '方向',
      render: (o: Order) => (
        <span className={o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}>
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
      <span className={l.status === 'success' || l.status === 'info' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}>{l.status}</span>
    )},
    { key: 'response_body', header: '错误描述', render: (l: ApiCallLogItem) => {
      try {
        const parsed = JSON.parse(l.response_body || '{}')
        if (parsed._error_desc) return <span className="text-[#FF4060] text-xs">{parsed._error_desc}</span>
        if (l.status === 'error' || l.status === 'exception') {
          const msg = parsed.msg || parsed.detail || ''
          return <span className="text-[#FF4060] text-xs max-w-[180px] truncate block">{msg}</span>
        }
      } catch {}
      return <span className="text-[#7B86A2] text-xs">-</span>
    }},
  ]

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[#EDF0F7]">仪表盘</h2>
          <p className="text-xs text-[#7B86A2] mt-0.5">实时监控量化交易状态</p>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-[#505C78]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00D4AA] animate-pulse" />
          LIVE
        </div>
      </div>

      {/* KPI Cards */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={{ visible: { transition: { staggerChildren: 0.08 } }, hidden: {} }}
        className="grid grid-cols-4 gap-4"
      >
        <KpiCard label="总权益" value={totalEquity ?? summary?.latest_equity ?? 0} prefix="$" accent="neutral" loading={kpiLoading} />
        <KpiCard label="未实现盈亏" value={summary?.total_unrealized_pnl ?? 0} prefix="$" accent={summary && summary.total_unrealized_pnl >= 0 ? 'profit' : 'loss'} loading={kpiLoading} />
        <KpiCard label="已实现盈亏" value={summary?.total_realized_pnl ?? 0} prefix="$" accent={summary && summary.total_realized_pnl >= 0 ? 'profit' : 'loss'} loading={kpiLoading} />
        <KpiCard label="活跃策略" value={instances.filter((i) => i.status === 'running').length} accent="neutral" decimals={0} loading={kpiLoading} />
      </motion.div>

      {/* Account Assets */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="glass-panel p-5"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold">账户资产</h3>
          <div className="flex items-center gap-3">
            {selectedAccount && (
              <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold uppercase border ${
                selectedAccount.trade_mode === 'demo'
                  ? 'badge-warning'
                  : 'badge-profit'
              }`}>
                {selectedAccount.trade_mode === 'demo' ? '模拟盘' : '实盘'}
              </span>
            )}
            {lastRefresh && (
              <span className="text-[10px] text-[#7B86A2] flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {lastRefresh}
              </span>
            )}
            {refreshInterval > 0 && (
              <span className="text-[10px] text-[#505C78]">
                {effectiveInterval}s
                {hasRunning && <span className="text-[#F0A500] ml-0.5">(延长)</span>}
              </span>
            )}
            <button
              onClick={handleRefreshAssets}
              disabled={assetLoading}
              className="btn-ghost flex items-center gap-1.5 px-2.5 py-1.5 text-xs disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${assetLoading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>

        {accounts.length === 0 ? (
          <p className="text-sm text-[#7B86A2]">请先添加账户</p>
        ) : assets.length === 0 ? (
          <p className="text-sm text-[#7B86A2]">{assetLoading ? '加载中...' : '暂无资产数据'}</p>
        ) : (
          <div className="grid grid-cols-5 gap-2">
            {assets.map((a, i) => (
              <motion.div
                key={a.ccy}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 + i * 0.03 }}
                className="glass-card p-3"
              >
                <div className="text-xs font-mono text-[#EDF0F7] font-bold">{a.ccy}</div>
                <div className="text-sm font-mono text-[#7B86A2] mt-1">{a.equity.toFixed(4)}</div>
                <div className="text-[10px] text-[#505C78] mt-0.5">
                  可用 {a.avail.toFixed(4)}
                  {a.frozen > 0 ? ` | 冻结 ${a.frozen.toFixed(4)}` : ''}
                </div>
              </motion.div>
            ))}
          </div>
        )}

        {/* Positions */}
        {positions.length > 0 && (
          <div className="mt-4 pt-4 border-t border-[rgba(0,212,170,0.06)]">
            <h4 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">当前持仓</h4>
            {/* Header row */}
            <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
              <span className="w-28">交易对</span>
              <span className="w-12 text-center">方向</span>
              <span className="w-20 text-right">数量</span>
              <span className="w-20 text-right">标记价</span>
              <span className="w-24 text-right">未实现盈亏</span>
            </div>
            <div className="grid grid-cols-1 gap-1.5">
              {positions.map((p, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[rgba(10,15,30,0.5)] text-xs">
                  <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(p.instId)}</span>
                  <span className={`w-12 text-center font-semibold ${p.posSide === 'long' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                    {p.posSide === 'long' ? '多' : p.posSide === 'short' ? '空' : p.posSide}
                  </span>
                  <span className="font-mono text-[#EDF0F7] w-20 text-right">{Number(p.pos).toFixed(4)}</span>
                  <span className="font-mono text-[#7B86A2] w-20 text-right">${Number(p.markPx).toFixed(2)}</span>
                  <span className={`font-mono w-24 text-right font-semibold ${Number(p.upl) >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                    ${Number(p.upl).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </motion.div>

      {/* Chart + Strategy List */}
      <div className="flex gap-5">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="flex-1 glass-panel p-5 h-72"
        >
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold">盈亏曲线</h3>
            <div className="flex gap-1">
              {(['24h', '7d', '30d', 'all'] as TimeRange[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setTimeRange(r)}
                  className={`px-2.5 py-1 text-[11px] rounded-full font-medium transition-all duration-200 border ${
                    timeRange === r
                      ? 'bg-[#00D4AA] text-[#0A0F1E] border-[#00D4AA]'
                      : 'text-[#7B86A2] border-[#2A3350] hover:text-[#EDF0F7] hover:border-[#505C78]'
                  }`}
                >
                  {r === '24h' ? '过去24小时' : r === '7d' ? '过去7天' : r === '30d' ? '过去30天' : '全部'}
                </button>
              ))}
            </div>
          </div>
          <PnLChart data={pnlRecords} timeRange={timeRange} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="w-80 glass-panel p-5"
        >
          <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">策略列表</h3>
          <div className="space-y-1 max-h-[280px] overflow-y-auto pr-1">
            <button
              onClick={() => setSelectedStrategyId(0)}
              className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all duration-200 ${
                selectedStrategyId === 0
                  ? 'bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.15)] text-[#00D4AA]'
                  : 'text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.04)] border border-transparent'
              }`}
            >
              <div className="font-medium">全部策略</div>
              <div className="text-[11px] mt-0.5 opacity-60">{instances.length} 个实例</div>
            </button>
            {instances.length === 0 ? (
              <p className="text-sm text-[#7B86A2] px-3 py-2">暂无策略实例</p>
            ) : (
              instances.map((inst) => (
                <button
                  key={inst.id}
                  onClick={() => setSelectedStrategyId(inst.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-xl transition-all duration-200 ${
                    selectedStrategyId === inst.id
                      ? 'bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.15)]'
                      : 'border border-transparent hover:bg-[rgba(0,212,170,0.04)]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-sm font-medium ${selectedStrategyId === inst.id ? 'text-[#00D4AA]' : 'text-[#EDF0F7]'}`}>
                      {inst.name}
                    </span>
                    <StatusBadge status={inst.status} />
                  </div>
                  <div className={`text-[11px] mt-0.5 ${selectedStrategyId === inst.id ? 'text-[#00D4AA]/60' : 'text-[#7B86A2]'}`}>
                    {formatInstId(inst.symbol)}
                  </div>
                </button>
              ))
            )}
          </div>
        </motion.div>
      </div>

      {/* Recent Orders */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.55, ease: [0.16, 1, 0.3, 1] }}
        className="glass-panel p-5"
      >
        <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">最近交易</h3>
        <div className="max-h-[400px] overflow-y-auto">
          {ordersLoading ? (
            <div className="flex items-center justify-center py-8 text-[#7B86A2] text-sm">加载中...</div>
          ) : orders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
              <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
              <span>暂无交易记录</span>
              <span className="text-[11px] text-[#505C78]">启动策略后交易记录将在此展示</span>
            </div>
          ) : (
            <DataTable columns={orderColumns} data={orders} keyField="id" />
          )}
        </div>
      </motion.div>

      {/* Live Orders */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="glass-panel p-5"
      >
        <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">未成交委托</h3>
        <div className="max-h-[400px] overflow-y-auto">
          {liveOrders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
              <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
              <span>暂无未成交委托</span>
              <span className="text-[11px] text-[#505C78]">当前没有活跃的挂单</span>
            </div>
          ) : (
            <DataTable columns={orderColumns} data={liveOrders} keyField="id" />
          )}
        </div>
      </motion.div>

      {/* API Logs */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.65, ease: [0.16, 1, 0.3, 1] }}
        className="glass-panel p-5"
      >
        <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">OKX API 调用日志</h3>
        <div className="max-h-[400px] overflow-y-auto">
          {logsLoading ? (
            <div className="flex items-center justify-center py-8 text-[#7B86A2] text-sm">加载中...</div>
          ) : apiLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
              <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
              <span>暂无 API 调用日志</span>
              <span className="text-[11px] text-[#505C78]">策略启动后 API 调用日志将在此展示</span>
            </div>
          ) : (
            <DataTable columns={apiLogColumns} data={apiLogs.slice(0, 20)} keyField="id" />
          )}
        </div>
      </motion.div>
    </div>
  )
}
