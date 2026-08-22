<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { customersApi } from '@/api'

const props = defineProps<{
  environmentId: string
  domain?: string | null
  mailboxLimit?: number | null
  storageLimitMb?: number | null
}>()

type MailboxRow = {
  id: string
  email: string
  local_part?: string
  quota_mb?: number | null
  used_mb?: number | null
  suspended?: boolean
}

type AliasRow = {
  id: string
  source_email: string
  destination: string
  enabled: boolean
}

const loading = ref(true)
const error = ref('')
const mailboxes = ref<MailboxRow[]>([])
const aliases = ref<AliasRow[]>([])
const domainName = ref(props.domain || '')
const webmail = ref('https://mail.ifnotus.space/')
const clients = ref<Record<string, unknown> | null>(null)
const localPart = ref('hello')
const password = ref('')
const msg = ref('')
const creating = ref(false)
const busyId = ref('')
const showConnect = ref(false)
const aliasSource = ref('')
const aliasDest = ref('')
const resetPassword = ref('')

const atLimit = computed(() => {
  if (props.mailboxLimit == null) return false
  return mailboxes.value.length >= props.mailboxLimit
})

const previewEmail = computed(() => {
  const local = localPart.value.trim().toLowerCase() || 'hello'
  const host = domainName.value || props.domain || 'your-site.ifnotus.space'
  return `${local}@${host}`
})

const totalQuotaMb = computed(() =>
  mailboxes.value.reduce((sum, m) => sum + (m.quota_mb || m.used_mb || 0), 0),
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.getEnvMail(props.environmentId)
    mailboxes.value = data.mailboxes || []
    aliases.value = data.aliases || []
    domainName.value = data.domain?.name || props.domain || ''
    webmail.value = data.webmail_url || data.clients?.webmail_url || 'https://mail.ifnotus.space/'
    clients.value = data.clients || null
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = x.response?.data?.error?.message ?? 'Email is not ready yet.'
  } finally {
    loading.value = false
  }
}

async function createBox() {
  msg.value = ''
  creating.value = true
  try {
    await customersApi.createEnvMailbox(props.environmentId, {
      local_part: localPart.value.trim(),
      password: password.value,
    })
    password.value = ''
    msg.value = `Created ${previewEmail.value}. Open Roundcube with that address and password.`
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not create mailbox.'
  } finally {
    creating.value = false
  }
}

async function deleteBox(id: string, email: string) {
  if (!confirm(`Delete mailbox ${email}?`)) return
  busyId.value = id
  try {
    await customersApi.deleteEnvMailbox(props.environmentId, id)
    msg.value = `Deleted ${email}.`
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Delete failed.'
  } finally {
    busyId.value = ''
  }
}

async function toggleSuspend(box: MailboxRow) {
  busyId.value = box.id
  try {
    await customersApi.updateEnvMailbox(props.environmentId, box.id, {
      suspended: !box.suspended,
    })
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not update mailbox.'
  } finally {
    busyId.value = ''
  }
}

async function resetBoxPassword(box: MailboxRow) {
  const pwd = resetPassword.value.trim()
  if (pwd.length < 8) {
    msg.value = 'Enter a new password (8+ characters) in the field below first.'
    return
  }
  if (!confirm(`Reset password for ${box.email}?`)) return
  busyId.value = box.id
  try {
    await customersApi.resetEnvMailboxPassword(props.environmentId, box.id, pwd)
    resetPassword.value = ''
    msg.value = `Password reset for ${box.email}. Copy it now.`
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Reset failed.'
  } finally {
    busyId.value = ''
  }
}

async function createAlias() {
  msg.value = ''
  creating.value = true
  try {
    await customersApi.createEnvMailAlias(props.environmentId, {
      source_local: aliasSource.value.trim(),
      destination: aliasDest.value.trim(),
    })
    aliasSource.value = ''
    aliasDest.value = ''
    msg.value = 'Forwarder created.'
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not create forwarder.'
  } finally {
    creating.value = false
  }
}

async function deleteAlias(id: string) {
  if (!confirm('Delete this forwarder?')) return
  busyId.value = id
  try {
    await customersApi.deleteEnvMailAlias(props.environmentId, id)
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Delete failed.'
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="mail">
    <header class="hero">
      <div>
        <p class="kicker">Email</p>
        <h3>Email Accounts</h3>
        <p class="lede">
          Create <strong>name@{{ domainName || domain || 'your-domain' }}</strong>, forward mail, and open Roundcube at
          <strong>mail.ifnotus.space</strong>.
          <span v-if="mailboxLimit != null"> Up to {{ mailboxLimit }} mailbox{{ mailboxLimit === 1 ? '' : 'es' }}.</span>
          <span v-if="storageLimitMb != null"> · {{ totalQuotaMb }}/{{ storageLimitMb }} MB allocated.</span>
        </p>
      </div>
      <a class="btn-webmail" :href="webmail" target="_blank" rel="noopener">Open Roundcube</a>
    </header>

    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <template v-else>
      <div class="grid">
        <section class="card">
          <h4>Create an email account</h4>
          <p v-if="atLimit" class="hint">
            You have {{ mailboxes.length }} of {{ mailboxLimit }} mailbox{{ mailboxLimit === 1 ? '' : 'es' }} on this package.
          </p>
          <form v-else class="create-form" @submit.prevent="createBox">
            <label class="field">
              <span>Username</span>
              <div class="email-row">
                <input v-model="localPart" class="input" placeholder="hello" autocomplete="off" required />
                <span class="at">@{{ domainName || domain || '…' }}</span>
              </div>
            </label>
            <label class="field">
              <span>Password</span>
              <input
                v-model="password"
                class="input"
                type="password"
                placeholder="At least 8 characters"
                minlength="8"
                required
                autocomplete="new-password"
              />
            </label>
            <p class="hint">
              Will create <strong>{{ previewEmail }}</strong>
              <span v-if="mailboxLimit != null"> · {{ mailboxes.length }}/{{ mailboxLimit }} used</span>
            </p>
            <button type="submit" class="btn" :disabled="creating || password.length < 8">
              {{ creating ? 'Creating…' : 'Create account' }}
            </button>
          </form>
        </section>

        <section class="card">
          <div class="list-head">
            <h4>Accounts</h4>
            <button type="button" class="linkish" @click="load">Refresh</button>
          </div>
          <ul v-if="mailboxes.length" class="accounts">
            <li v-for="mb in mailboxes" :key="mb.id">
              <div class="grow">
                <p class="email">
                  {{ mb.email }}
                  <span v-if="mb.suspended" class="pill warn">Suspended</span>
                </p>
                <p class="hint">
                  {{ mb.used_mb ?? 0 }} MB used
                  <template v-if="mb.quota_mb"> · {{ mb.quota_mb }} MB quota</template>
                </p>
              </div>
              <div class="row-actions">
                <button
                  type="button"
                  class="btn-ghost"
                  :disabled="busyId === mb.id"
                  @click="toggleSuspend(mb)"
                >
                  {{ mb.suspended ? 'Unsuspend' : 'Suspend' }}
                </button>
                <button type="button" class="btn-ghost" :disabled="busyId === mb.id" @click="resetBoxPassword(mb)">
                  Reset pass
                </button>
                <button type="button" class="btn-ghost" :disabled="busyId === mb.id" @click="deleteBox(mb.id, mb.email)">
                  Delete
                </button>
                <a class="btn-ghost" :href="webmail" target="_blank" rel="noopener">Webmail</a>
              </div>
            </li>
          </ul>
          <div v-else class="empty">
            <p>No mailboxes yet</p>
            <p class="hint">Create one on the left to get started.</p>
          </div>
          <label v-if="mailboxes.length" class="field mt">
            <span>New password (for Reset pass)</span>
            <input v-model="resetPassword" class="input" type="password" minlength="8" autocomplete="new-password" />
          </label>
        </section>
      </div>

      <section class="card mt">
        <h4>Forwarders</h4>
        <form class="create-form" @submit.prevent="createAlias">
          <label class="field">
            <span>From</span>
            <div class="email-row">
              <input v-model="aliasSource" class="input" placeholder="info" required />
              <span class="at">@{{ domainName || domain || '…' }}</span>
            </div>
          </label>
          <label class="field">
            <span>To (full email)</span>
            <input v-model="aliasDest" class="input" type="email" placeholder="you@gmail.com" required />
          </label>
          <button type="submit" class="btn" :disabled="creating">Add forwarder</button>
        </form>
        <ul v-if="aliases.length" class="accounts mt">
          <li v-for="a in aliases" :key="a.id">
            <div>
              <p class="email">{{ a.source_email }} → {{ a.destination }}</p>
              <p v-if="!a.enabled" class="hint">Disabled</p>
            </div>
            <button type="button" class="btn-ghost" :disabled="busyId === a.id" @click="deleteAlias(a.id)">
              Delete
            </button>
          </li>
        </ul>
        <p v-else class="hint mt">No forwarders yet.</p>
      </section>

      <p v-if="msg" class="status">{{ msg }}</p>

      <section class="card connect-card mt">
        <button type="button" class="connect-toggle" @click="showConnect = !showConnect">
          <span>{{ showConnect ? 'Hide' : 'Show' }} device settings (IMAP / SMTP)</span>
          <span class="chev">{{ showConnect ? '−' : '+' }}</span>
        </button>
        <div v-if="showConnect" class="connect">
          <p class="hint">
            Username is the full email address. Hostnames stay on IFNOTUS names — never a raw server IP.
          </p>
          <div class="creds">
            <div>
              <p class="cred-k">Incoming (IMAP)</p>
              <p class="cred-v">{{ clients?.imap_host || 'mail.ifnotus.space' }}:{{ clients?.imap_port || 993 }} · {{ clients?.imap_security || 'SSL/TLS' }}</p>
            </div>
            <div>
              <p class="cred-k">Outgoing (SMTP)</p>
              <p class="cred-v">{{ clients?.smtp_host || 'mail.ifnotus.space' }}:{{ clients?.smtp_port || 587 }} · {{ clients?.smtp_security || 'STARTTLS' }}</p>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.mail { display: flex; flex-direction: column; gap: 1rem; }
.hero {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  padding: 1.15rem 1.25rem;
  border-radius: 1rem;
  border: 1px solid var(--if-border, #d7dee8);
  background:
    radial-gradient(520px 180px at 100% 0%, color-mix(in srgb, #1e3a5f 12%, transparent), transparent 60%),
    var(--if-surface, #fff);
}
.kicker {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #1e3a5f;
}
h3, h4 { margin: 0; color: var(--if-ink, #0f172a); }
h3 { margin-top: 0.2rem; font-family: Sora, sans-serif; font-size: 1.25rem; letter-spacing: -0.03em; }
.lede { margin: 0.45rem 0 0; max-width: 36rem; color: #5c6670; font-size: 0.9rem; line-height: 1.45; }
.muted { color: #5c6670; font-size: 0.9rem; }
.err { color: #b42318; }
.hint { margin: 0.35rem 0 0; font-size: 0.82rem; color: #5c6670; }
.status { margin: 0.75rem 0 0; font-size: 0.88rem; color: #5c6670; }
.grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr;
}
@media (min-width: 860px) {
  .grid { grid-template-columns: 1.05fr 0.95fr; }
}
.card {
  border: 1px solid var(--if-border, #d7dee8);
  border-radius: 0.95rem;
  padding: 1.05rem 1.15rem;
  background: var(--if-surface, #fff);
}
.mt { margin-top: 1rem; }
.create-form { display: flex; flex-direction: column; gap: 0.8rem; margin-top: 0.85rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.78rem; color: #5c6670; font-weight: 600; }
.email-row { display: flex; align-items: center; gap: 0.35rem; }
.email-row .input { flex: 1; min-width: 0; }
.at { font-size: 0.88rem; font-weight: 600; color: var(--if-ink, #0f172a); white-space: nowrap; }
.input {
  border: 1px solid var(--if-border, #d8dee4);
  border-radius: 0.65rem;
  padding: 0.55rem 0.75rem;
  font: inherit;
  font-weight: 500;
  background: #fff;
}
.btn {
  align-self: flex-start;
  border: 0;
  background: #1e3a5f;
  color: #fff;
  border-radius: 0.65rem;
  padding: 0.55rem 1rem;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn-webmail {
  display: inline-flex;
  align-items: center;
  border-radius: 0.7rem;
  background: #1e3a5f;
  color: #fff;
  text-decoration: none;
  font-weight: 650;
  font-size: 0.9rem;
  padding: 0.6rem 1rem;
}
.btn-ghost {
  border: 1px solid var(--if-border, #d8dee4);
  background: #fff;
  color: #1e3a5f;
  border-radius: 0.55rem;
  padding: 0.4rem 0.75rem;
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 650;
  cursor: pointer;
}
.list-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.linkish {
  border: 0;
  background: transparent;
  color: #1e3a5f;
  font: inherit;
  font-weight: 650;
  font-size: 0.86rem;
  cursor: pointer;
  padding: 0;
}
.accounts { list-style: none; margin: 0.85rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.accounts li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.55rem;
  align-items: center;
  padding: 0.75rem 0.85rem;
  border-radius: 0.7rem;
  background: #eef2f6;
}
.grow { flex: 1; min-width: 0; }
.row-actions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.email { margin: 0; font-weight: 650; color: var(--if-ink, #0f172a); }
.pill.warn {
  display: inline-block;
  margin-left: 0.35rem;
  font-size: 0.68rem;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  background: #fef3c7;
  color: #92400e;
}
.empty { margin-top: 0.85rem; padding: 1rem; border-radius: 0.7rem; background: #eef2f6; }
.empty p { margin: 0; font-weight: 650; }
.connect-card { padding: 0; overflow: hidden; }
.connect-toggle {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  border: 0;
  background: transparent;
  padding: 0.95rem 1.15rem;
  font: inherit;
  font-weight: 650;
  color: #1e3a5f;
  cursor: pointer;
  text-align: left;
}
.chev { font-size: 1.1rem; }
.connect { padding: 0 1.15rem 1.1rem; border-top: 1px solid var(--if-border, #d7dee8); }
.creds { margin-top: 0.75rem; display: grid; gap: 0.7rem; }
.cred-k { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: #5c6670; }
.cred-v { margin: 0.2rem 0 0; font-size: 0.9rem; color: var(--if-ink, #0f172a); word-break: break-all; }
</style>
