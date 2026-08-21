<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
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
  <div class="login-page">
    <form
      v-if="step === 'credentials'"
      class="card"
      @submit.prevent="handleLogin"
    >
      <div class="brand">
        <span class="mark" aria-hidden="true">i</span>
        <strong>IFNOTUS</strong>
      </div>
      <h1>Log in</h1>
      <p class="hint">Customers: use your phone. Staff: email and password.</p>

      <p class="customer-entry">
        <router-link class="phone-cta" :to="{ name: 'portal-signup' }">Continue with phone</router-link>
      </p>

      <p v-if="route.query.verified === '1'" class="note ok">Email verified. You can log in.</p>

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

      <p v-if="auth.error" class="note err">{{ auth.error }}</p>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Log in' }}
      </button>
    </form>

    <form
      v-else-if="step === 'challenge'"
      class="card"
      @submit.prevent="handleVerify"
    >
      <div class="brand">
        <span class="mark" aria-hidden="true">i</span>
        <strong>IFNOTUS</strong>
      </div>
      <h1>Approve device</h1>
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

      <p v-if="auth.error" class="note err">{{ auth.error }}</p>

      <button type="submit" :disabled="auth.loading || approvalCode.trim().length < 4">
        {{ auth.loading ? 'Verifying…' : 'Continue' }}
      </button>
      <button type="button" class="ghost" @click="backToCredentials">Back</button>
    </form>

    <form v-else class="card" @submit.prevent="handleTotp">
      <div class="brand">
        <span class="mark" aria-hidden="true">i</span>
        <strong>IFNOTUS</strong>
      </div>
      <h1>Authenticator</h1>

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

      <p v-if="auth.error" class="note err">{{ auth.error }}</p>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Continue' }}
      </button>
      <button type="button" class="ghost" @click="backToCredentials">Back</button>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: #eef2f6;
  color: #0f172a;
  font-family: Inter, Figtree, ui-sans-serif, system-ui, sans-serif;
  color-scheme: light;
}

.card {
  width: 100%;
  max-width: 22rem;
  display: grid;
  gap: 0.55rem;
  padding: 1rem 1.05rem 0.95rem;
  border: 1px solid #d7dee8;
  border-radius: 0.65rem;
  background: #fff;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.1rem;
}

.mark {
  display: inline-flex;
  width: 1.55rem;
  height: 1.55rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.35rem;
  background: #1e3a5f;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 800;
}

.brand strong {
  font-size: 0.78rem;
  font-weight: 750;
  letter-spacing: 0.04em;
}

h1 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.hint {
  margin: 0;
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.35;
}

label {
  display: grid;
  gap: 0.22rem;
}

label span {
  font-size: 0.72rem;
  font-weight: 650;
  color: #475569;
}

input {
  width: 100%;
  border: 1px solid #c9d3df;
  border-radius: 0.4rem;
  background: #fff;
  padding: 0.42rem 0.55rem;
  font-size: 0.84rem;
  color: #0f172a;
}

input::placeholder {
  color: #94a3b8;
}

input:focus {
  outline: none;
  border-color: #1e3a5f;
  box-shadow: 0 0 0 3px rgb(30 58 95 / 0.14);
}

input.code {
  text-align: center;
  font-family: ui-monospace, monospace;
  letter-spacing: 0.28em;
}

.row {
  display: flex;
  justify-content: flex-end;
  margin-top: -0.15rem;
}

.link {
  font-size: 0.72rem;
  font-weight: 650;
  color: #1e3a5f;
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

.note {
  margin: 0;
  padding: 0.4rem 0.5rem;
  border-radius: 0.4rem;
  font-size: 0.75rem;
  line-height: 1.35;
}

.note.ok {
  border: 1px solid #a7f3d0;
  background: #ecfdf5;
  color: #047857;
}

.note.err {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

button[type='submit'] {
  margin-top: 0.15rem;
  width: 100%;
  border: none;
  border-radius: 0.4rem;
  background: #1e3a5f;
  color: #fff;
  font-size: 0.84rem;
  font-weight: 650;
  padding: 0.48rem 0.75rem;
  cursor: pointer;
}

button[type='submit']:hover:not(:disabled) {
  background: #16304d;
}

button[type='submit']:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.ghost {
  border: none;
  background: none;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0.15rem;
}

.ghost:hover {
  color: #334155;
}

.customer-entry {
  margin: 0.15rem 0 0.35rem;
}

.phone-cta {
  display: block;
  text-align: center;
  text-decoration: none;
  border-radius: 0.45rem;
  background: #ff6c2c;
  color: #fff;
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.55rem 0.75rem;
}

.phone-cta:hover {
  filter: brightness(0.96);
}
</style>
