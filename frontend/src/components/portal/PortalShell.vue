<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { useSiteTheme } from '@/composables/useSiteTheme'
import '@/assets/portal.css'

const props = withDefaults(
  defineProps<{
    subtitle?: string
    email?: string
    displayName?: string
    /** Marketing landing vs signed-in panel */
    mode?: 'marketing' | 'app'
    /** Active package accent */
    planAccent?: string
    /** Profile avatar menu in the header (app mode). Default on. */
    profileMenu?: boolean
    /** Unread support replies badge shown on the Support FAB (app mode only). */
    supportCount?: number
  }>(),
  {
    profileMenu: true,
    supportCount: 0,
  },
)

const emit = defineEmits<{
  account: []
  support: []
  logout: []
}>()

const router = useRouter()
const auth = useAuthStore()
const { load, isDark } = useSiteTheme()
let previousDark = false

const menuOpen = ref(false)
const showProfile = computed(() => props.mode === 'app' && props.profileMenu)
const supportCountLabel = computed(() => {
  const n = Number(props.supportCount || 0)
  if (!Number.isFinite(n) || n <= 0) return ''
  if (n > 99) return '99+'
  return String(n)
})

const resolvedEmail = computed(
  () => props.email || auth.user?.email || '',
)
const resolvedDisplayName = computed(
  () => props.displayName || auth.user?.full_name || auth.user?.username || '',
)

const initials = computed(() => {
  const src = (resolvedDisplayName.value || resolvedEmail.value || 'U').trim()
  const parts = src.split(/[\s@]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return src.slice(0, 2).toUpperCase()
})

/** Customer panel uses one navy. Plan tints are for marketing cards only. */
const planStyle = computed(() => {
  if (props.mode === 'app') return undefined
  const accent = props.planAccent
  if (!accent) return undefined
  return {
    '--if-plan': accent,
    '--p-accent': accent,
    '--if-primary': accent,
    '--if-primary-hover': accent,
  } as Record<string, string>
})

function closeMenu() {
  menuOpen.value = false
}

function onDocClick(e: MouseEvent) {
  const t = e.target as HTMLElement | null
  if (!t?.closest?.('.profile-wrap')) menuOpen.value = false
}

function goAccount() {
  closeMenu()
  emit('account')
  router.push({ name: 'portal-account-settings' })
}

function goSupport() {
  closeMenu()
  emit('support')
  router.push({ name: 'portal-support' })
}

function doLogout() {
  closeMenu()
  emit('logout')
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('ifnotus_portal')
  router.push({ name: 'login' })
}

onMounted(async () => {
  previousDark = document.documentElement.classList.contains('dark')
  await load()
  document.documentElement.classList.toggle('dark', isDark.value)
  document.documentElement.style.colorScheme = isDark.value ? 'dark' : 'light'
  document.addEventListener('click', onDocClick)
  if (props.mode === 'app' && auth.isAuthenticated && !auth.user) {
    try {
      await auth.fetchUser()
    } catch {
      /* stay guest-looking; avatar still shows fallback initials */
    }
  }
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  if (previousDark) {
    document.documentElement.classList.add('dark')
    document.documentElement.style.colorScheme = 'dark'
  }
})
</script>

<template>
  <div
    class="portal-shell min-h-screen"
    :class="mode === 'app' ? 'portal-app' : 'portal-marketing'"
    :style="planStyle"
  >
    <header class="portal-header">
      <div class="portal-header-inner">
        <UiBrandMark
          :to="{ name: mode === 'app' ? 'portal-dashboard' : 'home' }"
        />
        <nav class="flex items-center gap-1 text-sm sm:gap-3">
          <slot name="actions" />
          <div v-if="showProfile" class="profile-wrap">
            <button
              type="button"
              class="profile-btn"
              :aria-expanded="menuOpen"
              aria-haspopup="menu"
              aria-label="Account menu"
              @click.stop="menuOpen = !menuOpen"
            >
              <span class="profile-avatar">{{ initials }}</span>
            </button>
            <div v-if="menuOpen" class="profile-menu" role="menu">
              <p v-if="resolvedEmail" class="profile-email">{{ resolvedEmail }}</p>
              <button type="button" role="menuitem" @click="goAccount">Account</button>
              <button type="button" role="menuitem" @click="goSupport">Support</button>
              <button type="button" role="menuitem" class="danger" @click="doLogout">Log out</button>
            </div>
          </div>
        </nav>
      </div>
    </header>

    <div v-if="mode === 'app'" class="portal-desk">
      <div class="portal-frame">
        <div class="portal-box">
          <aside class="portal-nav">
            <slot name="sidebar" />
          </aside>
          <div class="portal-main">
            <slot />
          </div>
        </div>
      </div>
    </div>
    <main v-else class="portal-marketing-main">
      <slot />
    </main>

    <footer v-if="mode !== 'app'" class="portal-footer">
      © {{ new Date().getFullYear() }} IFNOTUS · Hosting with an AI engineer
    </footer>

    <button
      v-if="mode === 'app'"
      type="button"
      class="support-fab"
      aria-label="Open support"
      @click="goSupport"
    >
      <span class="support-fab-ring" aria-hidden="true" />
      <span v-if="supportCountLabel" class="support-fab-badge" aria-hidden="true">{{ supportCountLabel }}</span>
      <svg class="support-fab-icon" viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
        <path
          d="M4 12a8 8 0 0 1 8-8h0a8 8 0 0 1 8 8v5.2A1.8 1.8 0 0 1 18.2 19H13l-3.4 2.4c-.5.35-1.2-.02-1.2-.62V19H5.8A1.8 1.8 0 0 1 4 17.2V12Z"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linejoin="round"
        />
      </svg>
      <span class="support-fab-label">Support</span>
    </button>
  </div>
</template>

<style scoped>
.portal-shell {
  color-scheme: inherit;
  font-family: 'Figtree', 'Segoe UI', sans-serif;
  color: var(--if-ink);
  background: var(--if-paper);
}

.portal-marketing {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--if-paper, #f4f1ec);
}

.portal-marketing-main {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  width: 100%;
  margin: 0 auto;
  padding: 1.25rem 1.25rem 2rem;
  box-sizing: border-box;
}

.portal-app {
  --if-primary: #1e3a5f;
  --if-primary-hover: #16304d;
  --if-plan: #1e3a5f;
  --p-accent: #1e3a5f;
  --if-ink: #0f172a;
  --if-paper: #f4f1ec;
  --if-surface: #ffffff;
  --if-muted: #5b6b7c;
  --if-border: #d7dee8;
  background: var(--if-paper, #f4f1ec);
}

.portal-header-inner {
  margin: 0 auto;
  width: 100%;
  max-width: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1.15rem;
}
.portal-desk {
  min-height: calc(100vh - 4.1rem);
}
.portal-frame {
  padding: 1.1rem 1.15rem 2.4rem;
  width: 100%;
}
.portal-box {
  margin: 0;
  width: 100%;
  max-width: none;
}
.portal-nav {
  margin: 0 0 1.25rem;
}
.portal-main {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

@media (min-width: 1100px) {
  .portal-header-inner,
  .portal-frame {
    padding-left: 1.75rem;
    padding-right: 1.75rem;
  }
  .portal-box {
    display: grid;
    grid-template-columns: 13.5rem minmax(0, 1fr);
    gap: 1.5rem;
    align-items: start;
  }
  .portal-nav {
    margin: 0;
    position: sticky;
    top: 5rem;
  }
}

@media (min-width: 1440px) {
  .portal-header-inner,
  .portal-frame {
    padding-left: 2.25rem;
    padding-right: 2.25rem;
  }
  .portal-box {
    grid-template-columns: 14.5rem minmax(0, 1fr);
    gap: 1.85rem;
  }
}

@media (min-width: 1800px) {
  .portal-header-inner,
  .portal-frame {
    padding-left: 2.75rem;
    padding-right: 2.75rem;
  }
}

.portal-header {
  border-bottom: 1px solid color-mix(in srgb, var(--if-border) 80%, transparent);
  background: color-mix(in srgb, var(--if-surface) 88%, transparent);
  backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 20;
}

.portal-mark {
  display: inline-flex;
  height: 2.25rem;
  width: 2.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.55rem;
  background: var(--if-primary);
  font-family: Sora, sans-serif;
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.02em;
  color: #fff;
}

.portal-wordmark {
  font-family: Sora, sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--if-ink);
}

.profile-wrap {
  position: relative;
}
.profile-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
}
.profile-avatar {
  display: inline-flex;
  height: 2.15rem;
  width: 2.15rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--if-primary, #1e3a5f);
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.profile-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 0.45rem);
  min-width: 14rem;
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #d7dee8);
  border-radius: 0.75rem;
  box-shadow: 0 12px 28px rgb(15 23 42 / 0.12);
  padding: 0.4rem;
  z-index: 40;
}
.profile-email {
  margin: 0;
  padding: 0.55rem 0.7rem 0.45rem;
  font-size: 0.75rem;
  color: var(--if-muted, #5b6b7c);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-bottom: 1px solid var(--if-border, #d7dee8);
  margin-bottom: 0.25rem;
}
.profile-menu button {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  border-radius: 0.45rem;
  padding: 0.55rem 0.7rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--if-ink, #0f172a);
  cursor: pointer;
}
.profile-menu button:hover {
  background: color-mix(in srgb, var(--if-primary, #1e3a5f) 8%, transparent);
}
.profile-menu button.danger {
  color: #b91c1c;
}

.support-fab {
  position: fixed;
  right: max(1rem, env(safe-area-inset-right, 0px));
  bottom: max(1rem, env(safe-area-inset-bottom, 0px));
  z-index: 60;
  display: inline-flex;
  align-items: center;
  gap: 0;
  min-width: 3.25rem;
  height: 3.25rem;
  justify-content: center;
  padding: 0 0.95rem;
  border: none;
  border-radius: 999px;
  background: var(--if-primary, #1e3a5f);
  color: #fff;
  box-shadow:
    0 10px 22px rgb(15 23 42 / 0.18),
    0 2px 6px rgb(15 23 42 / 0.08);
  cursor: pointer;
  overflow: visible;
  animation: support-fab-enter 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease,
    background 0.2s ease,
    padding 0.2s ease;
}
.support-fab-ring {
  position: absolute;
  inset: -4px;
  border-radius: inherit;
  border: 2px solid color-mix(in srgb, var(--if-primary, #1e3a5f) 35%, transparent);
  opacity: 0;
  animation: support-fab-pulse 2.8s ease-in-out 0.6s infinite;
  pointer-events: none;
}
.support-fab-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.support-fab-label {
  max-width: 0;
  opacity: 0;
  overflow: hidden;
  white-space: nowrap;
  font-size: 0.8125rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  transition: max-width 0.25s ease, opacity 0.2s ease;
}
.support-fab:hover,
.support-fab:focus-visible {
  transform: translateY(-2px);
  background: var(--if-primary-hover, #16304d);
  box-shadow:
    0 14px 28px rgb(15 23 42 / 0.22),
    0 4px 10px rgb(15 23 42 / 0.1);
}
.support-fab:hover .support-fab-label,
.support-fab:focus-visible .support-fab-label {
  max-width: 4.5rem;
  opacity: 1;
}
.support-fab:hover .support-fab-ring,
.support-fab:focus-visible .support-fab-ring {
  animation: none;
  opacity: 0;
}
.support-fab:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--if-primary, #1e3a5f) 55%, white);
  outline-offset: 3px;
}
.support-fab:active {
  transform: translateY(0) scale(0.98);
}

@keyframes support-fab-enter {
  from {
    opacity: 0;
    transform: translateY(14px) scale(0.9);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes support-fab-pulse {
  0%,
  100% {
    opacity: 0;
    transform: scale(1);
  }
  50% {
    opacity: 0.55;
    transform: scale(1.08);
  }
}

@media (prefers-reduced-motion: reduce) {
  .support-fab {
    animation: none;
  }
  .support-fab-ring {
    animation: none;
    opacity: 0;
  }
  .support-fab:hover,
  .support-fab:focus-visible {
    transform: none;
  }
}

@media (max-width: 639px) {
  .support-fab {
    width: 3.25rem;
    padding: 0;
    justify-content: center;
  }
  .support-fab-label {
    display: none;
  }
  .support-fab-badge {
    top: -0.2rem;
    right: -0.1rem;
  }
}

.support-fab-badge {
  position: absolute;
  top: -0.25rem;
  right: -0.15rem;
  min-width: 1.4rem;
  height: 1.4rem;
  padding: 0 0.25rem;
  border-radius: 999px;
  background: #ef4444;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 900;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 22px rgb(15 23 42 / 0.18);
  pointer-events: none;
}

.portal-footer {
  flex-shrink: 0;
  margin-top: auto;
  border-top: 1px solid var(--if-border);
  padding: 1.25rem 1rem;
  text-align: center;
  font-size: 0.75rem;
  color: var(--if-muted);
}
</style>
