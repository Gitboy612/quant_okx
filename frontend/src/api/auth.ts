import type { LoginRequest } from '../types'
import client from './client'

export function login(data: LoginRequest) {
  return client.post('/auth/login', data)
}

export function getSetupStatus() {
  return client.get<{ setup_required: boolean }>('/auth/setup-status')
}

export function completeInitialSetup(data: { password: string; confirm_password: string }) {
  return client.post('/auth/setup', data)
}

export function getMe() {
  return client.get('/auth/me')
}

export function changePassword(data: { old_password: string; new_password: string }) {
  return client.put('/auth/password', data)
}
