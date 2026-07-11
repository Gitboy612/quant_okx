import client from './client'

export type ChannelType = 'email' | 'webhook' | 'telegram'

export interface NotificationRule {
  id: number
  name: string
  event_types: string[]
  channel_type: ChannelType
  channel_config: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string | null
}

export interface NotificationRuleInput {
  name: string
  event_types: string[]
  channel_type: ChannelType
  channel_config: Record<string, unknown>
  is_active?: boolean
}

export interface TestNotificationInput {
  channel_type: ChannelType
  channel_config?: Record<string, unknown>
}

export interface TestNotificationResult {
  ok: boolean
  channel_type: ChannelType
}

export function getRules() {
  return client.get<{ items: NotificationRule[] }>('/notifications/rules')
}

export function createRule(data: NotificationRuleInput) {
  return client.post<NotificationRule>('/notifications/rules', data)
}

export function updateRule(id: number, data: Partial<NotificationRuleInput>) {
  return client.put<NotificationRule>(`/notifications/rules/${id}`, data)
}

export function deleteRule(id: number) {
  return client.delete<{ message: string }>(`/notifications/rules/${id}`)
}

export function testNotification(data: TestNotificationInput) {
  return client.post<TestNotificationResult>('/notifications/test', data)
}
