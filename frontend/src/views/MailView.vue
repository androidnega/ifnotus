<script setup lang="ts">
import { onMounted, ref, watch, computed } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { domainsApi, mailApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { IconApp, IconDatabase, IconGlobe, IconLock, IconMail, IconRefresh, IconSettings } from '@/components/icons'
import type { Domain, MailAlias, Mailbox, MailDomainResponse } from '@/types/hosting'

const DEFAULT_MAIL_HOST = 'mail.ifnotus.space'
const DEFAULT_WEBMAIL = 'https://mail.ifnotus.space/'
const DEFAULT_DOMAIN = 'ifnotus.space'

type MailTab = 'connect' | 'dns' | 'mailboxes' | 'forwarders'

const loading = ref(true)
const domains = ref<Domain[]>([])
const selectedId = ref('')
const mailData = ref<MailDomainResponse | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionKey = ref<string | null>(null)
const mailboxQuery = ref('')
const activeTab = ref<MailTab>('mailboxes')
const expandedMb = ref<string | null>(null)

const mailboxForm = ref<{
  local_part: string
  password: string
  display_name: string
  quota_mb: string | number
}>({ local_part: '', password: '', display_name: '', quota_mb: '' })
const aliasForm = ref({ source_local: '', destination: '', catchAll: false })
const resetPassword = ref<Record<string, string>>({})
const quotaEdit = ref<Record<string, string>>({})
const displayEdit = ref<Record<string, string>>({})
const destEdit = ref<Record<string, string>>({})
const probeTo = ref('')
const authHints = ref<Array<{ record_type: string; host: string; value: string; priority?: number | null }>>([])
const authBusy = ref(false)
const authStatus = ref<{
  ready?: boolean
  spf_ok?: boolean
  dkim_dns_ok?: boolean
  mx_ok?: boolean
  dmarc_ok?: boolean
  dkim_signing?: boolean
  messages?: string[]
  tunnel?: { submission?: string; milter?: string; sender_binding?: string }
  server_ip?: string
  mail_hostname?: string
  mail_mx_host?: string
} | null>(null)

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.MAIL_WRITE))
const canAdmin = computed(() => can(Permission.SYSTEM_ADMIN))
const clients = computed(() => mailData.value?.clients)
const mailHost = computed(
  () =>
    authStatus.value?.mail_hostname ||
    clients.value?.imap_host ||
    clients.value?.mail_a_host ||
    DEFAULT_MAIL_HOST,
)
const webmailUrl = computed(
  () => clients.value?.webmail_url || mailData.value?.webmail_url || DEFAULT_WEBMAIL,
)
const imapEndpoint = computed(
  () => `${clients.value?.imap_host || mailHost.value}:${clients.value?.imap_port || 993}`,
)
const smtpEndpoint = computed(
  () => `${clients.value?.smtp_host || mailHost.value}:${clients.value?.smtp_port || 587}`,
)
const popEndpoint = computed(
  () => `${clients.value?.pop_host || mailHost.value}:${clients.value?.pop_port || 995}`,
)
const mxHost = computed(
  () => authStatus.value?.mail_mx_host || clients.value?.mail_a_host || mailHost.value,
)
const filteredMailboxes = computed(() => {
  const boxes = mailData.value?.mailboxes ?? []
  const q = mailboxQuery.value.trim().toLowerCase()
  if (!q) return boxes
  return boxes.filter(
    (mb) =>
      mb.email.toLowerCase().includes(q) ||
      (mb.display_name || '').toLowerCase().includes(q),
  )
})

const sortedDomains = computed(() => {
  const list = [...domains.value]
  list.sort((a, b) => {
    const aPref = a.name.toLowerCase() === DEFAULT_DOMAIN ? 0 : 1
    const bPref = b.name.toLowerCase() === DEFAULT_DOMAIN ? 0 : 1
    if (aPref !== bPref) return aPref - bPref
    return a.name.localeCompare(b.name)
  })
  return list
})

function pickDefaultDomainId(list: Domain[]): string {
  const preferred = list.find((d) => d.name.toLowerCase() === DEFAULT_DOMAIN)
  return preferred?.id || list[0]?.id || ''
}

async function loadDomains() {
  loading.value = true
  try {
    const { data } = await domainsApi.list()
    domains.value = data.domains
    const stillValid = selectedId.value && domains.value.some((d) => d.id === selectedId.value)
    if (!stillValid) {
      selectedId.value = pickDefaultDomainId(domains.value)
    }
  } finally {
    loading.value = false
  }
}

async function loadMail() {
  if (!selectedId.value) {
    mailData.value = null
    authHints.value = []
    authStatus.value = null
    return
  }
  actionKey.value = 'load'
  mailData.value = null
  try {
    const { data } = await mailApi.getDomain(selectedId.value)
    mailData.value = data
    const auth = data.auth
    if (auth) {
      applyAuth(auth)
    } else if (canWrite.value) {
      await ensureDeliveryAuth()
    }
  } catch (e) {
    mailData.value = null
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to load mail config') }
  } finally {
    actionKey.value = null
  }
}

function applyAuth(auth: Record<string, unknown>) {
  authHints.value = (auth.dns as typeof authHints.value) ?? []
  authStatus.value = {
    ready: Boolean(auth.ready),
    spf_ok: Boolean(auth.spf_ok),
    dkim_dns_ok: Boolean(auth.dkim_dns_ok),
    mx_ok: Boolean(auth.mx_ok),
    dmarc_ok: Boolean(auth.dmarc_ok),
    dkim_signing: Boolean(auth.dkim_signing),
    messages: (auth.messages as string[]) ?? [],
    tunnel: auth.tunnel as NonNullable<typeof authStatus.value>['tunnel'],
    server_ip: typeof auth.server_ip === 'string' ? auth.server_ip : undefined,
    mail_hostname: typeof auth.mail_hostname === 'string' ? auth.mail_hostname : undefined,
    mail_mx_host: typeof auth.mail_mx_host === 'string' ? auth.mail_mx_host : undefined,
  }
}

async function ensureDeliveryAuth() {
  if (!selectedId.value) return
  authBusy.value = true
  try {
    const { data } = await mailApi.ensureAuth(selectedId.value)
    const details = (data.details as Record<string, unknown> | undefined) ?? {}
    applyAuth(details)
    message.value = {
      type: details.ready ? 'ok' : 'err',
      text: data.message || 'Mail auth tunnel updated.',
    }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not prepare mail auth') }
  } finally {
    authBusy.value = false
  }
}

async function syncAllAuth() {
  authBusy.value = true
  try {
    const { data } = await mailApi.syncAuth()
    message.value = { type: 'ok', text: data.message || 'Synced DKIM for every mailbox domain.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Auth sync failed') }
  } finally {
    authBusy.value = false
  }
}

async function syncWebmail() {
  actionKey.value = 'webmail'
  try {
    const { data } = await mailApi.syncDomains()
    message.value = { type: 'ok', text: data.message || 'Webmail /mail locations synced.' }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Webmail sync failed') }
  } finally {
    actionKey.value = null
  }
}

function generatePassword() {
  const bytes = new Uint8Array(18)
  crypto.getRandomValues(bytes)
  mailboxForm.value.password =
    Array.from(bytes, (b) => b.toString(36).padStart(2, '0'))
      .join('')
      .replace(/[^a-z0-9]/gi, '')
      .slice(0, 14) + 'Aa1!'
}

async function copyText(text: string, label = 'Copied') {
  try {
    await navigator.clipboard.writeText(text)
    message.value = { type: 'ok', text: label }
  } catch {
    message.value = { type: 'err', text: 'Could not copy to clipboard.' }
  }
}

function copyDnsAll() {
  if (!authHints.value.length) return
  const lines = authHints.value.map((row) => {
    const prio = row.priority != null ? String(row.priority) : ''
    return [row.record_type, row.host, prio, row.value].filter(Boolean).join('\t')
  })
  void copyText(lines.join('\n'), 'DNS records copied.')
}

function toggleMb(id: string) {
  expandedMb.value = expandedMb.value === id ? null : id
  const mb = mailData.value?.mailboxes.find((m) => m.id === id)
  if (mb && expandedMb.value === id) {
    if (displayEdit.value[id] == null) displayEdit.value[id] = mb.display_name || ''
    if (quotaEdit.value[id] == null) quotaEdit.value[id] = mb.quota_mb != null ? String(mb.quota_mb) : ''
  }
}

function quotaInputValue(raw: unknown): string {
  if (raw == null || raw === '') return ''
  return String(raw).trim()
}

async function createMailbox() {
  if (!mailboxForm.value.local_part.trim()) {
    message.value = { type: 'err', text: 'Enter the local part (before @).' }
    return
  }
  if (!mailboxForm.value.password || mailboxForm.value.password.length < 8) {
    message.value = { type: 'err', text: 'Password must be at least 8 characters.' }
    return
  }
  actionKey.value = 'mb-create'
  try {
    const quota = quotaInputValue(mailboxForm.value.quota_mb)
    await mailApi.createMailbox(selectedId.value, {
      local_part: mailboxForm.value.local_part.trim(),
      password: mailboxForm.value.password,
      display_name: mailboxForm.value.display_name.trim() || undefined,
      quota_mb: quota ? Number(quota) : undefined,
    })
    mailboxForm.value = { local_part: '', password: '', display_name: '', quota_mb: '' }
    message.value = { type: 'ok', text: 'Mailbox created.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Create failed') }
  } finally {
    actionKey.value = null
  }
}

async function toggleSuspend(mb: Mailbox) {
  actionKey.value = mb.id
  try {
    await mailApi.updateMailbox(selectedId.value, mb.id, { suspended: !mb.suspended })
    await loadMail()
  } finally {
    actionKey.value = null
  }
}

async function resetMbPassword(mb: Mailbox) {
  const pwd = resetPassword.value[mb.id]
  if (!pwd || pwd.length < 8) return
  actionKey.value = `pwd-${mb.id}`
  try {
    await mailApi.updateMailbox(selectedId.value, mb.id, { password: pwd })
    resetPassword.value[mb.id] = ''
    message.value = { type: 'ok', text: `Password updated for ${mb.email}.` }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Reset failed') }
  } finally {
    actionKey.value = null
  }
}

async function saveQuota(mb: Mailbox) {
  const raw = quotaInputValue(quotaEdit.value[mb.id])
  const n = raw === '' ? null : Number(raw)
  if (n != null && (!Number.isFinite(n) || n < 0)) {
    message.value = { type: 'err', text: 'Quota must be ≥ 0 MB, or empty for unlimited.' }
    return
  }
  actionKey.value = `quota-${mb.id}`
  try {
    await mailApi.updateMailbox(selectedId.value, mb.id, { quota_mb: n ?? 0 })
    message.value = { type: 'ok', text: n ? `Quota set to ${n} MB.` : 'Quota unlimited.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Quota update failed') }
  } finally {
    actionKey.value = null
  }
}

async function saveDisplayName(mb: Mailbox) {
  actionKey.value = `dn-${mb.id}`
  try {
    await mailApi.updateMailbox(selectedId.value, mb.id, {
      display_name: (displayEdit.value[mb.id] ?? '').trim(),
    })
    message.value = { type: 'ok', text: 'Display name updated.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Display name update failed') }
  } finally {
    actionKey.value = null
  }
}

async function deleteMailbox(mb: Mailbox) {
  if (!confirm(`Delete ${mb.email}? Stored mail on disk is not removed automatically.`)) return
  try {
    await mailApi.deleteMailbox(selectedId.value, mb.id)
    message.value = { type: 'ok', text: 'Mailbox deleted.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Delete failed') }
  }
}

async function createAlias() {
  const source = aliasForm.value.catchAll ? '*' : aliasForm.value.source_local.trim()
  if (!source) {
    message.value = { type: 'err', text: 'Enter an alias local part, or enable catch-all.' }
    return
  }
  actionKey.value = 'alias-create'
  try {
    await mailApi.createAlias(selectedId.value, {
      source_local: source,
      destination: aliasForm.value.destination.trim(),
    })
    aliasForm.value = { source_local: '', destination: '', catchAll: false }
    message.value = { type: 'ok', text: source === '*' ? 'Catch-all created.' : 'Forwarder created.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Create failed') }
  } finally {
    actionKey.value = null
  }
}

async function toggleAlias(alias: MailAlias) {
  try {
    await mailApi.updateAlias(selectedId.value, alias.id, { enabled: !alias.enabled })
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not update forwarder') }
  }
}

async function saveAliasDest(alias: MailAlias) {
  const dest = (destEdit.value[alias.id] ?? alias.destination).trim()
  if (!dest || dest.length < 3) {
    message.value = { type: 'err', text: 'Enter a valid destination address.' }
    return
  }
  actionKey.value = `ad-${alias.id}`
  try {
    await mailApi.updateAlias(selectedId.value, alias.id, { destination: dest })
    message.value = { type: 'ok', text: 'Forwarder destination updated.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not update destination') }
  } finally {
    actionKey.value = null
  }
}

async function deleteAlias(alias: MailAlias) {
  try {
    await mailApi.deleteAlias(selectedId.value, alias.id)
    message.value = { type: 'ok', text: 'Forwarder removed.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Delete failed') }
  }
}

async function sendProbe() {
  if (!selectedId.value) return
  actionKey.value = 'probe'
  try {
    const { data } = await mailApi.probe(selectedId.value, { to: probeTo.value.trim() || undefined })
    message.value = { type: 'ok', text: data.message || 'Probe queued.' }
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Probe failed') }
  } finally {
    actionKey.value = null
  }
}

function quotaLabel(mb: Mailbox) {
  const used = mb.used_mb ?? 0
  if (!mb.quota_mb) return `${used} MB · ∞`
  return `${used}/${mb.quota_mb} MB`
}

watch(selectedId, async () => {
  authHints.value = []
  authStatus.value = null
  probeTo.value = ''
  expandedMb.value = null
  await loadMail()
})
onMounted(async () => {
  await loadDomains()
  await loadMail()
})
</script>

<template>
  <DashboardLayout @refresh="() => { loadDomains(); loadMail() }">
    <div class="mail">
      <header class="hero">
        <div class="hero-copy">
          <p class="kicker">Shared mail · {{ mailHost }}</p>
          <div class="title-row">
            <h1>Mail</h1>
            <select v-model="selectedId" class="domain" aria-label="Mail domain">
              <option v-for="d in sortedDomains" :key="d.id" :value="d.id">{{ d.name }}</option>
            </select>
          </div>
          <div v-if="mailData" class="meta">
            <span class="stat">{{ mailData.mailboxes.length }} boxes</span>
            <span class="stat">{{ mailData.aliases.length }} fwd</span>
            <span class="pill" :class="authStatus?.ready ? 'ok' : 'warn'">
              {{ authStatus?.ready ? 'DNS ready' : 'DNS needed' }}
            </span>
          </div>
        </div>
        <div class="hero-actions">
          <a class="btn primary" :href="webmailUrl" target="_blank" rel="noopener">Roundcube</a>
          <button
            v-if="canWrite"
            type="button"
            class="btn"
            :disabled="authBusy"
            @click="ensureDeliveryAuth"
          >
            {{ authBusy ? '…' : 'Recheck DNS' }}
          </button>
          <button v-if="canWrite" type="button" class="btn" :disabled="authBusy" @click="syncAllAuth">
            Sync all
          </button>
          <button
            v-if="canAdmin"
            type="button"
            class="btn"
            :disabled="!!actionKey"
            @click="syncWebmail"
          >
            {{ actionKey === 'webmail' ? '…' : 'Sync /mail' }}
          </button>
        </div>
      </header>

      <p v-if="message" class="flash" :class="message.type">
        {{ message.text }}
        <button type="button" aria-label="Dismiss" @click="message = null">×</button>
      </p>

      <div v-if="loading || actionKey === 'load'" class="empty">Loading…</div>
      <div v-else-if="!domains.length" class="empty">Add a DNS zone first, then create mailboxes.</div>

      <template v-else-if="mailData">
        <nav class="tab-cards" aria-label="Mail sections">
          <button
            type="button"
            class="tab-card"
            :class="{ on: activeTab === 'mailboxes' }"
            @click="activeTab = 'mailboxes'"
          >
            <span class="tab-ico"><IconMail :size="16" /></span>
            <span class="tab-copy">
              <strong>Mailboxes</strong>
              <em>{{ mailData.mailboxes.length }} accounts</em>
            </span>
          </button>
          <button
            type="button"
            class="tab-card"
            :class="{ on: activeTab === 'forwarders' }"
            @click="activeTab = 'forwarders'"
          >
            <span class="tab-ico"><IconRefresh :size="16" /></span>
            <span class="tab-copy">
              <strong>Forwarders</strong>
              <em>{{ mailData.aliases.length }} rules</em>
            </span>
          </button>
          <button
            type="button"
            class="tab-card"
            :class="{ on: activeTab === 'connect' }"
            @click="activeTab = 'connect'"
          >
            <span class="tab-ico"><IconGlobe :size="16" /></span>
            <span class="tab-copy">
              <strong>Connect</strong>
              <em>{{ mailHost }}</em>
            </span>
          </button>
          <button
            type="button"
            class="tab-card"
            :class="{ on: activeTab === 'dns' }"
            @click="activeTab = 'dns'"
          >
            <span class="tab-ico"><IconSettings :size="16" /></span>
            <span class="tab-copy">
              <strong>Mail DNS</strong>
              <em :class="authStatus?.ready ? 'ok' : 'warn'">
                {{ authStatus?.ready ? 'Ready' : 'Needed' }}
              </em>
            </span>
          </button>
        </nav>

        <section v-if="activeTab === 'mailboxes'" class="panel">
          <div class="panel-h">
            <div>
              <h2>Mailboxes</h2>
              <p class="lede">Create <strong>name@{{ mailData.domain.name }}</strong> addresses for this domain.</p>
            </div>
            <input v-model="mailboxQuery" class="search" placeholder="Filter…" aria-label="Filter mailboxes" />
          </div>

          <form v-if="canWrite" class="create-card" @submit.prevent="createMailbox">
            <label class="field-ico">
              <span class="ico" title="Local part"><IconMail :size="15" /></span>
              <input v-model="mailboxForm.local_part" placeholder="local" required aria-label="Local part" />
              <span class="at">@{{ mailData.domain.name }}</span>
            </label>
            <label class="field-ico">
              <span class="ico" title="Display name"><IconApp :size="15" /></span>
              <input v-model="mailboxForm.display_name" placeholder="Display name" aria-label="Display name" />
            </label>
            <label class="field-ico compact">
              <span class="ico" title="Quota MB"><IconDatabase :size="15" /></span>
              <input
                v-model="mailboxForm.quota_mb"
                type="number"
                min="0"
                placeholder="MB"
                aria-label="Quota MB"
              />
            </label>
            <label class="field-ico">
              <span class="ico" title="Password"><IconLock :size="15" /></span>
              <input
                v-model="mailboxForm.password"
                type="password"
                placeholder="Password"
                required
                minlength="8"
                aria-label="Password"
              />
            </label>
            <div class="create-actions">
              <button type="button" class="btn" @click="generatePassword">Gen</button>
              <button type="submit" class="btn primary" :disabled="!!actionKey">
                {{ actionKey === 'mb-create' ? '…' : 'Add mailbox' }}
              </button>
            </div>
          </form>
          <p v-else class="muted pad-sm">Mail write access required.</p>

          <div class="scroll">
            <table class="mb-table">
              <thead>
                <tr>
                  <th>Address</th>
                  <th>Quota</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <template v-for="mb in filteredMailboxes" :key="mb.id">
                  <tr :class="{ open: expandedMb === mb.id }">
                    <td data-label="Address">
                      <strong>{{ mb.email }}</strong>
                      <span v-if="mb.display_name" class="sub">{{ mb.display_name }}</span>
                    </td>
                    <td class="mono" data-label="Quota">{{ quotaLabel(mb) }}</td>
                    <td data-label="Status">
                      <span class="pill" :class="mb.suspended ? 'warn' : 'ok'">
                        {{ mb.suspended ? 'Off' : 'On' }}
                      </span>
                    </td>
                    <td class="acts" data-label="">
                      <button type="button" class="link" @click="copyText(mb.email, 'Copied')">Copy</button>
                      <button v-if="canWrite" type="button" class="link" @click="toggleMb(mb.id)">
                        {{ expandedMb === mb.id ? 'Less' : 'Edit' }}
                      </button>
                      <button v-if="canWrite" type="button" class="danger" @click="deleteMailbox(mb)">Del</button>
                    </td>
                  </tr>
                  <tr v-if="canWrite && expandedMb === mb.id" class="expand">
                    <td colspan="4">
                      <div class="edit-row">
                        <label>
                          Display
                          <input v-model="displayEdit[mb.id]" placeholder="Display name" />
                        </label>
                        <button type="button" class="btn" :disabled="!!actionKey" @click="saveDisplayName(mb)">
                          Save name
                        </button>
                        <label>
                          Password
                          <input v-model="resetPassword[mb.id]" type="password" placeholder="New (≥8)" />
                        </label>
                        <button
                          type="button"
                          class="btn"
                          :disabled="!resetPassword[mb.id] || resetPassword[mb.id].length < 8 || !!actionKey"
                          @click="resetMbPassword(mb)"
                        >
                          Reset pwd
                        </button>
                        <label>
                          Quota MB
                          <input
                            v-model="quotaEdit[mb.id]"
                            type="number"
                            min="0"
                            placeholder="∞"
                            class="w-mb"
                          />
                        </label>
                        <button type="button" class="btn" :disabled="!!actionKey" @click="saveQuota(mb)">
                          Save quota
                        </button>
                        <button type="button" class="btn" @click="toggleSuspend(mb)">
                          {{ mb.suspended ? 'Restore' : 'Suspend' }}
                        </button>
                      </div>
                    </td>
                  </tr>
                </template>
                <tr v-if="!filteredMailboxes.length">
                  <td colspan="4" class="muted">No mailboxes{{ mailboxQuery ? ' match' : '' }}.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-else-if="activeTab === 'forwarders'" class="panel">
          <div class="panel-h"><h2>Forwarders</h2></div>
          <form v-if="canWrite" class="create-card alias" @submit.prevent="createAlias">
            <label class="field-ico">
              <span class="ico"><IconMail :size="15" /></span>
              <input
                v-model="aliasForm.source_local"
                placeholder="alias"
                :disabled="aliasForm.catchAll"
                aria-label="Alias local part"
              />
              <span class="at">@{{ mailData.domain.name }}</span>
            </label>
            <label class="chk">
              <input v-model="aliasForm.catchAll" type="checkbox" />
              Catch-all *
            </label>
            <label class="field-ico">
              <span class="ico"><IconGlobe :size="15" /></span>
              <input
                v-model="aliasForm.destination"
                type="email"
                placeholder="deliver to"
                required
                aria-label="Destination"
              />
            </label>
            <button type="submit" class="btn" :disabled="!!actionKey">
              {{ actionKey === 'alias-create' ? '…' : 'Add' }}
            </button>
          </form>
          <ul class="fwd">
            <li v-for="al in mailData.aliases" :key="al.id">
              <div class="fwd-main">
                <strong>
                  {{ al.source_local === '*' ? `*@${mailData.domain.name}` : al.source_email }}
                </strong>
                <span class="arrow">→</span>
                <template v-if="canWrite">
                  <input
                    :value="destEdit[al.id] ?? al.destination"
                    class="dest"
                    aria-label="Forwarder destination"
                    @input="destEdit[al.id] = ($event.target as HTMLInputElement).value"
                    @change="saveAliasDest(al)"
                  />
                </template>
                <span v-else class="muted">{{ al.destination }}</span>
                <span class="pill" :class="al.enabled ? 'ok' : 'warn'">{{ al.enabled ? 'On' : 'Off' }}</span>
              </div>
              <div v-if="canWrite" class="acts">
                <button type="button" class="link" @click="toggleAlias(al)">
                  {{ al.enabled ? 'Disable' : 'Enable' }}
                </button>
                <button type="button" class="danger" @click="deleteAlias(al)">Del</button>
              </div>
            </li>
            <li v-if="!mailData.aliases.length" class="muted empty-fwd">No forwarders.</li>
          </ul>
        </section>

        <section v-else-if="activeTab === 'connect'" class="panel clients" aria-label="Client settings">
          <div class="panel-h">
            <div>
              <h2>Connect</h2>
              <p class="lede">Use <strong>{{ mailHost }}</strong> for webmail, IMAP, SMTP, and POP3.</p>
            </div>
          </div>
          <div class="clients-grid">
            <article class="endpoint">
              <span class="lbl">Webmail</span>
              <code>{{ mailHost }}</code>
              <button type="button" class="link" @click="copyText(webmailUrl)">Copy</button>
            </article>
            <article class="endpoint">
              <span class="lbl">IMAP</span>
              <code>{{ imapEndpoint }}</code>
              <button type="button" class="link" @click="copyText(imapEndpoint)">Copy</button>
            </article>
            <article class="endpoint">
              <span class="lbl">SMTP</span>
              <code>{{ smtpEndpoint }}</code>
              <button type="button" class="link" @click="copyText(smtpEndpoint)">Copy</button>
            </article>
            <article class="endpoint">
              <span class="lbl">POP3</span>
              <code>{{ popEndpoint }}</code>
              <button type="button" class="link" @click="copyText(popEndpoint)">Copy</button>
            </article>
          </div>
          <form v-if="canWrite" class="probe" @submit.prevent="sendProbe">
            <label class="probe-label">
              Probe to
              <input v-model="probeTo" type="email" placeholder="you@example.com" />
            </label>
            <button type="submit" class="btn" :disabled="!!actionKey">
              {{ actionKey === 'probe' ? '…' : 'Probe' }}
            </button>
          </form>
        </section>

        <section v-else class="panel dns-panel">
          <div class="panel-h dns-head">
            <div>
              <h2>Mail DNS</h2>
              <div class="pills">
                <i :class="authStatus?.spf_ok ? 'ok' : 'bad'">SPF</i>
                <i :class="authStatus?.dkim_dns_ok ? 'ok' : 'bad'">DKIM</i>
                <i :class="authStatus?.mx_ok ? 'ok' : 'warn'">MX</i>
                <i :class="authStatus?.dmarc_ok ? 'ok' : 'warn'">DMARC</i>
                <i :class="authStatus?.dkim_signing ? 'ok' : 'bad'">Sign</i>
              </div>
            </div>
          </div>
          <div class="dns-body">
            <div class="dns-intro">
              <div class="dns-intro-copy">
                <p class="hint">
                  Point MX at <code>{{ mxHost }}</code>, publish one SPF that authorizes this server,
                  then add DKIM + DMARC at the registrar.
                </p>
                <div v-if="authStatus?.tunnel" class="tunnel">
                  <span v-if="authStatus.tunnel.submission" class="chip">
                    <em>Sub</em>{{ authStatus.tunnel.submission }}
                  </span>
                  <span v-if="authStatus.tunnel.milter" class="chip">
                    <em>Milter</em>{{ authStatus.tunnel.milter }}
                  </span>
                  <span v-if="authStatus.mail_hostname" class="chip">
                    <em>Host</em>{{ authStatus.mail_hostname }}
                  </span>
                </div>
              </div>
              <button
                v-if="authHints.length"
                type="button"
                class="btn"
                @click="copyDnsAll"
              >
                Copy all
              </button>
            </div>

            <ul v-if="authStatus?.messages?.length" class="tips">
              <li v-for="(msg, i) in authStatus.messages" :key="i">{{ msg }}</li>
            </ul>

            <div v-if="authHints.length" class="dns-records">
              <article v-for="(row, idx) in authHints" :key="idx" class="dns-row">
                <div class="dns-meta">
                  <span class="type">
                    {{ row.record_type }}
                    <template v-if="row.priority != null"> {{ row.priority }}</template>
                  </span>
                  <span class="host">{{ row.host }}</span>
                </div>
                <code class="dns-value">{{ row.value }}</code>
                <button
                  type="button"
                  class="btn dns-copy"
                  @click="copyText(row.value, `${row.record_type} copied`)"
                >
                  Copy
                </button>
              </article>
            </div>
          </div>
        </section>
      </template>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.mail {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  font-size: 0.82rem;
  width: 100%;
  max-width: none;
}
.hero {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.85rem 1rem;
  padding: 0.85rem 1rem;
  background:
    linear-gradient(135deg, color-mix(in srgb, #1e3a5f 8%, transparent), transparent 60%),
    var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
}
.kicker {
  margin: 0 0 0.2rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
}
.hero h1 {
  margin: 0;
  font-size: clamp(1.15rem, 2.4vw, 1.45rem);
  font-weight: 750;
  letter-spacing: -0.02em;
}
.domain {
  min-width: min(100%, 14rem);
  max-width: 100%;
  padding: 0.4rem 0.55rem;
  border: 1px solid var(--color-border);
  border-radius: 0.45rem;
  background: var(--color-surface);
  font-size: 0.82rem;
  font-weight: 650;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.45rem;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}
.stat {
  color: var(--color-text-muted);
  font-size: 0.72rem;
  font-weight: 650;
}
.pill {
  display: inline-block;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 700;
  background: var(--color-surface);
  color: var(--color-text-muted);
}
.pill.ok {
  background: #ecfdf5;
  color: #047857;
}
.pill.warn {
  background: #fffbeb;
  color: #b45309;
}
.pill.bad {
  background: #fef2f2;
  color: #b91c1c;
}
.btn {
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: 0.45rem;
  padding: 0.38rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 650;
  cursor: pointer;
  color: var(--if-ink, inherit);
  text-decoration: none;
  white-space: nowrap;
}
.btn.primary {
  background: #1e3a5f;
  border-color: #1e3a5f;
  color: #fff;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.link {
  border: none;
  background: none;
  color: #1e3a5f;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}
.danger {
  border: none;
  background: none;
  color: #b91c1c;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}
.flash {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  padding: 0.5rem 0.7rem;
  border-radius: 0.5rem;
  font-size: 0.78rem;
}
.flash.ok {
  background: #ecfdf5;
  color: #047857;
}
.flash.err {
  background: #fef2f2;
  color: #b91c1c;
}
.flash button {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}
.muted {
  color: var(--color-text-muted);
}
.empty {
  padding: 1.1rem;
  border: 1px dashed var(--color-border);
  border-radius: 0.65rem;
  color: var(--color-text-muted);
  text-align: center;
}
.pad-sm {
  padding: 0.35rem 0;
  margin: 0;
}
.panel {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 0.7rem;
  padding: 0.75rem 0.85rem 0.85rem;
}
.tab-cards {
  display: grid;
  gap: 0.55rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (min-width: 900px) {
  .tab-cards {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.tab-card {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  width: 100%;
  text-align: left;
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  border-radius: 0.75rem;
  padding: 0.7rem 0.8rem;
  cursor: pointer;
  color: inherit;
  font: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.tab-card:hover {
  border-color: color-mix(in srgb, #1e3a5f 35%, var(--color-border));
}
.tab-card.on {
  border-color: color-mix(in srgb, #1e3a5f 55%, var(--color-border));
  background: color-mix(in srgb, #1e3a5f 8%, var(--color-surface-raised));
  box-shadow: 0 0 0 3px color-mix(in srgb, #1e3a5f 10%, transparent);
}
.tab-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.55rem;
  background: color-mix(in srgb, #1e3a5f 10%, transparent);
  color: #1e3a5f;
  flex-shrink: 0;
}
.tab-card.on .tab-ico {
  background: #1e3a5f;
  color: #fff;
}
.tab-copy {
  display: grid;
  gap: 0.1rem;
  min-width: 0;
}
.tab-copy strong {
  font-size: 0.8rem;
  font-weight: 750;
}
.tab-copy em {
  font-style: normal;
  font-size: 0.68rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tab-copy em.ok { color: #047857; font-weight: 700; }
.tab-copy em.warn { color: #b45309; font-weight: 700; }
.create-card {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 0.7rem;
  background: var(--color-surface);
}
@media (min-width: 900px) {
  .create-card {
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 6.5rem minmax(0, 1fr) auto;
    align-items: center;
  }
  .create-card.alias {
    grid-template-columns: minmax(0, 1.2fr) auto minmax(0, 1.3fr) auto;
  }
}
.field-ico {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
  margin: 0;
  padding: 0.28rem 0.45rem;
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  background: var(--color-surface-raised);
}
.field-ico .ico {
  display: inline-flex;
  color: #1e3a5f;
  opacity: 0.85;
  flex-shrink: 0;
}
.field-ico input {
  border: none;
  background: transparent;
  padding: 0.28rem 0;
  font-size: 0.78rem;
  color: inherit;
  width: 100%;
  min-width: 0;
  outline: none;
}
.field-ico.compact {
  max-width: 100%;
}
.field-ico .at {
  margin-left: 0.1rem;
}
.create-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.dns-head {
  align-items: center;
}
.dns-head .pills {
  margin-top: 0.35rem;
}
.panel-h {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.65rem;
  margin-bottom: 0.55rem;
  flex-wrap: wrap;
}
.panel-h h2 {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 750;
}
.lede {
  margin: 0.2rem 0 0;
  font-size: 0.74rem;
  color: var(--color-text-muted);
  line-height: 1.4;
}
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.pills i {
  font-style: normal;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  background: var(--color-surface);
}
.pills .ok {
  background: #ecfdf5;
  color: #047857;
}
.pills .bad {
  background: #fef2f2;
  color: #b91c1c;
}
.pills .warn {
  background: #fffbeb;
  color: #b45309;
}
.clients-grid {
  display: grid;
  gap: 0.55rem;
  grid-template-columns: repeat(auto-fit, minmax(11.5rem, 1fr));
}
.endpoint {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-rows: auto auto;
  gap: 0.15rem 0.45rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--color-border);
  border-radius: 0.55rem;
  background: var(--color-surface);
  align-items: center;
}
.endpoint .lbl {
  grid-column: 1 / -1;
  color: var(--color-text-muted);
  font-weight: 700;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.endpoint code {
  font-size: 0.74rem;
  word-break: break-all;
}
.probe {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: end;
  margin-top: 0.7rem;
}
.probe-label {
  display: grid;
  gap: 0.2rem;
  flex: 1 1 12rem;
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.probe input,
.search,
.create input,
.edit-row input,
.dest {
  border: 1px solid var(--color-border);
  border-radius: 0.4rem;
  background: var(--color-surface);
  padding: 0.38rem 0.5rem;
  font-size: 0.78rem;
  color: inherit;
  width: 100%;
  box-sizing: border-box;
}
.search {
  max-width: 11rem;
  width: 100%;
}
.dns-body {
  margin-top: 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.dns-intro {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.65rem 0.85rem;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--color-border);
  border-radius: 0.6rem;
  background: var(--color-surface);
}
.dns-intro-copy {
  flex: 1 1 16rem;
  min-width: 0;
}
.hint {
  margin: 0;
  font-size: 0.76rem;
  color: var(--color-text-muted);
  line-height: 1.5;
}
.hint code {
  font-size: 0.74rem;
  font-weight: 700;
  color: inherit;
}
.tips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.4rem;
}
.tips li {
  padding: 0.55rem 0.7rem;
  border-radius: 0.55rem;
  border: 1px solid color-mix(in srgb, #b45309 25%, var(--color-border));
  background: color-mix(in srgb, #fffbeb 70%, var(--color-surface));
  color: #92400e;
  font-size: 0.74rem;
  line-height: 1.45;
}
.tunnel {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.55rem;
}
.tunnel .chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  max-width: 100%;
  padding: 0.22rem 0.5rem;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  font-size: 0.68rem;
  font-family: ui-monospace, monospace;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tunnel .chip em {
  font-style: normal;
  font-family: inherit;
  font-weight: 750;
  font-size: 0.6rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #1e3a5f;
}
.dns-records {
  display: grid;
  gap: 0.45rem;
}
.dns-row {
  display: grid;
  grid-template-columns: minmax(6.5rem, 8.5rem) minmax(0, 1fr) auto;
  gap: 0.55rem 0.75rem;
  align-items: start;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--color-border);
  border-radius: 0.6rem;
  background: var(--color-surface);
}
.dns-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}
.dns-meta .type {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  background: color-mix(in srgb, #1e3a5f 12%, transparent);
  color: #1e3a5f;
  font-size: 0.66rem;
  font-weight: 750;
  letter-spacing: 0.03em;
}
.dns-meta .host {
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--color-text-muted);
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
.dns-value {
  display: block;
  margin: 0;
  padding: 0.45rem 0.55rem;
  border-radius: 0.45rem;
  background: color-mix(in srgb, #1e3a5f 4%, var(--color-surface-raised));
  border: 1px solid var(--color-border);
  font-size: 0.72rem;
  line-height: 1.45;
  word-break: break-all;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  max-height: 7.5rem;
  overflow: auto;
}
.dns-copy {
  align-self: start;
}
.scroll {
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.74rem;
  font-family: ui-monospace, monospace;
}
th {
  text-align: left;
  color: var(--color-text-muted);
  font-weight: 650;
  padding: 0.3rem 0.4rem;
  font-size: 0.64rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
td {
  padding: 0.4rem;
  border-top: 1px solid var(--color-border);
  vertical-align: top;
}
td.val {
  word-break: break-all;
  max-width: 36rem;
}
.mb-table strong {
  display: block;
  font-family: inherit;
  font-size: 0.8rem;
}
.mb-table .sub {
  display: block;
  color: var(--color-text-muted);
  font-size: 0.7rem;
  font-family: inherit;
}
.mb-table .mono {
  font-family: ui-monospace, monospace;
  white-space: nowrap;
}
.mb-table tr.open td {
  background: color-mix(in srgb, #1e3a5f 6%, transparent);
}
.acts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  justify-content: flex-end;
}
.expand td {
  background: color-mix(in srgb, #1e3a5f 4%, var(--color-surface));
}
.edit-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: end;
  padding: 0.25rem 0;
}
.edit-row label {
  display: grid;
  gap: 0.18rem;
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  min-width: min(100%, 9rem);
  flex: 1 1 8rem;
}
.create .w-mb,
.edit-row .w-mb {
  width: 5rem;
  max-width: 100%;
}
.at {
  font-size: 0.74rem;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.chk {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.76rem;
  font-weight: 650;
}
.fwd {
  list-style: none;
  margin: 0;
  padding: 0;
}
.fwd li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.45rem;
  padding: 0.55rem 0;
  border-top: 1px solid var(--color-border);
  font-size: 0.78rem;
}
.fwd-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  flex: 1;
  min-width: 0;
}
.fwd .arrow {
  color: var(--color-text-muted);
}
.dest {
  flex: 1 1 10rem;
  min-width: 0;
  max-width: 18rem;
}
.empty-fwd {
  border-top: none;
  padding-top: 0.2rem;
}

@media (min-width: 640px) {
  .edit-row .w-mb {
    width: 5rem;
  }
}

@media (min-width: 960px) {
  .tab-cards {
    gap: 0.65rem;
  }
}

@media (max-width: 700px) {
  .hero {
    padding: 0.75rem;
  }
  .hero-actions {
    width: 100%;
  }
  .hero-actions .btn {
    flex: 1 1 calc(50% - 0.4rem);
    text-align: center;
    justify-content: center;
  }
  .tab-cards {
    grid-template-columns: 1fr 1fr;
  }
  .search {
    max-width: none;
  }
  .dns-row {
    grid-template-columns: 1fr auto;
  }
  .dns-meta {
    grid-column: 1 / 2;
  }
  .dns-copy {
    grid-column: 2 / 3;
    grid-row: 1;
  }
  .dns-value {
    grid-column: 1 / -1;
    max-height: none;
  }
  table.mb-table thead {
    display: none;
  }
  table.mb-table,
  table.mb-table tbody,
  table.mb-table tr,
  table.mb-table td {
    display: block;
    width: 100%;
  }
  table.mb-table tr {
    padding: 0.55rem 0;
    border-top: 1px solid var(--color-border);
  }
  table.mb-table td {
    border: none;
    padding: 0.15rem 0;
  }
  table.mb-table td::before {
    content: attr(data-label);
    display: inline-block;
    min-width: 4.2rem;
    margin-right: 0.4rem;
    color: var(--color-text-muted);
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  table.mb-table td.acts {
    justify-content: flex-start;
  }
  table.mb-table td.acts::before {
    display: none;
  }
  .expand td {
    padding-top: 0.45rem !important;
  }
  .expand td::before {
    display: none !important;
  }
}
</style>
