<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { isCustomerCpanelHost, isStaffPanelHost, isTenantSubdomainHost } from '@/lib/platformHosts'
import PortalShell from '@/components/portal/PortalShell.vue'

function peekSsoDomain(token: string): string {
  try {
    const part = token.split('.')[1]
    if (!part) return ''
    const json = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')))
    return String(json.domain || '').toLowerCase().trim()
  } catch {
    return ''
  }
}

const route = useRoute()
const router = useRouter()
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  const token = String(route.query.token || '').trim()
  const tab = String(route.query.tab || '').trim()
  if (!token) {
    error.value = 'Missing or invalid SSO token.'
    loading.value = false
    return
  }

  // Legacy handoffs sometimes land on fpanel.ifnotus.space for *.ifnotus.space tenants — bounce to same-host panel.
  if (isStaffPanelHost()) {
    const domain = peekSsoDomain(token)
    if (domain && isTenantSubdomainHost(domain)) {
      const q = new URLSearchParams({ token })
      if (tab && tab !== 'overview') q.set('tab', tab)
      window.location.replace(`https://${domain}/hosting/sso?${q.toString()}`)
      return
    }
  }

  try {
    const { data } = await customersApi.consumeSsoToken(token, window.location.hostname)
    const auth = useAuthStore()
    localStorage.setItem('access_token', data.access_token)
    if (data.refresh_token) {
      localStorage.setItem('refresh_token', data.refresh_token)
    }
    if (data.environment_id) {
      localStorage.setItem('tenant_env_id', String(data.environment_id))
    }
    if (data.domain) {
      localStorage.setItem('tenant_domain', String(data.domain))
    }
    auth.accessToken = data.access_token
    await auth.fetchUser().catch(() => {})

    const envId = String(data.environment_id || '')
    if (isTenantSubdomainHost() && envId) {
      const q = tab && tab !== 'overview' ? { tab } : undefined
      await router.replace({ name: 'hosting-panel', params: { environmentId: envId }, query: q })
      return
    }
    if (isCustomerCpanelHost()) {
      const target = tab && tab !== 'overview' ? `/${tab.replace(/^\//, '')}` : '/'
      await router.replace(target)
      return
    }
    if (envId) {
      await router.replace({ name: 'hosting-panel', params: { environmentId: envId }, query: tab ? { tab } : undefined })
      return
    }
    await router.replace('/')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } }; message?: string }
    error.value = err.response?.data?.error?.message || err.message || 'Invalid or expired SSO token.'
    loading.value = false
  }
})
</script>

<template>
  <PortalShell mode="app">
    <div v-if="loading" class="sso-loading">
      <p class="muted">Logging into your hosting panel…</p>
    </div>
    <div v-else class="sso-error box">
      <h1>Sign-in error</h1>
      <p class="err-msg">{{ error }}</p>
      <a href="https://ifnotus.space/account" class="btn-link">Return to IFNOTUS Account</a>
    </div>
  </PortalShell>
</template>

<style scoped>
.sso-loading {
  padding: 3rem 1rem;
  text-align: center;
}
.muted {
  color: #5c6670;
}
.box {
  max-width: 28rem;
  margin: 2rem auto;
  padding: 2rem;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e3e7ec;
  text-align: center;
}
h1 {
  font-family: Sora, sans-serif;
  font-size: 1.35rem;
  margin-bottom: 0.75rem;
}
.err-msg {
  color: #dc2626;
  margin-bottom: 1.5rem;
}
.btn-link {
  display: inline-block;
  padding: 0.5rem 1.25rem;
  background: #1e3a5f;
  color: #fff;
  text-decoration: none;
  border-radius: 6px;
  font-weight: 500;
}
</style>
