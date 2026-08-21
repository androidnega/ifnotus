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

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    guestOnly?: boolean
    /** staff = WHM host panel; portal = customer product panel */
    panel?: 'staff' | 'portal' | 'public'
    permission?: string
    /** Hosting panel deep-link tab (e.g. files route) */
    hostingTab?: 'files'
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { panel: 'public' },
  },
  {
    path: '/plans',
    name: 'plans',
    component: () => import('@/views/PlansView.vue'),
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
    component: () => import('@/views/LoginView.vue'),
    meta: { guestOnly: true, panel: 'public' },
  },
  {
    path: '/signup',
    name: 'portal-signup',
    component: () => import('@/views/portal/PortalSignupView.vue'),
    meta: { panel: 'public' },
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
    component: () => import('@/views/portal/PortalFilesView.vue'),
    meta: { requiresAuth: true, panel: 'portal' },
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
    name: 'monitoring',
    component: () => import('@/views/MonitoringView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/servers',
    name: 'servers',
    component: () => import('@/views/ServersView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/applications',
    name: 'applications',
    component: () => import('@/views/ApplicationsView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/applications/:id',
    name: 'application-detail',
    component: () => import('@/views/ApplicationDetailView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/operations',
    name: 'operations',
    component: () => import('@/views/OperationsView.vue'),
    meta: { requiresAuth: true, panel: 'staff' },
  },
  {
    path: '/platform/customers',
    name: 'platform-customers',
    component: () => import('@/views/PlatformCustomersView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:read' },
  },
  {
    path: '/platform/plans',
    name: 'platform-plans',
    component: () => import('@/views/PlatformPlansView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:read' },
  },
  {
    path: '/platform/orders',
    name: 'platform-orders',
    component: () => import('@/views/PlatformOrdersView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:read' },
  },
  {
    path: '/platform/capacity',
    name: 'platform-capacity',
    component: () => import('@/views/PlatformCapacityView.vue'),
    meta: { requiresAuth: true, panel: 'staff', permission: 'platform:read' },
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
    path: '/files',
    name: 'files',
    component: () => import('@/views/FilesView.vue'),
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
    meta: { requiresAuth: true, panel: 'staff' },
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
    candidate !== '/portal/login'
  ) {
    return candidate
  }
  return fallback
}

router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')

  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
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
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
    syncPanelFlag(auth.user)

    const panel = to.meta.panel
    if (panel === 'staff' && isPureCustomer(auth.user)) {
      return { name: 'portal-dashboard' }
    }
    if (panel === 'portal' && isStaffUser(auth.user) && !isPureCustomer(auth.user)) {
      // Staff without customer role: keep them in WHM unless they also have customer
      const roles = new Set(auth.user?.roles ?? [])
      if (!roles.has('customer') && !auth.user?.is_superuser) {
        return { name: 'dashboard' }
      }
      // Superadmin / dual-role: allow portal
    }

    const requiredPermission = to.meta.permission
    if (requiredPermission) {
      const perms = auth.user?.permissions ?? []
      const fullSuper = Boolean(auth.user?.is_superuser && !auth.user?.privilege_viewing_as)
      if (!fullSuper && !perms.includes(requiredPermission)) {
        return { name: homeRouteNameForUser(auth.user) }
      }
    }
  }
})

router.afterEach((to) => {
  const path = to.path || '/'
  const staff = isStaffPath(path)
  const authSurface =
    path === '/login' ||
    path.startsWith('/login/') ||
    path.startsWith('/forgot-password') ||
    path.startsWith('/reset-password')
  document.documentElement.classList.toggle('control-ui', staff || authSurface)
  if (!(staff || authSurface)) {
    document.documentElement.classList.remove('control-ui')
  }
})

export default router
