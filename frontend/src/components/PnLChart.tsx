import { memo } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface PnlRecord {
  recorded_at: string
  total_pnl: number
  realized_pnl?: number
  unrealized_pnl?: number
}

export type TimeRange = '24h' | '7d' | '30d' | 'all'

interface PnLChartProps {
  data: PnlRecord[]
  timeRange?: TimeRange
}

function formatPnl(value: number): string {
  const absVal = Math.abs(value).toFixed(2)
  if (value >= 0) return `盈利 $${absVal}`
  return `亏损 $${absVal}`
}

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000

function startOfToday(): number {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

interface ChartPoint { time: string; pnl: number; realized_pnl: number; unrealized_pnl: number }

function buildBuckets(data: PnlRecord[], timeRange: TimeRange): ChartPoint[] {
  if (timeRange === 'all') {
    return [...data]
      .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime())
      .map((r) => ({
        time: new Date(r.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        pnl: r.total_pnl,
        realized_pnl: r.realized_pnl ?? 0,
        unrealized_pnl: r.unrealized_pnl ?? 0,
      }))
  }

  const buckets: { start: number; end: number; label: string }[] = []
  if (timeRange === '24h') {
    const now = new Date()
    now.setMinutes(0, 0, 0)
    const base = now.getTime()
    for (let i = 0; i < 24; i++) {
      const start = base - (23 - i) * HOUR_MS
      buckets.push({ start, end: start + HOUR_MS, label: new Date(start).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) })
    }
  } else {
    const count = timeRange === '7d' ? 8 : 31
    const back = timeRange === '7d' ? 7 : 30
    const todayStart = startOfToday()
    for (let i = 0; i < count; i++) {
      const start = todayStart - (back - i) * DAY_MS
      const d = new Date(start)
      buckets.push({ start, end: start + DAY_MS, label: `${d.getMonth() + 1}/${d.getDate()}` })
    }
  }

  const sorted = [...data].sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime())
  let lastValue = 0
  let lastRealized = 0
  let lastUnrealized = 0
  let dataIdx = 0
  return buckets.map((b) => {
    while (dataIdx < sorted.length) {
      const ts = new Date(sorted[dataIdx].recorded_at).getTime()
      if (ts >= b.start && ts < b.end) {
        lastValue = sorted[dataIdx].total_pnl
        lastRealized = sorted[dataIdx].realized_pnl ?? 0
        lastUnrealized = sorted[dataIdx].unrealized_pnl ?? 0
        dataIdx++
      } else if (ts >= b.end) {
        break
      } else {
        dataIdx++
      }
    }
    return { time: b.label, pnl: lastValue, realized_pnl: lastRealized, unrealized_pnl: lastUnrealized }
  })
}

function PnLChart({ data, timeRange = 'all' }: PnLChartProps) {
  if (timeRange === 'all' && data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-[#7B86A2] text-sm gap-2">
        <span>暂无盈亏数据</span>
        <span className="text-xs text-[#505C78]">策略启动后约2分钟开始记录盈亏</span>
      </div>
    )
  }

  const chartData = buildBuckets(data, timeRange)

  const isPositive = chartData.length > 0 && chartData[chartData.length - 1].pnl >= 0
  const accentColor = isPositive ? '#00D4AA' : '#FF4060'

  const chartContent = (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accentColor} stopOpacity={0.25} />
            <stop offset="50%" stopColor={accentColor} stopOpacity={0.08} />
            <stop offset="100%" stopColor={accentColor} stopOpacity={0} />
          </linearGradient>
          <filter id="pnlGlow">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#7B86A2', fontSize: 11 }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fill: '#7B86A2', fontSize: 11 }} />
        <Tooltip
          contentStyle={{
            backgroundColor: 'rgba(10, 15, 30, 0.9)',
            border: '1px solid rgba(0, 212, 170, 0.18)',
            borderRadius: '10px',
            color: '#EDF0F7',
            fontSize: '13px',
            backdropFilter: 'blur(12px)',
            boxShadow: '0 0 20px rgba(0, 212, 170, 0.1), 0 8px 24px rgba(0, 0, 0, 0.4)',
          }}
          labelStyle={{ color: '#7B86A2', fontWeight: 500 }}
          formatter={(value: number, _name: string, entry: any) => {
            const realized = entry?.payload?.realized_pnl ?? 0
            const unrealized = entry?.payload?.unrealized_pnl ?? 0
            return [
              `${formatPnl(value)} | 实现 $${realized.toFixed(2)} | 浮动 $${unrealized.toFixed(2)}`,
              ''
            ]
          }}
          itemStyle={{ color: accentColor, fontWeight: 600 }}
        />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke={accentColor}
          strokeWidth={1.5}
          fill="url(#pnlGradient)"
          filter="url(#pnlGlow)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )

  if (chartData.length > 50) {
    return (
      <div className="overflow-x-auto" style={{ width: '100%' }}>
        <div style={{ minWidth: `${Math.max(chartData.length * 8, 100)}%`, height: '100%' }}>
          {chartContent}
        </div>
      </div>
    )
  }

  return chartContent
}

export default memo(PnLChart)
