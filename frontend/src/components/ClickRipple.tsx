import { useEffect, useRef, useCallback } from 'react'
import { usePerformanceMode } from '../hooks/usePerformanceMode'

interface Ripple {
  id: number
  x: number
  y: number
  createdAt: number
  color: string
}

export default function ClickRipple() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const ripplesRef = useRef<Ripple[]>([])
  const nextIdRef = useRef(0)
  const animIdRef = useRef<number>(0)
  const { performanceMode } = usePerformanceMode()

  const addRipple = useCallback((e: MouseEvent) => {
    const ripple: Ripple = {
      id: nextIdRef.current++,
      x: e.clientX,
      y: e.clientY,
      createdAt: Date.now(),
      color: Math.random() > 0.7 ? '0, 168, 255' : '0, 212, 170',
    }
    ripplesRef.current.push(ripple)
    // Start animation loop if not already running
    if (!animIdRef.current) {
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      animIdRef.current = requestAnimationFrame(function loop() {
        ctx!.clearRect(0, 0, canvas!.width, canvas!.height)
        const now = Date.now()
        ripplesRef.current = ripplesRef.current.filter((r) => {
          const age = now - r.createdAt
          if (age > 1200) return false
          const progress = age / 1200
          const radius = progress * 80
          const opacity = (1 - progress) * 0.5
          ctx!.beginPath()
          ctx!.arc(r.x, r.y, radius, 0, Math.PI * 2)
          ctx!.strokeStyle = `rgba(${r.color}, ${opacity})`
          ctx!.lineWidth = 2 * (1 - progress)
          ctx!.stroke()
          if (progress < 0.3) {
            ctx!.beginPath()
            ctx!.arc(r.x, r.y, radius * 0.6, 0, Math.PI * 2)
            ctx!.fillStyle = `rgba(${r.color}, ${(1 - progress / 0.3) * 0.15})`
            ctx!.fill()
          }
          for (let i = 0; i < 6; i++) {
            const angle = (Math.PI * 2 / 6) * i + progress * 0.5
            const dist = radius * 1.2
            ctx!.beginPath()
            ctx!.arc(r.x + Math.cos(angle) * dist, r.y + Math.sin(angle) * dist, 1.5 * (1 - progress), 0, Math.PI * 2)
            ctx!.fillStyle = `rgba(${r.color}, ${opacity * 0.8})`
            ctx!.fill()
          }
          return true
        })
        if (ripplesRef.current.length > 0) {
          animIdRef.current = requestAnimationFrame(loop)
        } else {
          animIdRef.current = 0
        }
      })
    }
  }, [])

  useEffect(() => {
    if (performanceMode) return
    const canvas = canvasRef.current
    if (!canvas) return
    const resize = () => {
      canvas!.width = window.innerWidth
      canvas!.height = window.innerHeight
    }
    resize()
    window.addEventListener('resize', resize)
    document.addEventListener('click', addRipple)
    return () => {
      cancelAnimationFrame(animIdRef.current)
      animIdRef.current = 0
      window.removeEventListener('resize', resize)
      document.removeEventListener('click', addRipple)
    }
  }, [performanceMode, addRipple])

  if (performanceMode) return null

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-[100] pointer-events-none"
    />
  )
}
