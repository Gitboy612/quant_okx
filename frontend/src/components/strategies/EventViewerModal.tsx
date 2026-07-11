import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import type { StrategyEvent } from '../../types'

// 策略事件查看器：渲染策略实例的下单失败等事件告警（内联展示）
export default function EventViewerModal({ events }: { events: StrategyEvent[] | undefined }) {
  const failedEvents = events?.filter((e) => e.event_type === 'order_failed')
  if (!failedEvents || failedEvents.length === 0) return null
  return (
    <motion.div
      initial={{ opacity: 0, y: -5 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 flex items-center gap-2 bg-[#FF4757]/10 border border-[#FF4757]/20 rounded-md px-3 py-2 text-xs text-[#FF4757]"
    >
      <AlertTriangle className="w-4 h-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <span className="font-medium">策略下单失败</span>
        <span className="ml-2 text-[#FF4757]/70">{failedEvents[0].message}</span>
        {failedEvents.length > 1 && (
          <span className="ml-1 text-[#FF4757]/50">等 {failedEvents.length} 条</span>
        )}
      </div>
    </motion.div>
  )
}
