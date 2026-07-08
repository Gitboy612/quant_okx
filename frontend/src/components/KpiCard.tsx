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
  loss: 'text-[#FF4060]',
  neutral: 'text-[#EDF0F7]',
}

export default function KpiCard({ label, value, prefix = '', suffix = '', accent = 'default', decimals = 2, loading = false }: KpiCardProps) {
  return (
    <motion.div
      variants={variants}
      whileHover={{
        boxShadow: '0 0 20px rgba(0, 212, 170, 0.12), 0 0 40px rgba(0, 212, 170, 0.06)',
        borderColor: 'rgba(0, 212, 170, 0.18)',
      }}
      className="glass-card rounded-xl p-5 relative overflow-hidden"
    >
      {/* Subtle gradient top border accent line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#00D4AA]/40 to-transparent" />
      <div className="text-xs text-[#7B86A2] mb-2 tracking-wider uppercase font-medium">{label}</div>
      <div className={`text-2xl font-bold font-mono ${accentColors[accent]}`}>
        {loading ? (
          <span className="text-[#7B86A2] text-base font-normal animate-pulse">获取中...</span>
        ) : (
          <>{prefix}{value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</>
        )}
      </div>
    </motion.div>
  )
}
