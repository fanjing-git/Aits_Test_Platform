import request from './request'

export function listUsers() {
  return request.get('/api/auth/users/')
}

export function updateUser(id, payload) {
  return request.patch(`/api/auth/users/${id}/`, payload)
}

export function inviteUser(payload) {
  return request.post('/api/auth/users/', payload)
}

export function resendUserInvitation(id) {
  return request.post(`/api/auth/users/${id}/resend-invitation/`)
}

export function createPasswordResetLink(id) {
  return request.post(`/api/auth/users/${id}/password-reset-link/`)
}

export function revokeUserActions(id) {
  return request.post(`/api/auth/users/${id}/revoke-actions/`)
}

export function listAccountAuditEvents() {
  return request.get('/api/auth/audit-events/')
}
