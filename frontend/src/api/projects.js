import request from './request'

export const listProjects = () => request.get('/api/projects/')
export const createProject = (payload) => request.post('/api/projects/', payload)
export const updateProject = (id, payload) => request.patch(`/api/projects/${id}/`, payload)
export const deleteProject = (id) => request.delete(`/api/projects/${id}/`)
export const listProjectMembers = (id) => request.get(`/api/projects/${id}/members/`)
export const listMemberCandidates = (id) => request.get(`/api/projects/${id}/member-candidates/`)
export const addProjectMember = (id, payload) => request.post(`/api/projects/${id}/members/`, payload)
export const updateProjectMember = (projectId, memberId, payload) => request.patch(`/api/projects/${projectId}/members/${memberId}/`, payload)
export const deleteProjectMember = (projectId, memberId) => request.delete(`/api/projects/${projectId}/members/${memberId}/`)
