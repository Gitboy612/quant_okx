import client from './client'
import type { UserSettings } from '../types'

export function getSettings() {
  return client.get<UserSettings>('/settings')
}

export function saveSettings(data: Record<string, string>) {
  return client.put('/settings', data)
}

export const getProxySettings = () => client.get('/settings/proxy')
export const saveProxySettings = (data: { proxy_enabled?: boolean; proxy_url?: string; proxy_embedded_port?: string }) =>
  client.put('/settings/proxy', data)
export const testProxy = (proxy_url: string) =>
  client.post('/settings/proxy/test', { proxy_url })
export const importProxyConfig = (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return client.post('/settings/proxy/config/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const getSampleConfigs = () => client.get('/settings/proxy/sample-configs')
export const importSampleConfig = (path: string) => client.post('/settings/proxy/sample-configs/import', { path })

export const getProxyStatus = () => client.get('/settings/proxy/status')
export const startProxy = (data?: { config_path?: string; port?: number; bootstrap_proxy?: string }) => client.post('/settings/proxy/start', data || {})
export const stopProxy = () => client.post('/settings/proxy/stop')
export const getMmdbStatus = () => client.get('/settings/proxy/mmdb-status')

export interface RateLimitStatus {
  remaining: number | null
  limit: number | null
  percentage: number | null
}

export const getRateLimitStatus = () => client.get<RateLimitStatus>('/settings/rate-limit')
