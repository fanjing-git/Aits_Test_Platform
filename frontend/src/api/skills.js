import request from './request'

export const listSkills = (params = {}) => request.get('/api/skills/', { params })
export const createSkill = (payload) => request.post('/api/skills/', payload)
export const updateSkill = (id, payload) => request.patch(`/api/skills/${id}/`, payload)
export const deleteSkill = (id) => request.delete(`/api/skills/${id}/`)
export const toggleSkill = (id) => request.post(`/api/skills/${id}/toggle/`)
