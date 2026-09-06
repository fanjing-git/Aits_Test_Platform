import request from './request'

export const listRequirementDocuments = (project) => request.get('/api/requirement-documents/', { params: project ? { project } : {} })
export const createRequirementDocument = (payload) => request.post('/api/requirement-documents/', payload, { headers: { 'Content-Type': 'multipart/form-data' } })
export const deleteRequirementDocument = (id) => request.delete(`/api/requirement-documents/${id}/`)
export const parseRequirementDocument = (id) => request.post(`/api/requirement-documents/${id}/parse/`)
export const analyzeRequirementDocument = (id) => request.post(`/api/requirement-documents/${id}/analyze/`)
export const identifyRequirementLinkages = (id) => request.post(`/api/requirement-documents/${id}/linkages/`)
export const analyzeRequirementScreenshot = (id) => request.post(`/api/requirement-documents/${id}/screenshot-analysis/`)
