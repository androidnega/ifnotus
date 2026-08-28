import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import {
  homeRouteNameForUser,
  isPortalPath,
  isPureCustomer,
  isStaffPath,
  isStaffUser,
  syncPanelFlag,
} from '@/lib/roles'
import { isCustomerCpanelHost, isStaffPanelHost } from '@/lib/platformHosts'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    guestOnly?: boolean
    /** staff = WHM host panel; portal = customer product panel */
    panel?: 'staff' | 'portal' | 'public'
    permission?: string
    /** Hosting panel deep-link tab (e.g. files route) */
    hostingTab?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/maintenance',
    name: 'maintenance',
    component: () => import('@/views/MaintenanceView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/',
    name: 'home',
    component: () => {
      if (typeof window !== 'undefined' && isCustomerCpanelHost()) {
        return import('@/views/hosting/HostingPanelView.vue')
      }
      return import('@/views/HomeView.vue')
    },
    meta: { panel: 'public' },
  },
  {
    path: '/overview',
    name: 'cpanel-overview',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'overview' },
  },
  {
    path: '/plans',
    name: 'plans',
    component: () => import('@/views/PlansView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/plans/:slug',
    name: 'plan-detail',
    component: () => import('@/views/PlanDetailView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/panel',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/login',
    name: 'login',
    component: () => {
      if (typeof window !== 'undefined' && isStaffPanelHost()) {
        return import('@/views/LoginView.vue')
      }
      return import('@/views/portal/PortalSignupView.vue')
    },
    meta: { guestOnly: true, panel: 'public' },
  },
  {
    path: '/signup',
    name: 'portal-signup',
    component: () => import('@/views/portal/PortalSignupView.vue'),
    meta: { guestOnly: true, panel: 'public' },
  },
  {
    path: '/admin_1',
    redirect: (to) => {
      if (typeof window !== 'undefined' && !isStaffPanelHost()) {
        return { path: '/login', query: to.query }
      }
      return { path: '/login', query: to.query }
    },
  },
  {
    path: '/staff-login',
    redirect: (to) => ({ path: '/login', query: to.query }),
  },
  {
    path: '/staff/login',
    redirect: (to) => ({ path: '/login', query: to.query }),
  },
  {
    path: '/admin-login',
    name: 'admin-login',
    redirect: (to) => ({ path: '/login', query: to.query }),
  },
  {
    path: '/go/hosting',
    name: 'go-hosting',
    component: () => import('@/views/portal/GoHostingView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account',
    name: 'portal-dashboard',
    component: () => import('@/views/portal/PortalDashboardView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/plans',
    name: 'portal-account-plans',
    component: () => import('@/views/portal/PortalAccountPlansView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/invoice/:id',
    name: 'portal-invoice',
    component: () => import('@/views/portal/PortalInvoiceView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/settings',
    name: 'portal-account-settings',
    component: () => import('@/views/portal/PortalAccountSettingsView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/support',
    name: 'portal-support',
    component: () => import('@/views/portal/PortalSupportView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/files',
    name: 'portal-files',
    redirect: (to) => {
      const env = String(to.query.env || '')
      if (env) {
        const q = { ...to.query } as Record<string, string | string[]>
        delete q.env
        return { name: 'hosting-files', params: { environmentId: env }, query: q }
      }
      return { name: 'portal-dashboard' }
    },
  },
  {
    path: '/account/files/upload',
    name: 'portal-file-upload',
    component: () => import('@/views/portal/PortalFileUploadView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/files/edit',
    name: 'portal-file-editor',
    component: () => import('@/views/portal/PortalFileEditorView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/account/database/studio',
    name: 'portal-database-studio',
    component: () => import('@/views/portal/PortalDatabaseStudioView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/hosting/:environmentId',
    name: 'hosting-panel',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
  },
  {
    path: '/hosting/:environmentId/files',
    name: 'hosting-files',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'files' },
  },
  {
    path: '/sso',
    name: 'sso-landing',
    component: () => import('@/views/portal/SsoLandingView.vue'),
    meta: { panel: 'portal' },
  },
  {
    path: '/files',
    name: 'cpanel-files',
    alias: '/files-portal',
    component: () => {
      if (typeof window !== 'undefined' && isCustomerCpanelHost()) {
        return import('@/views/hosting/HostingPanelView.vue')
      }
      return import('@/views/FilesView.vue')
    },
    meta: {
      requiresAuth: true,
      panel: typeof window !== 'undefined' && isCustomerCpanelHost() ? 'portal' : 'staff',
      hostingTab: 'files',
      permission: typeof window !== 'undefined' && isCustomerCpanelHost() ? undefined : 'files:read',
    },
  },
  {
    path: '/filemanager',
    redirect: '/files',
  },
  {
    path: '/file-manager',
    redirect: '/files',
  },
  {
    path: '/databases',
    name: 'cpanel-databases',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'databases' },
  },
  {
    path: '/domains',
    name: 'cpanel-domains',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'domains' },
  },
  {
    path: '/email',
    name: 'cpanel-email',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'email' },
  },
  {
    path: '/apps',
    name: 'cpanel-apps',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'apps' },
  },
  {
    path: '/cron',
    name: 'cpanel-cron',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'cron' },
  },
  {
    path: '/backups',
    name: 'cpanel-backups',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'backups' },
  },
  {
    path: '/logs',
    name: 'cpanel-logs',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'logs' },
  },
  {
    path: '/usage',
    name: 'cpanel-usage',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'usage' },
  },
  {
    path: '/transfer',
    name: 'cpanel-transfer',
    component: () => import('@/views/hosting/HostingPanelView.vue'),
    meta: { requiresAuth: true, panel: 'portal', hostingTab: 'transfer' },
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { guestOnly: true, panel: 'public' },
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('@/views/ResetPasswordView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/monitoring',
    redirect: { name: 'dashboard' },
  },
  {
    path: '/platform/capacity',
    redirect: { name: 'dashboard' },
  },
  {
    path: '/servers',
    name: 'servers',
    component: () => import('@/views/ServersView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'servers:read' },
  },
  {
    path: '/applications',
    name: 'applications',
    component: () => import('@/views/ApplicationsView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'apps:read' },
  },
  {
    path: '/applications/:id',
    name: 'application-detail',
    component: () => import('@/views/ApplicationDetailView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'apps:read' },
  },
  {
    path: '/operations',
    name: 'operations',
    component: () => import('@/views/OperationsView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'system:read' },
  },
  {
    path: '/platform/customers',
    name: 'platform-customers',
    component: () => import('@/views/PlatformCustomersView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:read' },
  },
  {
    path: '/platform/orders',
    name: 'platform-orders',
    component: () => import('@/views/PlatformOrdersView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'billing:view' },
  },
  {
    path: '/platform/orders/:id/receipt',
    name: 'platform-order-receipt',
    component: () => import('@/views/PlatformOrderReceiptView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'billing:view' },
  },
  {
    path: '/platform/accounting',
    name: 'platform-accounting',
    component: () => import('@/views/PlatformAccountingView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'billing:view' },
  },
  {
    path: '/platform/plans',
    name: 'platform-plans',
    component: () => import('@/views/PlatformPlansView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:write' },
  },
  {
    path: '/support',
    name: 'support',
    component: () => import('@/views/SupportTicketsView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'support:read' },
  },
  {
    path: '/domains',
    name: 'domains',
    component: () => import('@/views/DomainsView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'domains:read' },
  },
  {
    path: '/databases',
    name: 'databases',
    component: () => import('@/views/DatabasesView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'databases:read' },
  },
  {
    path: '/databases/studio',
    name: 'database-studio',
    component: () => import('@/views/DatabaseStudioView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'databases:read' },
  },
  {
    path: '/ssl',
    name: 'ssl',
    component: () => import('@/views/SslView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'ssl:read' },
  },
  {
    path: '/admin/mail',
    name: 'mail-admin',
    component: () => import('@/views/MailView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'mail:read' },
  },
  {
    path: '/mail',
    redirect: { name: 'mail-admin' },
  },
  {
    path: '/files/upload',
    name: 'files-upload',
    component: () => import('@/views/FileUploadView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'files:write' },
  },
  {
    path: '/files/edit',
    name: 'file-editor',
    component: () => import('@/views/FileEditorView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'files:read' },
  },
  {
    path: '/terminal/full',
    name: 'terminal-full',
    component: () => import('@/views/TerminalFullscreenView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'terminal:execute' },
  },
  {
    path: '/terminal',
    name: 'terminal',
    component: () => import('@/views/TerminalView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'terminal:execute' },
  },
  {
    path: '/security',
    name: 'security',
    component: () => import('@/views/SecurityView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'system:admin' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'system:read' },
  },
  // Legacy /portal URLs → main site (no /portal in the address bar)
  {
    path: '/portal',
    redirect: { name: 'home' },
  },
  {
    path: '/portal/plans',
    redirect: { name: 'plans' },
  },
  {
    path: '/portal/signup',
    redirect: { name: 'portal-signup' },
  },
  {
    path: '/portal/login',
    name: 'portal-login',
    redirect: (to) => ({ name: 'login', query: to.query }),
  },
  {
    path: '/portal/dashboard',
    redirect: { name: 'portal-dashboard' },
  },
  {
    path: '/portal/support',
    redirect: { name: 'portal-support' },
  },
  {
    path: '/contact',
    name: 'contact',
    component: () => import('@/views/ContactView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/status',
    name: 'status',
    component: () => import('@/views/PublicStatusView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/legal/:slug',
    name: 'legal',
    component: () => import('@/views/LegalView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/privacy',
    redirect: { name: 'legal', params: { slug: 'privacy' } },
  },
  {
    path: '/terms',
    redirect: { name: 'legal', params: { slug: 'terms' } },
  },
  {
    path: '/refunds',
    redirect: { name: 'legal', params: { slug: 'refunds' } },
  },
  {
    path: '/aup',
    redirect: { name: 'legal', params: { slug: 'aup' } },
  },
  {
    path: '/billing/callback',
    redirect: { name: 'legal', params: { slug: 'pay' } },
  },
  {
    path: '/billing/demo-pay',
    redirect: { name: 'legal', params: { slug: 'pay' } },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to) {
    if (to.hash) {
      return { el: to.hash, behavior: 'smooth' }
    }
    return { top: 0 }
  },
})

function safeRedirect(raw: unknown, fallback: string): string {
  const candidate = Array.isArray(raw) ? raw[0] : raw
  if (
    typeof candidate === 'string' &&
    candidate.startsWith('/') &&
    !candidate.startsWith('//') &&
    candidate !== '/login' &&
    candidate !== '/signup' &&
    candidate !== '/admin_1' &&
    candidate !== '/portal/login'
  ) {
    return candidate
  }
  return fallback
}

function loginRouteForTarget(toPath: string, panel: unknown) {
  // Tenant hosting SSO / panel → panel username+password login (not staff).
  if (toPath.startsWith('/go/hosting') || toPath.startsWith('/hosting')) {
    const hostMatch = /[?&]host=([^&]+)/.exec(toPath)
    const host = hostMatch ? decodeURIComponent(hostMatch[1]) : ''
    return {
      name: 'login' as const,
      query: {
        mode: 'panel',
        redirect: toPath,
        ...(host ? { host } : {}),
      },
    }
  }
  if (panel === 'portal' || toPath.startsWith('/go/') || toPath.startsWith('/account')) {
    return { name: 'login' as const, query: { redirect: toPath } }
  }
  if (panel === 'staff' || isStaffPath(toPath) || isStaffPanelHost()) {
    return { name: 'login' as const, query: { redirect: toPath } }
  }
  return { name: 'login' as const, query: { redirect: toPath } }
}

router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')

  // Custom-domain panel host (cpanel.customer.com): stay on this origin — never bounce to ifnotus.space.
  if (isCustomerCpanelHost()) {
    if (to.name === 'sso-landing' || to.path === '/sso') {
      return true
    }
    // Account, billing, settings, support, and invoices NEVER exist on customer domains.
    if (
      to.path === '/account' ||
      to.path.startsWith('/account/') ||
      to.path === '/billing' ||
      to.path === '/invoices' ||
      to.path.startsWith('/invoice/') ||
      to.path === '/support' ||
      to.path === '/settings' ||
      to.path === '/profile'
    ) {
      if (typeof window !== 'undefined') {
        window.location.href = `https://ifnotus.space${to.fullPath}`
        return false
      }
    }
    if (to.path.startsWith('/hosting/')) {
      if (to.path.endsWith('/files')) {
        return '/files'
      }
      return '/'
    }
    if (
      to.path === '/' ||
      to.name === 'home' ||
      to.name === 'plans' ||
      to.name === 'plan-detail' ||
      to.name === 'portal-signup' ||
      to.name === 'admin-login'
    ) {
      if (!token) {
        if (to.name === 'login') return true
        return {
          name: 'login',
          query: { redirect: '/' },
        }
      }
      // Stays on clean root hosting panel on cpanel.<domain>
      if (to.path !== '/') {
        return '/'
      }
    }
    // Ensure session is valid on customer cpanel hosts.
    if (token && to.meta.requiresAuth) {
      const { useAuthStore } = await import('@/stores/auth')
      const { isPureCustomer, isStaffUser } = await import('@/lib/roles')
      const auth = useAuthStore()
      if (!auth.user) {
        try {
          await auth.fetchUser()
        } catch {
          auth.clearSession()
          return {
            name: 'login',
            query: { redirect: to.fullPath || '/' },
          }
        }
      }
      if (isStaffUser(auth.user) && !isPureCustomer(auth.user)) {
        const roles = new Set(auth.user?.roles ?? [])
        if (!roles.has('customer')) {
          auth.clearSession()
          return {
            name: 'login',
            query: {
              redirect: to.fullPath || '/',
              reason: 'customer_panel',
            },
          }
        }
      }
      return true
    }
    if (!token && to.meta.requiresAuth) {
      return {
        name: 'login',
        query: { redirect: to.fullPath || '/' },
      }
    }
    return true
  }

  if (isStaffPanelHost()) {
    if (to.path === '/' || to.name === 'home' || to.name === 'plans' || to.name === 'portal-signup') {
      if (!token) {
        if (to.name === 'login') return true
        return { name: 'login' }
      }
      return { name: 'dashboard' }
    }
  }

  // Public maintenance gate (staff login and API stay available).
  if (
    to.name !== 'maintenance' &&
    to.name !== 'login' &&
    to.meta.panel === 'public'
  ) {
    try {
      const { catalogApi } = await import('@/api')
      const { data } = await catalogApi.meta()
      if (data.maintenance_mode) {
        return { name: 'maintenance' }
      }
    } catch {
      /* allow browse if meta fails */
    }
  }

  if (to.meta.requiresAuth && !token) {
    return loginRouteForTarget(to.fullPath, to.meta.panel)
  }

  if (to.meta.guestOnly && token) {
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    if (!auth.user) {
      try {
        await auth.fetchUser()
      } catch {
        auth.clearSession()
        return true
      }
    }
    syncPanelFlag(auth.user)
    const home = homeRouteNameForUser(auth.user)
    const preferred = safeRedirect(to.query.redirect, '')
    if (preferred) {
      if (isPureCustomer(auth.user) && isStaffPath(preferred)) {
        return { name: 'portal-dashboard' }
      }
      if (isStaffUser(auth.user) && !isPureCustomer(auth.user) && isPortalPath(preferred) && preferred.includes('/dashboard')) {
        // staff may open portal if they have a customer profile; allow
        return preferred
      }
      if (isPureCustomer(auth.user) && (isPortalPath(preferred) || preferred.startsWith('/portal'))) {
        return preferred
      }
      if (isStaffUser(auth.user) && isStaffPath(preferred)) {
        return preferred
      }
    }
    return { name: home }
  }

  if (token && to.meta.requiresAuth) {
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    if (!auth.user) {
      try {
        await auth.fetchUser()
      } catch {
        auth.clearSession()
        return loginRouteForTarget(to.fullPath, to.meta.panel)
      }
    }
    syncPanelFlag(auth.user)

    const panel = to.meta.panel
    if (panel === 'staff' && isPureCustomer(auth.user)) {
      return { name: 'portal-dashboard' }
    }
    if (panel === 'portal' && isStaffUser(auth.user) && !isPureCustomer(auth.user)) {
      // Staff without a customer profile stay in WHM. Anyone with a linked
      // customer account (incl. superadmin demo) may open portal invoices.
      const roles = new Set(auth.user?.roles ?? [])
      if (
        !roles.has('customer') &&
        !auth.user?.is_superuser &&
        !roles.has('superadmin') &&
        !roles.has('admin')
      ) {
        return { name: 'dashboard' }
      }
    }

    const requiredPermission = to.meta.permission
    if (requiredPermission) {
      const perms = auth.user?.permissions ?? []
      const fullSuper = Boolean(auth.user?.is_superuser && !auth.user?.privilege_viewing_as)
      if (!fullSuper && !perms.includes(requiredPermission)) {
        return { name: homeRouteNameForUser(auth.user) }
      }
    }

    // Role-boundary enforcement (prevents platform_admin infrastructure pollution and support_agent financial leaks)
    const { getCanonicalRole } = await import('@/lib/roles')
    const role = getCanonicalRole(auth.user)
    const targetPath = to.path || ''

    if (role === 'platform_admin') {
      const infraRoutes = ['/files', '/servers', '/operations', '/databases', '/domains', '/admin/mail', '/mail', '/ssl', '/applications', '/security', '/terminal']
      if (infraRoutes.some((prefix) => targetPath === prefix || targetPath.startsWith(`${prefix}/`))) {
        return { name: 'dashboard' }
      }
    } else if (role === 'hosting_operator') {
      const bizRoutes = ['/platform/orders', '/platform/accounting', '/platform/plans', '/security', '/terminal', '/settings']
      if (bizRoutes.some((prefix) => targetPath === prefix || targetPath.startsWith(`${prefix}/`))) {
        return { name: 'dashboard' }
      }
    } else if (role === 'billing_agent') {
      const techRoutes = ['/files', '/servers', '/operations', '/databases', '/domains', '/admin/mail', '/mail', '/ssl', '/applications', '/security', '/terminal', '/platform/plans', '/settings']
      if (techRoutes.some((prefix) => targetPath === prefix || targetPath.startsWith(`${prefix}/`))) {
        return { name: 'dashboard' }
      }
    } else if (role === 'support_agent') {
      const restrictedRoutes = ['/platform/orders', '/platform/accounting', '/platform/plans', '/files', '/servers', '/operations', '/databases', '/domains', '/admin/mail', '/mail', '/ssl', '/applications', '/security', '/terminal', '/settings']
      if (restrictedRoutes.some((prefix) => targetPath === prefix || targetPath.startsWith(`${prefix}/`))) {
        return { name: 'support' }
      }
    } else if (role === 'auditor') {
      const forbiddenRoutes = ['/terminal', '/files']
      if (forbiddenRoutes.some((prefix) => targetPath === prefix || targetPath.startsWith(`${prefix}/`))) {
        return { name: 'dashboard' }
      }
    } else if (role !== 'platform_owner') {
      // General non-owner barrier for emergency terminal and raw storage roots
      if (targetPath.startsWith('/terminal') || targetPath.startsWith('/files')) {
        return { name: homeRouteNameForUser(auth.user) }
      }
    }
  }
})

router.afterEach((to) => {
  const path = to.path || '/'
  const staff = isStaffPath(path)
  const authSurface =
    path === '/admin_1' ||
    path.startsWith('/admin_1/') ||
    path.startsWith('/forgot-password') ||
    path.startsWith('/reset-password')
  document.documentElement.classList.toggle('control-ui', staff || authSurface)
  if (!(staff || authSurface)) {
    document.documentElement.classList.remove('control-ui')
  }
})

export default router
