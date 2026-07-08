import { useEffect, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
}

export default function Modal({ open, onClose, title, children, wide }: ModalProps) {
  useEffect(() => {
    if (open) {
      const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', handleEsc)
      return () => {
        document.body.style.overflow = ''
        window.removeEventListener('keydown', handleEsc)
      }
    } else {
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-[#050711]/80"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: 20, rotateX: 2 }}
            animate={{ opacity: 1, scale: 1, y: 0, rotateX: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 20, rotateX: 2 }}
            transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
            className={`relative glass-panel rounded-2xl w-full ${wide ? 'max-w-2xl' : 'max-w-md'} p-6 shadow-[0_0_60px_rgba(0,212,170,0.08),0_25px_50px_rgba(0,0,0,0.5)] border border-[rgba(0,212,170,0.12)]`}
            style={{ perspective: '800px' }}
          >
            {/* Top accent glow line */}
            <div className="absolute top-0 left-[10%] right-[10%] h-px bg-gradient-to-r from-transparent via-[#00D4AA]/50 to-transparent" />
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-[#EDF0F7]">{title}</h2>
              <button
                onClick={onClose}
                className="btn-ghost px-4 py-1.5 text-sm font-medium transition-all duration-200 group"
              >
                <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-white/5 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700 ease-in-out" />
                <span className="relative">取消</span>
              </button>
            </div>
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
