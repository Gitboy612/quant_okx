import { memo } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface PnlRecord {
  recorded_at: string
  total_pnl: number
}

export type TimeRange = '1h' | '1d' | '1w' | '1mo' | 'all'

interface PnLChartProps {
  data: PnlRecord[]
  timeRange?: TimeRange
}

const TIME_RANGE_DURATIONS: Record<TimeRange, number | null> = {
  '1h': 60 * 60 * 1000,
  '1d': 24 * 60 * 60 * 1000,
  '1w': 7 * 24 * 60 * 60 * 1000,
  '1mo': 30 * 24 * 60 * 60 * 1000,
  'all': null,
}

function formatPnl(value: number): string {
  const absVal = Math.abs(value).toFixed(2)
  if (value >= 0) return `盈利 $${absVal}`
  return `亏损 $${absVal}`
}

function PnLChart({ data, timeRange = 'all' }: PnLChartProps) {
  const duration = TIME_RANGE_DURATIONS[timeRange]
  const cutoff = duration != null ? Date.now() - duration : 0

  const filteredData = data.filter((r) => new Date(r.recorded_at).getTime() >= cutoff)

  if (filteredData.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-[#7B86A2] text-sm gap-2">
        <span>暂无盈亏数据</span>
        <span className="text-xs text-[#505C78]">策略启动后约2分钟开始记录盈亏</span>
      </div>
    )
  }

  const chartData = filteredData
    .map((r) => ({
      time: new Date(r.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      pnl: r.total_pnl,
    }))
    .reverse()

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
          formatter={(value: number) => [formatPnl(value), '']}
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
