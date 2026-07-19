<script setup lang="ts">
import { onMounted, ref, watch, computed } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { domainsApi, mailApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { Domain, MailAlias, Mailbox, MailDomainResponse } from '@/types/hosting'

const loading = ref(true)
const domains = ref<Domain[]>([])
const selectedId = ref('')
const mailData = ref<MailDomainResponse | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionKey = ref<string | null>(null)

const mailboxForm = ref({ local_part: '', password: '', display_name: '' })
const aliasForm = ref({ source_local: '', destination: '' })
const resetPassword = ref<Record<string, string>>({})

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.MAIL_WRITE))

async function loadDomains() {
  loading.value = true
  try {
    const { data } = await domainsApi.list()
    domains.value = data.domains
    if (!selectedId.value && domains.value.length) {
      selectedId.value = domains.value[0].id
    }
  } finally {
    loading.value = false
  }
}

async function loadMail() {
  if (!selectedId.value) {
    mailData.value = null
    return
  }
  actionKey.value = 'load'
  mailData.value = null
  try {
    const { data } = await mailApi.getDomain(selectedId.value)
    mailData.value = data
  } catch (e) {
    mailData.value = null
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to load mail config') }
  } finally {
    actionKey.value = null
  }
}

async function createMailbox() {
  if (!mailboxForm.value.password || mailboxForm.value.password.length < 8) {
    message.value = { type: 'err', text: 'Password must be at least 8 characters.' }
    return
  }
  actionKey.value = 'mb-create'
  try {
    await mailApi.createMailbox(selectedId.value, mailboxForm.value)
    mailboxForm.value = { local_part: '', password: '', display_name: '' }
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
    message.value = { type: 'ok', text: 'Password updated.' }
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Reset failed' }
  } finally {
    actionKey.value = null
  }
}

async function deleteMailbox(mb: Mailbox) {
  if (!confirm(`Delete ${mb.email}?`)) return
  try {
    await mailApi.deleteMailbox(selectedId.value, mb.id)
    message.value = { type: 'ok', text: 'Mailbox deleted.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Delete failed') }
  }
}

async function createAlias() {
  actionKey.value = 'alias-create'
  try {
    await mailApi.createAlias(selectedId.value, aliasForm.value)
    aliasForm.value = { source_local: '', destination: '' }
    message.value = { type: 'ok', text: 'Alias created.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Create failed') }
  } finally {
    actionKey.value = null
  }
}

async function deleteAlias(alias: MailAlias) {
  try {
    await mailApi.deleteAlias(selectedId.value, alias.id)
    message.value = { type: 'ok', text: 'Alias deleted.' }
    await loadMail()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Delete failed') }
  }
}

watch(selectedId, loadMail)
onMounted(async () => {
  await loadDomains()
  await loadMail()
})
</script>

<template>
  <DashboardLayout @refresh="() => { loadDomains(); loadMail() }">
    <div class="animate-fade-in space-y-5">
      <div>
        <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Mail</h1>
        <p class="text-sm text-surface-muted">Mailboxes, aliases, and webmail access</p>
      </div>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <label class="block max-w-sm text-sm">
        <span class="text-surface-muted">Domain</span>
        <select v-model="selectedId" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>

      <a
        v-if="mailData?.webmail_url"
        :href="mailData.webmail_url"
        target="_blank"
        rel="noopener"
        class="inline-flex rounded-lg bg-brand-600 px-3 py-2 text-sm text-white hover:bg-brand-700"
      >
        Open webmail
      </a>

      <div v-if="!domains.length && !loading" class="text-sm text-surface-muted">Add a domain first.</div>

      <template v-else-if="mailData">
        <Card v-if="mailData.mail_config_path" padding="sm">
          <h2 class="text-sm font-semibold">Mail configuration</h2>
          <p class="mt-1 font-mono text-xs text-surface-muted">{{ mailData.mail_config_path }}</p>
          <p class="mt-1 text-xs text-surface-muted">
            {{ mailData.mailboxes.length }} mailbox(es), {{ mailData.aliases.length }} alias(es)
          </p>
        </Card>

        <Card padding="md">
          <h2 class="mb-3 text-sm font-semibold">Mailboxes</h2>
          <div v-if="canWrite" class="mb-4 grid gap-2 md:grid-cols-3">
            <input v-model="mailboxForm.local_part" placeholder="local part" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
            <input v-model="mailboxForm.password" type="password" placeholder="password" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
            <button type="button" class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white" :disabled="!!actionKey" @click="createMailbox">Add mailbox</button>
          </div>
          <div v-if="!mailData.mailboxes.length" class="text-sm text-surface-muted">No mailboxes.</div>
          <div v-for="mb in mailData.mailboxes" :key="mb.id" class="flex flex-wrap items-center justify-between gap-2 border-t border-surface-border py-2 text-sm">
            <div>
              <span class="font-medium">{{ mb.email }}</span>
              <Badge :variant="mb.suspended ? 'warning' : 'success'" size="sm" class="ml-2">{{ mb.suspended ? 'Suspended' : 'Active' }}</Badge>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <input v-if="canWrite" v-model="resetPassword[mb.id]" type="password" placeholder="new password" class="rounded border border-surface-border bg-transparent px-2 py-1 text-xs" />
              <button v-if="canWrite" type="button" class="text-xs underline" @click="resetMbPassword(mb)">Reset</button>
              <button v-if="canWrite" type="button" class="text-xs" @click="toggleSuspend(mb)">{{ mb.suspended ? 'Unsuspend' : 'Suspend' }}</button>
              <button v-if="canWrite" type="button" class="text-xs text-red-600" @click="deleteMailbox(mb)">Delete</button>
            </div>
          </div>
        </Card>

        <Card padding="md">
          <h2 class="mb-3 text-sm font-semibold">Forwarders / aliases</h2>
          <div v-if="canWrite" class="mb-4 grid gap-2 md:grid-cols-3">
            <input v-model="aliasForm.source_local" placeholder="source local" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
            <input v-model="aliasForm.destination" placeholder="destination@email" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
            <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" :disabled="!!actionKey" @click="createAlias">Add alias</button>
          </div>
          <div v-for="al in mailData.aliases" :key="al.id" class="flex items-center justify-between border-t border-surface-border py-2 text-sm">
            <span>{{ al.source_email }} → {{ al.destination }}</span>
            <button v-if="canWrite" type="button" class="text-xs text-red-600" @click="deleteAlias(al)">Delete</button>
          </div>
        </Card>
      </template>
    </div>
  </DashboardLayout>
</template>
