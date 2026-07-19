import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'
import type { LoginRequest, User } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!localStorage.getItem('access_token'))

  function clearSession() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    user.value = null
    error.value = null
  }

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
        clearSession()
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
    // Clear local session first so navigation/guards cannot bounce back into the app.
    const hadToken = !!localStorage.getItem('access_token')
    clearSession()
    try {
      const { useNotificationStore } = await import('@/stores/notifications')
      useNotificationStore().stopPolling()
      useNotificationStore().closePanel()
    } catch {
      /* optional */
    }
    if (!hadToken) return
    try {
      await authApi.logout()
    } catch {
      /* Server logout is best-effort; local session is already cleared. */
    }
  }

  return { user, loading, error, isAuthenticated, login, fetchUser, logout, clearSession }
})
