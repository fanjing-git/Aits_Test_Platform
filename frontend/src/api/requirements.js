import request from './request'

// Structured analysis may execute several bounded model segments. Keep the
// normal API timeout for page reads, but allow long-running analysis to return
// its structured backend error instead of being aborted by the browser first.
const STRUCTURED_ANALYSIS_TIMEOUT = 10 * 60 * 1000

export const listRequirementDocuments = (project) => request.get('/api/requirement-documents/', { params: project ? { project } : {} })
export const createRequirementDocument = (payload) => request.post('/api/requirement-documents/', payload, { headers: { 'Content-Type': 'multipart/form-data' } })
export const deleteRequirementDocument = (id) => request.delete(`/api/requirement-documents/${id}/`)
export const parseRequirementDocument = (id) => request.post(`/api/requirement-documents/${id}/parse/`)
export const analyzeRequirementDocument = (id, payload = {}) => request.post(`/api/requirement-documents/${id}/analyze/`, payload, { timeout: STRUCTURED_ANALYSIS_TIMEOUT })
export const listRequirementModelOptions = (id) => request.get(`/api/requirement-documents/${id}/model-options/`)
export const identifyRequirementLinkages = (id) => request.post(`/api/requirement-documents/${id}/linkages/`)
export const clearRequirementAnalysis = (id) => request.post(`/api/requirement-documents/${id}/clear-analysis/`)
export const analyzeRequirementScreenshot = (id, payload = {}) => request.post(`/api/requirement-documents/${id}/screenshot-analysis/`, payload, { timeout: STRUCTURED_ANALYSIS_TIMEOUT })
