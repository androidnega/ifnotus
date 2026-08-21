<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { authApi } from '@/api'

const email = ref('')
const emailInput = ref<HTMLInputElement | null>(null)
const loading = ref(false)
const error = ref('')
const sent = ref(false)

onMounted(() => {
  nextTick(() => emailInput.value?.focus())
})

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await authApi.requestPasswordReset(email.value.trim())
    sent.value = true
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not send reset email. Try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page flex min-h-screen flex-col bg-[#e8ebef]">
    <header class="border-b border-[#cfd5dd] bg-white">
      <div class="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4">
        <div
          class="flex h-8 w-8 items-center justify-center rounded bg-[var(--if-primary)] text-sm font-bold text-white"
          aria-hidden="true"
        >
          i
        </div>
        <div class="leading-tight">
          <p class="text-sm font-semibold text-[#1f2937]">IFNOTUS</p>
          <p class="text-[11px] text-[#6b7280]">Password reset</p>
        </div>
      </div>
    </header>

    <main class="flex flex-1 items-center justify-center px-4 py-10">
      <form
        class="w-full max-w-[400px] overflow-hidden rounded border border-[#cfd5dd] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
        @submit.prevent="submit"
      >
        <div class="border-b border-[#dfe3e8] bg-[#f7f8fa] px-6 py-4">
          <h1 class="text-base font-semibold text-[#1f2937]">Forgot password</h1>
          <p class="mt-1 text-sm text-[#6b7280]">
            Enter your account email and we’ll send a reset link if it exists.
          </p>
        </div>

        <div class="space-y-4 px-6 py-5">
          <p
            v-if="sent"
            class="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
          >
            If an account exists for that email, a reset link has been sent. Check your inbox.
          </p>

          <template v-else>
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-[#374151]">Email</span>
              <input
                ref="emailInput"
                v-model="email"
                type="email"
                autocomplete="username"
                required
                placeholder="you@example.com"
                class="login-input"
              />
            </label>

            <p v-if="error" class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {{ error }}
            </p>

            <button type="submit" :disabled="loading" class="login-submit">
              {{ loading ? 'Sending…' : 'Send reset link' }}
            </button>
          </template>

          <p class="text-center text-sm text-[#6b7280]">
            <router-link class="text-[var(--if-primary)] hover:underline" :to="{ name: 'login' }"
              >Back to login</router-link
            >
          </p>
        </div>
      </form>
    </main>

    <footer class="border-t border-[#cfd5dd] bg-white py-3 text-center text-xs text-[#9ca3af]">
      © {{ new Date().getFullYear() }} IFNOTUS
    </footer>
  </div>
</template>

<style scoped>
.login-page {
  color-scheme: light;
  color: #1f2937;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

.login-input {
  width: 100%;
  border-radius: 4px;
  border: 1px solid #c5ccd6;
  background: #fff;
  padding: 0.625rem 0.75rem;
  font-size: 0.875rem;
  color: #111827;
}

.login-input::placeholder {
  color: #9ca3af;
}

.login-input:focus {
  outline: none;
  border-color: var(--if-primary, #ff6c2c);
  box-shadow: 0 0 0 3px var(--if-primary-ring, rgba(255, 108, 44, 0.2));
}

.login-submit {
  width: 100%;
  border-radius: 4px;
  background: var(--if-primary, #ff6c2c);
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #fff;
  transition: background-color 0.15s ease;
}

.login-submit:hover:not(:disabled) {
  background: var(--if-primary-hover, #e85f22);
}

.login-submit:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
