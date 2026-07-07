import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface PnlRecord {
  recorded_at: string
  total_pnl: number
}

interface PnLChartProps {
  data: PnlRecord[]
}

export default function PnLChart({ data }: PnLChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-[#6B6B7B] text-sm gap-2">
        <span>暂无盈亏数据</span>
        <span className="text-xs text-[#6B6B7B]/60">策略启动后约2分钟开始记录盈亏</span>
      </div>
    )
  }

  const chartData = data
    .map((r) => ({
      time: new Date(r.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      pnl: r.total_pnl,
    }))
    .reverse()

  const isPositive = chartData.length > 0 && chartData[chartData.length - 1].pnl >= 0

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isPositive ? '#00D4AA' : '#FF4757'} stopOpacity={0.2} />
            <stop offset="100%" stopColor={isPositive ? '#00D4AA' : '#FF4757'} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#6B6B7B', fontSize: 11 }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6B6B7B', fontSize: 11 }} />
        <Tooltip
          contentStyle={{
            backgroundColor: '#14141A',
            border: '1px solid #1E1E28',
            borderRadius: '8px',
            color: '#E8E8ED',
            fontSize: '13px',
          }}
        />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke={isPositive ? '#00D4AA' : '#FF4757'}
          strokeWidth={1.5}
          fill="url(#pnlGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
