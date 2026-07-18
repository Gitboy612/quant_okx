import { memo } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface PnlRecord {
  recorded_at: string
  total_pnl: number
  realized_pnl?: number
  unrealized_pnl?: number
}

interface PnLChartProps {
  data: PnlRecord[]
  loading?: boolean
}

function formatPnl(value: number): string {
  const absVal = Math.abs(value).toFixed(2)
  if (value >= 0) return `盈利 $${absVal}`
  return `亏损 $${absVal}`
}

// X 轴时间格式化：MM/DD HH:mm
function formatXTick(iso: string): string {
  const d = new Date(iso)
  const mm = d.getMonth() + 1
  const dd = d.getDate().toString().padStart(2, '0')
  const hh = d.getHours().toString().padStart(2, '0')
  const min = d.getMinutes().toString().padStart(2, '0')
  return `${mm}/${dd} ${hh}:${min}`
}

function PnLChart({ data }: PnLChartProps) {
  // 空数据态
  if (data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-[#7B86A2] text-sm gap-2">
        <span>暂无盈亏数据</span>
        <span className="text-xs text-[#505C78]">策略启动后约2分钟开始记录盈亏</span>
      </div>
    )
  }

  // 按 recorded_at 升序排序后直接使用原始数据点
  const sorted = [...data].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  )

  const isPositive = sorted[sorted.length - 1].total_pnl >= 0
  const accentColor = isPositive ? '#00D4AA' : '#FF4060'

  const chartContent = (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={sorted}>
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
        <XAxis
          dataKey="recorded_at"
          axisLine={false}
          tickLine={false}
          tick={{ fill: '#7B86A2', fontSize: 11 }}
          tickFormatter={formatXTick}
        />
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
          labelFormatter={(label) => formatXTick(String(label ?? ''))}
          formatter={(value, _name, entry) => {
            const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0))
            const realized = Number(entry?.payload?.realized_pnl ?? 0)
            const unrealized = Number(entry?.payload?.unrealized_pnl ?? 0)
            return [
              `${formatPnl(numericValue)} | 实现 $${realized.toFixed(2)} | 浮动 $${unrealized.toFixed(2)}`,
              ''
            ]
          }}
          itemStyle={{ color: accentColor, fontWeight: 600 }}
        />
        <Area
          type="monotone"
          dataKey="total_pnl"
          stroke={accentColor}
          strokeWidth={1.5}
          fill="url(#pnlGradient)"
          filter="url(#pnlGlow)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )

  // 数据点 > 400 时启用横向滚动
  if (sorted.length > 400) {
    return (
      <div className="overflow-x-auto" style={{ width: '100%' }}>
        <div style={{ minWidth: `${Math.max(sorted.length * 8, 100)}%`, height: '100%' }}>
          {chartContent}
        </div>
      </div>
    )
  }

  return chartContent
}

export default memo(PnLChart)
