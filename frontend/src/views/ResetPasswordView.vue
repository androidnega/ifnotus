<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()

const token = computed(() => {
  const raw = route.query.token
  return typeof raw === 'string' ? raw.trim() : ''
})

const password = ref('')
const confirm = ref('')
const passwordInput = ref<HTMLInputElement | null>(null)
const loading = ref(false)
const error = ref('')
const done = ref(false)

onMounted(() => {
  nextTick(() => passwordInput.value?.focus())
})

async function submit() {
  error.value = ''
  if (!token.value || token.value.length < 20) {
    error.value = 'This reset link is invalid or incomplete. Request a new one.'
    return
  }
  if (password.value.length < 8) {
    error.value = 'Password must be at least 8 characters.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'Passwords do not match.'
    return
  }
  loading.value = true
  try {
    await authApi.confirmPasswordReset(token.value, password.value)
    done.value = true
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not reset password. Try again.'
  } finally {
    loading.value = false
  }
}

function goLogin() {
  router.push({ name: 'login' })
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
          <p class="text-[11px] text-[#6b7280]">Choose a new password</p>
        </div>
      </div>
    </header>

    <main class="flex flex-1 items-center justify-center px-4 py-10">
      <form
        class="w-full max-w-[400px] overflow-hidden rounded border border-[#cfd5dd] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
        @submit.prevent="done ? goLogin() : submit()"
      >
        <div class="border-b border-[#dfe3e8] bg-[#f7f8fa] px-6 py-4">
          <h1 class="text-base font-semibold text-[#1f2937]">Reset password</h1>
          <p class="mt-1 text-sm text-[#6b7280]">
            Set a new password for your IFNOTUS account.
          </p>
        </div>

        <div class="space-y-4 px-6 py-5">
          <template v-if="done">
            <p class="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Password updated. You can sign in with your new password.
            </p>
            <button type="submit" class="login-submit">Go to login</button>
          </template>

          <template v-else>
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-[#374151]">New password</span>
              <input
                ref="passwordInput"
                v-model="password"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                placeholder="At least 8 characters"
                class="login-input"
              />
            </label>

            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-[#374151]">Confirm password</span>
              <input
                v-model="confirm"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                placeholder="Repeat new password"
                class="login-input"
              />
            </label>

            <p v-if="error" class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {{ error }}
            </p>

            <button type="submit" :disabled="loading" class="login-submit">
              {{ loading ? 'Saving…' : 'Update password' }}
            </button>

            <p class="text-center text-sm text-[#6b7280]">
              <router-link class="text-[var(--if-primary)] hover:underline" :to="{ name: 'forgot-password' }"
                >Request a new link</router-link
              >
            </p>
          </template>
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
