<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalShell from '@/components/portal/PortalShell.vue'
import { hostingLocation } from '@/lib/hostingDeepLink'
import {
  hostnameNow,
  isCustomerCpanelHost,
  isReservedPanelHost,
  isStaffPanelHost,
  isTenantSubdomainHost,
  normalizeGoHostingHost,
  openTenantFpanel,
  portalLoginUrl,
  redirectToPortalAccount,
  redirectToStaffPanel,
  staffPanelHref,
} from '@/lib/platformHosts'
import { isStaffUser, isPureCustomer } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const error = ref('')
const loading = ref(true)

function normalizeHost(raw: string): string {
  return normalizeGoHostingHost(String(raw || '').trim())
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
  if (isReservedPanelHost(host)) {
    if (isStaffPanelHost()) {
      redirectToStaffPanel('/panel')
      return
    }
    if (isStaffUser(auth.user) && !isPureCustomer(auth.user)) {
      redirectToStaffPanel('/panel')
      return
    }
    redirectToPortalAccount('/account')
    return
  }
  try {
    const { data } = await customersApi.resolvePanelAlias(String(host))
    const domain = data.domain || host
    if (isTenantSubdomainHost(domain)) {
      const opened = await openTenantFpanel(domain, tab || null, data.environment_id, false)
      if (!opened) {
        await router.replace({ name: 'portal-dashboard' })
      }
      return
    }
    await router.replace(hostingLocation(data.environment_id, String(tab || 'overview')))
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { error?: { message?: string } } } }
    if (err.response?.status === 401) {
      const redirect = tab
        ? `/go/hosting?host=${encodeURIComponent(String(host))}&tab=${encodeURIComponent(String(tab))}`
        : `/go/hosting?host=${encodeURIComponent(String(host))}`
      window.location.href = portalLoginUrl(redirect)
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
      <router-link :to="isStaffPanelHost() ? staffPanelHref('/login') : '/account'">
        {{ isStaffPanelHost() ? 'Back to staff panel login' : 'Back to account' }}
      </router-link>
    </div>
  </PortalShell>
</template>

<style scoped>
.muted { color: #5c6670; }
.box { max-width: 28rem; }
h1 { font-family: Sora, sans-serif; font-size: 1.4rem; }
</style>
