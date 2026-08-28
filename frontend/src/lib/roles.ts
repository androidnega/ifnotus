import type { User } from '@/types/auth'

const STAFF_ROLES = new Set([
  'platform_owner',
  'platform_admin',
  'hosting_operator',
  'billing_agent',
  'support_agent',
  'auditor',
  'superadmin',
  'admin',
  'operator',
  'viewer',
  'customer_care',
])

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
  // Strip query/hash so /go/hosting?host=… is classified correctly.
  const bare = path.split('?')[0]?.split('#')[0] || path
  if (
    bare.startsWith('/portal') ||
    bare.startsWith('/billing') ||
    bare.startsWith('/account') ||
    bare.startsWith('/hosting') ||
    bare.startsWith('/go/') ||
    bare.startsWith('/login') ||
    bare.startsWith('/signup') ||
    bare.startsWith('/staff/login') ||
    bare.startsWith('/admin_1') ||
    bare.startsWith('/staff-login') ||
    bare.startsWith('/plans') ||
    bare.startsWith('/forgot-password') ||
    bare.startsWith('/reset-password')
  ) {
    return false
  }
  return true
}

export function isPortalPath(path: string): boolean {
  const bare = path.split('?')[0]?.split('#')[0] || path
  return (
    bare.startsWith('/portal') ||
    bare.startsWith('/billing') ||
    bare.startsWith('/account') ||
    bare.startsWith('/hosting') ||
    bare.startsWith('/go/') ||
    bare === '/signup' ||
    bare === '/login'
  )
}
