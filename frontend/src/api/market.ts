import client from './client'

export interface InstrumentInfo {
  instId: string
  ctVal: number
  ctType: string | null
  settleCcy: string | null
  tickSz: string | null
  lotSz: string | null
  minSz: string | null
}

export interface TickerPrice {
  instId: string
  last: string
}

export function getInstrumentInfo(instId: string) {
  return client.get<InstrumentInfo>('/market/instrument', { params: { instId } })
}

export function getTickerPrice(symbol: string) {
  return client.get<{ code: string; msg?: string; data: TickerPrice | null }>('/market/ticker', { params: { symbol } })
}
