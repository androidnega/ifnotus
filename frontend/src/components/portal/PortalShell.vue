<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSiteTheme } from '@/composables/useSiteTheme'
import '@/assets/portal.css'

const props = defineProps<{
  subtitle?: string
  email?: string
  displayName?: string
  /** Marketing landing vs signed-in panel */
  mode?: 'marketing' | 'app'
  /** Active package accent */
  planAccent?: string
  /** Built-in profile menu + support FAB (app mode) */
  profileMenu?: boolean
}>()

const emit = defineEmits<{
  account: []
  support: []
  logout: []
}>()

const router = useRouter()
const { load, isDark } = useSiteTheme()
let previousDark = false

const menuOpen = ref(false)
const showProfile = computed(() => props.mode === 'app' && props.profileMenu !== false)

const initials = computed(() => {
  const src = (props.displayName || props.email || 'U').trim()
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
        <router-link :to="{ name: mode === 'app' ? 'portal-dashboard' : 'home' }" class="flex items-center gap-3">
          <span class="portal-mark" aria-hidden="true">IF</span>
          <span class="portal-wordmark">IFNOTUS</span>
        </router-link>
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
              <p v-if="email" class="profile-email">{{ email }}</p>
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
    <main v-else class="mx-auto w-full max-w-6xl px-5 pb-20">
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
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
        <path
          d="M4 12a8 8 0 0 1 8-8h0a8 8 0 0 1 8 8v5.2A1.8 1.8 0 0 1 18.2 19H13l-3.4 2.4c-.5.35-1.2-.02-1.2-.62V19H5.8A1.8 1.8 0 0 1 4 17.2V12Z"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linejoin="round"
        />
      </svg>
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
  background:
    radial-gradient(900px 420px at 88% -8%, color-mix(in srgb, var(--if-primary) 18%, transparent), transparent 55%),
    linear-gradient(165deg, color-mix(in srgb, var(--if-paper) 70%, white) 0%, var(--if-paper) 45%, color-mix(in srgb, var(--if-border) 35%, var(--if-paper)) 100%);
}

.portal-app {
  --if-primary: #1e3a5f;
  --if-primary-hover: #16304d;
  --if-plan: #1e3a5f;
  --p-accent: #1e3a5f;
  --if-ink: #0f172a;
  --if-paper: #eef2f6;
  --if-surface: #ffffff;
  --if-muted: #5b6b7c;
  --if-border: #d7dee8;
  background:
    radial-gradient(720px 280px at 0% 0%, color-mix(in srgb, #1e3a5f 10%, transparent), transparent 60%),
    var(--if-paper);
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
  right: 1.15rem;
  bottom: 1.15rem;
  z-index: 50;
  width: 3.25rem;
  height: 3.25rem;
  border: none;
  border-radius: 999px;
  background: var(--if-primary, #1e3a5f);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 24px rgb(15 23 42 / 0.22);
  cursor: pointer;
}
.support-fab:hover {
  background: var(--if-primary-hover, #16304d);
}

.portal-footer {
  border-top: 1px solid var(--if-border);
  padding: 2rem 1rem;
  text-align: center;
  font-size: 0.75rem;
  color: var(--if-muted);
}
</style>
