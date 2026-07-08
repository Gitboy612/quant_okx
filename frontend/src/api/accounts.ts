import client from './client'
import type { Account, BalanceData, Position } from '../types'

export function listAccounts() {
  return client.get<Account[]>('/accounts')
}

export function createAccount(data: {
  name: string
  api_key: string
  secret_key: string
  passphrase?: string
  trade_mode: string
}) {
  return client.post('/accounts', data)
}

export function updateAccount(id: number, data: Record<string, unknown>) {
  return client.put(`/accounts/${id}`, data)
}

export function deleteAccount(id: number) {
  return client.delete(`/accounts/${id}`)
}

export function getAccountBalance(id: number) {
  return client.get<BalanceData>(`/accounts/${id}/balance`)
}

export function getAccountBalanceCached(id: number) {
  return client.get<BalanceData>(`/accounts/${id}/balance/cached`)
}

export function getPositions(accountId: number) {
  return client.get<Position[]>(`/accounts/${accountId}/positions`)
}
