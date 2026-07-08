import client from './client'

// 数据清理
export const resetPnl = (data: { account_id?: number; strategy_instance_id?: number }) =>
  client.post('/maintenance/reset-pnl', data)
export const cleanupPnlRecords = (data: { strategy_instance_id?: number; before_date?: string }) =>
  client.post('/maintenance/cleanup/pnl-records', data)
export const cleanupOrderRecords = (data: { strategy_instance_id?: number; status_list?: string[] }) =>
  client.post('/maintenance/cleanup/order-records', data)
export const cleanupStrategyEvents = (data: { strategy_instance_id: number }) =>
  client.post('/maintenance/cleanup/strategy-events', data)

// 数据校正
export const correctEquity = (data: { account_id: number }) =>
  client.post('/maintenance/correct/equity', data)
export const correctUnrealizedPnl = (data: { strategy_instance_id: number }) =>
  client.post('/maintenance/correct/unrealized-pnl', data)
export const correctRealizedPnl = (data: { strategy_instance_id: number }) =>
  client.post('/maintenance/correct/realized-pnl', data)
