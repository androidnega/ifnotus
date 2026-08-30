<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import { IconEye, IconEyeOff } from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'
import { ensureDeviceFingerprint } from '@/api/client'
import { isPortalPath, isPureCustomer, isStaffPath } from '@/lib/roles'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const showPassword = ref(false)
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
    candidate !== '/staff/login' &&
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
  <div class="cpanel-login-shell">
    <div class="cpanel-login-container">
      <div class="cpanel-login-brand">
        <UiBrandMark variant="staff" />
      </div>

      <!-- Credentials step -->
      <template v-if="step === 'credentials'">
        <form class="cpanel-login-card" @submit.prevent="handleLogin">
          <UiAlert v-if="route.query.verified === '1'" tone="ok" class="compact-alert">Email verified. You can log in.</UiAlert>

          <div class="cpanel-input-wrap">
            <span class="cpanel-input-icon">
              <i class="fas fa-user" aria-hidden="true" />
            </span>
            <input
              ref="emailInput"
              v-model="email"
              type="email"
              autocomplete="username"
              required
              placeholder="Username or email"
            />
          </div>

          <div class="cpanel-input-wrap">
            <span class="cpanel-input-icon">
              <i class="fas fa-lock" aria-hidden="true" />
            </span>
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              placeholder="Password"
            />
            <button
              type="button"
              class="cpanel-eye-btn"
              :title="showPassword ? 'Hide password' : 'Show password'"
              tabindex="-1"
              @click="showPassword = !showPassword"
            >
              <IconEyeOff v-if="showPassword" :size="16" />
              <IconEye v-else :size="16" />
            </button>
          </div>

          <UiAlert v-if="auth.error" tone="err" class="compact-alert">{{ auth.error }}</UiAlert>

          <button type="submit" class="cpanel-btn-submit" :disabled="auth.loading">
            {{ auth.loading ? 'Signing in…' : 'Log in' }}
          </button>
        </form>

        <div class="cpanel-card-foot">
          <router-link class="cpanel-foot-link" :to="{ name: 'forgot-password' }">Reset Password</router-link>
        </div>
      </template>

      <!-- Challenge step -->
      <form
        v-else-if="step === 'challenge'"
        class="cpanel-login-card"
        @submit.prevent="handleVerify"
      >
        <div class="cpanel-input-wrap">
          <span class="cpanel-input-icon">
            <i class="fas fa-shield-alt" aria-hidden="true" />
          </span>
          <input
            ref="codeInput"
            v-model="approvalCode"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            maxlength="8"
            placeholder="Device code"
            class="code"
          />
        </div>

        <UiAlert v-if="auth.error" tone="err" class="compact-alert">{{ auth.error }}</UiAlert>

        <button type="submit" class="cpanel-btn-submit" :disabled="auth.loading || approvalCode.trim().length < 4">
          {{ auth.loading ? 'Verifying…' : 'Continue' }}
        </button>
        <button type="button" class="cpanel-btn-ghost" @click="backToCredentials">Back</button>
      </form>

      <!-- TOTP step -->
      <form
        v-else-if="step === 'totp'"
        class="cpanel-login-card"
        @submit.prevent="handleTotp"
      >
        <div class="cpanel-input-wrap">
          <span class="cpanel-input-icon">
            <i class="fas fa-key" aria-hidden="true" />
          </span>
          <input
            v-model="totpCode"
            class="code"
            maxlength="8"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            placeholder="6-digit code"
          />
        </div>

        <UiAlert v-if="auth.error" tone="err" class="compact-alert">{{ auth.error }}</UiAlert>

        <button type="submit" class="cpanel-btn-submit" :disabled="auth.loading">
          {{ auth.loading ? 'Signing in…' : 'Continue' }}
        </button>
        <button type="button" class="cpanel-btn-ghost" @click="backToCredentials">Back</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.cpanel-login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1.25rem;
  background: var(--ds-paper, #f1f4f8);
  color-scheme: light;
}

.cpanel-login-container {
  width: min(100%, 19.5rem);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.65rem;
}

.cpanel-login-brand {
  display: flex;
  justify-content: center;
  margin-bottom: 0.2rem;
}

.cpanel-login-card {
  width: 100%;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.75rem;
  padding: 1.15rem 1.25rem 0.95rem;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 6px 18px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.cpanel-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

.cpanel-input-icon {
  position: absolute;
  left: 0.75rem;
  color: #94a3b8;
  font-size: 0.82rem;
  pointer-events: none;
  display: grid;
  place-items: center;
}

.cpanel-input-wrap input {
  width: 100%;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #1e293b;
  font-family: inherit;
  font-size: 0.86rem;
  padding: 0.52rem 0.65rem 0.52rem 2.25rem;
  transition: all 0.15s ease;
  outline: none;
}

.cpanel-input-wrap input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.cpanel-input-wrap input::placeholder {
  color: #94a3b8;
}

.cpanel-eye-btn {
  position: absolute;
  right: 0.65rem;
  border: none;
  background: transparent;
  color: #94a3b8;
  padding: 0.2rem;
  cursor: pointer;
  display: grid;
  place-items: center;
  border-radius: 0.35rem;
  transition: color 0.15s ease;
}

.cpanel-eye-btn:hover {
  color: #475569;
}

.cpanel-btn-submit {
  width: 100%;
  border: none;
  border-radius: 0.5rem;
  background: #1e3a5f;
  color: #ffffff;
  font-family: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  padding: 0.58rem 1rem;
  cursor: pointer;
  margin-top: 0.25rem;
  transition: background 0.15s ease;
}

.cpanel-btn-submit:hover:not(:disabled) {
  background: #152c48;
}

.cpanel-btn-submit:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.cpanel-btn-ghost {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  background: transparent;
  color: #475569;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.48rem 1rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cpanel-btn-ghost:hover:not(:disabled) {
  background: #f1f5f9;
  color: #1e293b;
}

.cpanel-card-foot {
  text-align: center;
  margin-top: 0.25rem;
}

.cpanel-foot-link {
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 500;
  text-decoration: none;
  transition: color 0.15s ease;
}

.cpanel-foot-link:hover {
  color: #1e3a5f;
  text-decoration: underline;
}

.compact-alert {
  margin: 0;
  padding: 0.4rem 0.6rem;
  font-size: 0.76rem;
}

input.code {
  text-align: center;
  font-family: var(--ds-font-mono, ui-monospace, monospace);
  letter-spacing: 0.25em;
  padding-left: 0.75rem;
}
</style>
