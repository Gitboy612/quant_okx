import { motion } from 'framer-motion'
import PnLChart from '../PnLChart'
import type { PnlRecord } from '../../types'

interface PnLCurveSectionProps {
  pnlRecords: PnlRecord[]
  loading?: boolean
}

export default function PnLCurveSection({ pnlRecords, loading }: PnLCurveSectionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="flex-1 glass-panel p-5 h-72"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold">盈亏曲线</h3>
      </div>
      {/* 加载占位：切换策略时显示，避免布局抖动 */}
      {loading ? (
        <div className="h-48 flex items-center justify-center text-[#7B86A2] text-sm">加载中...</div>
      ) : (
        <PnLChart data={pnlRecords} />
      )}
    </motion.div>
  )
}
