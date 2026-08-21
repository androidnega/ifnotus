<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps<{
  hasEnv?: boolean
  environmentId?: string | null
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
    const id = props.environmentId
    if (id) {
      void router.push({ name: 'hosting-panel', params: { environmentId: id } })
      return
    }
    void router.push({ name: 'portal-dashboard', query: { panel: 'site', tab: 'stack' } })
    return
  }
  void router.push({ name: 'portal-dashboard', query: { panel: next } })
}
</script>

<template>
  <nav class="pills" aria-label="Account">
    <button type="button" :class="{ on: panel === 'home' }" @click="go('home')">Overview</button>
    <button
      v-if="hasEnv"
      type="button"
      :class="{ on: panel === 'hosting' || panel === 'site' }"
      @click="go('hosting')"
    >
      Hosting services
    </button>
    <button type="button" :class="{ on: panel === 'billing' }" @click="go('billing')">Billing</button>
    <button type="button" :class="{ on: panel === 'support' }" @click="go('support')">Support</button>
    <button type="button" :class="{ on: panel === 'settings' }" @click="go('settings')">Settings</button>
  </nav>
</template>

<style scoped>
.pills {
  display: flex;
  gap: 0.25rem;
  padding: 0.28rem;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  border-radius: 999px;
  background: color-mix(in srgb, var(--if-border) 55%, var(--if-surface));
}
.pills button {
  border: none;
  background: transparent;
  color: var(--if-muted);
  font-size: 0.86rem;
  font-weight: 650;
  padding: 0.48rem 1.05rem;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}
.pills button.on {
  background: var(--if-surface);
  color: var(--if-ink);
  box-shadow: 0 1px 2px rgb(22 26 29 / 0.08);
}
.pills button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

@media (min-width: 1100px) {
  .pills {
    flex-direction: column;
    width: 100%;
    border-radius: 1rem;
    padding: 0.4rem;
    gap: 0.2rem;
  }
  .pills button {
    width: 100%;
    text-align: left;
    border-radius: 0.7rem;
    padding: 0.62rem 0.85rem;
  }
}
</style>
