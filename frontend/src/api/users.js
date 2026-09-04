import request from './request'

export function listUsers() {
  return request.get('/api/auth/users/')
}

export function updateUser(id, payload) {
  return request.patch(`/api/auth/users/${id}/`, payload)
}
