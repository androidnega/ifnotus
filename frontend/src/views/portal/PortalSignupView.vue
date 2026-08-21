<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import PortalShell from '@/components/portal/PortalShell.vue'

type Step = 'phone' | 'otp' | 'first_name' | 'last_name' | 'email'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const phone = ref('')
const otp = ref('')
const challengeId = ref('')
const debugCode = ref<string | null>(null)
const otpMessage = ref('')

const firstName = ref('')
const lastName = ref('')
const email = ref('')

const loading = ref(false)
const error = ref('')
const step = ref<Step>('phone')

const planSlug = computed(() => {
  const raw = route.query.plan
  return typeof raw === 'string' ? raw : ''
})

const titles: Record<Step, string> = {
  phone: 'Your number',
  otp: 'Check your phone',
  first_name: 'What should we call you?',
  last_name: 'And your family name?',
  email: 'Where should we send updates?',
}

const subs: Record<Step, string> = {
  phone: 'We verify your mobile number first. New and returning customers use the same step.',
  otp: 'Enter the SMS code to open your account.',
  first_name: 'Just your first name for now — you can finish the rest in a moment.',
  last_name: 'Needed for student project addresses and invoices.',
  email: 'Required before you place a paid order. Company and password stay optional in account settings.',
}

function goAfterAuth(profile: {
  can_order?: boolean
  first_name?: string | null
  last_name?: string | null
  email?: string
  profile_complete?: boolean
}) {
  const pendingEmail = (profile.email || '').includes('@phone.pending.ifnotus')
  if (!profile.first_name) {
    step.value = 'first_name'
    return
  }
  if (!profile.last_name) {
    step.value = 'last_name'
    return
  }
  if (pendingEmail || !profile.can_order) {
    // Soft: allow account access; only block checkout server-side.
    // Still offer email step when heading to plans.
    if (planSlug.value) {
      step.value = 'email'
      return
    }
    void router.replace({ name: 'portal-dashboard' })
    return
  }
  if (planSlug.value) {
    void router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    return
  }
  void router.replace({ name: 'portal-dashboard' })
}

onMounted(async () => {
  if (!auth.isAuthenticated) return
  try {
    const { data } = await customersApi.me()
    phone.value = data.phone || ''
    firstName.value = data.first_name || ''
    lastName.value = data.last_name || ''
    email.value = data.email?.includes('@phone.pending.ifnotus') ? '' : data.email
    goAfterAuth(data)
  } catch {
    /* stay on phone step */
  }
})

async function sendOtp() {
  loading.value = true
  error.value = ''
  debugCode.value = null
  try {
    const { data } = await customersApi.requestPhoneOtp({ phone: phone.value.trim() })
    challengeId.value = data.challenge_id
    phone.value = data.phone
    otpMessage.value = data.message
    debugCode.value = data.debug_code || null
    if (data.debug_code) otp.value = data.debug_code
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
      throw new Error('Sign-in failed')
    }
    await auth.applyTokens(data)
    const me = await customersApi.me()
    goAfterAuth(me.data)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Invalid code.'
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
    } else if (planSlug.value && !data.can_order) {
      step.value = 'email'
    } else if (planSlug.value) {
      await router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    } else {
      await router.replace({ name: 'portal-dashboard' })
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
    if (planSlug.value && !data.can_order) {
      step.value = 'email'
    } else if (planSlug.value) {
      await router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    } else {
      // Reach account quickly; email can wait until checkout.
      await router.replace({ name: 'portal-dashboard' })
    }
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
    await customersApi.updateMe({ email: email.value.trim() })
    await auth.fetchUser()
    if (planSlug.value) {
      await router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    } else {
      await router.replace({ name: 'portal-dashboard' })
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save email.'
  } finally {
    loading.value = false
  }
}

function skipFirstName() {
  step.value = 'last_name'
}

function onSubmit() {
  if (step.value === 'phone') return sendOtp()
  if (step.value === 'otp') return verifyOtp()
  if (step.value === 'first_name') return saveFirstName()
  if (step.value === 'last_name') return saveLastName()
  return saveEmail()
}
</script>

<template>
  <PortalShell mode="marketing">
    <template #actions>
      <router-link class="link" :to="{ name: 'plans' }">Plans</router-link>
      <router-link class="cta" :to="{ name: 'login' }">Staff log in</router-link>
    </template>

    <div class="wrap">
      <p class="brand">IFNOTUS</p>
      <h1>{{ titles[step] }}</h1>
      <p class="sub">{{ step === 'otp' ? otpMessage || subs.otp : subs[step] }}</p>
      <p v-if="planSlug && step !== 'email'" class="plan-note">
        Plan selected: <strong>{{ planSlug }}</strong>
      </p>

      <form class="card" @submit.prevent="onSubmit">
        <div v-if="step === 'phone'" class="fields">
          <input
            v-model="phone"
            required
            inputmode="tel"
            autocomplete="tel"
            placeholder="Mobile number (e.g. 024… or +233…)"
          />
        </div>
        <div v-else-if="step === 'otp'" class="fields">
          <p v-if="debugCode" class="debug">
            Debug OTP (SMS not live yet): <strong>{{ debugCode }}</strong>
          </p>
          <input
            v-model="otp"
            required
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="8"
            placeholder="6-digit code"
          />
          <button type="button" class="text-btn" :disabled="loading" @click="sendOtp">
            Resend code
          </button>
        </div>
        <div v-else-if="step === 'first_name'" class="fields">
          <input
            v-model="firstName"
            required
            placeholder="First name"
            autocomplete="given-name"
          />
          <button type="button" class="text-btn" :disabled="loading" @click="skipFirstName">
            Skip for now
          </button>
        </div>
        <div v-else-if="step === 'last_name'" class="fields">
          <input
            v-model="lastName"
            required
            minlength="2"
            placeholder="Family name"
            autocomplete="family-name"
          />
        </div>
        <div v-else class="fields">
          <input v-model="email" type="email" required placeholder="Email" autocomplete="email" />
          <p class="hint">Phone {{ phone }} is verified. Password and company stay optional later.</p>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
        <button type="submit" class="submit" :disabled="loading">
          {{
            loading
              ? 'Please wait…'
              : step === 'phone'
                ? 'Send code'
                : step === 'otp'
                  ? 'Verify & continue'
                  : 'Continue'
          }}
        </button>
      </form>
    </div>
  </PortalShell>
</template>

<style scoped>
.wrap {
  max-width: 26rem;
  margin: 2.5rem auto 0;
  padding-bottom: 2rem;
}
.brand {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: var(--if-primary, #ff6c2c);
}
h1 {
  margin: 0.5rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.03em;
}
.sub {
  margin: 0.5rem 0 0;
  color: #5c6670;
  font-size: 0.95rem;
  line-height: 1.5;
}
.plan-note {
  margin: 0.85rem 0 0;
  font-size: 0.85rem;
  color: #5c6670;
}
.card {
  margin-top: 1.35rem;
  background: #fff;
  border: 1px solid #e4e8ec;
  border-radius: 0.85rem;
  padding: 1.25rem;
}
.fields {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.fields input {
  border: 1px solid #d7dde5;
  border-radius: 0.65rem;
  padding: 0.75rem 0.9rem;
  font-size: 0.95rem;
}
.debug {
  margin: 0;
  font-size: 0.85rem;
  color: #8a5a00;
  background: #fff7e6;
  border-radius: 0.5rem;
  padding: 0.55rem 0.7rem;
}
.hint {
  margin: 0;
  font-size: 0.8rem;
  color: #7a8490;
}
.text-btn {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: #3d4650;
  font-size: 0.85rem;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}
.err {
  margin: 0.75rem 0 0;
  color: #b42318;
  font-size: 0.88rem;
}
.submit {
  margin-top: 1rem;
  width: 100%;
  border: 0;
  border-radius: 999px;
  background: #0f1720;
  color: #fff;
  font-weight: 650;
  padding: 0.8rem 1rem;
  cursor: pointer;
}
.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.link {
  color: #3d4650;
  text-decoration: none;
  font-size: 0.9rem;
}
.cta {
  text-decoration: none;
  font-size: 0.9rem;
  color: #fff;
  background: #0f1720;
  border-radius: 999px;
  padding: 0.45rem 0.9rem;
}
</style>
