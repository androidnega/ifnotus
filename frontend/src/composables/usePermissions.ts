import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { PermissionKey } from '@/lib/permissions'

export function usePermissions() {
  const auth = useAuthStore()

  const permissions = computed(() => auth.user?.permissions ?? [])

  function can(permission: PermissionKey): boolean {
    if (!auth.isAuthenticated) return false
    if (auth.user?.is_superuser) return true
    // While profile is still loading, keep nav visible; route guards enforce real access.
    if (!auth.user) return true
    return permissions.value.includes(permission)
  }

  return { permissions, can }
}
