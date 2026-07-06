import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guestOnly: true },
  },
  {
    path: '/monitoring',
    name: 'monitoring',
    component: () => import('@/views/MonitoringView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/servers',
    name: 'servers',
    component: () => import('@/views/ServersView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/applications',
    name: 'applications',
    component: () => import('@/views/ApplicationsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/applications/:id',
    name: 'application-detail',
    component: () => import('@/views/ApplicationDetailView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/operations',
    name: 'operations',
    component: () => import('@/views/OperationsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/domains',
    name: 'domains',
    component: () => import('@/views/DomainsView.vue'),
    meta: { requiresAuth: true, permission: 'domains:read' },
  },
  {
    path: '/ssl',
    name: 'ssl',
    component: () => import('@/views/SslView.vue'),
    meta: { requiresAuth: true, permission: 'ssl:read' },
  },
  {
    path: '/mail',
    name: 'mail',
    component: () => import('@/views/MailView.vue'),
    meta: { requiresAuth: true, permission: 'mail:read' },
  },
  {
    path: '/files',
    name: 'files',
    component: () => import('@/views/FilesView.vue'),
    meta: { requiresAuth: true, permission: 'files:read' },
  },
  {
    path: '/terminal',
    name: 'terminal',
    component: () => import('@/views/TerminalView.vue'),
    meta: { requiresAuth: true, permission: 'terminal:execute' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && token) {
    return { name: 'dashboard' }
  }

  const requiredPermission = to.meta.permission as string | undefined
  if (requiredPermission && token) {
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    if (!auth.user) {
      try {
        await auth.fetchUser()
      } catch {
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
    const perms = auth.user?.permissions ?? []
    if (!auth.user?.is_superuser && !perms.includes(requiredPermission)) {
      return { name: 'dashboard' }
    }
  }
})

export default router
