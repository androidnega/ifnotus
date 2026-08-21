import type { User } from '@/types/auth'

const STAFF_ROLES = new Set(['superadmin', 'admin', 'operator', 'viewer', 'customer_care'])

export function isStaffUser(user: Pick<User, 'roles' | 'is_superuser'> | null | undefined): boolean {
  if (!user) return false
  if (user.is_superuser) return true
  return (user.roles ?? []).some((role) => STAFF_ROLES.has(role))
}

/** Paying customer with no staff privileges — portal only. */
export function isPureCustomer(user: Pick<User, 'roles' | 'is_superuser'> | null | undefined): boolean {
  if (!user || user.is_superuser) return false
  const roles = new Set(user.roles ?? [])
  if ([...STAFF_ROLES].some((role) => roles.has(role))) return false
  return roles.has('customer')
}

export function homeRouteNameForUser(
  user: Pick<User, 'roles' | 'is_superuser'> | null | undefined,
): 'dashboard' | 'portal-dashboard' {
  return isPureCustomer(user) ? 'portal-dashboard' : 'dashboard'
}

export function syncPanelFlag(user: Pick<User, 'roles' | 'is_superuser'> | null | undefined): void {
  if (isPureCustomer(user)) {
    localStorage.setItem('ifnotus_portal', '1')
  } else {
    localStorage.removeItem('ifnotus_portal')
  }
}

export function isStaffPath(path: string): boolean {
  if (path === '/' || path === '') return false
  if (
    path.startsWith('/portal') ||
    path.startsWith('/billing') ||
    path.startsWith('/account') ||
    path.startsWith('/login') ||
    path.startsWith('/signup') ||
    path.startsWith('/plans') ||
    path.startsWith('/forgot-password') ||
    path.startsWith('/reset-password')
  ) {
    return false
  }
  return true
}

export function isPortalPath(path: string): boolean {
  return (
    path.startsWith('/portal') ||
    path.startsWith('/billing') ||
    path.startsWith('/account') ||
    path === '/signup'
  )
}
