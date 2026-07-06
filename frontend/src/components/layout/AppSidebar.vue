<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import {
  IconApp,
  IconChart,
  IconChevron,
  IconDashboard,
  IconDeploy,
  IconFolder,
  IconGlobe,
  IconLock,
  IconMail,
  IconServer,
  IconSettings,
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

const allNavItems: Array<{
  to: string
  name: string
  label: string
  icon: typeof IconDashboard
  permission?: PermissionKey
}> = [
  { to: '/', name: 'dashboard', label: 'Dashboard', icon: IconDashboard },
  { to: '/monitoring', name: 'monitoring', label: 'Monitoring', icon: IconChart, permission: Permission.MONITORING_READ },
  { to: '/applications', name: 'applications', label: 'Applications', icon: IconApp, permission: Permission.APPS_READ },
  { to: '/operations', name: 'operations', label: 'Operations', icon: IconDeploy, permission: Permission.SYSTEM_READ },
  { to: '/domains', name: 'domains', label: 'Domains', icon: IconGlobe, permission: Permission.DOMAINS_READ },
  { to: '/ssl', name: 'ssl', label: 'SSL', icon: IconLock, permission: Permission.SSL_READ },
  { to: '/mail', name: 'mail', label: 'Mail', icon: IconMail, permission: Permission.MAIL_READ },
  { to: '/files', name: 'files', label: 'Files', icon: IconFolder, permission: Permission.FILES_READ },
  { to: '/terminal', name: 'terminal', label: 'Terminal', icon: IconTerminal, permission: Permission.TERMINAL_EXECUTE },
  { to: '/servers', name: 'servers', label: 'Servers', icon: IconServer, permission: Permission.SERVERS_READ },
  { to: '/settings', name: 'settings', label: 'Settings', icon: IconSettings },
]

const navItems = computed(() =>
  allNavItems.filter((item) => !item.permission || can(item.permission)),
)

const activeName = computed(() => route.name)
</script>

<template>
  <aside
    class="fixed inset-y-0 left-0 z-40 flex h-screen shrink-0 flex-col overflow-hidden border-r border-surface-border bg-surface-raised transition-all duration-300 ease-smooth lg:relative lg:translate-x-0"
    :class="[
      mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      collapsed ? 'w-[72px]' : 'w-64',
    ]"
    aria-label="Main navigation"
  >
    <div class="flex h-14 items-center border-b border-surface-border px-4">
      <RouterLink to="/" class="flex items-center gap-2 overflow-hidden" @click="$emit('closeMobile')">
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white"
        >
          I
        </div>
        <span
          v-if="!collapsed"
          class="truncate text-sm font-semibold tracking-tight text-slate-900 dark:text-white"
        >
          IFNOTUS
        </span>
      </RouterLink>
    </div>

    <nav class="flex-1 space-y-1 overflow-hidden p-3" role="navigation">
      <component
        :is="RouterLink"
        v-for="item in navItems"
        :key="item.name"
        :to="item.to"
        class="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors"
        :class="[
          activeName === item.name
            ? 'bg-brand-500/10 text-brand-700 dark:text-brand-300'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
        ]"
        :aria-current="activeName === item.name ? 'page' : undefined"
        @click="$emit('closeMobile')"
      >
        <component :is="item.icon" :size="18" class="shrink-0" />
        <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
      </component>
    </nav>

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
