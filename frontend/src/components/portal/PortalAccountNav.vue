<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UiTabBar from '@/components/ui/UiTabBar.vue'
import { PORTAL_ACCOUNT_TABS } from '@/lib/uiRegistry'
import { openHostingFromAccount } from '@/lib/hostingDeepLink'

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

const tabItems = computed(() =>
  PORTAL_ACCOUNT_TABS.filter((t) => !('requiresEnv' in t && t.requiresEnv) || props.hasEnv).map((t) => ({
    id: t.id,
    label: t.label,
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
  if (next === 'hosting') {
    if (props.domain && openHostingFromAccount(props.domain)) return
    void router.push({ name: 'portal-dashboard', query: { panel: 'billing' } })
    return
  }
  void router.push({ name: 'portal-dashboard', query: { panel: next } })
}

function onTab(id: string) {
  go(id)
}
</script>

<template>
  <UiTabBar
    :items="tabItems"
    :model-value="panel"
    variant="sidebar"
    aria-label="Account"
    class="portal-account-nav"
    @update:model-value="onTab"
  />
</template>

<style scoped>
.portal-account-nav :deep(.ds-tabbar--sidebar) {
  background: color-mix(in srgb, var(--if-border) 45%, var(--if-surface));
}
@media (max-width: 1099px) {
  .portal-account-nav :deep(.ds-tabbar--sidebar) {
    flex-direction: row;
    width: fit-content;
    max-width: 100%;
    border-radius: 999px;
    padding: 0.28rem;
  }
  .portal-account-nav :deep(.ds-tabbar--sidebar .ds-tab) {
    width: auto;
    text-align: center;
    border-radius: 999px;
    padding: 0.48rem 1.05rem;
  }
}
</style>
