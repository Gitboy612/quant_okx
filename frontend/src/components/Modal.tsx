import { useEffect, useState, useRef, useCallback, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
  scrollable?: boolean
}

export default function Modal({ open, onClose, title, children, wide, scrollable = true }: ModalProps) {
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const offsetRef = useRef({ x: 0, y: 0 })

  useEffect(() => {
    if (open) {
      setOffset({ x: 0, y: 0 })
      offsetRef.current = { x: 0, y: 0 }
    }
  }, [open])

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    dragging.current = true
    dragStart.current = { x: e.clientX - offsetRef.current.x, y: e.clientY - offsetRef.current.y }
    document.body.style.userSelect = 'none'
  }, [])

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging.current) return
    const newX = e.clientX - dragStart.current.x
    const newY = e.clientY - dragStart.current.y
    offsetRef.current = { x: newX, y: newY }
    setOffset({ x: newX, y: newY })
  }, [])

  const onMouseUp = useCallback(() => {
    dragging.current = false
    document.body.style.userSelect = ''
  }, [])

  useEffect(() => {
    if (open) {
      const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', handleEsc)
      window.addEventListener('mousemove', onMouseMove)
      window.addEventListener('mouseup', onMouseUp)
      return () => {
        document.body.style.overflow = ''
        document.body.style.userSelect = ''
        window.removeEventListener('keydown', handleEsc)
        window.removeEventListener('mousemove', onMouseMove)
        window.removeEventListener('mouseup', onMouseUp)
      }
    } else {
      document.body.style.overflow = ''
    }
  }, [open, onClose, onMouseMove, onMouseUp])

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-[#050711]/80 backdrop-blur-sm"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            className="relative z-10 rounded-2xl border border-[rgba(0,212,170,0.12)] shadow-[0_0_60px_rgba(0,212,170,0.08),0_25px_50px_rgba(0,0,0,0.5)]"
            style={{
              width: wide ? 'min(672px, calc(100vw - 2rem))' : 'min(512px, calc(100vw - 2rem))',
              maxHeight: scrollable ? 'calc(100vh - 4rem)' : 'none',
              display: 'flex',
              flexDirection: 'column',
              background: 'var(--color-bg-panel)',
              overflow: scrollable ? 'hidden' : 'visible',
              position: 'relative',
              left: offset.x,
              top: offset.y,
            }}
          >
            {/* Top accent glow line */}
            <div className="absolute top-0 left-[10%] right-[10%] h-px bg-gradient-to-r from-transparent via-[#00D4AA]/50 to-transparent pointer-events-none" />

            {/* Header — fixed height, no scroll; draggable handle */}
            <div
              onMouseDown={onMouseDown}
              className="flex items-center justify-between px-6 pt-5 pb-3 shrink-0 cursor-grab active:cursor-grabbing"
            >
              <h2 className="text-lg font-bold text-[#EDF0F7] select-none">{title}</h2>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.06)] transition-all duration-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body — scrollable content area */}
            <div
              className={scrollable ? 'overflow-y-auto' : ''}
              style={{ flex: '1 1 0%', minHeight: 0, padding: '0 1.5rem 1.5rem' }}
            >
              {children}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body
  )
}
