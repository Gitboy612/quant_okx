import { useEffect, useState } from 'react'

export function useWebSocket<T>(url: string, onMessage: (data: T) => void) {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}${url}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage(data)
      } catch {
        /* ignore */
      }
    }

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 30000)

    return () => {
      clearInterval(ping)
      ws.close()
    }
  }, [url])

  return { connected }
}

export interface TickerData {
  instId: string
  last: string
  lastSz?: string
  askPx?: string
  askSz?: string
  bidPx?: string
  bidSz?: string
  open24h?: string
  high24h?: string
  low24h?: string
  vol24h?: string
  volCcy24h?: string
  ts?: string
  [key: string]: string | undefined
}

/**
 * Subscribe to real-time ticker updates for a given symbol via the
 * `/ws/market/{symbol}` backend endpoint.
 *
 * Returns the latest ticker data and connection status.  Automatically
 * unsubscribes on unmount or when the symbol changes.
 */
export function useMarketData(symbol: string | null | undefined) {
  const [connected, setConnected] = useState(false)
  const [ticker, setTicker] = useState<TickerData | null>(null)

  useEffect(() => {
    if (!symbol) {
      setConnected(false)
      setTicker(null)
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/market/${encodeURIComponent(symbol)}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'ticker' && msg.data) {
          setTicker(msg.data as TickerData)
        }
      } catch {
        /* ignore */
      }
    }

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 30000)

    return () => {
      clearInterval(ping)
      ws.close()
      setConnected(false)
    }
  }, [symbol])

  return { connected, ticker }
}
