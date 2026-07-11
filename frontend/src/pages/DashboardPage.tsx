import { motion } from 'framer-motion'
import { RefreshCw, Clock } from 'lucide-react'
import { useDashboardState } from '../hooks/useDashboardState'
import { formatInstId } from '../utils/instId'
import StatusBadge from '../components/StatusBadge'
import DataTable from '../components/DataTable'
import KpiSummarySection from '../components/dashboard/KpiSummarySection'
import PnLCurveSection from '../components/dashboard/PnLCurveSection'
import PositionsSection from '../components/dashboard/PositionsSection'
import RecentOrdersSection, { orderColumns } from '../components/dashboard/RecentOrdersSection'
import type { ApiCallLogItem } from '../types'

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

export default function DashboardPage() {
  const state = useDashboardState()

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
      <KpiSummarySection
        totalEquity={state.totalEquity}
        summary={state.summary}
        instances={state.instances}
        kpiLoading={state.kpiLoading}
      />

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
            {state.selectedAccount && (
              <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold uppercase border ${
                state.selectedAccount.trade_mode === 'demo'
                  ? 'badge-warning'
                  : 'badge-profit'
              }`}>
                {state.selectedAccount.trade_mode === 'demo' ? '模拟盘' : '实盘'}
              </span>
            )}
            {state.lastRefresh && (
              <span className="text-[10px] text-[#7B86A2] flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {state.lastRefresh}
              </span>
            )}
            {state.refreshInterval > 0 && (
              <span className="text-[10px] text-[#505C78]">
                {state.effectiveInterval}s
                {state.hasRunning && <span className="text-[#F0A500] ml-0.5">(延长)</span>}
              </span>
            )}
            <button
              onClick={state.handleRefreshAssets}
              disabled={state.assetLoading}
              className="btn-ghost flex items-center gap-1.5 px-2.5 py-1.5 text-xs disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${state.assetLoading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>

        {state.accounts.length === 0 ? (
          <p className="text-sm text-[#7B86A2]">请先添加账户</p>
        ) : state.assets.length === 0 ? (
          <p className="text-sm text-[#7B86A2]">{state.assetLoading ? '加载中...' : '暂无资产数据'}</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
            {state.assets.map((a, i) => (
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
        <PositionsSection positions={state.positions} />
      </motion.div>

      {/* Chart + Strategy List */}
      <div className="flex flex-col lg:flex-row gap-5">
        <PnLCurveSection
          pnlRecords={state.pnlRecords}
          timeRange={state.timeRange}
          setTimeRange={state.setTimeRange}
        />

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="w-full lg:w-80 glass-panel p-5"
        >
          <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">策略列表</h3>
          <div className="space-y-1 max-h-[280px] overflow-y-auto pr-1">
            <button
              onClick={() => state.setSelectedStrategyId(0)}
              className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all duration-200 ${
                state.selectedStrategyId === 0
                  ? 'bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.15)] text-[#00D4AA]'
                  : 'text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.04)] border border-transparent'
              }`}
            >
              <div className="font-medium">全部策略</div>
              <div className="text-[11px] mt-0.5 opacity-60">{state.instances.length} 个实例</div>
            </button>
            {state.instances.length === 0 ? (
              <p className="text-sm text-[#7B86A2] px-3 py-2">暂无策略实例</p>
            ) : (
              state.instances.map((inst) => (
                <button
                  key={inst.id}
                  onClick={() => state.setSelectedStrategyId(inst.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-xl transition-all duration-200 ${
                    state.selectedStrategyId === inst.id
                      ? 'bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.15)]'
                      : 'border border-transparent hover:bg-[rgba(0,212,170,0.04)]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-sm font-medium ${state.selectedStrategyId === inst.id ? 'text-[#00D4AA]' : 'text-[#EDF0F7]'}`}>
                      {inst.name}
                    </span>
                    <StatusBadge status={inst.status} />
                  </div>
                  <div className={`text-[11px] mt-0.5 ${state.selectedStrategyId === inst.id ? 'text-[#00D4AA]/60' : 'text-[#7B86A2]'}`}>
                    {formatInstId(inst.symbol)}
                  </div>
                </button>
              ))
            )}
          </div>
        </motion.div>
      </div>

      {/* Recent Orders */}
      <RecentOrdersSection orders={state.orders} ordersLoading={state.ordersLoading} />

      {/* Live Orders */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="glass-panel p-5"
      >
        <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">未成交委托</h3>
        <div className="max-h-[400px] overflow-y-auto">
          {state.liveOrders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
              <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
              <span>暂无未成交委托</span>
              <span className="text-[11px] text-[#505C78]">当前没有活跃的挂单</span>
            </div>
          ) : (
            <DataTable columns={orderColumns} data={state.liveOrders} keyField="id" />
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
          {state.logsLoading ? (
            <div className="flex items-center justify-center py-8 text-[#7B86A2] text-sm">加载中...</div>
          ) : state.apiLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
              <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
              <span>暂无 API 调用日志</span>
              <span className="text-[11px] text-[#505C78]">策略启动后 API 调用日志将在此展示</span>
            </div>
          ) : (
            <DataTable columns={apiLogColumns} data={state.apiLogs.slice(0, 20)} keyField="id" />
          )}
        </div>
      </motion.div>
    </div>
  )
}
