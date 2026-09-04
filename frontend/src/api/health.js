import request from './request'

export function getServiceHealth() {
  return request.get('/api/health/')
}
