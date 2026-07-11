import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { XCircle, X, RefreshCw } from 'lucide-react'

interface ErrorBannerProps {
  message: string
  onRetry?: () => void
  autoDismiss?: boolean
  dismissMs?: number
}

export function ErrorBanner({
  message,
  onRetry,
  autoDismiss = true,
  dismissMs = 10000,
}: ErrorBannerProps) {
  const [visible, setVisible] = useState(true)

  const handleDismiss = useCallback(() => setVisible(false), [])

  // Re-show when a new error message arrives
  useEffect(() => {
    if (message) setVisible(true)
  }, [message])

  // Auto-dismiss timer
  useEffect(() => {
    if (!autoDismiss || !visible) return
    const timer = setTimeout(handleDismiss, dismissMs)
    return () => clearTimeout(timer)
  }, [autoDismiss, dismissMs, visible, handleDismiss, message])

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
          className="flex items-center gap-3 p-3 rounded-xl border border-[#FF4060]/20 bg-[#FF4060]/8"
        >
          <XCircle className="w-4 h-4 text-[#FF4060] flex-shrink-0" />
          <span className="flex-1 text-sm text-[#FF4060] break-words">{message}</span>
          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg border border-[#FF4060]/20 text-[#FF4060] hover:bg-[#FF4060]/10 transition-colors flex-shrink-0"
            >
              <RefreshCw className="w-3 h-3" />
              重试
            </button>
          )}
          <button
            onClick={handleDismiss}
            className="text-[#FF4060]/60 hover:text-[#FF4060] transition-colors flex-shrink-0"
            aria-label="关闭"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default ErrorBanner
