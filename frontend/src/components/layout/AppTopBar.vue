<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { useThemeStore } from '@/stores/theme'
import NotificationCenter from '@/components/layout/NotificationCenter.vue'
import { IconBell, IconMenu, IconMoon, IconRefresh, IconSun } from '@/components/icons'

defineProps<{
  refreshing?: boolean
}>()

defineEmits<{
  toggleMobileNav: []
  refresh: []
}>()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notifications = useNotificationStore()
const theme = useThemeStore()
const menuOpen = ref(false)
const search = ref('')
const searchOpen = ref(false)
const privilegeBusy = ref(false)

const privilegeOptions = [
  { value: '', label: 'Super admin (full)' },
  { value: 'admin', label: 'Business admin' },
  { value: 'operator', label: 'Hosting operator' },
  { value: 'customer_care', label: 'Customer care' },
  { value: 'viewer', label: 'Viewer (read-only)' },
]

const privilegeSelect = computed({
  get: () => auth.privilegeViewingAs || '',
  set: (value: string) => {
    void changePrivilege(value)
  },
})

async function changePrivilege(role: string) {
  if (privilegeBusy.value) return
  privilegeBusy.value = true
  try {
    await auth.switchPrivilege(role || null)
    await router.replace({ name: 'dashboard' })
  } catch {
    /* keep current view */
  } finally {
    privilegeBusy.value = false
  }
}

const titles: Record<string, string> = {
  dashboard: 'Dashboard',
  monitoring: 'Monitoring',
  applications: 'Websites',
  'application-detail': 'Website',
  operations: 'Backups',
  domains: 'Domains / DNS',
  ssl: 'SSL',
  'mail-admin': 'Email',
  files: 'File Manager',
  'files-upload': 'Upload Files',
  terminal: 'Terminal',
  'terminal-full': 'Terminal',
  security: 'Security',
  servers: 'Host',
  settings: 'Settings',
}

const pageTitle = computed(() => titles[String(route.name)] || 'IFNOTUS')

const palettes = [
  { label: 'Dashboard', to: '/panel', hint: 'overview' },
  { label: 'Websites', to: '/applications', hint: 'apps' },
  { label: 'Domains', to: '/domains', hint: 'dns' },
  { label: 'File Manager', to: '/files', hint: 'files' },
  { label: 'Databases', to: '/databases', hint: 'mysql' },
  { label: 'Email', to: '/admin/mail', hint: 'mail' },
  { label: 'SSL', to: '/ssl', hint: 'https' },
  { label: 'Monitoring', to: '/monitoring', hint: 'cpu' },
  { label: 'Terminal', to: '/terminal', hint: 'ssh' },
  { label: 'Security', to: '/security', hint: 'firewall' },
  { label: 'Customers', to: '/platform/customers', hint: 'accounts' },
  { label: 'Plans', to: '/platform/plans', hint: 'packages' },
  { label: 'Capacity', to: '/platform/capacity', hint: 'shared node' },
  { label: 'Support', to: '/support', hint: 'tickets' },
]

const searchHits = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return palettes.slice(0, 6)
  return palettes.filter((p) => `${p.label} ${p.hint} ${p.to}`.toLowerCase().includes(q)).slice(0, 8)
})

function goSearch(to: string) {
  searchOpen.value = false
  search.value = ''
  router.push(to)
}

async function handleLogout() {
  menuOpen.value = false
  await auth.logout()
  await router.replace({ name: 'login' })
}

function onDocClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (!target?.closest('[data-user-menu]')) menuOpen.value = false
  if (!target?.closest('[data-cmd-search]')) searchOpen.value = false
}

function onKey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    searchOpen.value = true
  }
}

onMounted(() => {
  if (auth.isAuthenticated) {
    auth.fetchUser().catch(() => undefined)
    notifications.startPolling()
  }
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  notifications.stopPolling()
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <header
    class="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-surface-border bg-surface-raised/80 px-4 backdrop-blur-md md:px-5"
  >
    <button
      type="button"
      class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 lg:hidden"
      aria-label="Open navigation menu"
      @click="$emit('toggleMobileNav')"
    >
      <IconMenu :size="20" />
    </button>

    <p class="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900 dark:text-white md:hidden">
      {{ pageTitle }}
    </p>

    <div class="hidden min-w-0 flex-1 md:block" data-cmd-search>
      <div class="relative max-w-xl">
        <input
          v-model="search"
          type="search"
          class="h-9 w-full rounded-lg border border-surface-border bg-slate-50 px-3 text-sm outline-none ring-blue-500/30 placeholder:text-surface-muted focus:ring-2 dark:bg-slate-800"
          placeholder="Search websites, domains, tools…"
          @focus="searchOpen = true"
        />
        <kbd class="pointer-events-none absolute right-2 top-1.5 rounded border border-surface-border px-1.5 py-0.5 text-[10px] text-surface-muted">⌘K</kbd>
        <div
          v-if="searchOpen"
          class="absolute z-50 mt-1 w-full overflow-hidden rounded-lg border border-surface-border bg-surface-raised shadow-elevated"
        >
          <button
            v-for="hit in searchHits"
            :key="hit.to"
            type="button"
            class="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            @click="goSearch(hit.to)"
          >
            {{ hit.label }}
            <span class="ml-2 text-xs text-surface-muted">{{ hit.hint }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="hidden items-center gap-2 rounded-full border border-surface-border px-2.5 py-1 lg:flex">
      <span class="h-2 w-2 rounded-full bg-emerald-500" />
      <span class="text-xs font-medium text-slate-700 dark:text-slate-200">IFNOTUS host</span>
      <span class="text-[10px] text-emerald-600">Online</span>
    </div>

    <div class="flex items-center gap-1.5">
      <label
        v-if="auth.canPrivilegeSwitch"
        class="hidden items-center gap-1.5 rounded-lg border border-amber-300/70 bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-100 sm:flex"
        title="Work as a lesser staff role to verify unique privileges. Client accounts are not available."
      >
        <span class="whitespace-nowrap">Work as</span>
        <select
          v-model="privilegeSelect"
          class="max-w-[9.5rem] rounded border-0 bg-transparent py-0.5 text-[11px] font-semibold outline-none"
          :disabled="privilegeBusy"
        >
          <option v-for="opt in privilegeOptions" :key="opt.value || 'full'" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </label>

      <button
        type="button"
        class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-surface-muted transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        aria-label="Refresh dashboard"
        :disabled="refreshing"
        @click="$emit('refresh')"
      >
        <IconRefresh :size="18" :class="refreshing ? 'animate-spin' : ''" />
      </button>

      <button
        type="button"
        class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-surface-muted transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        :aria-label="theme.isDark ? 'Switch to light mode' : 'Switch to dark mode'"
        @click="theme.toggle()"
      >
        <IconSun v-if="theme.isDark" :size="18" />
        <IconMoon v-else :size="18" />
      </button>

      <div class="relative" data-notification-center>
        <button
          type="button"
          class="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-surface-muted transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          :class="notifications.panelOpen ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' : ''"
          aria-label="Notifications"
          :aria-expanded="notifications.panelOpen"
          @click.stop="notifications.togglePanel()"
        >
          <IconBell :size="18" />
          <span
            v-if="notifications.unreadCount"
            class="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white"
          >
            {{ notifications.unreadCount }}
          </span>
        </button>
        <NotificationCenter />
      </div>

      <div class="relative ml-1" data-user-menu>
        <button
          type="button"
          class="flex items-center gap-2 rounded-lg border border-surface-border px-2.5 py-1.5 transition hover:bg-slate-50 dark:hover:bg-slate-800"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click.stop="menuOpen = !menuOpen"
        >
          <div
            class="flex h-7 w-7 items-center justify-center rounded-full bg-brand-500/15 text-xs font-semibold text-brand-700 dark:text-brand-300"
          >
            {{ (auth.user?.username || 'U').charAt(0).toUpperCase() }}
          </div>
          <div class="hidden text-left md:block">
            <p class="text-xs font-medium text-slate-900 dark:text-white">
              {{ auth.user?.username || 'Operator' }}
            </p>
            <p class="text-[10px] text-surface-muted">Root access</p>
          </div>
        </button>

        <div
          v-if="menuOpen"
          class="absolute right-0 z-50 mt-2 w-48 overflow-hidden rounded-lg border border-surface-border bg-surface-raised shadow-elevated"
          role="menu"
        >
          <button
            type="button"
            class="block w-full px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
            role="menuitem"
            @click="menuOpen = false; router.push({ name: 'settings' })"
          >
            Settings
          </button>
          <button
            type="button"
            class="block w-full border-t border-surface-border px-3 py-2 text-left text-sm font-medium text-red-600 transition hover:bg-red-500/10 dark:text-red-400"
            role="menuitem"
            @click="handleLogout"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  </header>
</template>
