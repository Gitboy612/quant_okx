import client from './client'
import type { StrategyEvent } from '../types'

export const getStrategyEvents = (id: number, limit = 100) =>
  client.get<{ total: number; items: StrategyEvent[] }>(`/monitoring/strategy/${id}/events`, { params: { limit } })

export const deleteStrategyEvents = (id: number) =>
  client.delete(`/monitoring/strategy/${id}/events`)

export const exportStrategyEvents = (id: number) =>
  client.get(`/monitoring/strategy/${id}/events/export`, { responseType: 'text' })