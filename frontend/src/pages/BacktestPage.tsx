import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Loader2, CheckCircle, XCircle, Download, Activity, TrendingDown, TrendingUp, Target } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import SymbolPicker from '../components/SymbolPicker'
import { listTemplates } from '../api/strategies'
import { runBacktest, exportBacktestToInstance } from '../api/backtest'
import type { StrategyTemplate } from '../types'
import type { BacktestResult, BacktestConfig, BacktestTrade } from '../api/backtest'

const INTERVALS = [
  { value: '1m', label: '1 分钟' },
  { value: '5m', label: '5 分钟' },
  { value: '15m', label: '15 分钟' },
  { value: '1H', label: '1 小时' },
  { value: '4H', label: '4 小时' },
  { value: '1D', label: '1 天' },
]

const STRATEGY_TYPES = [
  { value: 'grid', label: '网格策略' },
  { value: 'trend', label: '趋势策略' },
  { value: 'arbitrage', label: '套利策略' },
]

function toIsoLocal(dt: string): string {
  // <input type="datetime-local"> 返回 'YYYY-MM-DDTHH:MM'，转 ISO8601 UTC
  if (!dt) return ''
  const d = new Date(dt)
  if (isNaN(d.getTime())) return ''
  return d.toISOString()
}

function fromIsoToLocal(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(2)}%`
}

function fmtNum(v: number, digits = 4): string {
  if (!isFinite(v)) return '∞'
  return v.toFixed(digits)
}

export default function BacktestPage() {
  const [templates, setTemplates] = useState<StrategyTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null)
  const [symbol, setSymbol] = useState('BTC-USDT')
  const [strategyType, setStrategyType] = useState<'grid' | 'trend' | 'arbitrage'>('grid')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [intervalValue, setIntervalValue] = useState('1H')
  const [initialCapital, setInitialCapital] = useState(10000)
  const [slippage, setSlippage] = useState(0.001)
  const [feeRate, setFeeRate] = useState(0.001)
  const [paramsText, setParamsText] = useState(
    JSON.stringify(
      { upper_price: 70000, lower_price: 60000, grid_count: 10, order_qty: 0.001 },
      null,
      2,
    ),
  )

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    listTemplates()
      .then((res) => setTemplates(res.data))
      .catch(() => {})
  }, [])

  // 默认时间范围：最近 30 天
  useEffect(() => {
    if (!endTime) {
      const now = new Date()
      const past = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
      setEndTime(fromIsoToLocal(now.toISOString()))
      setStartTime(fromIsoToLocal(past.toISOString()))
    }
  }, [endTime])

  function handleTemplateChange(id: number) {
    setSelectedTemplateId(id)
    const tpl = templates.find((t) => t.id === id)
    if (!tpl) return
    setStrategyType(tpl.strategy_type as 'grid' | 'trend' | 'arbitrage')
    // 用模板默认参数填充
    const dp = tpl.default_params || {}
    if (Object.keys(dp).length > 0) {
      setParamsText(JSON.stringify(dp, null, 2))
    } else {
      // 按策略类型填入示例
      if (tpl.strategy_type === 'grid') {
        setParamsText(
          JSON.stringify(
            { upper_price: 70000, lower_price: 60000, grid_count: 10, order_qty: 0.001 },
            null,
            2,
          ),
        )
      } else if (tpl.strategy_type === 'trend') {
        setParamsText(JSON.stringify({ fast_period: 5, slow_period: 20, order_qty: 0.01 }, null, 2))
      }
    }
  }

  async function handleRun() {
    let params: Record<string, unknown> = {}
    try {
      params = JSON.parse(paramsText)
    } catch (e) {
      setToast({ type: 'error', msg: '策略参数 JSON 解析失败' })
      return
    }

    const startIso = toIsoLocal(startTime)
    const endIso = toIsoLocal(endTime)
    if (!startIso || !endIso) {
      setToast({ type: 'error', msg: '请填写开始和结束时间' })
      return
    }
    if (new Date(startIso) >= new Date(endIso)) {
      setToast({ type: 'error', msg: '开始时间必须早于结束时间' })
      return
    }

    const config: BacktestConfig = {
      symbol,
      strategy_type: strategyType,
      params,
      start_time: startIso,
      end_time: endIso,
      interval: intervalValue,
      initial_capital: initialCapital,
      slippage,
      fee_rate: feeRate,
    }

    setLoading(true)
    setResult(null)
    try {
      const res = await runBacktest(config)
      setResult(res.data)
      if (res.data.error) {
        setToast({ type: 'error', msg: res.data.error })
      } else {
        setToast({ type: 'success', msg: `回测完成，共 ${res.data.kline_count} 根 K 线` })
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '回测请求失败'
      setToast({ type: 'error', msg })
    } finally {
      setLoading(false)
    }
  }

  async function handleExport() {
    if (!result) return
    setExporting(true)
    try {
      const res = await exportBacktestToInstance({
        symbol: result.config.symbol,
        strategy_type: result.config.strategy_type,
        params: result.config.params,
      })
      setToast({ type: 'success', msg: res.data.message })
    } catch (e: any) {
      setToast({ type: 'error', msg: e?.response?.data?.detail || '导出失败' })
    } finally {
      setExporting(false)
    }
  }

  const equityChartData = useMemo(() => {
    if (!result) return []
    return result.equity_curve.map((p) => ({
      time: new Date(p.timestamp).toLocaleString('zh-CN', { hour12: false }),
      equity: p.equity,
    }))
  }, [result])

  const metrics = result?.metrics

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">历史回测</h2>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className={`flex items-center gap-2 text-sm p-3 rounded-md border ${
              toast.type === 'success'
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
            }`}
          >
            {toast.type === 'success' ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 参数配置表单 */}
      <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-xl p-5 space-y-4">
        <div className="text-[11px] text-[#7B86A2] uppercase tracking-wider font-semibold">参数配置</div>

        <div className="grid grid-cols-2 gap-4">
          {/* 策略模板选择 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">策略模板</label>
            <select
              value={selectedTemplateId ?? ''}
              onChange={(e) => e.target.value && handleTemplateChange(Number(e.target.value))}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            >
              <option value="">不使用模板（手动配置）</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  [{t.strategy_type}] {t.name}
                </option>
              ))}
            </select>
          </div>

          {/* 策略类型 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">策略类型</label>
            <select
              value={strategyType}
              onChange={(e) => setStrategyType(e.target.value as 'grid' | 'trend' | 'arbitrage')}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            >
              {STRATEGY_TYPES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {/* 交易对 */}
          <div className="space-y-1.5 col-span-2">
            <label className="text-xs text-[#7B86A2]">交易对</label>
            <SymbolPicker value={symbol} onChange={setSymbol} className="w-full" />
          </div>

          {/* 开始时间 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">开始时间</label>
            <input
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          {/* 结束时间 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">结束时间</label>
            <input
              type="datetime-local"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          {/* K 线周期 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">K 线周期</label>
            <select
              value={intervalValue}
              onChange={(e) => setIntervalValue(e.target.value)}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            >
              {INTERVALS.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
          </div>

          {/* 初始资金 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">初始资金 (USDT)</label>
            <input
              type="number"
              value={initialCapital}
              onChange={(e) => setInitialCapital(Number(e.target.value))}
              min={1}
              step={100}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          {/* 滑点 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">滑点 (默认 0.001)</label>
            <input
              type="number"
              value={slippage}
              onChange={(e) => setSlippage(Number(e.target.value))}
              min={0}
              step={0.0001}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          {/* 手续费率 */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#7B86A2]">手续费率 (默认 0.001)</label>
            <input
              type="number"
              value={feeRate}
              onChange={(e) => setFeeRate(Number(e.target.value))}
              min={0}
              step={0.0001}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          {/* 策略参数 JSON */}
          <div className="space-y-1.5 col-span-2">
            <label className="text-xs text-[#7B86A2]">策略参数 (JSON)</label>
            <textarea
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
              rows={6}
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-xs text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] font-mono"
              placeholder='{"upper_price": 70000, "lower_price": 60000, "grid_count": 10, "order_qty": 0.001}'
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <button
            onClick={handleRun}
            disabled={loading}
            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-5 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {loading ? '回测中...' : '运行回测'}
          </button>
        </div>
      </div>

      {/* 回测结果 */}
      {result && !result.error && metrics && (
        <div className="space-y-4">
          {/* 指标卡片 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              icon={<TrendingUp className="w-4 h-4" />}
              label="总收益率"
              value={fmtPct(metrics.total_return)}
              positive={metrics.total_return >= 0}
            />
            <MetricCard
              icon={<TrendingDown className="w-4 h-4" />}
              label="最大回撤"
              value={fmtPct(-metrics.max_drawdown)}
              positive={false}
            />
            <MetricCard
              icon={<Activity className="w-4 h-4" />}
              label="夏普比率"
              value={fmtNum(metrics.sharpe_ratio, 3)}
              positive={metrics.sharpe_ratio >= 0}
            />
            <MetricCard
              icon={<Target className="w-4 h-4" />}
              label="胜率"
              value={fmtPct(metrics.win_rate)}
              positive={metrics.win_rate >= 0.5}
            />
          </div>

          {/* 详细指标行 */}
          <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-xl p-4 grid grid-cols-2 md:grid-cols-5 gap-4 text-xs">
            <div>
              <div className="text-[#7B86A2] mb-1">最终权益</div>
              <div className="text-[#E8E8ED] font-mono">{fmtNum(metrics.final_equity, 2)} USDT</div>
            </div>
            <div>
              <div className="text-[#7B86A2] mb-1">交易笔数</div>
              <div className="text-[#E8E8ED] font-mono">{metrics.trade_count}</div>
            </div>
            <div>
              <div className="text-[#7B86A2] mb-1">盈亏比</div>
              <div className="text-[#E8E8ED] font-mono">{fmtNum(metrics.profit_factor, 3)}</div>
            </div>
            <div>
              <div className="text-[#7B86A2] mb-1">K 线数量</div>
              <div className="text-[#E8E8ED] font-mono">{result.kline_count}</div>
            </div>
            <div>
              <div className="text-[#7B86A2] mb-1">交易明细</div>
              <div className="text-[#E8E8ED] font-mono">{result.trades.length} 笔</div>
            </div>
          </div>

          {/* 权益曲线图 */}
          <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="text-sm text-[#E8E8ED] font-medium">权益曲线</div>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-[#1A1A24] transition-colors disabled:opacity-50"
              >
                {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                导出为策略实例
              </button>
            </div>
            <div style={{ width: '100%', height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityChartData}>
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00D4AA" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#00D4AA" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1E1E28" vertical={false} />
                  <XAxis
                    dataKey="time"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#7B86A2', fontSize: 10 }}
                    minTickGap={50}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#7B86A2', fontSize: 10 }}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'rgba(10, 15, 30, 0.9)',
                      border: '1px solid rgba(0, 212, 170, 0.18)',
                      borderRadius: '10px',
                      color: '#EDF0F7',
                      fontSize: '12px',
                    }}
                    formatter={(value: any) => [`${Number(value).toFixed(2)} USDT`, '权益']}
                  />
                  <Line
                    type="monotone"
                    dataKey="equity"
                    stroke="#00D4AA"
                    strokeWidth={1.5}
                    dot={false}
                    fill="url(#equityGradient)"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* 交易明细表格 */}
          <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-xl p-5">
            <div className="text-sm text-[#E8E8ED] font-medium mb-3">交易明细</div>
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-[#0C0C14]">
                  <tr className="text-[#7B86A2] border-b border-[#1E1E28]">
                    <th className="text-left py-2 px-2 font-medium">时间</th>
                    <th className="text-left py-2 px-2 font-medium">方向</th>
                    <th className="text-left py-2 px-2 font-medium">类型</th>
                    <th className="text-right py-2 px-2 font-medium">价格</th>
                    <th className="text-right py-2 px-2 font-medium">数量</th>
                    <th className="text-right py-2 px-2 font-medium">手续费</th>
                    <th className="text-right py-2 px-2 font-medium">已实现盈亏</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t: BacktestTrade, i: number) => (
                    <tr key={i} className="border-b border-[#1E1E28]/50 hover:bg-[#1A1A24]/50">
                      <td className="py-2 px-2 text-[#7B86A2] font-mono">
                        {new Date(t.timestamp).toLocaleString('zh-CN', { hour12: false })}
                      </td>
                      <td className="py-2 px-2">
                        <span className={t.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4757]'}>
                          {t.side === 'buy' ? '买入' : '卖出'}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-[#7B86A2]">{t.order_type === 'limit' ? '限价' : '市价'}</td>
                      <td className="py-2 px-2 text-right text-[#E8E8ED] font-mono">{t.price.toFixed(4)}</td>
                      <td className="py-2 px-2 text-right text-[#E8E8ED] font-mono">{t.quantity.toFixed(6)}</td>
                      <td className="py-2 px-2 text-right text-[#7B86A2] font-mono">{t.fee.toFixed(6)}</td>
                      <td
                        className={`py-2 px-2 text-right font-mono ${
                          t.pnl > 0 ? 'text-[#00D4AA]' : t.pnl < 0 ? 'text-[#FF4757]' : 'text-[#7B86A2]'
                        }`}
                      >
                        {t.pnl.toFixed(6)}
                      </td>
                    </tr>
                  ))}
                  {result.trades.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-[#7B86A2]">
                        无成交记录
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 错误展示 */}
      {result?.error && (
        <div className="bg-[#FF4757]/5 border border-[#FF4757]/20 rounded-xl p-4 text-sm text-[#FF4757]">
          <div className="flex items-center gap-2 mb-1">
            <XCircle className="w-4 h-4" />
            <span className="font-medium">回测失败</span>
          </div>
          <div className="text-xs opacity-80">{result.error}</div>
        </div>
      )}
    </div>
  )
}

interface MetricCardProps {
  icon: React.ReactNode
  label: string
  value: string
  positive: boolean
}

function MetricCard({ icon, label, value, positive }: MetricCardProps) {
  return (
    <div className="bg-[#0C0C14] border border-[#1E1E28] rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`p-1.5 rounded-md ${positive ? 'bg-[#00D4AA]/10 text-[#00D4AA]' : 'bg-[#FF4757]/10 text-[#FF4757]'}`}>
          {icon}
        </div>
        <span className="text-xs text-[#7B86A2]">{label}</span>
      </div>
      <div className={`text-lg font-mono font-semibold ${positive ? 'text-[#00D4AA]' : 'text-[#FF4757]'}`}>{value}</div>
    </div>
  )
}
