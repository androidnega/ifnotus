<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalShell from '@/components/portal/PortalShell.vue'

const name = ref('')
const phone = ref('')
const company = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const totpSecret = ref('')
const totpUrl = ref('')
const totpCode = ref('')
const msg = ref('')
const err = ref('')
const twoFactor = ref(false)

async function load() {
  const { data } = await customersApi.me()
  name.value = data.full_name
  phone.value = data.phone || ''
  company.value = data.company || ''
  twoFactor.value = data.two_factor_enabled
}

onMounted(load)

async function saveProfile() {
  err.value = ''
  try {
    await customersApi.updateMe({
      full_name: name.value,
      phone: phone.value,
      company: company.value,
    })
    msg.value = 'Profile saved.'
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    err.value = x.response?.data?.error?.message ?? 'Could not save.'
  }
}

async function savePassword() {
  err.value = ''
  try {
    await customersApi.changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    msg.value = 'Password updated.'
    currentPassword.value = ''
    newPassword.value = ''
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    err.value = x.response?.data?.error?.message ?? 'Could not update password.'
  }
}

async function startTotp() {
  const { data } = await customersApi.totpSetup()
  totpSecret.value = data.secret
  totpUrl.value = data.otpauth_url
}

async function confirmTotp() {
  await customersApi.totpConfirm(totpCode.value)
  twoFactor.value = true
  totpSecret.value = ''
  msg.value = 'Authenticator is on.'
}
</script>

<template>
  <PortalShell mode="app" :email="undefined" profile-menu>
    <template #sidebar>
      <PortalAccountNav active="settings" />
    </template>
    <div class="account-page">
      <h1>Your account</h1>
      <p class="muted">Profile, password, and authenticator — not server or hosting settings.</p>
      <p v-if="msg" class="ok">{{ msg }}</p>
      <p v-if="err" class="err">{{ err }}</p>

      <section class="card">
        <h2>Profile</h2>
        <label>Full name <input v-model="name" class="input" /></label>
        <label>Phone <input v-model="phone" class="input" /></label>
        <label>Company <input v-model="company" class="input" /></label>
        <button type="button" class="btn" @click="saveProfile">Save</button>
      </section>

      <section class="card">
        <h2>Password</h2>
        <label>Current <input v-model="currentPassword" type="password" class="input" /></label>
        <label>New <input v-model="newPassword" type="password" class="input" /></label>
        <button type="button" class="btn" @click="savePassword">Update password</button>
      </section>

      <section class="card">
        <h2>Authenticator (2FA)</h2>
        <p v-if="twoFactor" class="ok">Two-factor is on for this login.</p>
        <template v-else>
          <button type="button" class="btn" @click="startTotp">Set up authenticator</button>
          <p v-if="totpSecret" class="mono">Secret: {{ totpSecret }}</p>
          <p v-if="totpUrl" class="hint">Add this in Google Authenticator / Authy, then enter a code.</p>
          <label v-if="totpSecret">Code <input v-model="totpCode" class="input" maxlength="6" /></label>
          <button v-if="totpSecret" type="button" class="btn" @click="confirmTotp">Confirm</button>
        </template>
      </section>
    </div>
  </PortalShell>
</template>

<style scoped>
.account-page { width: 100%; min-width: 0; max-width: 36rem; }
.nav-text, .nav-cta {
  border: none;
  background: transparent;
  font-size: 0.875rem;
  cursor: pointer;
  padding: 0.4rem 0.75rem;
  border-radius: 999px;
}
.nav-text { color: var(--if-muted, #5b6b7c); }
.nav-cta {
  background: var(--if-primary, #1e3a5f);
  color: #fff;
  font-weight: 600;
}
h1 { margin: 0; font-family: Sora, sans-serif; font-size: 1.45rem; letter-spacing: -0.03em; }
.muted, .hint { color: #5c6670; margin-top: 0.35rem; }
.ok { color: #0f7a45; }
.err { color: #b42318; }
.card {
  margin-top: 1rem;
  padding: 1rem 1.1rem;
  background: #fff;
  border: 1px solid #e4e8ec;
  border-radius: 1rem;
}
label { display: block; margin-top: 0.6rem; font-size: 0.82rem; color: #5c6670; }
.input { display: block; width: 100%; margin-top: 0.25rem; padding: 0.5rem 0.65rem; border: 1px solid #d8dee4; border-radius: 0.6rem; box-sizing: border-box; }
.btn { margin-top: 0.8rem; border: 0; background: #1e3a5f; color: #fff; border-radius: 0.65rem; padding: 0.5rem 0.9rem; cursor: pointer; }
.mono { font-family: ui-monospace, monospace; font-size: 0.8rem; word-break: break-all; }
</style>
