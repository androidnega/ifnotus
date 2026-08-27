<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
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
  <div class="login-page ds-auth-shell">
    <form class="card ds-auth-card" @submit.prevent="submit">
      <UiBrandMark class="auth-brand" />
      <h1 class="ds-page-title">Forgot password</h1>
      <p class="hint">Enter your account email and we’ll send a reset link if it exists.</p>

      <UiAlert v-if="sent" tone="ok">
        If an account exists for that email, a reset link has been sent. Check your inbox.
      </UiAlert>

      <template v-else>
        <label>
          <span>Email</span>
          <input
            ref="emailInput"
            v-model="email"
            type="email"
            autocomplete="username"
            required
            placeholder="you@example.com"
          />
        </label>

        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>

        <button type="submit" :disabled="loading">
          {{ loading ? 'Sending…' : 'Send reset link' }}
        </button>
      </template>

      <p class="row row--center">
        <router-link class="link" :to="{ name: 'admin-login' }">Back to login</router-link>
      </p>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  color-scheme: light;
}
</style>
