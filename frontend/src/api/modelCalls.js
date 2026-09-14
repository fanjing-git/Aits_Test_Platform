import request from './request'

export function listModelCallRecords(params = {}) {
  return request.get('/api/configs/models/call-records/', { params })
}
