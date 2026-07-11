import { motion } from 'framer-motion'
import PnLChart, { type TimeRange } from '../PnLChart'
import type { PnlRecord } from '../../types'

interface PnLCurveSectionProps {
  pnlRecords: PnlRecord[]
  timeRange: TimeRange
  setTimeRange: (r: TimeRange) => void
}

export default function PnLCurveSection({ pnlRecords, timeRange, setTimeRange }: PnLCurveSectionProps) {
  return (
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
  )
}
