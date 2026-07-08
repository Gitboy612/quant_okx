import client from './client'
import type { Order } from '../types'

export function listOrders(params: {
  account_id?: number
  strategy_instance_id?: number
  symbol?: string
  status?: string
  limit?: number
}) {
  return client.get<Order[]>('/orders', { params })
}
