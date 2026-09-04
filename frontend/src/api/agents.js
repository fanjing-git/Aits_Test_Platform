import request from './request'

export const listAgents = (params = {}) => request.get('/api/agents/', { params })
export const createAgent = (payload) => request.post('/api/agents/', payload)
export const updateAgent = (id, payload) => request.patch(`/api/agents/${id}/`, payload)
export const deleteAgent = (id) => request.delete(`/api/agents/${id}/`)
export const getAgentHistory = (id) => request.get(`/api/agents/${id}/history/`)
export const rollbackAgent = (id, version) => request.post(`/api/agents/${id}/rollback/`, { version })
export const getAgentOptions = () => request.get('/api/agents/options/')
