import request from './request'

export function getBootstrapStatus() {
  return request.get('/api/auth/bootstrap/status/')
}

export function bootstrapAdmin(payload) {
  return request.post('/api/auth/bootstrap/', payload)
}
