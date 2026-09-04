import axios from 'axios'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 10_000,
  headers: { Accept: 'application/json' },
})

const ACCESS_TOKEN_KEY = 'aits_access_token'
const REFRESH_TOKEN_KEY = 'aits_refresh_token'

request.interceptors.request.use((config) => {
  const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY)
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const originalRequest = error.config
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    const canRefresh = error.response?.status === 401
      && refreshToken
      && !originalRequest?._retried
      && !originalRequest?.url?.includes('/api/auth/refresh/')

    if (canRefresh) {
      originalRequest._retried = true
      try {
        const response = await request.post('/api/auth/refresh/', { refresh: refreshToken })
        localStorage.setItem(ACCESS_TOKEN_KEY, response.access)
        originalRequest.headers.Authorization = `Bearer ${response.access}`
        return request(originalRequest)
      } catch {
        localStorage.removeItem(ACCESS_TOKEN_KEY)
        localStorage.removeItem(REFRESH_TOKEN_KEY)
      }
    }

    return Promise.reject(error)
  },
)

export default request
