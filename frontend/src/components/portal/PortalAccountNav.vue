<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PORTAL_ACCOUNT_TABS } from '@/lib/uiRegistry'
import { openHostingFromAccount } from '@/lib/hostingDeepLink'
import {
  IconDashboard,
  IconServer,
  IconChart,
  IconActivity,
  IconSettings,
} from '@/components/icons'

const props = defineProps<{
  hasEnv?: boolean
  environmentId?: string | null
  domain?: string | null
  active?: string
}>()

const route = useRoute()
const router = useRouter()

const panel = computed(() => {
  if (props.active) return props.active
  if (route.name === 'portal-account-plans' || route.name === 'plans') return 'billing'
  if (route.name === 'portal-account-settings') return 'settings'
  if (route.name === 'portal-support') return 'support'
  if (route.name === 'portal-invoice') return 'billing'
  if (String(route.name || '').startsWith('hosting')) return 'hosting'
  const q = String(route.query.panel || 'home')
  if (q === 'plans') return 'billing'
  if (q === 'ai' || q === 'site') return 'hosting'
  return q
})

const tabIconMap: Record<string, any> = {
  home: IconDashboard,
  billing: IconChart,
  support: IconActivity,
  settings: IconSettings,
}

const tabItems = computed(() =>
  PORTAL_ACCOUNT_TABS.map((t) => ({
    id: t.id,
    label: t.label,
    icon: tabIconMap[t.id] || IconDashboard,
  })),
)

function go(next: string) {
  if (next === 'support') {
    void router.push({ name: 'portal-support' })
    return
  }
  if (next === 'settings') {
    void router.push({ name: 'portal-account-settings' })
    return
  }
  if (next === 'home') {
    void router.push({ name: 'portal-dashboard' })
    return
  }
  void router.push({ name: 'portal-dashboard', query: { panel: next } })
}
</script>

<template>
  <nav class="portal-account-nav-card" aria-label="Account navigation">
    <div class="nav-list">
      <button
        v-for="item in tabItems"
        :key="item.id"
        type="button"
        class="nav-tab-btn"
        :class="{ on: panel === item.id }"
        @click="go(item.id)"
      >
        <component :is="item.icon" :size="17" class="nav-icon" />
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.portal-account-nav-card {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1.15rem;
  padding: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.nav-tab-btn {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--p-muted, #64748b);
  font-family: inherit;
  font-size: 0.88rem;
  font-weight: 600;
  padding: 0.65rem 0.95rem;
  border-radius: 0.8rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.nav-icon {
  flex-shrink: 0;
  opacity: 0.75;
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.nav-tab-btn:hover {
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 7%, transparent);
  color: var(--p-ink, #0f172a);
}

.nav-tab-btn:hover .nav-icon {
  opacity: 1;
  transform: scale(1.05);
}

.nav-tab-btn.on {
  background: var(--p-accent, #1e3a5f);
  color: #ffffff;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--p-accent, #1e3a5f) 30%, transparent);
}

.nav-tab-btn.on .nav-icon {
  opacity: 1;
}

@media (max-width: 1099px) {
  .portal-account-nav-card {
    border-radius: 999px;
    padding: 0.3rem;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .portal-account-nav-card::-webkit-scrollbar {
    display: none;
  }
  .nav-list {
    flex-direction: row;
    gap: 0.25rem;
  }
  .nav-tab-btn {
    width: auto;
    white-space: nowrap;
    border-radius: 999px;
    padding: 0.45rem 0.95rem;
    font-size: 0.82rem;
  }
}
</style>
