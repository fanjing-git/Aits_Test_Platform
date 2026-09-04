import request from './request'

export function registerAccount(payload) {
  return request.post('/api/auth/register/', payload)
}

export function loginAccount(payload) {
  return request.post('/api/auth/login/', payload)
}

export function getCurrentUser() {
  return request.get('/api/auth/me/')
}
