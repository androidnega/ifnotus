<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import PortalShell from '@/components/portal/PortalShell.vue'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import { IconEye, IconEyeOff } from '@/components/icons'
import { ensureDeviceFingerprint } from '@/api/client'
import { hostnameNow, isCustomerCpanelHost } from '@/lib/platformHosts'

type Step = 'phone' | 'otp' | 'password' | 'first_name' | 'last_name' | 'email'
type AuthMode = 'phone' | 'password'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isSignup = computed(() => route.name === 'portal-signup')
const panelMode = computed(() => {
  if (isSignup.value) return false
  if (String(route.query.mode || '') === 'panel') return true
  if (isCustomerCpanelHost()) return true
  return false
})
const panelLogin = panelMode
const compactAuth = computed(() => panelLogin.value || !isSignup.value)

const phone = ref('')
const otp = ref('')
const challengeId = ref('')
const debugCode = ref<string | null>(null)
const otpMessage = ref('')

const emailLogin = ref('')
const passwordLogin = ref('')
const showPasswordLogin = ref(false)
const showPanelPass = ref(false)
const showPanelPassConfirm = ref(false)
const panelUsername = ref('')
const panelPassword = ref('')
const panelPasswordConfirm = ref('')
const panelNeedsCreate = ref(false)
const panelDomainHint = ref('')
const panelStatusLoaded = ref(false)

const firstName = ref('')
const lastName = ref('')
const email = ref('')

const loading = ref(false)
const error = ref('')
const step = ref<Step>(isSignup.value ? 'phone' : 'password')
const authMode = ref<AuthMode>(isSignup.value ? 'phone' : 'password')

const planSlug = computed(() => {
  const raw = route.query.plan
  return typeof raw === 'string' ? raw : ''
})

const titles = computed<Record<Step, string>>(() => ({
  phone: isSignup.value ? 'Create your account' : 'Log in with phone',
  otp: 'Check your phone',
  password: 'Log in',
  first_name: 'What should we call you?',
  last_name: 'And your family name?',
  email: 'Where should we send updates?',
}))

const subs = computed<Record<Step, string>>(() => ({
  phone: isSignup.value
    ? 'Enter your mobile number. We’ll text a one-time code to get you started.'
    : 'Enter your mobile number. We’ll text a one-time code to open your account.',
  otp: 'Enter the code to continue.',
  password: 'Enter your email and password to access your account.',
  first_name: 'Your first name — shown on invoices and your account.',
  last_name: 'Needed for invoices and student project addresses.',
  email: 'Required before you place a paid order.',
}))

async function loadPanelStatus() {
  if (!panelLogin.value) return
  const hostRaw = route.query.host
  const host = typeof hostRaw === 'string' ? hostRaw : isCustomerCpanelHost() ? hostnameNow() : ''
  const userHint = typeof route.query.username === 'string' ? route.query.username : ''
  try {
    const { data } = await customersApi.panelStatus({
      ...(userHint ? { username: userHint } : {}),
      ...(host ? { host: host.replace(/^cpanel\./, '') } : {}),
    })
    panelUsername.value = data.username
    panelNeedsCreate.value = !data.password_set
    panelDomainHint.value = data.domain || host.replace(/^cpanel\./, '') || ''
  } catch {
    /* user can still type username */
    if (host) panelDomainHint.value = host.replace(/^cpanel\./, '')
  } finally {
    panelStatusLoaded.value = true
  }
}

onMounted(() => {
  if (panelLogin.value) {
    step.value = 'password'
    authMode.value = 'password'
    void loadPanelStatus()
  } else if (!isSignup.value) {
    step.value = 'password'
    authMode.value = 'password'
  }
})

function safeRedirectTarget(): string | null {
  const raw = route.query.redirect
  const candidate = Array.isArray(raw) ? raw[0] : raw
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
    return candidate
  }
  return null
}

async function finishAuth(profile: {
  can_order?: boolean
  first_name?: string | null
  last_name?: string | null
  email?: string
}) {
  const redirect = safeRedirectTarget()
  if (redirect) {
    try {
      await router.replace(redirect)
      return
    } catch {
      /* fall through */
    }
  }
  if (panelLogin.value) {
    const hostRaw = route.query.host
    const host = typeof hostRaw === 'string' ? hostRaw : isCustomerCpanelHost() ? hostnameNow() : panelDomainHint.value
    if (host) {
      await router.replace({
        name: 'go-hosting',
        query: { host: host.replace(/^cpanel\./, '') },
      })
      return
    }
    await router.replace({ name: 'portal-dashboard' })
    return
  }

  const pendingEmail = (profile.email || '').includes('@phone.pending.ifnotus')
  if (!profile.first_name) {
    step.value = 'first_name'
    return
  }
  if (!profile.last_name) {
    step.value = 'last_name'
    return
  }
  if (pendingEmail) {
    step.value = 'email'
    return
  }

  // Profile is complete — continue to checkout/plans if a package was chosen.
  if (planSlug.value) {
    localStorage.setItem('ifnotus_selected_plan_slug', planSlug.value)
    await router.replace({
      name: 'portal-account-plans',
      query: { plan: planSlug.value },
    })
    return
  }
  await router.replace({ name: 'portal-dashboard' })
}

async function sendOtp() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.requestPhoneOtp({ phone: phone.value.trim() })
    challengeId.value = data.challenge_id
    debugCode.value = data.debug_code ?? null
    otpMessage.value = data.message
    step.value = 'otp'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not send code.'
  } finally {
    loading.value = false
  }
}

async function verifyOtp() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.verifyPhoneOtp({
      phone: phone.value.trim(),
      challenge_id: challengeId.value,
      code: otp.value.trim(),
    })
    if (!data.access_token || !data.refresh_token) {
      throw new Error('Verify failed')
    }
    await auth.applyTokens(data)
    const me = await customersApi.me()
    await finishAuth(me.data)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Invalid code.'
  } finally {
    loading.value = false
  }
}

async function loginWithPassword() {
  loading.value = true
  error.value = ''
  try {
    if (panelLogin.value) {
      const username = panelUsername.value.trim()
      const password = panelPassword.value
      if (panelNeedsCreate.value) {
        if (password !== panelPasswordConfirm.value) {
          error.value = 'Passwords do not match.'
          return
        }
        await customersApi.panelCreatePassword({ username, password })
        panelNeedsCreate.value = false
      }
      const { data } = await customersApi.panelLogin({
        username,
        password,
        device_fingerprint: await ensureDeviceFingerprint().catch(() => undefined),
      })
      if (!data.access_token || !data.refresh_token) {
        throw new Error('Sign-in failed')
      }
      await auth.applyTokens(data)
      const me = await customersApi.me()
      await finishAuth(me.data)
      return
    }
    const identity = emailLogin.value.trim()
    const password = passwordLogin.value
    const { data } = await customersApi.login({
      email: identity,
      password,
      device_fingerprint: await ensureDeviceFingerprint().catch(() => undefined),
    })
    if (data.status === 'totp_required') {
      error.value = data.message || 'Enter your authenticator code.'
      return
    }
    if (!data.access_token || !data.refresh_token) {
      throw new Error('Sign-in failed')
    }
    await auth.applyTokens(data)
    const me = await customersApi.me()
    await finishAuth(me.data)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string; code?: string } } } }
    const code = err.response?.data?.error?.code
    if (panelLogin.value && code === 'panel_password_exists') {
      panelNeedsCreate.value = false
      error.value = 'Password already set — log in with it.'
      return
    }
    error.value =
      err.response?.data?.error?.message ??
      (panelLogin.value ? 'Username or password is incorrect.' : 'Username or password is incorrect.')
  } finally {
    loading.value = false
  }
}

async function saveFirstName() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.updateMe({ first_name: firstName.value.trim() })
    firstName.value = data.first_name || firstName.value
    if (!data.last_name) {
      step.value = 'last_name'
    } else {
      await finishAuth(data)
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save.'
  } finally {
    loading.value = false
  }
}

async function saveLastName() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.updateMe({ last_name: lastName.value.trim() })
    lastName.value = data.last_name || lastName.value
    await finishAuth(data)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save.'
  } finally {
    loading.value = false
  }
}

async function saveEmail() {
  loading.value = true
  error.value = ''
  try {
    const trimmed = email.value.trim()
    if (!trimmed || !trimmed.includes('@')) {
      error.value = 'Enter a valid email address.'
      return
    }
    const { data } = await customersApi.updateMe({ email: trimmed })
    try {
      await auth.fetchUser()
    } catch {
      /* non-fatal */
    }
    await finishAuth(data)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save email.'
  } finally {
    loading.value = false
  }
}

function onSubmit() {
  if (panelLogin.value) return loginWithPassword()
  if (step.value === 'phone') return sendOtp()
  if (step.value === 'otp') return verifyOtp()
  if (step.value === 'password') return loginWithPassword()
  if (step.value === 'first_name') return saveFirstName()
  if (step.value === 'last_name') return saveLastName()
  return saveEmail()
}

const submitLabel = computed(() => {
  if (loading.value) return 'Please wait…'
  if (panelLogin.value) return panelNeedsCreate.value ? 'Create password & log in' : 'Log in'
  if (step.value === 'phone') return isSignup.value ? 'Send code' : 'Send login code'
  if (step.value === 'otp') return 'Verify & continue'
  if (step.value === 'password') return 'Log in'
  return 'Continue'
})

async function onPanelUsernameBlur() {
  const u = panelUsername.value.trim()
  if (!u || !panelLogin.value) return
  try {
    const { data } = await customersApi.panelStatus({ username: u })
    panelNeedsCreate.value = !data.password_set
    if (data.domain) panelDomainHint.value = data.domain
  } catch {
    /* keep current mode */
  }
}
</script>

<template>
  <!-- Tenant hosting panel login (domain/cpanel) — username + create/use password -->
  <div v-if="panelLogin" class="panel-login">
    <div class="panel-login-container">
      <div class="panel-brand">
        <UiBrandMark variant="staff" />
      </div>

      <form class="panel-card" @submit.prevent="onSubmit">
        <div class="panel-input-wrap">
          <span class="panel-input-icon">
            <i class="fas fa-user" aria-hidden="true" />
          </span>
          <input
            id="panel-user"
            v-model="panelUsername"
            type="text"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            placeholder="Username or ID"
            required
            @blur="onPanelUsernameBlur"
          />
        </div>

        <div class="panel-input-wrap">
          <span class="panel-input-icon">
            <i class="fas fa-lock" aria-hidden="true" />
          </span>
          <input
            id="panel-pass"
            v-model="panelPassword"
            :type="showPanelPass ? 'text' : 'password'"
            :autocomplete="panelNeedsCreate ? 'new-password' : 'current-password'"
            :placeholder="panelNeedsCreate ? 'Create password' : 'Password'"
            required
            minlength="8"
          />
          <button
            type="button"
            class="panel-eye-btn"
            :title="showPanelPass ? 'Hide password' : 'Show password'"
            tabindex="-1"
            @click="showPanelPass = !showPanelPass"
          >
            <IconEyeOff v-if="showPanelPass" :size="16" />
            <IconEye v-else :size="16" />
          </button>
        </div>

        <template v-if="panelNeedsCreate">
          <div class="panel-input-wrap">
            <span class="panel-input-icon">
              <i class="fas fa-lock" aria-hidden="true" />
            </span>
            <input
              id="panel-pass2"
              v-model="panelPasswordConfirm"
              :type="showPanelPassConfirm ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="Confirm password"
              required
              minlength="8"
            />
            <button
              type="button"
              class="panel-eye-btn"
              :title="showPanelPassConfirm ? 'Hide password' : 'Show password'"
              tabindex="-1"
              @click="showPanelPassConfirm = !showPanelPassConfirm"
            >
              <IconEyeOff v-if="showPanelPassConfirm" :size="16" />
              <IconEye v-else :size="16" />
            </button>
          </div>
        </template>

        <p v-if="error" class="err">{{ error }}</p>

        <button type="submit" class="submit" :disabled="loading || (!panelStatusLoaded && !panelUsername)">
          {{ submitLabel }}
        </button>
      </form>

      <div class="panel-card-foot">
        <router-link class="panel-foot-link" :to="{ name: 'forgot-password' }">Reset Password</router-link>
      </div>
    </div>
  </div>

  <PortalShell v-else mode="marketing">
    <template v-if="!compactAuth" #actions>
      <router-link class="link" :to="{ name: 'plans' }">Plans</router-link>
      <router-link
        v-if="isSignup"
        class="cta"
        :to="{ name: 'login', query: route.query }"
      >
        Log in
      </router-link>
      <router-link
        v-else
        class="cta"
        :to="{ name: 'portal-signup', query: route.query }"
      >
        Sign up
      </router-link>
    </template>

    <div class="wrap" :class="{ compact: compactAuth }">
      <h1>{{ titles[step] }}</h1>
      <p class="sub">{{ step === 'otp' ? otpMessage || subs.otp : subs[step] }}</p>
      <p v-if="planSlug && step !== 'email'" class="plan-note">
        Plan selected: <strong>{{ planSlug }}</strong>
      </p>

      <form class="card" @submit.prevent="onSubmit">
        <div v-if="step === 'phone'" class="fields">
          <label for="phone">Mobile number</label>
          <input
            id="phone"
            v-model="phone"
            type="tel"
            inputmode="tel"
            autocomplete="tel"
            placeholder="024 000 0000"
            required
          />
        </div>
        <div v-else-if="step === 'otp'" class="fields">
          <p v-if="!debugCode" class="otp-hint">Only the newest SMS code works — ignore older messages.</p>
          <p v-if="debugCode" class="debug">
            Your code: <strong>{{ debugCode }}</strong>
          </p>
          <label for="otp">One-time code</label>
          <input
            id="otp"
            v-model="otp"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            placeholder="6-digit code"
            required
          />
          <div class="otp-actions">
            <button type="button" class="text-btn" :disabled="loading" @click="sendOtp">
              Resend code
            </button>
            <button
              v-if="!isSignup"
              type="button"
              class="text-btn muted"
              @click="step = 'phone'; otp = ''; error = ''"
            >
              Change number
            </button>
          </div>
        </div>
        <div v-else-if="step === 'password'" class="fields">
          <label for="email-login">Email</label>
          <input
            id="email-login"
            v-model="emailLogin"
            type="email"
            autocomplete="username"
            placeholder="you@example.com"
            required
          />
          <label for="password-login">Password</label>
          <div class="ds-input-eye-wrap">
            <input
              id="password-login"
              v-model="passwordLogin"
              :type="showPasswordLogin ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="Password"
              required
            />
            <button
              type="button"
              class="ds-eye-btn"
              :title="showPasswordLogin ? 'Hide password' : 'Show password'"
              tabindex="-1"
              @click="showPasswordLogin = !showPasswordLogin"
            >
              <IconEyeOff v-if="showPasswordLogin" :size="18" />
              <IconEye v-else :size="18" />
            </button>
          </div>
          <router-link class="text-btn" :to="{ name: 'forgot-password' }">
            Forgot password?
          </router-link>
        </div>
        <div v-else-if="step === 'first_name'" class="fields">
          <label for="first">First name</label>
          <input id="first" v-model="firstName" type="text" autocomplete="given-name" required />
        </div>
        <div v-else-if="step === 'last_name'" class="fields">
          <label for="last">Last name</label>
          <input id="last" v-model="lastName" type="text" autocomplete="family-name" required />
        </div>
        <div v-else class="fields">
          <label for="email">Email</label>
          <input id="email" v-model="email" type="email" autocomplete="email" required />
          <p class="hint">Phone {{ phone }} is verified. You can set a password later in settings.</p>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
        <button type="submit" class="submit" :disabled="loading">
          {{ submitLabel }}
        </button>

        <div v-if="!isSignup && step === 'password'" class="alt-auth-section">
          <div class="alt-divider"><span>or</span></div>
          <button
            type="button"
            class="btn-alt-auth"
            @click="step = 'phone'; authMode = 'phone'; error = ''"
          >
            Log in with phone number
          </button>
        </div>

        <div v-if="!isSignup && step === 'phone'" class="alt-auth-section">
          <div class="alt-divider"><span>or</span></div>
          <button
            type="button"
            class="btn-alt-auth"
            @click="step = 'password'; authMode = 'password'; error = ''"
          >
            Log in with email &amp; password
          </button>
        </div>
      </form>

      <p v-if="compactAuth && !isSignup" class="switch">
        New here?
        <router-link :to="{ name: 'portal-signup', query: route.query }">Create account</router-link>
      </p>
    </div>
  </PortalShell>
</template>

<style scoped>
.panel-login {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.25rem;
  background: var(--if-paper, #f1f4f8);
  font-family: Figtree, ui-sans-serif, system-ui, sans-serif;
  color-scheme: light;
}
.panel-login-container {
  width: min(100%, 19.5rem);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.65rem;
}
.panel-brand {
  display: flex;
  justify-content: center;
  margin-bottom: 0.2rem;
}
.panel-card {
  width: 100%;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.75rem;
  padding: 1.15rem 1.25rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 6px 18px rgba(15, 23, 42, 0.03);
}
.panel-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}
.panel-input-icon {
  position: absolute;
  left: 0.75rem;
  color: #94a3b8;
  font-size: 0.82rem;
  pointer-events: none;
  display: grid;
  place-items: center;
}
.panel-input-wrap input {
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
.panel-input-wrap input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
.panel-input-wrap input::placeholder {
  color: #94a3b8;
}
.panel-eye-btn {
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
.panel-eye-btn:hover {
  color: #475569;
}
.panel-card .submit {
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
.panel-card .submit:hover:not(:disabled) {
  background: #152c48;
}
.panel-card .submit:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.panel-card .err {
  margin: 0.25rem 0 0;
  color: #b42318;
  font-size: 0.78rem;
  text-align: center;
}
.panel-card-foot {
  display: flex;
  justify-content: center;
  margin-top: 0.35rem;
}
.panel-foot-link {
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
  text-decoration: none;
  transition: color 0.15s ease;
}
.panel-foot-link:hover {
  color: #0f172a;
  text-decoration: underline;
}

.wrap {
  width: min(22rem, 100%);
  margin: 0 auto;
  padding: 0;
}
.wrap.compact {
  width: min(20rem, 100%);
  margin: 0 auto;
  padding: 0;
}
h1 {
  margin: 0;
  font-family: var(--ds-font-display, Sora, sans-serif);
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--if-ink, #161a1d);
}
.wrap.compact h1 { font-size: 1.2rem; }
.sub {
  margin: 0.35rem 0 0;
  color: var(--if-muted, #5c6670);
  font-size: 0.86rem;
  line-height: 1.4;
}
.wrap.compact .sub { margin-top: 0.25rem; font-size: 0.8rem; }
.plan-note {
  margin: 0.55rem 0 0;
  font-size: 0.8rem;
  color: var(--if-muted, #5c6670);
}
.mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.25rem;
  margin-top: 0.75rem;
  padding: 0.2rem;
  border-radius: 0.6rem;
  background: color-mix(in srgb, var(--if-border, #e4e8ec) 55%, transparent);
}
.mode-tabs button {
  border: 0;
  border-radius: 0.45rem;
  background: transparent;
  color: var(--if-muted, #5c6670);
  font-size: 0.8rem;
  font-weight: 650;
  padding: 0.4rem 0.55rem;
  cursor: pointer;
}
.mode-tabs button.on {
  background: var(--if-surface, #fff);
  color: var(--if-ink, #161a1d);
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.06);
}
.card {
  margin-top: 0.75rem;
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #e4e8ec);
  border-radius: 0.7rem;
  padding: 0.9rem;
}
.wrap.compact .card { margin-top: 0.55rem; padding: 0.75rem; }
.fields { display: flex; flex-direction: column; gap: 0.4rem; }
.fields label {
  font-size: 0.75rem;
  font-weight: 650;
  color: var(--if-muted, #5c6670);
}
.fields input {
  border: 1px solid var(--if-border, #d7dde5);
  border-radius: 0.55rem;
  padding: 0.55rem 0.7rem;
  font-size: 0.9rem;
  background: var(--if-surface, #fff);
  color: var(--if-ink, #161a1d);
}
.fields input:focus {
  outline: none;
  border-color: var(--if-primary, #ff6c2c);
  box-shadow: 0 0 0 3px var(--if-primary-soft, rgba(255, 108, 44, 0.14));
}
.debug {
  margin: 0;
  font-size: 0.78rem;
  color: #8a5a00;
  background: #fff7e6;
  border-radius: 0.45rem;
  padding: 0.4rem 0.55rem;
}
.otp-hint {
  margin: 0 0 0.55rem;
  font-size: 0.78rem;
  line-height: 1.4;
  color: var(--if-muted, #7a8490);
}
.hint { margin: 0; font-size: 0.75rem; color: var(--if-muted, #7a8490); }
.text-btn {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: var(--if-primary, #3d4650);
  font-size: 0.78rem;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}
.text-btn.muted {
  color: var(--if-muted, #7a8490);
}
.otp-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.25rem;
}
.alt-auth-section {
  margin-top: 0.85rem;
  text-align: center;
}
.alt-divider {
  display: flex;
  align-items: center;
  text-align: center;
  margin: 0.65rem 0;
  color: var(--if-muted, #8a94a0);
  font-size: 0.78rem;
}
.alt-divider::before,
.alt-divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid var(--if-border, #e4e8ec);
}
.alt-divider span {
  padding: 0 0.55rem;
  text-transform: uppercase;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--if-muted, #8a94a0);
}
.btn-alt-auth {
  width: 100%;
  border: 1px solid var(--if-border, #d7dde5);
  border-radius: 0.55rem;
  background: var(--if-surface, #fff);
  color: var(--if-ink, #161a1d);
  font-size: 0.86rem;
  font-weight: 600;
  padding: 0.55rem 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-alt-auth:hover {
  background: var(--if-subtle, #f8fafc);
  border-color: var(--if-border-focus, #cbd5e1);
}
.err { margin: 0.55rem 0 0; color: #b42318; font-size: 0.8rem; }
.submit {
  margin-top: 0.75rem;
  width: 100%;
  border: 0;
  border-radius: 0.55rem;
  background: var(--if-primary, #0f1720);
  color: #fff;
  font-weight: 650;
  font-size: 0.9rem;
  padding: 0.65rem 0.85rem;
  cursor: pointer;
}
.submit:hover:not(:disabled) { background: var(--if-primary-hover, #161a1d); }
.submit:disabled { opacity: 0.6; cursor: not-allowed; }
.switch {
  margin: 0.75rem 0 0;
  text-align: center;
  font-size: 0.8rem;
  color: var(--if-muted, #5c6670);
}
.switch a {
  color: var(--if-primary, #ff6c2c);
  font-weight: 650;
  text-decoration: none;
}
.link {
  color: var(--if-muted, #3d4650);
  text-decoration: none;
  font-size: 0.9rem;
}
.cta {
  text-decoration: none;
  font-size: 0.9rem;
  color: #fff;
  background: var(--if-primary, #0f1720);
  border-radius: 999px;
  padding: 0.45rem 0.9rem;
}
</style>
