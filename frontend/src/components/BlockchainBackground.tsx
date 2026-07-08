import { useEffect, useRef, useCallback } from 'react'

/* ---------- Types ---------- */
interface TokenNode {
  symbol: string
  name: string
  color: string
  x: number
  y: number
  vx: number
  vy: number
  baseRadius: number
  radius: number
  opacity: number
  hovered: boolean
  dragging: boolean
  clickScale: number
  clickPulseRadius: number
  price: string
  change24h: string
  changePositive: boolean
  marketCap: string
  img: HTMLImageElement | null
  imgLoaded: boolean
}

interface Dot {
  x: number
  y: number
  vx: number
  vy: number
  opacity: number
}

interface Star {
  x: number
  y: number
  z: number
  speed: number
  size: number
  brightness: number
}

/* ---------- Token Meta (14 tokens, price data via API) ---------- */
const TOKEN_META = [
  { symbol: 'BTC', name: 'Bitcoin', color: '#F7931A', imgSrc: new URL('../assets/btc.png', import.meta.url).href, marketCap: '$1.33T' },
  { symbol: 'ETH', name: 'Ethereum', color: '#627EEA', imgSrc: new URL('../assets/eth.png', import.meta.url).href, marketCap: '$468B' },
  { symbol: 'AVAX', name: 'Avalanche', color: '#E84142', imgSrc: new URL('../assets/avax.jpg', import.meta.url).href, marketCap: '$14.2B' },
  { symbol: 'LINK', name: 'Chainlink', color: '#2A5ADA', imgSrc: new URL('../assets/link.png', import.meta.url).href, marketCap: '$8.7B' },
  { symbol: 'SOL', name: 'Solana', color: '#00FFA3', imgSrc: new URL('../assets/sol.png', import.meta.url).href, marketCap: '$79B' },
  { symbol: 'HYPE', name: 'Hyperliquid', color: '#FF3E6C', imgSrc: new URL('../assets/hype.jpg', import.meta.url).href, marketCap: '$9.1B' },
  { symbol: 'OKB', name: 'OKB', color: '#00D4AA', imgSrc: new URL('../assets/okb.jpg', import.meta.url).href, marketCap: '$3.2B' },
  { symbol: 'BNB', name: 'BNB', color: '#F3BA2F', imgSrc: new URL('../assets/bnb.png', import.meta.url).href, marketCap: '$94B' },
  { symbol: 'ADA', name: 'Cardano', color: '#0033AD', imgSrc: new URL('../assets/ada.png', import.meta.url).href, marketCap: '$16.2B' },
  { symbol: 'DOGE', name: 'Dogecoin', color: '#C2A633', imgSrc: new URL('../assets/doge.png', import.meta.url).href, marketCap: '$23.5B' },
  { symbol: 'TRX', name: 'TRON', color: '#FF0013', imgSrc: new URL('../assets/trx.png', import.meta.url).href, marketCap: '$8.7B' },
  { symbol: 'USDT', name: 'Tether', color: '#26A17B', imgSrc: new URL('../assets/usdt.png', import.meta.url).href, marketCap: '$144B' },
  { symbol: 'XRP', name: 'Ripple', color: '#00AAE4', imgSrc: new URL('../assets/xrp.png', import.meta.url).href, marketCap: '$28.9B' },
  { symbol: 'XLM', name: 'Stellar', color: '#14B6E7', imgSrc: new URL('../assets/xlm.jpg', import.meta.url).href, marketCap: '$3.2B' },
]

const DOT_COUNT = 25
const CONNECTION_DIST = 150
const STAR_COUNT = 600
const STAR_LAYERS = 5
const RESTING_OPACITY = 0.28

/* ---------- Preload images ---------- */
const preloadedImages: Record<string, HTMLImageElement> = {}
TOKEN_META.forEach((t) => {
  const img = new Image()
  img.src = t.imgSrc
  preloadedImages[t.symbol] = img
})

/* ---------- Draw circular clipped image ---------- */
function drawTokenImage(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement | null,
  x: number,
  y: number,
  r: number,
  opacity: number
) {
  if (!img || !img.complete || img.naturalWidth === 0) return false
  ctx.save()
  ctx.globalAlpha = opacity
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.clip()
  ctx.drawImage(img, x - r, y - r, r * 2, r * 2)
  ctx.restore()
  return true
}

/* ---------- Init stars ---------- */
function initStars(w: number, h: number): Star[] {
  const stars: Star[] = []
  const cx = w / 2
  const cy = h / 2
  for (let i = 0; i < STAR_COUNT; i++) {
    const layer = Math.floor(Math.random() * STAR_LAYERS)
    const depthFactor = layer / (STAR_LAYERS - 1) // 0=near, 1=far
    stars.push({
      x: cx + (Math.random() - 0.5) * 120,
      y: cy + (Math.random() - 0.5) * 120,
      z: 1 - depthFactor, // near=1(fast/big), far=0(slow/small)
      speed: 0.2 + depthFactor * 0.15, // far slower: 0.2-0.35
      size: Math.max(0.3, 1.6 - depthFactor * 0.35), // far smaller: 0.3-1.6
      brightness: Math.max(0.1, 0.6 - depthFactor * 0.12), // far dimmer
    })
  }
  return stars
}

/* ---------- Price utilities ---------- */
interface PriceSnapshot {
  price: string
  change24h: string
  changePositive: boolean
}

const PRICE_CACHE_KEY = 'okx_bg_prices_v1'

function loadPriceCache(): Record<string, PriceSnapshot> | null {
  try {
    const raw = localStorage.getItem(PRICE_CACHE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return null
}

function savePriceCache(data: Record<string, PriceSnapshot>) {
  try {
    localStorage.setItem(PRICE_CACHE_KEY, JSON.stringify(data))
  } catch { /* ignore */ }
}

function formatPrice(price: number): string {
  if (price >= 10000) return '$' + Math.round(price).toLocaleString('en-US')
  if (price >= 1) return '$' + price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (price >= 0.1) return '$' + price.toFixed(3)
  if (price >= 0.01) return '$' + price.toFixed(4)
  return '$' + price.toFixed(6)
}

export default function BlockchainBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const tokensRef = useRef<TokenNode[]>([])
  const dotsRef = useRef<Dot[]>([])
  const starsRef = useRef<Star[]>([])
  const mouseRef = useRef({ x: -1000, y: -1000 })
  const hoveredTokenRef = useRef<TokenNode | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const initializedRef = useRef(false)
  const dragStateRef = useRef<{
    active: boolean
    token: TokenNode | null
    offsetX: number
    offsetY: number
    startX: number
    startY: number
  }>({ active: false, token: null, offsetX: 0, offsetY: 0, startX: 0, startY: 0 })

  const initNodes = useCallback((w: number, h: number) => {
    const cachedPrices = loadPriceCache()
    tokensRef.current = TOKEN_META.map((t, i) => {
      const angle = (Math.PI * 2 / TOKEN_META.length) * i + (i * 0.3)
      const dist = Math.min(w, h) * 0.24 + Math.random() * Math.min(w, h) * 0.16
      let price = '---'
      let change24h = '---'
      let changePositive = true
      if (t.symbol === 'USDT') {
        price = '$1.00'
        change24h = '+0.00%'
      } else if (cachedPrices && cachedPrices[t.symbol]) {
        price = cachedPrices[t.symbol].price
        change24h = cachedPrices[t.symbol].change24h
        changePositive = cachedPrices[t.symbol].changePositive
      }
      return {
        symbol: t.symbol,
        name: t.name,
        color: t.color,
        marketCap: t.marketCap,
        price,
        change24h,
        changePositive,
        x: w / 2 + Math.cos(angle) * dist,
        y: h / 2 + Math.sin(angle) * dist,
        vx: (Math.random() - 0.5) * 0.1,
        vy: (Math.random() - 0.5) * 0.1,
        baseRadius: 18,
        radius: 18,
        opacity: 0,
        hovered: false,
        dragging: false,
        clickScale: 0,
        clickPulseRadius: 0,
        img: preloadedImages[t.symbol] || null,
        imgLoaded: false,
      } as TokenNode
    })

    dotsRef.current = Array.from({ length: DOT_COUNT }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      opacity: Math.random() * 0.2 + 0.08,
    }))

    starsRef.current = initStars(w, h)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let animId: number
    let w = 0, h = 0

    // Create tooltip
    const tooltip = document.createElement('div')
    tooltip.className = 'token-tooltip token-tooltip-enter'
    tooltip.style.display = 'none'
    document.body.appendChild(tooltip)
    tooltipRef.current = tooltip

    const resize = () => {
      w = canvas!.width = window.innerWidth
      h = canvas!.height = window.innerHeight
      if (!initializedRef.current) {
        initNodes(w, h)
        initializedRef.current = true
      }
    }
    resize()
    window.addEventListener('resize', resize)

    /* ---- Tooltip helpers ---- */
    const showTooltip = (token: TokenNode, mx: number, my: number, pinned: boolean) => {
      const imgHtml = token.img && token.img.complete
        ? `<img src="${token.img.src}" style="width:28px;height:28px;border-radius:50%;border:1.5px solid ${token.color}50;" />`
        : `<div style="width:28px;height:28px;border-radius:50%;background:${token.color}20;border:1.5px solid ${token.color}50;display:flex;align-items:center;justify-content:center;"><span style="font-size:10px;font-weight:700;color:${token.color};font-family:'JetBrains Mono',monospace;">${token.symbol.slice(0, 2)}</span></div>`

      tooltip.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
          ${imgHtml}
          <div>
            <div style="font-size:14px;font-weight:600;color:#EDF0F7;line-height:1.2;">${token.symbol}</div>
            <div style="font-size:11px;color:#7B86A2;line-height:1.3;">${token.name}</div>
          </div>
        </div>
        <div style="font-size:16px;font-weight:700;color:#EDF0F7;font-family:'JetBrains Mono',monospace;letter-spacing:-0.02em;">${token.price}</div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
          <span style="font-size:12px;color:${token.changePositive ? '#00D4AA' : '#FF4060'};font-weight:600;font-family:'JetBrains Mono',monospace;">${token.change24h} 24h</span>
          <span style="font-size:11px;color:#505C78;">MCap ${token.marketCap}</span>
        </div>
        ${pinned ? '<div style="font-size:10px;color:#505C78;text-align:center;margin-top:8px;border-top:1px solid rgba(0,212,170,0.08);padding-top:6px;">Click elsewhere to dismiss</div>' : ''}
      `
      tooltip.style.display = 'block'
      tooltip.style.left = `${Math.min(mx + 20, w - 200)}px`
      tooltip.style.top = `${Math.min(my - 20, h - 160)}px`
      tooltip.className = 'token-tooltip token-tooltip-visible'
    }

    const hideTooltip = () => {
      if (hoveredTokenRef.current) return
      tooltip.className = 'token-tooltip token-tooltip-enter'
      setTimeout(() => {
        if (tooltip.className.includes('enter')) tooltip.style.display = 'none'
      }, 200)
    }

    /* ---- Mouse events ---- */
    const onMouseDown = (e: MouseEvent) => {
      const tokens = tokensRef.current
      for (let i = tokens.length - 1; i >= 0; i--) {
        const token = tokens[i]
        const dx = e.clientX - token.x
        const dy = e.clientY - token.y
        if (Math.sqrt(dx * dx + dy * dy) < token.radius * 1.8) {
          dragStateRef.current = {
            active: true,
            token,
            offsetX: dx,
            offsetY: dy,
            startX: e.clientX,
            startY: e.clientY,
          }
          token.dragging = true
          e.preventDefault()
          return
        }
      }
    }

    const onMouseMove = (e: MouseEvent) => {
      mouseRef.current.x = e.clientX
      mouseRef.current.y = e.clientY

      if (dragStateRef.current.active && dragStateRef.current.token) {
        const token = dragStateRef.current.token
        token.x = e.clientX - dragStateRef.current.offsetX
        token.y = e.clientY - dragStateRef.current.offsetY
        token.x = Math.max(30, Math.min(w - 30, token.x))
        token.y = Math.max(30, Math.min(h - 30, token.y))
      }
    }

    const onMouseUp = (e: MouseEvent) => {
      if (dragStateRef.current.active && dragStateRef.current.token) {
        const token = dragStateRef.current.token
        const moved = Math.abs(e.clientX - dragStateRef.current.startX) +
                      Math.abs(e.clientY - dragStateRef.current.startY)
        token.dragging = false
        token.vx = (Math.random() - 0.5) * 0.06
        token.vy = (Math.random() - 0.5) * 0.06
        dragStateRef.current = { active: false, token: null, offsetX: 0, offsetY: 0, startX: 0, startY: 0 }

        // If barely moved, treat as click (pin tooltip)
        if (moved < 5) {
          if (hoveredTokenRef.current === token) {
            hoveredTokenRef.current = null
            tooltip.style.display = 'none'
          } else {
            hoveredTokenRef.current = token
            showTooltip(token, e.clientX, e.clientY, true)
          }
        }
        return
      }
      // Click empty space dismisses pinned tooltip
      if (hoveredTokenRef.current) {
        hoveredTokenRef.current = null
        tooltip.style.display = 'none'
      }
    }

    window.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    /* ---- Draw loop ---- */
    const draw = () => {
      ctx!.clearRect(0, 0, w, h)
      const cx = w / 2
      const cy = h / 2
      const time = Date.now() * 0.001

      const tokens = tokensRef.current
      const dots = dotsRef.current
      const stars = starsRef.current

      // ====== LAYER 1: Starfield (bottom) ======
      stars.forEach((star) => {
        const dx = star.x - cx
        const dy = star.y - cy
        const dist = Math.sqrt(dx * dx + dy * dy)

        if (dist > 1) {
          const moveSpeed = star.speed * star.z
          star.x += (dx / dist) * moveSpeed
          star.y += (dy / dist) * moveSpeed
        }

        // Reset to center when leaving screen
        if (star.x < -20 || star.x > w + 20 || star.y < -20 || star.y > h + 20) {
          star.x = cx + (Math.random() - 0.5) * 80
          star.y = cy + (Math.random() - 0.5) * 80
        }

        // Twinkle
        const twinkle = Math.sin(time * 2 + star.x * 0.01 + star.y * 0.01) * 0.15 + 0.85

        ctx!.beginPath()
        ctx!.arc(star.x, star.y, star.size, 0, Math.PI * 2)
        ctx!.fillStyle = `rgba(200, 220, 255, ${star.brightness * twinkle})`
        ctx!.fill()
      })

      // ====== LAYER 2: Token-to-token connections ======
      for (let i = 0; i < tokens.length; i++) {
        for (let j = i + 1; j < tokens.length; j++) {
          const dx = tokens[i].x - tokens[j].x
          const dy = tokens[i].y - tokens[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < 280) {
            const baseOpacity = (1 - dist / 280) * 0.04
            const boost = (tokens[i].hovered || tokens[j].hovered) ? 0.05 : 0
            ctx!.beginPath()
            ctx!.strokeStyle = `rgba(0, 212, 170, ${baseOpacity + boost})`
            ctx!.lineWidth = 0.4 + boost * 2
            ctx!.setLineDash([3, 5])
            ctx!.moveTo(tokens[i].x, tokens[i].y)
            ctx!.lineTo(tokens[j].x, tokens[j].y)
            ctx!.stroke()
            ctx!.setLineDash([])

            // Data packet
            if (dist < 220) {
              const speed = 0.0003 + i * 0.00008
              const t = ((Date.now() * speed) % 1 + 1) % 1
              const px = tokens[i].x + (tokens[j].x - tokens[i].x) * t
              const py = tokens[i].y + (tokens[j].y - tokens[i].y) * t
              ctx!.beginPath()
              ctx!.arc(px, py, 1.2, 0, Math.PI * 2)
              ctx!.fillStyle = `rgba(0, 212, 170, ${(baseOpacity + boost) * 5})`
              ctx!.fill()
            }
          }
        }
      }

      // ====== LAYER 3: Dot connections ======
      for (let i = 0; i < dots.length; i++) {
        for (let j = i + 1; j < dots.length; j++) {
          const dx = dots[i].x - dots[j].x
          const dy = dots[i].y - dots[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < CONNECTION_DIST) {
            ctx!.beginPath()
            ctx!.strokeStyle = `rgba(0, 212, 170, ${(1 - dist / CONNECTION_DIST) * 0.03})`
            ctx!.lineWidth = 0.3
            ctx!.moveTo(dots[i].x, dots[i].y)
            ctx!.lineTo(dots[j].x, dots[j].y)
            ctx!.stroke()
          }
        }
      }

      // ====== LAYER 3b: Draw dots ======
      dots.forEach((d) => {
        ctx!.beginPath()
        ctx!.arc(d.x, d.y, 1, 0, Math.PI * 2)
        ctx!.fillStyle = `rgba(0, 212, 170, ${d.opacity})`
        ctx!.fill()
        d.x += d.vx
        d.y += d.vy
        if (d.x < 0 || d.x > w) d.vx *= -1
        if (d.y < 0 || d.y > h) d.vy *= -1
      })

      // ====== LAYER 4: Token nodes ======
      let hoveredAny = false

      tokens.forEach((token) => {
        // Check image load
        if (token.img && token.img.complete && token.img.naturalWidth > 0) {
          token.imgLoaded = true
        }

        const dx = mouseRef.current.x - token.x
        const dy = mouseRef.current.y - token.y
        const mouseDist = Math.sqrt(dx * dx + dy * dy)
        const isHovered = mouseDist < token.baseRadius * 2.2
        token.hovered = isHovered
        if (isHovered) hoveredAny = true

        // Opacity: resting = 0.28, hovered = 1.0
        const targetOpacity = isHovered ? 1.0 : RESTING_OPACITY
        token.opacity += (targetOpacity - token.opacity) * 0.08

        // Smooth radius
        const targetRadius = isHovered ? token.baseRadius * 1.4 : token.baseRadius
        token.radius += (targetRadius - token.radius) * 0.1

        // Click pulse decay
        if (token.clickScale > 0.01) {
          token.clickScale *= 0.93
          token.clickPulseRadius += 2.5
        } else {
          token.clickScale = 0
        }

        // Movement (skip if dragging)
        if (!token.dragging) {
          token.x += token.vx
          token.y += token.vy
          const pad = 60
          if (token.x < pad || token.x > w - pad) token.vx *= -1
          if (token.y < pad || token.y > h - pad) token.vy *= -1
          token.x = Math.max(pad, Math.min(w - pad, token.x))
          token.y = Math.max(pad, Math.min(h - pad, token.y))
        }

        const r = token.radius
        const op = token.opacity

        // 1) Click pulse ring
        if (token.clickScale > 0.01) {
          ctx!.beginPath()
          ctx!.arc(token.x, token.y, token.clickPulseRadius, 0, Math.PI * 2)
          const alpha = Math.floor(token.clickScale * 100).toString(16).padStart(2, '0')
          ctx!.strokeStyle = token.color + alpha
          ctx!.lineWidth = 2 * token.clickScale
          ctx!.stroke()
        }

        // 2) Outer glow
        const glowR = r * (isHovered ? 3.5 : 2.0)
        const glow = ctx!.createRadialGradient(token.x, token.y, r * 0.8, token.x, token.y, glowR)
        glow.addColorStop(0, token.color + (isHovered ? '20' : '08'))
        glow.addColorStop(1, token.color + '00')
        ctx!.beginPath()
        ctx!.arc(token.x, token.y, glowR, 0, Math.PI * 2)
        ctx!.fillStyle = glow
        ctx!.fill()

        // 3) Circle border + bg
        ctx!.beginPath()
        ctx!.arc(token.x, token.y, r + 1, 0, Math.PI * 2)
        ctx!.fillStyle = isHovered ? token.color + '18' : 'rgba(5, 7, 17, 0.5)'
        ctx!.fill()
        ctx!.strokeStyle = isHovered ? token.color + '60' : token.color + '18'
        ctx!.lineWidth = isHovered ? 1.5 : 0.8
        ctx!.stroke()

        // 4) Token image (circular clipped)
        const hasImage = drawTokenImage(ctx!, token.imgLoaded ? token.img : null, token.x, token.y, r, op)
        if (!hasImage) {
          ctx!.font = `700 ${isHovered ? 11 : 9}px 'JetBrains Mono', monospace`
          ctx!.textAlign = 'center'
          ctx!.textBaseline = 'middle'
          ctx!.fillStyle = token.color + 'CC'
          ctx!.fillText(token.symbol, token.x, token.y)
        }

        // 5) Hover info (only when hovered enough)
        if (isHovered && op > 0.7) {
          const infoOpacity = Math.min(1, (op - 0.7) / 0.3)
          ctx!.font = "600 11px 'Inter', sans-serif"
          ctx!.textAlign = 'center'
          ctx!.textBaseline = 'top'
          ctx!.fillStyle = `rgba(237, 240, 247, ${infoOpacity * 0.8})`
          ctx!.fillText(token.name, token.x, token.y + r + 12)
          ctx!.font = "600 11px 'JetBrains Mono', monospace"
          ctx!.fillStyle = token.changePositive
            ? `rgba(0, 212, 170, ${infoOpacity * 0.9})`
            : `rgba(255, 64, 96, ${infoOpacity * 0.9})`
          ctx!.fillText(token.change24h, token.x, token.y + r + 26)
        }
      })

      // ====== Cursor & tooltip management ======
      const isDragging = dragStateRef.current.active
      canvas!.style.pointerEvents = (hoveredAny || isDragging) ? 'auto' : 'none'
      canvas!.style.cursor = isDragging ? 'grabbing' : hoveredAny ? 'grab' : 'none'

      if (hoveredAny && !hoveredTokenRef.current) {
        const ht = tokens.find(t => t.hovered)
        if (ht) showTooltip(ht, mouseRef.current.x, mouseRef.current.y, false)
      } else if (!hoveredAny && !hoveredTokenRef.current) {
        hideTooltip()
      }

      animId = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      tooltip.remove()
    }
  }, [initNodes])

  /* ---------- Fetch live prices ---------- */
  useEffect(() => {
    let active = true

    const fetchPrices = async () => {
      const tokens = tokensRef.current
      if (tokens.length === 0) return

      const fetchable = TOKEN_META.filter(t => t.symbol !== 'USDT').map(t => t.symbol)
      if (fetchable.length === 0) return
      const symbolsParam = fetchable.join(',')

      try {
        const resp = await fetch(`/api/market/spot-tickers?symbols=${encodeURIComponent(symbolsParam)}`)
        const data = await resp.json()
        if (data.code !== '0' || !data.data) return

        const snapshot: Record<string, PriceSnapshot> = {}
        tokens.forEach((token) => {
          const ticker = data.data[token.symbol]
          if (ticker && ticker.last) {
            const priceNum = parseFloat(ticker.last)
            if (!isNaN(priceNum) && priceNum > 0) {
              token.price = formatPrice(priceNum)
              token.change24h = ticker.change24h || '0.00%'
              token.changePositive = !token.change24h.startsWith('-')
              snapshot[token.symbol] = {
                price: token.price,
                change24h: token.change24h,
                changePositive: token.changePositive,
              }
            }
          }
        })
        if (active && Object.keys(snapshot).length > 0) {
          savePriceCache(snapshot)
        }
      } catch {
        /* keep showing cached data */
      }
    }

    fetchPrices()
    const interval = setInterval(fetchPrices, 20000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-0 pointer-events-none"
      style={{ opacity: 1 }}
    />
  )
}
