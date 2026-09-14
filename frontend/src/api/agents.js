import request from './request'

export const listAgents = (params = {}) => request.get('/api/agents/', { params })
export const createAgent = (payload) => request.post('/api/agents/', payload)
export const updateAgent = (id, payload) => request.patch(`/api/agents/${id}/`, payload)
export const deleteAgent = (id) => request.delete(`/api/agents/${id}/`)
export const getAgentHistory = (id) => request.get(`/api/agents/${id}/history/`)
export const rollbackAgent = (id, version) => request.post(`/api/agents/${id}/rollback/`, { version })
export const getAgentOptions = () => request.get('/api/agents/options/')
export const executeAgent = (id, payload) => request.post(`/api/agents/${id}/execute/`, payload)
export const listAgentExecutions = (params = {}) => request.get('/api/agent-executions/', { params })
export const pauseAgentExecution = (id) => request.post(`/api/agent-executions/${id}/pause/`)
export const cancelAgentExecution = (id) => request.post(`/api/agent-executions/${id}/cancel/`)
export const resumeAgentExecution = (id) => request.post(`/api/agent-executions/${id}/resume/`)
