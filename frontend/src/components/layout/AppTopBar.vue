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

const titles: Record<string, string> = {
  dashboard: 'Control Plane',
  monitoring: 'Monitoring',
  applications: 'Applications',
  'application-detail': 'Application',
  operations: 'Operations',
  domains: 'Domains',
  ssl: 'SSL',
  mail: 'Mail',
  files: 'File Manager',
  'files-upload': 'Upload Files',
  terminal: 'Terminal',
  servers: 'Servers',
  settings: 'Settings',
}

const pageTitle = computed(() => titles[String(route.name)] || 'IFNOTUS')

async function handleLogout() {
  menuOpen.value = false
  await auth.logout()
  await router.replace({ name: 'login' })
}

function onDocClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (!target?.closest('[data-user-menu]')) {
    menuOpen.value = false
  }
}

onMounted(() => {
  if (auth.isAuthenticated) {
    auth.fetchUser().catch(() => undefined)
    notifications.startPolling()
  }
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  notifications.stopPolling()
  document.removeEventListener('click', onDocClick)
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

    <div class="min-w-0 flex-1">
      <h1 class="truncate text-sm font-semibold text-slate-900 dark:text-white">{{ pageTitle }}</h1>
      <p class="hidden text-xs text-surface-muted sm:block">Infrastructure & Operations Platform</p>
    </div>

    <div class="flex items-center gap-1.5">
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
            <p class="text-[10px] text-surface-muted">{{ auth.user?.email || '—' }}</p>
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
