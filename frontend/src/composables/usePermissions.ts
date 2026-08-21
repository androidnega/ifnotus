import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { PermissionKey } from '@/lib/permissions'

export function usePermissions() {
  const auth = useAuthStore()

  const permissions = computed(() => auth.user?.permissions ?? [])

  function can(permission: PermissionKey): boolean {
    // Prefer loaded profile over token flag so a stale auth computed cannot blank the nav.
    if (!auth.user && !auth.isAuthenticated) return false
    // While privilege-switched, honor the reduced permission set (ignore raw is_superuser).
    if (auth.user?.privilege_viewing_as) {
      return permissions.value.includes(permission)
    }
    if (auth.user?.is_superuser) return true
    // While profile is still loading, keep nav visible; route guards enforce real access.
    if (!auth.user) return true
    return permissions.value.includes(permission)
  }

  return { permissions, can }
}
