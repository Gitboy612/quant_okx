import { useEffect, useRef, useCallback } from 'react'

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

  const addRipple = useCallback((e: MouseEvent) => {
    const ripple: Ripple = {
      id: nextIdRef.current++,
      x: e.clientX,
      y: e.clientY,
      createdAt: Date.now(),
      color: Math.random() > 0.7 ? '0, 168, 255' : '0, 212, 170',
    }
    ripplesRef.current.push(ripple)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number

    const resize = () => {
      canvas!.width = window.innerWidth
      canvas!.height = window.innerHeight
    }
    resize()
    window.addEventListener('resize', resize)
    document.addEventListener('click', addRipple)

    const draw = () => {
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height)
      const now = Date.now()

      ripplesRef.current = ripplesRef.current.filter((r) => {
        const age = now - r.createdAt
        if (age > 1200) return false

        const progress = age / 1200
        const maxRadius = 80
        const radius = progress * maxRadius
        const opacity = (1 - progress) * 0.5

        // Expanding ring
        ctx!.beginPath()
        ctx!.arc(r.x, r.y, radius, 0, Math.PI * 2)
        ctx!.strokeStyle = `rgba(${r.color}, ${opacity})`
        ctx!.lineWidth = 2 * (1 - progress)
        ctx!.stroke()

        // Inner filled circle (fading)
        if (progress < 0.3) {
          const innerOpacity = (1 - progress / 0.3) * 0.15
          ctx!.beginPath()
          ctx!.arc(r.x, r.y, radius * 0.6, 0, Math.PI * 2)
          ctx!.fillStyle = `rgba(${r.color}, ${innerOpacity})`
          ctx!.fill()
        }

        // Particle burst
        for (let i = 0; i < 6; i++) {
          const angle = (Math.PI * 2 / 6) * i + progress * 0.5
          const particleDist = radius * 1.2
          const px = r.x + Math.cos(angle) * particleDist
          const py = r.y + Math.sin(angle) * particleDist
          const particleSize = 1.5 * (1 - progress)

          ctx!.beginPath()
          ctx!.arc(px, py, particleSize, 0, Math.PI * 2)
          ctx!.fillStyle = `rgba(${r.color}, ${opacity * 0.8})`
          ctx!.fill()
        }

        return true
      })

      animationId = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      cancelAnimationFrame(animationId)
      window.removeEventListener('resize', resize)
      document.removeEventListener('click', addRipple)
    }
  }, [addRipple])

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-[100] pointer-events-none"
    />
  )
}
