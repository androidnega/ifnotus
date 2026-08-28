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
  IconGlobe,
  IconLock,
  IconMail,
  IconServer,
  IconSettings,
  IconShield,
  IconTerminal,
} from '@/components/icons'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import { Permission, type PermissionKey } from '@/lib/permissions'
import { getCanonicalRole, type CanonicalRole } from '@/lib/roles'
import { useNotificationStore } from '@/stores/notifications'

defineProps<{
  collapsed?: boolean
  mobileOpen?: boolean
}>()

defineEmits<{
  closeMobile: []
  toggleCollapse: []
}>()

const route = useRoute()
const auth = useAuthStore()
const { can } = usePermissions()
const notifications = useNotificationStore()

type NavItem = {
  to: string
  name: string
  label: string
  icon: typeof IconDashboard
  permission?: PermissionKey
  badgeKey?: 'orders' | 'support'
  isEmergency?: boolean
}

type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}

const canonicalRole = computed<CanonicalRole>(() => {
  return getCanonicalRole(auth.user) || 'platform_owner'
})

const navGroups = computed<NavGroup[]>(() => {
  const role = canonicalRole.value

  // 1. SUPPORT AGENT: Narrow support and customer lookup only
  if (role === 'support_agent') {
    return [
      {
        id: 'support',
        label: 'Support',
        items: [
          { to: '/support', name: 'support', label: 'Tickets', icon: IconMail, permission: Permission.SUPPORT_READ, badgeKey: 'support' },
        ],
      },
      {
        id: 'customers',
        label: 'Customers',
        items: [
          { to: '/platform/customers', name: 'platform-customers', label: 'Customer Lookup', icon: IconApp, permission: Permission.PLATFORM_READ },
        ],
      },
    ]
  }

  // 2. BILLING AGENT: Pure financial and billing reconciliation
  if (role === 'billing_agent') {
    return [
      {
        id: 'finance',
        label: 'Billing & Finance',
        items: [
          { to: '/panel', name: 'dashboard', label: 'Dashboard', icon: IconDashboard },
          { to: '/platform/orders', name: 'platform-orders', label: 'Orders', icon: IconGlobe, permission: Permission.BILLING_VIEW, badgeKey: 'orders' },
          { to: '/platform/accounting', name: 'platform-accounting', label: 'Accounting', icon: IconChart, permission: Permission.BILLING_VIEW },
        ],
      },
      {
        id: 'customers',
        label: 'Customers',
        items: [
          { to: '/platform/customers', name: 'platform-customers', label: 'Customers', icon: IconApp, permission: Permission.PLATFORM_READ },
        ],
      },
      {
        id: 'support',
        label: 'Support',
        items: [
          { to: '/support', name: 'support', label: 'Billing Tickets', icon: IconMail, permission: Permission.SUPPORT_READ, badgeKey: 'support' },
        ],
      },
    ]
  }

  // 3. HOSTING OPERATOR: Technical tenant hosting, runtimes, domains, DBs, mail
  if (role === 'hosting_operator') {
    return [
      {
        id: 'host',
        label: 'Hosting Operations',
        items: [
          { to: '/panel', name: 'dashboard', label: 'Operations Dashboard', icon: IconDashboard },
          { to: '/applications', name: 'applications', label: 'Modern Apps', icon: IconApp, permission: Permission.APPS_READ },
          { to: '/domains', name: 'domains', label: 'Domains & DNS', icon: IconGlobe, permission: Permission.DOMAINS_READ },
          { to: '/databases', name: 'databases', label: 'Databases', icon: IconDatabase, permission: Permission.DATABASES_READ },
          { to: '/admin/mail', name: 'mail-admin', label: 'Email Diagnostics', icon: IconMail, permission: Permission.MAIL_READ },
          { to: '/ssl', name: 'ssl', label: 'SSL Certificates', icon: IconLock, permission: Permission.SSL_READ },
          { to: '/operations', name: 'operations', label: 'Operations & Jobs', icon: IconDeploy, permission: Permission.SYSTEM_READ },
          { to: '/servers', name: 'servers', label: 'Host Capacity', icon: IconServer, permission: Permission.SERVERS_READ },
        ],
      },
      {
        id: 'customers',
        label: 'Tenants',
        items: [
          { to: '/platform/customers', name: 'platform-customers', label: 'Hosting Accounts', icon: IconApp, permission: Permission.PLATFORM_READ },
        ],
      },
      {
        id: 'support',
        label: 'Support',
        items: [
          { to: '/support', name: 'support', label: 'Technical Tickets', icon: IconMail, permission: Permission.SUPPORT_READ, badgeKey: 'support' },
        ],
      },
    ]
  }

  // 4. PLATFORM ADMIN: Commercial, customer, plan, and billing administration
  if (role === 'platform_admin') {
    return [
      {
        id: 'overview',
        label: 'Overview',
        items: [
          { to: '/panel', name: 'dashboard', label: 'Business Dashboard', icon: IconDashboard },
        ],
      },
      {
        id: 'customers',
        label: 'Customers',
        items: [
          { to: '/platform/customers', name: 'platform-customers', label: 'Customer Directory', icon: IconApp, permission: Permission.PLATFORM_READ },
        ],
      },
      {
        id: 'money',
        label: 'Commercial',
        items: [
          { to: '/platform/orders', name: 'platform-orders', label: 'Orders', icon: IconGlobe, permission: Permission.BILLING_VIEW, badgeKey: 'orders' },
          { to: '/platform/accounting', name: 'platform-accounting', label: 'Accounting', icon: IconChart, permission: Permission.BILLING_VIEW },
          { to: '/platform/plans', name: 'platform-plans', label: 'Plans & Pricing', icon: IconDeploy, permission: Permission.PLATFORM_WRITE },
        ],
      },
      {
        id: 'support',
        label: 'Support',
        items: [
          { to: '/support', name: 'support', label: 'Tickets', icon: IconMail, permission: Permission.SUPPORT_READ, badgeKey: 'support' },
        ],
      },
      {
        id: 'system',
        label: 'Settings',
        items: [
          { to: '/settings', name: 'settings', label: 'Business Settings', icon: IconSettings, permission: Permission.SYSTEM_READ },
        ],
      },
    ]
  }

  // 5. AUDITOR: Strictly read-only compliance, audit trails, and reports
  if (role === 'auditor') {
    return [
      {
        id: 'compliance',
        label: 'Compliance & Audit',
        items: [
          { to: '/panel', name: 'dashboard', label: 'Auditor Overview', icon: IconDashboard },
          { to: '/security', name: 'security', label: 'Audit Logs & Events', icon: IconShield, permission: Permission.SYSTEM_READ },
          { to: '/platform/accounting', name: 'platform-accounting', label: 'Financial Ledgers', icon: IconChart, permission: Permission.BILLING_VIEW },
          { to: '/servers', name: 'servers', label: 'System Health', icon: IconServer, permission: Permission.SERVERS_READ },
        ],
      },
      {
        id: 'customers',
        label: 'Records',
        items: [
          { to: '/platform/customers', name: 'platform-customers', label: 'Customer Records', icon: IconApp, permission: Permission.PLATFORM_READ },
        ],
      },
      {
        id: 'support',
        label: 'Review',
        items: [
          { to: '/support', name: 'support', label: 'Ticket History', icon: IconMail, permission: Permission.SUPPORT_READ },
        ],
      },
    ]
  }

  // 6. PLATFORM OWNER / SUPERADMIN: Complete governance and infrastructure
  return [
    {
      id: 'overview',
      label: 'Platform',
      items: [
        { to: '/panel', name: 'dashboard', label: 'Overview', icon: IconDashboard },
      ],
    },
    {
      id: 'customers',
      label: 'Accounts',
      items: [
        { to: '/platform/customers', name: 'platform-customers', label: 'Customers', icon: IconApp, permission: Permission.PLATFORM_READ },
      ],
    },
    {
      id: 'hosting',
      label: 'Hosting & Services',
      items: [
        { to: '/applications', name: 'applications', label: 'Apps', icon: IconApp, permission: Permission.APPS_READ },
        { to: '/domains', name: 'domains', label: 'DNS Zones', icon: IconGlobe, permission: Permission.DOMAINS_READ },
        { to: '/databases', name: 'databases', label: 'Databases', icon: IconDatabase, permission: Permission.DATABASES_READ },
        { to: '/admin/mail', name: 'mail-admin', label: 'Email Server', icon: IconMail, permission: Permission.MAIL_READ },
        { to: '/ssl', name: 'ssl', label: 'SSL Certificates', icon: IconLock, permission: Permission.SSL_READ },
      ],
    },
    {
      id: 'infrastructure',
      label: 'Infrastructure',
      items: [
        { to: '/servers', name: 'servers', label: 'Host Servers', icon: IconServer, permission: Permission.SERVERS_READ },
        { to: '/operations', name: 'operations', label: 'Operations & DR', icon: IconDeploy, permission: Permission.SYSTEM_READ },
        { to: '/security', name: 'security', label: 'Security & Access', icon: IconShield, permission: Permission.SYSTEM_ADMIN },
      ],
    },
    {
      id: 'money',
      label: 'Billing & Commercial',
      items: [
        { to: '/platform/orders', name: 'platform-orders', label: 'Orders', icon: IconGlobe, permission: Permission.BILLING_VIEW, badgeKey: 'orders' },
        { to: '/platform/accounting', name: 'platform-accounting', label: 'Accounting', icon: IconChart, permission: Permission.BILLING_VIEW },
        { to: '/platform/plans', name: 'platform-plans', label: 'Plans & Sizing', icon: IconDeploy, permission: Permission.PLATFORM_WRITE },
      ],
    },
    {
      id: 'support',
      label: 'Support',
      items: [
        { to: '/support', name: 'support', label: 'Tickets', icon: IconMail, permission: Permission.SUPPORT_READ, badgeKey: 'support' },
      ],
    },
    {
      id: 'system',
      label: 'Platform Control',
      items: [
        { to: '/settings', name: 'settings', label: 'Settings & Staff', icon: IconSettings, permission: Permission.SYSTEM_READ },
      ],
    },
  ]
})

const visibleGroups = computed(() =>
  navGroups.value
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.permission || can(item.permission)),
    }))
    .filter((group) => group.items.length > 0),
)

const showEmergencyTerminal = computed(() => {
  const role = canonicalRole.value
  return (role === 'platform_owner') && can(Permission.TERMINAL_EXECUTE)
})

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
      <UiBrandMark
        :to="{ name: 'dashboard' }"
        variant="staff"
        :compact="collapsed"
        class="overflow-hidden"
        @click="$emit('closeMobile')"
      />
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
          class="ds-staff-nav-link group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          :class="[
            activeName === item.name
              || (item.name === 'mail-admin' && String(route.path).startsWith('/mail'))
              || (item.name === 'platform-orders' && String(route.path).startsWith('/platform/orders'))
              || (item.name === 'platform-accounting' && String(route.path).startsWith('/platform/accounting'))
              ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300'
              : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
          ]"
          :aria-current="activeName === item.name ? 'page' : undefined"
          :title="collapsed ? item.label : undefined"
          @click="$emit('closeMobile')"
        >
          <component :is="item.icon" :size="18" class="shrink-0" />
          <span v-if="!collapsed" class="truncate flex-1">{{ item.label }}</span>
          <span
            v-if="!collapsed && item.badgeKey === 'orders' && notifications.ordersBadge > 0"
            class="ml-auto inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold leading-none text-white"
            :title="`${notifications.ordersBadge} payment(s) awaiting confirmation`"
          >
            {{ notifications.ordersBadge > 99 ? '99+' : notifications.ordersBadge }}
          </span>
          <span
            v-else-if="!collapsed && item.badgeKey === 'support' && notifications.supportBadge > 0"
            class="ml-auto inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-bold leading-none text-white"
            :title="`${notifications.supportBadge} open support ticket(s)`"
          >
            {{ notifications.supportBadge > 99 ? '99+' : notifications.supportBadge }}
          </span>
          <span
            v-else-if="collapsed && item.badgeKey === 'orders' && notifications.ordersBadge > 0"
            class="absolute right-2 top-1.5 h-2 w-2 rounded-full bg-amber-500"
            aria-hidden="true"
          />
          <span
            v-else-if="collapsed && item.badgeKey === 'support' && notifications.supportBadge > 0"
            class="absolute right-2 top-1.5 h-2 w-2 rounded-full bg-rose-500"
            aria-hidden="true"
          />
        </component>
      </div>

      <!-- Emergency Tools (Visually separated, platform_owner only) -->
      <div v-if="showEmergencyTerminal" class="pt-2">
        <div class="mx-auto my-2 h-px w-full bg-surface-border/60" aria-hidden="true" />
        <p
          v-if="!collapsed"
          class="px-3 pb-1 text-[0.65rem] font-bold uppercase tracking-[0.08em] text-rose-500/80 dark:text-rose-400/80"
        >
          Emergency Tools
        </p>
        <component
          :is="RouterLink"
          to="/terminal"
          class="ds-staff-nav-link group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-400 dark:hover:bg-rose-500/10 dark:hover:text-rose-300"
          :class="[
            activeName === 'terminal' ? 'bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200 font-semibold' : '',
          ]"
          :title="collapsed ? 'Emergency Terminal' : undefined"
          @click="$emit('closeMobile')"
        >
          <IconTerminal :size="18" class="shrink-0 text-rose-500" />
          <span v-if="!collapsed" class="truncate flex-1">Terminal</span>
          <span
            v-if="!collapsed"
            class="rounded bg-rose-100 px-1 py-0.2 text-[9px] font-bold text-rose-700 dark:bg-rose-900/40 dark:text-rose-300"
          >
            ROOT
          </span>
        </component>
      </div>
    </nav>

    <!-- Support quick card (collapsed off) -->
    <div v-if="!collapsed && can(Permission.SUPPORT_READ)" class="shrink-0 px-3 pb-2">
      <div
        class="rounded-xl border border-surface-border bg-slate-50/80 p-3 text-xs dark:bg-slate-900/60"
      >
        <div class="flex items-center justify-between font-semibold text-slate-800 dark:text-slate-100">
          <span class="inline-flex items-center gap-1.5">
            <span class="relative flex h-2 w-2">
              <span
                class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
              />
              <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            Support Queue
          </span>
          <RouterLink
            to="/support"
            class="font-mono text-[11px] font-bold text-blue-600 hover:underline dark:text-blue-400"
          >
            View
          </RouterLink>
        </div>
        <p class="mt-1 text-[11px] text-surface-muted">
          {{ notifications.supportBadge > 0 ? `${notifications.supportBadge} ticket(s) awaiting response` : 'All ticket queues clear' }}
        </p>
      </div>
    </div>

    <!-- User panel summary & collapse toggle -->
    <div
      class="flex shrink-0 items-center justify-between border-t border-surface-border p-3 text-xs text-surface-muted"
    >
      <div v-if="!collapsed" class="flex min-w-0 items-center gap-2">
        <div class="truncate">
          <p class="truncate font-medium text-slate-900 dark:text-white">
            {{ auth.user?.full_name || auth.user?.username || 'Staff' }}
          </p>
          <p class="text-[10px] text-surface-muted capitalize">
            {{ canonicalRole.replace('_', ' ') }}
          </p>
        </div>
      </div>
      <button
        type="button"
        class="hidden rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800 lg:block"
        :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="$emit('toggleCollapse')"
      >
        <IconChevron
          :size="16"
          :class="[collapsed ? 'rotate-180' : '']"
          class="transition-transform"
        />
      </button>
    </div>
  </aside>
</template>
