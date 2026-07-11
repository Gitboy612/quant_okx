import { motion } from 'framer-motion'
import KpiCard from '../KpiCard'
import { CardSkeleton } from '../Skeleton'
import type { PnlSummary, StrategyInstance } from '../../types'

interface KpiSummarySectionProps {
  totalEquity: number | null
  summary: PnlSummary | null
  instances: StrategyInstance[]
  kpiLoading: boolean
}

export default function KpiSummarySection({ totalEquity, summary, instances, kpiLoading }: KpiSummarySectionProps) {
  if (kpiLoading) {
    return <CardSkeleton count={4} />
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.08 } }, hidden: {} }}
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
    >
      <KpiCard label="总权益" value={totalEquity ?? summary?.latest_equity ?? 0} prefix="$" accent="neutral" loading={kpiLoading} />
      <KpiCard label="未实现盈亏" value={summary?.total_unrealized_pnl ?? 0} prefix="$" accent={summary && summary.total_unrealized_pnl >= 0 ? 'profit' : 'loss'} loading={kpiLoading} />
      <KpiCard label="已实现盈亏" value={summary?.total_realized_pnl ?? 0} prefix="$" accent={summary && summary.total_realized_pnl >= 0 ? 'profit' : 'loss'} loading={kpiLoading} />
      <KpiCard label="活跃策略" value={instances.filter((i) => i.status === 'running').length} accent="neutral" decimals={0} loading={kpiLoading} />
    </motion.div>
  )
}
