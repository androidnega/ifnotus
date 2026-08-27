<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'
import { ensureDeviceFingerprint } from '@/api/client'
import { isPortalPath, isPureCustomer, isStaffPath } from '@/lib/roles'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const approvalCode = ref('')
const emailInput = ref<HTMLInputElement | null>(null)
const codeInput = ref<HTMLInputElement | null>(null)
const fingerprint = ref<string | null>(null)
const totpCode = ref('')
const step = ref<'credentials' | 'challenge' | 'totp'>('credentials')
const challengeId = ref('')
const challengeIp = ref('')

onMounted(async () => {
  nextTick(() => emailInput.value?.focus())
  try {
    fingerprint.value = (await ensureDeviceFingerprint()) ?? null
    await authApi.probe({ device_fingerprint: fingerprint.value ?? undefined })
  } catch {
    /* probe is best-effort */
  }
})

async function finishRedirect(home: 'dashboard' | 'portal-dashboard') {
  const raw = route.query.redirect
  const candidate = Array.isArray(raw) ? raw[0] : raw
  let target: string | { name: string } = { name: home }

  if (
    typeof candidate === 'string' &&
    candidate.startsWith('/') &&
    !candidate.startsWith('//') &&
    candidate !== '/login' &&
    candidate !== '/signup' &&
    candidate !== '/admin_1' &&
    candidate !== '/portal/login'
  ) {
    const customer = isPureCustomer(auth.user)
    if (customer && isStaffPath(candidate)) {
      target = { name: 'portal-dashboard' }
    } else if (!customer && isPortalPath(candidate) && !candidate.includes('/dashboard')) {
      target = { name: home }
    } else {
      target = candidate
    }
  }

  try {
    await router.replace(target)
  } catch {
    const path = typeof target === 'string' ? target : home === 'portal-dashboard' ? '/account' : '/panel'
    window.location.assign(path)
  }
}

async function handleLogin() {
  const result = await auth.login({
    email: email.value,
    password: password.value,
    device_fingerprint: fingerprint.value ?? (await ensureDeviceFingerprint().catch(() => undefined)),
  })
  if (result.ok) {
    await finishRedirect(result.home)
    return
  }
  if (result.totp) {
    step.value = 'totp'
    totpCode.value = ''
    return
  }
  if (result.challenge?.challenge_id) {
    challengeId.value = result.challenge.challenge_id
    challengeIp.value = result.challenge.ip_address || ''
    step.value = 'challenge'
    approvalCode.value = ''
    nextTick(() => codeInput.value?.focus())
  }
}

async function handleVerify() {
  const result = await auth.verifyDevice({
    challenge_id: challengeId.value,
    code: approvalCode.value.trim(),
    device_fingerprint: fingerprint.value ?? (await ensureDeviceFingerprint().catch(() => undefined)),
  })
  if (!result.ok || !result.home) return
  await finishRedirect(result.home)
}

async function handleTotp() {
  const result = await auth.login({
    email: email.value,
    password: password.value,
    totp_code: totpCode.value.trim(),
    device_fingerprint: fingerprint.value ?? (await ensureDeviceFingerprint().catch(() => undefined)),
  })
  if (result.ok) {
    await finishRedirect(result.home)
  }
}

function backToCredentials() {
  step.value = 'credentials'
  approvalCode.value = ''
  totpCode.value = ''
  auth.error = null
  nextTick(() => emailInput.value?.focus())
}
</script>

<template>
  <div class="login-page ds-auth-shell">
    <form
      v-if="step === 'credentials'"
      class="card ds-auth-card"
      @submit.prevent="handleLogin"
    >
      <UiBrandMark class="auth-brand" />
      <h1 class="ds-page-title">Staff log in</h1>

      <UiAlert v-if="route.query.verified === '1'" tone="ok">Email verified. You can log in.</UiAlert>

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

      <label>
        <span>Password</span>
        <input
          v-model="password"
          type="password"
          required
          autocomplete="current-password"
          placeholder="Password"
        />
      </label>

      <div class="row">
        <router-link class="link" :to="{ name: 'forgot-password' }">Forgot password?</router-link>
      </div>

      <UiAlert v-if="auth.error" tone="err">{{ auth.error }}</UiAlert>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Log in' }}
      </button>
    </form>

    <form
      v-else-if="step === 'challenge'"
      class="card ds-auth-card"
      @submit.prevent="handleVerify"
    >
      <UiBrandMark class="auth-brand" />
      <h1 class="ds-page-title">Approve device</h1>
      <p class="hint">New IP{{ challengeIp ? ` · ${challengeIp}` : '' }}. Enter the server code.</p>

      <label>
        <span>Code</span>
        <input
          ref="codeInput"
          v-model="approvalCode"
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
          maxlength="8"
          placeholder="6-digit code"
          class="code"
        />
      </label>

      <UiAlert v-if="auth.error" tone="err">{{ auth.error }}</UiAlert>

      <button type="submit" :disabled="auth.loading || approvalCode.trim().length < 4">
        {{ auth.loading ? 'Verifying…' : 'Continue' }}
      </button>
      <button type="button" class="ghost" @click="backToCredentials">Back</button>
    </form>

    <form v-else class="card ds-auth-card" @submit.prevent="handleTotp">
      <UiBrandMark class="auth-brand" />
      <h1 class="ds-page-title">Authenticator</h1>

      <label>
        <span>Code</span>
        <input
          v-model="totpCode"
          class="code"
          maxlength="8"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
          placeholder="6-digit code"
        />
      </label>

      <UiAlert v-if="auth.error" tone="err">{{ auth.error }}</UiAlert>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Continue' }}
      </button>
      <button type="button" class="ghost" @click="backToCredentials">Back</button>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  color-scheme: light;
}
input.code {
  text-align: center;
  font-family: var(--ds-font-mono, ui-monospace, monospace);
  letter-spacing: 0.28em;
}
</style>
