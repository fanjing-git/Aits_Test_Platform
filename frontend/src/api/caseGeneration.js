import request from './request'

// Generation and review may contain multiple structured model segments.
const STRUCTURED_GENERATION_TIMEOUT = 10 * 60 * 1000

export const listCaseGenerations = (project) => request.get('/api/case-generation/', { params: project ? { project } : {} })
export const listCaseGenerationModelOptions = (feature = 'case_generation') => request.get('/api/case-generation/model-options/', { params: { feature } })
export const generateCaseRecord = (document, model_config_id = '') => request.post('/api/case-generation/', { document, model_config_id }, { timeout: STRUCTURED_GENERATION_TIMEOUT })
export const reviewCaseRecord = (id, model_config_id = '') => request.post(`/api/case-generation/${id}/review/`, { model_config_id }, { timeout: STRUCTURED_GENERATION_TIMEOUT })
export const selectCaseRecord = (id) => request.post(`/api/case-generation/${id}/select/`)
