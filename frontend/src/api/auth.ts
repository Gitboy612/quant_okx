import type { LoginRequest } from '../../types'
import client from './client'

export function login(data: LoginRequest) {
  return client.post('/auth/login', data)
}

export function getMe() {
  return client.get('/auth/me')
}
