<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import {
  IconApp,
  IconChart,
  IconChevron,
  IconDashboard,
  IconDatabase,
  IconDeploy,
  IconFolder,
  IconGlobe,
  IconLock,
  IconMail,
  IconServer,
  IconSettings,
  IconShield,
  IconTerminal,
} from '@/components/icons'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { PermissionKey } from '@/lib/permissions'

defineProps<{
  collapsed?: boolean
  mobileOpen?: boolean
}>()

defineEmits<{
  closeMobile: []
  toggleCollapse: []
}>()

const route = useRoute()
const { can } = usePermissions()

type NavItem = {
  to: string
  name: string
  label: string
  icon: typeof IconDashboard
  permission?: PermissionKey
}

type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    id: 'overview',
    label: 'Control',
    items: [
      { to: '/panel', name: 'dashboard', label: 'Dashboard', icon: IconDashboard },
      { to: '/applications', name: 'applications', label: 'Websites', icon: IconApp, permission: Permission.APPS_READ },
      { to: '/domains', name: 'domains', label: 'DNS', icon: IconGlobe, permission: Permission.DOMAINS_READ },
      { to: '/files', name: 'files', label: 'File Manager', icon: IconFolder, permission: Permission.FILES_READ },
      { to: '/databases', name: 'databases', label: 'Databases', icon: IconDatabase, permission: Permission.DATABASES_READ },
      { to: '/admin/mail', name: 'mail-admin', label: 'Email', icon: IconMail, permission: Permission.MAIL_READ },
      { to: '/ssl', name: 'ssl', label: 'SSL', icon: IconLock, permission: Permission.SSL_READ },
      { to: '/operations', name: 'operations', label: 'Backups', icon: IconDeploy, permission: Permission.SYSTEM_READ },
      { to: '/security', name: 'security', label: 'Firewall / Security', icon: IconShield, permission: Permission.SYSTEM_ADMIN },
      { to: '/monitoring', name: 'monitoring', label: 'Monitoring', icon: IconChart, permission: Permission.MONITORING_READ },
      { to: '/terminal', name: 'terminal', label: 'Terminal / SSH', icon: IconTerminal, permission: Permission.TERMINAL_EXECUTE },
      { to: '/servers', name: 'servers', label: 'Docker / host', icon: IconServer, permission: Permission.SERVERS_READ },
    ],
  },
  {
    id: 'hosting',
    label: 'Accounts',
    items: [
      { to: '/platform/customers', name: 'platform-customers', label: 'Customers', icon: IconApp, permission: Permission.PLATFORM_READ },
      { to: '/platform/plans', name: 'platform-plans', label: 'Plans', icon: IconDeploy, permission: Permission.PLATFORM_READ },
      { to: '/platform/orders', name: 'platform-orders', label: 'Orders', icon: IconGlobe, permission: Permission.PLATFORM_READ },
      { to: '/platform/capacity', name: 'platform-capacity', label: 'Capacity', icon: IconServer, permission: Permission.PLATFORM_READ },
      { to: '/support', name: 'support', label: 'Support', icon: IconMail, permission: Permission.SUPPORT_READ },
    ],
  },
  {
    id: 'system',
    label: 'System',
    items: [{ to: '/settings', name: 'settings', label: 'Settings', icon: IconSettings }],
  },
]

const visibleGroups = computed(() =>
  navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.permission || can(item.permission)),
    }))
    .filter((group) => group.items.length > 0),
)

const activeName = computed(() => route.name)
</script>

<template>
  <aside
    class="fixed inset-y-0 left-0 z-40 flex h-screen shrink-0 flex-col overflow-hidden border-r border-surface-border bg-surface-raised transition-all duration-300 ease-smooth lg:relative lg:translate-x-0"
    :class="[
      mobileOpen ? 'translate-x-0 pointer-events-auto' : '-translate-x-full pointer-events-none lg:translate-x-0 lg:pointer-events-auto',
      collapsed ? 'w-[72px]' : 'w-64',
    ]"
    aria-label="Main navigation"
  >
    <div class="flex h-14 items-center border-b border-surface-border px-4">
      <RouterLink to="/panel" class="flex items-center gap-2 overflow-hidden" @click="$emit('closeMobile')">
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white"
        >
          I
        </div>
        <span
          v-if="!collapsed"
          class="truncate text-sm font-semibold tracking-tight text-slate-900 dark:text-slate-100"
        >
          IFNOTUS
        </span>
      </RouterLink>
    </div>

    <nav class="flex-1 space-y-4 overflow-y-auto p-3" role="navigation">
      <div v-for="group in visibleGroups" :key="group.id" class="space-y-1">
        <p
          v-if="!collapsed"
          class="px-3 pb-1 text-[0.65rem] font-bold uppercase tracking-[0.08em] text-surface-muted"
        >
          {{ group.label }}
        </p>
        <div v-else class="mx-auto my-1 h-px w-6 bg-surface-border" aria-hidden="true" />
        <component
          :is="RouterLink"
          v-for="item in group.items"
          :key="item.name"
          :to="item.to"
          class="group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          :class="[
            activeName === item.name || (item.name === 'mail-admin' && String(route.path).startsWith('/mail'))
              ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300'
              : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
          ]"
          :aria-current="activeName === item.name ? 'page' : undefined"
          :title="collapsed ? item.label : undefined"
          @click="$emit('closeMobile')"
        >
          <component :is="item.icon" :size="18" class="shrink-0" />
          <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
        </component>
      </div>
    </nav>

    <div v-if="!collapsed" class="shrink-0 px-3 pb-2">
      <div class="rounded-xl border border-surface-border bg-slate-50 p-3 dark:bg-slate-800/60">
        <p class="text-xs font-semibold text-slate-800 dark:text-slate-100">Need help?</p>
        <p class="mt-1 text-[11px] leading-snug text-surface-muted">Open a ticket for this host or a customer site.</p>
        <RouterLink
          to="/support"
          class="mt-2 inline-flex w-full items-center justify-center rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white"
          @click="$emit('closeMobile')"
        >
          Open support ticket
        </RouterLink>
      </div>
    </div>

    <div class="hidden shrink-0 border-t border-surface-border p-3 lg:block">
      <button
        type="button"
        class="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs text-surface-muted transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="$emit('toggleCollapse')"
      >
        <IconChevron :size="16" class="transition-transform" :class="collapsed ? '' : 'rotate-180'" />
        <span v-if="!collapsed">Collapse</span>
      </button>
    </div>
  </aside>
</template>
