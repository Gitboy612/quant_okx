import type { CSSProperties } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2 } from 'lucide-react'

/* ===== Inline spinner (small, embeddable) ===== */
interface InlineSpinnerProps {
  size?: number
  className?: string
  style?: CSSProperties
}

export function InlineSpinner({ size = 16, className = '', style }: InlineSpinnerProps) {
  return (
    <Loader2
      className={`animate-spin ${className}`}
      style={{ width: size, height: size, ...style }}
    />
  )
}

/* ===== Button spinner (inside buttons) ===== */
interface ButtonSpinnerProps {
  size?: number
  className?: string
}

export function ButtonSpinner({ size = 14, className = '' }: ButtonSpinnerProps) {
  return <Loader2 className={`animate-spin ${className}`} style={{ width: size, height: size }} />
}

/* ===== Full-screen loading with overlay mask ===== */
interface FullScreenSpinnerProps {
  show: boolean
  text?: string
}

export function FullScreenSpinner({ show, text = '加载中...' }: FullScreenSpinnerProps) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-[#050711]/80 backdrop-blur-sm"
        >
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-8 h-8 animate-spin text-[#00D4AA]" />
            <span className="text-sm text-[#7B86A2]">{text}</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default FullScreenSpinner
