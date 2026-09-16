import request from './request'

export const listTestCases = (project) => request.get('/api/test-cases/', { params: { project } })
export const createTestCase = (payload) => request.post('/api/test-cases/', payload)
export const updateTestCase = (id, payload) => request.patch(`/api/test-cases/${id}/`, payload)
export const deleteTestCase = (id) => request.delete(`/api/test-cases/${id}/`)
export const listTestRuns = (project) => request.get('/api/test-runs/', { params: { project } })
export const createTestRun = (payload) => request.post('/api/test-runs/', payload)
export const executeTestRun = (id) => request.post(`/api/test-runs/${id}/execute/`)
export const getTestRunResults = (id) => request.get(`/api/test-runs/${id}/results/`)
