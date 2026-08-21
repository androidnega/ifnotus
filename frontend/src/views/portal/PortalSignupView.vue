<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import PortalShell from '@/components/portal/PortalShell.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const phone = ref('')
const otp = ref('')
const challengeId = ref('')
const debugCode = ref<string | null>(null)
const otpMessage = ref('')

const fullName = ref('')
const email = ref('')
const company = ref('')
const password = ref('')

const loading = ref(false)
const error = ref('')
const step = ref<'phone' | 'otp' | 'profile'>('phone')

const planSlug = computed(() => {
  const raw = route.query.plan
  return typeof raw === 'string' ? raw : ''
})

onMounted(async () => {
  if (!auth.isAuthenticated) return
  try {
    const { data } = await customersApi.me()
    if (!data.profile_complete) {
      phone.value = data.phone || ''
      fullName.value = data.full_name === 'Customer' ? '' : data.full_name
      email.value = data.email?.includes('@phone.pending.ifnotus') ? '' : data.email
      company.value = data.company || ''
      step.value = 'profile'
    } else if (planSlug.value) {
      await router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    } else {
      await router.replace({ name: 'portal-dashboard' })
    }
  } catch {
    /* stay on phone step */
  }
})

function nextAfterAuth(profileComplete: boolean) {
  if (!profileComplete) {
    step.value = 'profile'
    return
  }
  if (planSlug.value) {
    void router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    return
  }
  void router.replace({ name: 'portal-dashboard' })
}

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
    const home = await auth.applyTokens(data)
    const me = await customersApi.me()
    nextAfterAuth(!!me.data.profile_complete)
    void home
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Invalid code.'
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  loading.value = true
  error.value = ''
  try {
    await customersApi.completeProfile({
      full_name: fullName.value.trim(),
      email: email.value.trim(),
      company: company.value.trim() || null,
      password: password.value.trim() || undefined,
    })
    await auth.fetchUser()
    if (planSlug.value) {
      await router.replace({ name: 'portal-account-plans', query: { plan: planSlug.value } })
    } else {
      await router.replace({ name: 'portal-dashboard' })
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save profile.'
  } finally {
    loading.value = false
  }
}

function onSubmit() {
  if (step.value === 'phone') return sendOtp()
  if (step.value === 'otp') return verifyOtp()
  return saveProfile()
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
      <h1>
        {{
          step === 'phone'
            ? 'Continue with phone'
            : step === 'otp'
              ? 'Enter your code'
              : 'Complete your profile'
        }}
      </h1>
      <p class="sub">
        {{
          step === 'phone'
            ? 'We verify your mobile number first. New and returning customers use the same step.'
            : step === 'otp'
              ? otpMessage || 'Enter the SMS code to open your account.'
              : 'Add your name, email, and business details so we can invoice and support you.'
        }}
      </p>
      <p v-if="planSlug && step !== 'profile'" class="plan-note">
        Plan selected: <strong>{{ planSlug }}</strong> — you will choose domain next.
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
        <div v-else class="fields">
          <input v-model="fullName" required placeholder="Full name" autocomplete="name" />
          <input v-model="email" type="email" required placeholder="Email" autocomplete="email" />
          <input v-model="company" placeholder="Business / company (optional)" />
          <input
            v-model="password"
            type="password"
            minlength="8"
            placeholder="Password for later (optional, min 8)"
            autocomplete="new-password"
          />
          <p class="hint">Phone {{ phone }} is already verified. You can always sign in with a new OTP.</p>
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
                  : 'Save & continue'
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
  width: 100%;
  border: 1px solid #e4e8ec;
  border-radius: 0.5rem;
  padding: 0.7rem 0.85rem;
  font-size: 0.9rem;
}
.fields input:focus {
  outline: none;
  border-color: var(--if-primary, #ff6c2c);
  box-shadow: 0 0 0 3px var(--if-primary-ring, rgba(255, 108, 44, 0.15));
}
.debug {
  margin: 0;
  padding: 0.65rem 0.75rem;
  border-radius: 0.5rem;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  font-size: 0.85rem;
}
.hint {
  margin: 0;
  font-size: 0.75rem;
  color: #7a8490;
  line-height: 1.4;
}
.text-btn {
  align-self: flex-start;
  border: none;
  background: none;
  color: var(--if-primary, #ff6c2c);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}
.err {
  margin: 0.75rem 0 0;
  color: #b91c1c;
  font-size: 0.85rem;
}
.submit {
  margin-top: 1rem;
  width: 100%;
  border: none;
  border-radius: 0.5rem;
  background: var(--if-primary, #ff6c2c);
  color: #fff;
  font-weight: 600;
  font-size: 0.9rem;
  padding: 0.75rem;
  cursor: pointer;
}
.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.link {
  padding: 0.4rem 0.75rem;
  color: #5c6670;
  text-decoration: none;
  font-size: 0.875rem;
}
.link:hover {
  color: var(--if-primary, #ff6c2c);
}
.cta {
  border-radius: 0.5rem;
  background: var(--if-primary, #ff6c2c);
  padding: 0.5rem 1rem;
  font-weight: 600;
  color: #fff;
  text-decoration: none;
  font-size: 0.875rem;
}
</style>
