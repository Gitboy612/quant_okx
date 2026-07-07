import { motion, type Variants } from 'framer-motion'

interface KpiCardProps {
  label: string
  value: number
  prefix?: string
  suffix?: string
  accent?: 'default' | 'profit' | 'loss' | 'neutral'
  decimals?: number
  loading?: boolean
}

const variants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

const accentColors = {
  default: 'text-[#00D4AA]',
  profit: 'text-[#00D4AA]',
  loss: 'text-[#FF4757]',
  neutral: 'text-[#E8E8ED]',
}

export default function KpiCard({ label, value, prefix = '', suffix = '', accent = 'default', decimals = 2, loading = false }: KpiCardProps) {
  return (
    <motion.div
      variants={variants}
      className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
    >
      <div className="text-xs text-[#6B6B7B] mb-2 tracking-wide uppercase">{label}</div>
      <div className={`text-2xl font-bold font-mono ${accentColors[accent]}`}>
        {loading ? (
          <span className="text-[#6B6B7B] text-base font-normal animate-pulse">获取中...</span>
        ) : (
          <>{prefix}{value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</>
        )}
      </div>
    </motion.div>
  )
}
