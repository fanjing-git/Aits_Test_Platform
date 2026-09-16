import request from './request'

export function getDeploymentAccess() {
  return request.get('/api/configs/deployment-access/')
}

export function checkDeploymentAccess() {
  return request.post('/api/configs/deployment-access/check/')
}
