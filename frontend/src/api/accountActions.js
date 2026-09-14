import request from './request'

export function activateAccount(payload) {
  return request.post('/api/auth/activate/', payload)
}

export function resetAccountPassword(payload) {
  return request.post('/api/auth/password-reset/', payload)
}
