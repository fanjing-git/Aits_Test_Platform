import request from './request'

export function listPromptConfigs(params = {}) {
  return request.get('/api/configs/prompts/', { params })
}

export function createPromptConfig(payload) {
  return request.post('/api/configs/prompts/', payload)
}

export function updatePromptConfig(id, payload) {
  return request.patch(`/api/configs/prompts/${id}/`, payload)
}

export function deletePromptConfig(id) {
  return request.delete(`/api/configs/prompts/${id}/`)
}

export function previewPromptConfig(id, variables) {
  return request.post(`/api/configs/prompts/${id}/preview/`, { variables })
}

export function getPromptHistory(id) {
  return request.get(`/api/configs/prompts/${id}/history/`)
}

export function rollbackPromptConfig(id, version) {
  return request.post(`/api/configs/prompts/${id}/rollback/`, { version })
}
