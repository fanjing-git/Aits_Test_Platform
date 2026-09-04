import request from './request'

export function listModelConfigs() {
  return request.get('/api/configs/models/')
}

export function createModelConfig(payload) {
  return request.post('/api/configs/models/', payload)
}

export function updateModelConfig(id, payload) {
  return request.patch(`/api/configs/models/${id}/`, payload)
}

export function deleteModelConfig(id) {
  return request.delete(`/api/configs/models/${id}/`)
}

export function testModelConnection(id) {
  return request.post(`/api/configs/models/${id}/test-connection/`)
}

export function getModelUsage(id) {
  return request.get(`/api/configs/models/${id}/usage/`)
}
