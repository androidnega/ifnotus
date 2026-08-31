<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalShell from '@/components/portal/PortalShell.vue'
import { hostingLocation } from '@/lib/hostingDeepLink'
import { hostnameNow, isCustomerCpanelHost } from '@/lib/platformHosts'

const route = useRoute()
const router = useRouter()
const error = ref('')
const loading = ref(true)

function normalizeHost(raw: string): string {
  let host = String(raw || '').trim().toLowerCase().replace(/\.$/, '')
  if (host.startsWith('www.')) host = host.slice(4)
  if (host.startsWith('fpanel.') && host !== 'fpanel.ifnotus.space') {
    host = host.slice('fpanel.'.length)
  } else if (host.startsWith('cpanel.') && host !== 'cpanel.ifnotus.space') {
    host = host.slice('cpanel.'.length)
  }
  return host
}

onMounted(async () => {
  const raw = route.query.host
  const fromQuery = (Array.isArray(raw) ? raw[0] : raw) || ''
  // Legacy cpanel.<custom-domain> hosts still resolve to apex for lookup.
  const host = normalizeHost(
    String(fromQuery || (isCustomerCpanelHost() ? hostnameNow() : '')),
  )
  const tabRaw = route.query.tab
  const tab = (Array.isArray(tabRaw) ? tabRaw[0] : tabRaw) || ''
  if (!host) {
    error.value = 'Missing hostname.'
    loading.value = false
    return
  }
  try {
    const { data } = await customersApi.resolvePanelAlias(String(host))
    await router.replace(hostingLocation(data.environment_id, String(tab || 'overview')))
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { error?: { message?: string } } } }
    if (err.response?.status === 401) {
      const redirect = tab
        ? `/go/hosting?host=${encodeURIComponent(String(host))}&tab=${encodeURIComponent(String(tab))}`
        : `/go/hosting?host=${encodeURIComponent(String(host))}`
      await router.replace({
        name: 'login',
        query: { mode: 'panel', host, redirect },
      })
      return
    }
    error.value = err.response?.data?.error?.message ?? 'That control-panel address is not available for this account.'
    loading.value = false
  }
})
</script>

<template>
  <PortalShell mode="app">
    <p v-if="loading" class="muted">Opening hosting panel…</p>
    <div v-else class="box">
      <h1>Not authorized</h1>
      <p>{{ error }}</p>
      <router-link to="/account">Back to account</router-link>
    </div>
  </PortalShell>
</template>

<style scoped>
.muted { color: #5c6670; }
.box { max-width: 28rem; }
h1 { font-family: Sora, sans-serif; font-size: 1.4rem; }
</style>
