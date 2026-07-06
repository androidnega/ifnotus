<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')

async function handleLogin() {
  const ok = await auth.login({ email: email.value, password: password.value })
  if (!ok) return
  const redirect = (route.query.redirect as string) || '/'
  router.push(redirect)
}
</script>

<template>
  <div class="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
    <form
      class="w-full max-w-sm space-y-4 rounded-lg border border-gray-800 bg-gray-900 p-6"
      @submit.prevent="handleLogin"
    >
      <h1 class="text-xl font-semibold">Sign in to IFNOTUS</h1>

      <div>
        <label class="block text-sm text-gray-400">Email or username</label>
        <input
          v-model="email"
          type="text"
          autocomplete="username"
          required
          placeholder="admin"
          class="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
        />
      </div>

      <div>
        <label class="block text-sm text-gray-400">Password</label>
        <input
          v-model="password"
          type="password"
          required
          class="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
        />
      </div>

      <p v-if="auth.error" class="text-sm text-red-400">{{ auth.error }}</p>

      <button
        type="submit"
        :disabled="auth.loading"
        class="w-full rounded bg-brand-600 py-2 text-sm font-medium hover:bg-brand-500 disabled:opacity-50"
      >
        {{ auth.loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>
