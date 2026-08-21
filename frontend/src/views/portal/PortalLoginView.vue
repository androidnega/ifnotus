<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'

const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const info = ref('')

onMounted(() => {
  if (route.query.verified === '1') info.value = 'Email verified. You can log in now.'
})

async function login() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.login({ email: email.value, password: password.value })
    if (!data.access_token || !data.refresh_token) {
      error.value = data.message ?? 'Login failed.'
      return
    }
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    localStorage.setItem('ifnotus_portal', '1')
    await router.push({ name: 'portal-dashboard' })
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Login failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-[#f4f6f8] px-4">
    <form class="w-full max-w-md rounded border border-slate-200 bg-white p-6 shadow-sm" @submit.prevent="login">
      <h1 class="text-xl font-semibold">IFNOTUS Panel</h1>
      <p class="mt-1 text-sm text-slate-500">Customer login</p>
      <p v-if="info" class="mt-3 text-sm text-emerald-700">{{ info }}</p>
      <div class="mt-5 space-y-3">
        <input
          v-model="email"
          type="email"
          required
          placeholder="Email"
          class="w-full rounded border border-slate-300 px-3 py-2.5 text-sm focus:border-[var(--if-primary)] focus:outline-none focus:ring-2 focus:ring-[color:var(--if-primary-ring)]"
        />
        <input
          v-model="password"
          type="password"
          required
          placeholder="Password"
          class="w-full rounded border border-slate-300 px-3 py-2.5 text-sm focus:border-[var(--if-primary)] focus:outline-none focus:ring-2 focus:ring-[color:var(--if-primary-ring)]"
        />
      </div>
      <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
      <button
        type="submit"
        class="mt-5 w-full rounded bg-[var(--if-primary)] py-2.5 text-sm font-semibold text-white disabled:opacity-60"
        :disabled="loading"
      >
        {{ loading ? 'Signing in…' : 'Log in' }}
      </button>
      <p class="mt-3 text-center text-sm text-slate-500">
        <router-link class="text-[var(--if-primary)]" :to="{ name: 'home' }">View plans</router-link>
        ·
        <router-link class="text-slate-600" :to="{ name: 'login' }">Staff login</router-link>
      </p>
    </form>
  </div>
</template>
