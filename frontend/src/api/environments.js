import request from './request'

export const listEnvironments = (project) => request.get('/api/environments/', { params: { project } })
export const createEnvironment = (payload) => request.post('/api/environments/', payload)
export const updateEnvironment = (id, payload) => request.patch(`/api/environments/${id}/`, payload)
export const deleteEnvironment = (id) => request.delete(`/api/environments/${id}/`)
export const checkEnvironment = (id) => request.post(`/api/environments/${id}/health-check/`)
