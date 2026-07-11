import { useEffect, useState, useMemo, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  PieChart, Pie, Cell, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import { X, ChevronRight } from 'lucide-react'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import {
  getAttributionBySymbol,
  getAttributionByStrategyType,
  getAttributionByPeriod,
  getDrillDown,
} from '../api/analytics'
import { formatInstId } from '../utils/instId'
import { TableSkeleton, ChartSkeleton } from '../components/Skeleton'
import type {
  AttributionBySymbol,
  AttributionByStrategyType,
  AttributionByPeriod,
  DrillDownOrder,
} from '../types'

type TabKey = 'symbol' | 'strategy' | 'period'
type RangePreset = '7' | '30' | '90' | 'custom'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'symbol', label: '按币种' },
  { key: 'strategy', label: '按策略类型' },
  { key: 'period', label: '按时间段' },
]

const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
  { key: '7', label: '7天' },
  { key: '30', label: '30天' },
  { key: '90', label: '90天' },
  { key: 'custom', label: '自定义' },
]

const PIE_COLORS = [
  '#00D4AA', '#3B82F6', '#F0A500', '#FF4060', '#A855F7',
  '#10B981', '#EC4899', '#F59E0B', '#06B6D4', '#8B5CF6',
]

const AXIS_STYLE = { fontSize: 11, fill: '#7B86A2' }
const GRID_STROKE = 'rgba(0,212,170,0.08)'

function toISOStart(d: Date) {
  return d.toISOString().slice(0, 19)
}

function computeRange(preset: RangePreset, customStart: string, customEnd: string) {
  const end = new Date()
  if (preset === 'custom') {
    return {
      start_date: customStart ? `${customStart}T00:00:00` : toISOStart(new Date(Date.now() - 7 * 86400000)),
      end_date: customEnd ? `${customEnd}T23:59:59` : toISOStart(end),
    }
  }
  const days = parseInt(preset, 10)
  const start = new Date(end.getTime() - days * 86400000)
  return { start_date: toISOStart(start), end_date: toISOStart(end) }
}

function fmtNum(v: number, digits = 4) {
  if (v == null || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

function fmtTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

interface DrillState {
  open: boolean
  symbol?: string
  strategy_type?: string
  title: string
}

export default function AnalyticsPage() {
  const { selectedAccountId } = useSelectedAccount()
  const [activeTab, setActiveTab] = useState<TabKey>('symbol')
  const [rangePreset, setRangePreset] = useState<RangePreset>('30')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')

  const [symbolData, setSymbolData] = useState<AttributionBySymbol[]>([])
  const [strategyData, setStrategyData] = useState<AttributionByStrategyType[]>([])
  const [periodData, setPeriodData] = useState<AttributionByPeriod[]>([])
  const [loading, setLoading] = useState(false)

  const [drill, setDrill] = useState<DrillState>({ open: false, title: '' })
  const [drillOrders, setDrillOrders] = useState<DrillDownOrder[]>([])
  const [drillLoading, setDrillLoading] = useState(false)

  const { start_date, end_date } = useMemo(
    () => computeRange(rangePreset, customStart, customEnd),
    [rangePreset, customStart, customEnd],
  )

  const fetchData = useCallback(() => {
    if (selectedAccountId == null) return
    setLoading(true)
    const baseParams = { account_id: selectedAccountId, start_date, end_date }
    const fetcher =
      activeTab === 'symbol'
        ? getAttributionBySymbol(baseParams)
        : activeTab === 'strategy'
          ? getAttributionByStrategyType(baseParams)
          : getAttributionByPeriod({ ...baseParams, period: 'daily' })
    fetcher
      .then((res) => {
        if (activeTab === 'symbol') setSymbolData(res.data as AttributionBySymbol[])
        else if (activeTab === 'strategy') setStrategyData(res.data as AttributionByStrategyType[])
        else setPeriodData(res.data as AttributionByPeriod[])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [activeTab, selectedAccountId, start_date, end_date])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const openDrillDown = (params: { symbol?: string; strategy_type?: string; title: string }) => {
    if (selectedAccountId == null) return
    setDrill({ open: true, ...params })
    setDrillLoading(true)
    getDrillDown({
      account_id: selectedAccountId,
      start_date,
      end_date,
      symbol: params.symbol,
      strategy_type: params.strategy_type,
    })
      .then((res) => setDrillOrders(res.data))
      .catch(() => setDrillOrders([]))
      .finally(() => setDrillLoading(false))
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      {/* Header: title + range selector */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-[#EDF0F7]">PnL 归因分析</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-[#7B86A2]">时间范围</span>
          <div className="flex items-center gap-1 bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md p-0.5">
            {RANGE_PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => setRangePreset(p.key)}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  rangePreset === p.key
                    ? 'bg-[rgba(0,212,170,0.15)] text-[#00D4AA]'
                    : 'text-[#7B86A2] hover:text-[#EDF0F7]'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {rangePreset === 'custom' && (
            <div className="flex items-center gap-1">
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md px-2 py-1 text-xs text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA]"
              />
              <span className="text-xs text-[#7B86A2]">~</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md px-2 py-1 text-xs text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA]"
              />
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-xl p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-xs font-medium rounded-lg transition-all ${
              activeTab === t.key
                ? 'bg-[rgba(0,212,170,0.15)] text-[#00D4AA]'
                : 'text-[#7B86A2] hover:text-[#EDF0F7]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {selectedAccountId == null ? (
        <div className="glass-card p-12 text-center text-[#7B86A2] text-sm">请先选择账户</div>
      ) : loading ? (
        <div className="glass-card p-4">
          <ChartSkeleton height={280} />
        </div>
      ) : (
        <>
          {activeTab === 'symbol' && (
            <SymbolView data={symbolData} onDrillDown={(symbol) => openDrillDown({ symbol, title: `币种 ${formatInstId(symbol)} 订单明细` })} />
          )}
          {activeTab === 'strategy' && (
            <StrategyView data={strategyData} onDrillDown={(strategy_type) => openDrillDown({ strategy_type, title: `策略类型 ${strategy_type} 订单明细` })} />
          )}
          {activeTab === 'period' && <PeriodView data={periodData} />}
        </>
      )}

      {/* Drill-down panel */}
      {drill.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6" onClick={() => setDrill((d) => ({ ...d, open: false }))}>
          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="glass-card w-full max-w-5xl max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-[rgba(0,212,170,0.08)]">
              <h3 className="text-sm font-medium text-[#EDF0F7]">{drill.title}</h3>
              <button onClick={() => setDrill((d) => ({ ...d, open: false }))} className="text-[#7B86A2] hover:text-[#EDF0F7]">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="overflow-auto">
              {drillLoading ? (
                <div className="p-6">
                  <TableSkeleton rows={6} cols={6} />
                </div>
              ) : drillOrders.length === 0 ? (
                <div className="p-12 text-center text-[#7B86A2] text-sm">暂无符合条件的订单</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0">
                    <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.95)]">
                      <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">时间</th>
                      <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">交易对</th>
                      <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">方向</th>
                      <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">成交价</th>
                      <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">成交量</th>
                      <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">手续费</th>
                      <th className="text-center py-2.5 px-3 text-xs text-[#7B86A2] font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drillOrders.map((o) => (
                      <tr key={o.id} className="border-b border-[rgba(0,212,170,0.08)]/50 hover:bg-[rgba(0,212,170,0.06)] transition-colors">
                        <td className="py-2.5 px-3 text-xs text-[#7B86A2] whitespace-nowrap">{fmtTime(o.created_at)}</td>
                        <td className="py-2.5 px-3 text-xs font-mono">{formatInstId(o.symbol)}</td>
                        <td className="py-2.5 px-3">
                          <span className={`font-mono text-xs font-medium ${o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                            {o.side === 'buy' ? '买' : o.side === 'sell' ? '卖' : o.side}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-right text-[#00D4AA]">
                          {o.fill_px != null ? o.fill_px.toFixed(2) : o.price != null ? o.price.toFixed(2) : '-'}
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-right">
                          {o.fill_sz != null ? o.fill_sz : o.filled_quantity}
                        </td>
                        <td className="py-2.5 px-3 text-xs font-mono text-right text-[#7B86A2]">
                          {o.fee != null ? o.fee.toFixed(6) : '-'}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            o.status === 'filled' ? 'bg-[#00D4AA]/10 text-[#00D4AA]' :
                            o.status === 'canceled' ? 'bg-[#7B86A2]/10 text-[#7B86A2]' :
                            'bg-[#F0A500]/10 text-[#F0A500]'
                          }`}>
                            {o.status === 'filled' ? '已成交' : o.status === 'canceled' ? '已撤销' : o.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </motion.div>
  )
}

/* ---------------- 按币种视图 ---------------- */
function SymbolView({ data, onDrillDown }: { data: AttributionBySymbol[]; onDrillDown: (symbol: string) => void }) {
  const pieData = useMemo(
    () => data.filter((d) => d.realized_pnl !== 0).map((d) => ({ name: formatInstId(d.symbol), value: Math.abs(d.realized_pnl), raw: d })),
    [data],
  )

  if (data.length === 0) {
    return <div className="glass-card p-12 text-center text-[#7B86A2] text-sm">暂无归因数据</div>
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Pie chart */}
        <div className="glass-card p-4">
          <h4 className="text-xs text-[#7B86A2] mb-3">各币种 PnL 占比</h4>
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} innerRadius={45} paddingAngle={2}>
                {pieData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="#050711" strokeWidth={2} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: 'rgba(10,15,30,0.95)', border: '1px solid rgba(0,212,170,0.2)', borderRadius: 8, fontSize: 12 }}
                formatter={(v) => (Number(v) || 0).toFixed(4)}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: '#7B86A2' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Bar chart */}
        <div className="glass-card p-4">
          <h4 className="text-xs text-[#7B86A2] mb-3">各币种 PnL 金额</h4>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.map((d) => ({ name: formatInstId(d.symbol), pnl: d.realized_pnl }))} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
              <XAxis dataKey="name" tick={AXIS_STYLE} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
              <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: 'rgba(10,15,30,0.95)', border: '1px solid rgba(0,212,170,0.2)', borderRadius: 8, fontSize: 12 }}
                formatter={(v) => (Number(v) || 0).toFixed(4)}
              />
              <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={d.realized_pnl >= 0 ? '#00D4AA' : '#FF4060'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Table */}
      <div className="glass-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.8)]">
              <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">币种</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">已实现盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">手续费</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">交易次数</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">胜率</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">盈亏占比</th>
              <th className="text-center py-2.5 px-3 text-xs text-[#7B86A2] font-medium">明细</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.symbol} className="border-b border-[rgba(0,212,170,0.08)]/50 hover:bg-[rgba(0,212,170,0.06)] transition-colors">
                <td className="py-2.5 px-3 text-xs font-mono">{formatInstId(d.symbol)}</td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.realized_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.realized_pnl, 4)}
                </td>
                <td className="py-2.5 px-3 text-xs font-mono text-right text-[#7B86A2]">{fmtNum(d.fee, 6)}</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{d.trade_count}</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{(d.win_rate * 100).toFixed(1)}%</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{fmtNum(d.pnl_percentage, 2)}%</td>
                <td className="py-2.5 px-3 text-center">
                  <button onClick={() => onDrillDown(d.symbol)} className="text-[#00D4AA] hover:underline inline-flex items-center text-xs">
                    查看 <ChevronRight className="w-3 h-3" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------------- 按策略类型视图 ---------------- */
function StrategyView({ data, onDrillDown }: { data: AttributionByStrategyType[]; onDrillDown: (strategy_type: string) => void }) {
  if (data.length === 0) {
    return <div className="glass-card p-12 text-center text-[#7B86A2] text-sm">暂无归因数据</div>
  }

  return (
    <div className="space-y-4">
      <div className="glass-card p-4">
        <h4 className="text-xs text-[#7B86A2] mb-3">各类策略 PnL 对比</h4>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data.map((d) => ({ name: d.strategy_type, realized: d.realized_pnl, unrealized: d.unrealized_pnl }))} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="name" tick={AXIS_STYLE} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
            <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: 'rgba(10,15,30,0.95)', border: '1px solid rgba(0,212,170,0.2)', borderRadius: 8, fontSize: 12 }}
              formatter={(v) => (Number(v) || 0).toFixed(4)}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: '#7B86A2' }} />
            <Bar dataKey="realized" name="已实现" fill="#00D4AA" radius={[4, 4, 0, 0]} />
            <Bar dataKey="unrealized" name="未实现" fill="#3B82F6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="glass-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.8)]">
              <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">策略类型</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">已实现盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">未实现盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">交易次数</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">胜率</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">平均收益率</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">最大回撤</th>
              <th className="text-center py-2.5 px-3 text-xs text-[#7B86A2] font-medium">明细</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.strategy_type} className="border-b border-[rgba(0,212,170,0.08)]/50 hover:bg-[rgba(0,212,170,0.06)] transition-colors">
                <td className="py-2.5 px-3 text-xs font-mono">{d.strategy_type}</td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.realized_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.realized_pnl, 4)}
                </td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.unrealized_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.unrealized_pnl, 4)}
                </td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{d.trade_count}</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{(d.win_rate * 100).toFixed(1)}%</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{fmtNum(d.avg_return, 2)}%</td>
                <td className="py-2.5 px-3 text-xs font-mono text-right text-[#FF4060]">{fmtNum(d.max_drawdown, 4)}</td>
                <td className="py-2.5 px-3 text-center">
                  <button onClick={() => onDrillDown(d.strategy_type)} className="text-[#00D4AA] hover:underline inline-flex items-center text-xs">
                    查看 <ChevronRight className="w-3 h-3" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------------- 按时间段视图 ---------------- */
function PeriodView({ data }: { data: AttributionByPeriod[] }) {
  if (data.length === 0) {
    return <div className="glass-card p-12 text-center text-[#7B86A2] text-sm">暂无归因数据</div>
  }

  const chartData = data.map((d) => ({
    name: d.period_start.slice(0, 10),
    realized: d.realized_pnl,
    unrealized: d.unrealized_pnl,
    total: d.total_pnl,
  }))

  return (
    <div className="space-y-4">
      <div className="glass-card p-4">
        <h4 className="text-xs text-[#7B86A2] mb-3">PnL 趋势</h4>
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <defs>
              <linearGradient id="gradTotal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00D4AA" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#00D4AA" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradRealized" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="name" tick={AXIS_STYLE} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
            <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: 'rgba(10,15,30,0.95)', border: '1px solid rgba(0,212,170,0.2)', borderRadius: 8, fontSize: 12 }}
              formatter={(v) => (Number(v) || 0).toFixed(4)}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: '#7B86A2' }} />
            <Area type="monotone" dataKey="total" name="总盈亏" stroke="#00D4AA" strokeWidth={2} fill="url(#gradTotal)" />
            <Area type="monotone" dataKey="realized" name="已实现" stroke="#3B82F6" strokeWidth={2} fill="url(#gradRealized)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="glass-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.8)]">
              <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">时间段</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">已实现盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">未实现盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">总盈亏</th>
              <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">交易次数</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.period_start} className="border-b border-[rgba(0,212,170,0.08)]/50 hover:bg-[rgba(0,212,170,0.06)] transition-colors">
                <td className="py-2.5 px-3 text-xs font-mono">{d.period_start.slice(0, 10)}</td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.realized_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.realized_pnl, 4)}
                </td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.unrealized_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.unrealized_pnl, 4)}
                </td>
                <td className={`py-2.5 px-3 text-xs font-mono text-right ${d.total_pnl >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                  {fmtNum(d.total_pnl, 4)}
                </td>
                <td className="py-2.5 px-3 text-xs font-mono text-right">{d.trade_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
