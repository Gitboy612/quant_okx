import client from './client'
import type { UserSettings } from '../types'

export function getSettings() {
  return client.get<UserSettings>('/settings')
}

export function saveSettings(data: Record<string, string>) {
  return client.put('/settings', data)
}
