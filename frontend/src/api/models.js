import request from './request'

export function getModelCatalog() {
  return request.get('/api/configs/models/catalog/')
}

export function discoverModels(payload) {
  return request.post('/api/configs/models/discover/', payload, { timeout: 15_000 })
}

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

export function testModelConnection(id, mode = 'catalog') {
  return request.post(`/api/configs/models/${id}/test-connection/`, { mode }, { timeout: 35_000 })
}

export function getModelUsage(id) {
  return request.get(`/api/configs/models/${id}/usage/`)
}

export function listRoutingMatrix() {
  return request.get('/api/configs/routing-policies/matrix/')
}

export function upsertRoutingPolicy(payload) {
  return request.post('/api/configs/routing-policies/upsert/', payload)
}
