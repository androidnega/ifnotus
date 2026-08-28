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

export function isStaffUser(user: Pick<User, 'roles' | 'is_superuser' | 'privilege_viewing_as'> | null | undefined): boolean {
  if (!user) return false
  if (user.privilege_viewing_as) {
    return STAFF_ROLES.has(user.privilege_viewing_as)
  }
  if (user.is_superuser) return true
  return (user.roles ?? []).some((role) => STAFF_ROLES.has(role))
}

export type CanonicalRole =
  | 'platform_owner'
  | 'platform_admin'
  | 'hosting_operator'
  | 'billing_agent'
  | 'support_agent'
  | 'auditor'
  | 'customer'

export function getCanonicalRole(
  user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined,
): CanonicalRole | null {
  if (!user) return null
  const activeRole = user.privilege_viewing_as || (user.roles?.[0] ?? '')
  if (user.privilege_viewing_as) {
    if (activeRole === 'platform_owner' || activeRole === 'superadmin') return 'platform_owner'
    if (activeRole === 'platform_admin' || activeRole === 'admin') return 'platform_admin'
    if (activeRole === 'hosting_operator' || activeRole === 'operator') return 'hosting_operator'
    if (activeRole === 'billing_agent') return 'billing_agent'
    if (activeRole === 'support_agent' || activeRole === 'customer_care') return 'support_agent'
    if (activeRole === 'auditor' || activeRole === 'viewer') return 'auditor'
    if (activeRole === 'customer') return 'customer'
  }
  if (user.is_superuser) return 'platform_owner'
  const roles = new Set(user.roles ?? [])
  if (roles.has('platform_owner') || roles.has('superadmin')) return 'platform_owner'
  if (roles.has('platform_admin') || roles.has('admin')) return 'platform_admin'
  if (roles.has('hosting_operator') || roles.has('operator')) return 'hosting_operator'
  if (roles.has('billing_agent')) return 'billing_agent'
  if (roles.has('support_agent') || roles.has('customer_care')) return 'support_agent'
  if (roles.has('auditor') || roles.has('viewer')) return 'auditor'
  if (roles.has('customer')) return 'customer'
  return null
}

export function isPlatformOwner(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'platform_owner'
}

export function isPlatformAdmin(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'platform_admin'
}

export function isHostingOperator(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'hosting_operator'
}

export function isBillingAgent(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'billing_agent'
}

export function isSupportAgent(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'support_agent'
}

export function isAuditor(user: (Pick<User, 'roles' | 'is_superuser'> & { privilege_viewing_as?: string | null }) | null | undefined): boolean {
  return getCanonicalRole(user) === 'auditor'
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
