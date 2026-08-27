<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
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
  router.push({ name: 'admin-login' })
}
</script>

<template>
  <div class="login-page ds-auth-shell">
    <form class="card ds-auth-card" @submit.prevent="done ? goLogin() : submit()">
      <UiBrandMark class="auth-brand" />
      <h1 class="ds-page-title">Reset password</h1>
      <p class="hint">Set a new password for your IFNOTUS account.</p>

      <template v-if="done">
        <UiAlert tone="ok">Password updated. You can sign in with your new password.</UiAlert>
        <button type="submit">Go to login</button>
      </template>

      <template v-else>
        <label>
          <span>New password</span>
          <input
            ref="passwordInput"
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
            placeholder="At least 8 characters"
          />
        </label>

        <label>
          <span>Confirm password</span>
          <input
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
            placeholder="Repeat new password"
          />
        </label>

        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>

        <button type="submit" :disabled="loading">
          {{ loading ? 'Saving…' : 'Update password' }}
        </button>

        <p class="row row--center">
          <router-link class="link" :to="{ name: 'forgot-password' }">Request a new link</router-link>
        </p>
      </template>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  color-scheme: light;
}
</style>
