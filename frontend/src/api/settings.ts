import client from './client'
import type { UserSettings } from '../types'

export function getSettings() {
  return client.get<UserSettings>('/settings')
}

export function saveSettings(data: Record<string, string>) {
  return client.put('/settings', data)
}

export const getProxySettings = () => client.get('/settings/proxy')
export const saveProxySettings = (data: { proxy_enabled?: boolean; proxy_url?: string }) =>
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
