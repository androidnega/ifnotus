import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'
import type { LoginRequest, User } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!localStorage.getItem('access_token'))

  async function login(credentials: LoginRequest): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const { data } = await authApi.login(credentials)
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      try {
        await fetchUser()
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        throw new Error('Signed in but failed to load your profile. Please try again.')
      }
    } catch (e: unknown) {
      const axiosErr = e as { response?: { data?: { error?: { message?: string } } } }
      error.value =
        axiosErr.response?.data?.error?.message ??
        (e instanceof Error ? e.message : 'Sign in failed. Please try again.')
      return false
    } finally {
      loading.value = false
    }
    return true
  }

  async function fetchUser() {
    const { data } = await authApi.me()
    user.value = data
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      user.value = null
    }
  }

  return { user, loading, error, isAuthenticated, login, fetchUser, logout }
})
