import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'
import type { LoginRequest, LoginResponse, User } from '@/types/auth'
import { homeRouteNameForUser, isPureCustomer, isStaffUser, syncPanelFlag } from '@/lib/roles'

export type LoginResult =
  | { ok: true; home: 'dashboard' | 'portal-dashboard' }
  | {
      ok: false
      challenge?: { challenge_id: string; ip_address?: string | null; message?: string | null }
      totp?: boolean
    }

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  // Must be reactive — localStorage alone does not invalidate Vue computeds.
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))

  const isAuthenticated = computed(() => !!accessToken.value)
  const isStaff = computed(() => isStaffUser(user.value))
  const isCustomerOnly = computed(() => isPureCustomer(user.value))
  const homeRouteName = computed(() => homeRouteNameForUser(user.value))
  const privilegeViewingAs = computed(() => user.value?.privilege_viewing_as || null)
  const canPrivilegeSwitch = computed(
    () => Boolean(user.value?.can_privilege_switch || user.value?.privilege_viewing_as),
  )

  function clearSession() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('ifnotus_portal')
    localStorage.removeItem('tenant_env_id')
    localStorage.removeItem('tenant_domain')
    try {
      sessionStorage.clear()
    } catch {
      /* ignore */
    }
    accessToken.value = null
    user.value = null
    error.value = null
  }

  async function applyTokens(
    data: Pick<LoginResponse, 'access_token' | 'refresh_token'> | import('@/types/auth').TokenResponse,
  ): Promise<'dashboard' | 'portal-dashboard'> {
    if (!data.access_token || !data.refresh_token) {
      error.value = 'Sign in failed. Please try again.'
      throw new Error(error.value)
    }
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    accessToken.value = data.access_token
    // Brief retry: right after IP approval the allowlist may need a moment.
    let lastError: unknown = null
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await fetchUser()
        syncPanelFlag(user.value)
        return homeRouteNameForUser(user.value)
      } catch (e) {
        lastError = e
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)))
      }
    }
    clearSession()
    const axiosErr = lastError as { response?: { data?: { error?: { message?: string } } } }
    error.value =
      axiosErr?.response?.data?.error?.message ??
      'Signed in but failed to load your profile. Please try again.'
    throw new Error(error.value)
  }

  async function login(credentials: LoginRequest): Promise<LoginResult> {
    loading.value = true
    error.value = null
    try {
      const { data } = await authApi.login(credentials)
      if (data.status === 'totp_required') {
        return { ok: false, totp: true }
      }
      if (data.status === 'challenge_required' && data.challenge_id) {
        return {
          ok: false,
          challenge: {
            challenge_id: data.challenge_id,
            ip_address: data.ip_address,
            message: data.message,
          },
        }
      }
      const home = await applyTokens(data)
      return { ok: true, home }
    } catch (e: unknown) {
      const axiosErr = e as { response?: { data?: { error?: { message?: string } } } }
      error.value =
        axiosErr.response?.data?.error?.message ??
        (e instanceof Error ? e.message : 'Sign in failed. Please try again.')
      return { ok: false }
    } finally {
      loading.value = false
    }
  }

  async function verifyDevice(payload: {
    challenge_id: string
    code: string
    device_fingerprint?: string
  }): Promise<{ ok: boolean; home?: 'dashboard' | 'portal-dashboard' }> {
    loading.value = true
    error.value = null
    try {
      const { data } = await authApi.verifyDevice(payload)
      const home = await applyTokens(data)
      return { ok: true, home }
    } catch (e: unknown) {
      const axiosErr = e as { response?: { data?: { error?: { message?: string } } } }
      error.value =
        axiosErr.response?.data?.error?.message ??
        (e instanceof Error ? e.message : 'Invalid or expired approval code.')
      return { ok: false }
    } finally {
      loading.value = false
    }
  }

  async function fetchUser() {
    const { data } = await authApi.me()
    user.value = data
    syncPanelFlag(data)
  }

  async function switchPrivilege(role: string | null) {
    const { data } =
      role == null || role === ''
        ? await authApi.restorePrivilege()
        : await authApi.switchPrivilege(role)
    await applyTokens(data)
  }

  async function logout() {
    // Clear local session first so navigation/guards cannot bounce back into the app.
    const hadToken = !!accessToken.value
    clearSession()
    try {
      const { useNotificationStore } = await import('@/stores/notifications')
      useNotificationStore().stopPolling()
    } catch {
      /* optional */
    }
    if (!hadToken) return
    try {
      void authApi.logout().catch(() => undefined)
    } catch {
      /* Server logout is best-effort; local session is already cleared. */
    }
  }

  return {
    user,
    loading,
    error,
    isAuthenticated,
    isStaff,
    isCustomerOnly,
    homeRouteName,
    privilegeViewingAs,
    canPrivilegeSwitch,
    login,
    verifyDevice,
    fetchUser,
    applyTokens,
    switchPrivilege,
    logout,
    clearSession,
  }
})
