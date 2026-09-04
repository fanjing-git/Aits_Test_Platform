import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getCurrentUser, loginAccount, registerAccount } from '../api/auth'

const ACCESS_TOKEN_KEY = 'aits_access_token'
const REFRESH_TOKEN_KEY = 'aits_refresh_token'

export const useUserStore = defineStore('user', () => {
  const user = ref(null)
  const loading = ref(false)
  const accessToken = ref(localStorage.getItem(ACCESS_TOKEN_KEY))
  const isAuthenticated = computed(() => Boolean(accessToken.value))

  function saveTokens(tokens) {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access)
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh)
    accessToken.value = tokens.access
  }

  async function login(credentials) {
    loading.value = true
    try {
      const tokens = await loginAccount(credentials)
      saveTokens(tokens)
      user.value = await getCurrentUser()
      return user.value
    } finally {
      loading.value = false
    }
  }

  async function register(payload) {
    loading.value = true
    try {
      await registerAccount(payload)
      return await login({ account: payload.account, password: payload.password })
    } finally {
      loading.value = false
    }
  }

  async function hydrate() {
    if (!isAuthenticated.value) return false
    try {
      user.value = await getCurrentUser()
      return true
    } catch {
      logout()
      return false
    }
  }

  function logout() {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    accessToken.value = null
    user.value = null
  }

  return { user, loading, isAuthenticated, login, register, hydrate, logout }
})
