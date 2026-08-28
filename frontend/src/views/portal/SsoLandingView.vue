<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import PortalShell from '@/components/portal/PortalShell.vue'

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

  try {
    const { data } = await customersApi.consumeSsoToken(token, window.location.hostname)
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

    const auth = useAuthStore()
    await auth.fetchUser().catch(() => {})

    const target = tab && tab !== 'overview' ? `/${tab.replace(/^\//, '')}` : '/'
    await router.replace(target)
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
