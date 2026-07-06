import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { PermissionKey } from '@/lib/permissions'

export function usePermissions() {
  const auth = useAuthStore()

  const permissions = computed(() => auth.user?.permissions ?? [])

  function can(permission: PermissionKey): boolean {
    if (auth.user?.is_superuser) return true
    return permissions.value.includes(permission)
  }

  return { permissions, can }
}
