import request from './request'

export const listCaseGenerations = (project) => request.get('/api/case-generation/', { params: project ? { project } : {} })
export const listCaseGenerationModelOptions = (feature = 'case_generation') => request.get('/api/case-generation/model-options/', { params: { feature } })
export const generateCaseRecord = (document, model_config_id = '') => request.post('/api/case-generation/', { document, model_config_id })
export const reviewCaseRecord = (id, model_config_id = '') => request.post(`/api/case-generation/${id}/review/`, { model_config_id })
export const selectCaseRecord = (id) => request.post(`/api/case-generation/${id}/select/`)
