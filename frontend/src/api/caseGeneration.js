import request from './request'

export const listCaseGenerations = (project) => request.get('/api/case-generation/', { params: project ? { project } : {} })
export const generateCaseRecord = (document) => request.post('/api/case-generation/', { document })
export const reviewCaseRecord = (id) => request.post(`/api/case-generation/${id}/review/`)
export const selectCaseRecord = (id) => request.post(`/api/case-generation/${id}/select/`)
