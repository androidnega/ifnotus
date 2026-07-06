<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { applicationsApi, domainsApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { ApplicationSummary } from '@/types/dashboard'
import type { DnsCheckResponse, Domain } from '@/types/hosting'

const loading = ref(true)
const domains = ref<Domain[]>([])
const apps = ref<ApplicationSummary[]>([])
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionKey = ref<string | null>(null)
const dnsResult = ref<DnsCheckResponse | null>(null)
const showForm = ref(false)

const form = ref({
  name: '',
  domain_type: 'primary' as Domain['domain_type'],
  parent_domain_id: '',
  application_id: '',
  document_root: '',
  notes: '',
})

const primaryDomains = computed(() => domains.value.filter((d) => d.domain_type === 'primary'))

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.DOMAINS_WRITE))

const editingDomain = ref<Domain | null>(null)
const editForm = ref({ application_id: '', document_root: '', notes: '' })

async function load() {
  loading.value = true
  try {
    const [d, a] = await Promise.all([domainsApi.list(), applicationsApi.list()])
    domains.value = d.data.domains
    apps.value = a.data.applications
  } finally {
    loading.value = false
  }
}

async function createDomain() {
  actionKey.value = 'create'
  message.value = null
  try {
    await domainsApi.create({
      name: form.value.name,
      domain_type: form.value.domain_type,
      parent_domain_id: form.value.parent_domain_id || undefined,
      application_id: form.value.application_id || undefined,
      document_root: form.value.document_root || undefined,
      notes: form.value.notes || undefined,
    })
    message.value = { type: 'ok', text: 'Domain created.' }
    showForm.value = false
    form.value = { name: '', domain_type: 'primary', parent_domain_id: '', application_id: '', document_root: '', notes: '' }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Failed to create domain' }
  } finally {
    actionKey.value = null
  }
}

async function toggleEnabled(domain: Domain) {
  actionKey.value = domain.id
  try {
    await domainsApi.update(domain.id, { enabled: !domain.enabled })
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Update failed' }
  } finally {
    actionKey.value = null
  }
}

async function checkDns(domain: Domain) {
  actionKey.value = `dns-${domain.id}`
  dnsResult.value = null
  try {
    const { data } = await domainsApi.dnsCheck(domain.id)
    dnsResult.value = data
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'DNS check failed' }
  } finally {
    actionKey.value = null
  }
}

async function removeDomain(domain: Domain) {
  if (!confirm(`Delete ${domain.name}?`)) return
  actionKey.value = `del-${domain.id}`
  try {
    await domainsApi.delete(domain.id)
    message.value = { type: 'ok', text: 'Domain deleted.' }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Delete failed' }
  } finally {
    actionKey.value = null
  }
}

function startEdit(domain: Domain) {
  editingDomain.value = domain
  editForm.value = {
    application_id: domain.application_id ?? '',
    document_root: domain.document_root ?? '',
    notes: domain.notes ?? '',
  }
}

async function saveEdit() {
  if (!editingDomain.value) return
  actionKey.value = `edit-${editingDomain.value.id}`
  try {
    await domainsApi.update(editingDomain.value.id, {
      application_id: editForm.value.application_id || undefined,
      document_root: editForm.value.document_root || undefined,
      notes: editForm.value.notes || undefined,
    })
    message.value = { type: 'ok', text: 'Domain updated.' }
    editingDomain.value = null
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Update failed' }
  } finally {
    actionKey.value = null
  }
}

function dnsBadge(domain: Domain) {
  if (domain.dns_points_here === true) return { variant: 'success' as const, label: 'DNS OK' }
  if (domain.dns_points_here === false) return { variant: 'danger' as const, label: 'DNS mismatch' }
  return { variant: 'neutral' as const, label: 'DNS unknown' }
}

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Domains</h1>
          <p class="text-sm text-surface-muted">Manage hostnames, DNS, and nginx linkage</p>
        </div>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            :disabled="loading"
            @click="load"
          >
            Refresh
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
            @click="showForm = !showForm"
          >
            Add domain
          </button>
        </div>
      </div>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <Card v-if="showForm && canWrite" padding="md">
        <h2 class="mb-3 text-sm font-semibold">New domain</h2>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block text-sm">
            <span class="text-surface-muted">Hostname</span>
            <input v-model="form.name" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" placeholder="example.com" />
          </label>
          <label class="block text-sm">
            <span class="text-surface-muted">Type</span>
            <select v-model="form.domain_type" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
              <option value="primary">Primary</option>
              <option value="subdomain">Subdomain</option>
              <option value="addon">Addon</option>
            </select>
          </label>
          <label v-if="form.domain_type !== 'primary'" class="block text-sm">
            <span class="text-surface-muted">Parent domain</span>
            <select v-model="form.parent_domain_id" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
              <option value="">Select parent</option>
              <option v-for="p in primaryDomains" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <label class="block text-sm">
            <span class="text-surface-muted">Application</span>
            <select v-model="form.application_id" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
              <option value="">None</option>
              <option v-for="a in apps" :key="a.id" :value="a.id">{{ a.name }}</option>
            </select>
          </label>
          <label class="block text-sm md:col-span-2">
            <span class="text-surface-muted">Document root</span>
            <input v-model="form.document_root" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" placeholder="/var/www/example" />
          </label>
        </div>
        <div class="mt-4 flex gap-2">
          <button
            type="button"
            class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white"
            :disabled="actionKey === 'create' || !form.name"
            @click="createDomain"
          >
            Save
          </button>
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" @click="showForm = false">Cancel</button>
        </div>
      </Card>

      <Card v-if="editingDomain && canWrite" padding="md">
        <h2 class="mb-3 text-sm font-semibold">Edit {{ editingDomain.name }}</h2>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block text-sm">
            <span class="text-surface-muted">Application</span>
            <select v-model="editForm.application_id" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2">
              <option value="">None</option>
              <option v-for="a in apps" :key="a.id" :value="a.id">{{ a.name }}</option>
            </select>
          </label>
          <label class="block text-sm md:col-span-2">
            <span class="text-surface-muted">Document root</span>
            <input v-model="editForm.document_root" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" />
          </label>
          <label class="block text-sm md:col-span-2">
            <span class="text-surface-muted">Notes</span>
            <input v-model="editForm.notes" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" />
          </label>
        </div>
        <div class="mt-4 flex gap-2">
          <button type="button" class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white" @click="saveEdit">Save</button>
          <button type="button" class="rounded-lg border border-surface-border px-3 py-2 text-sm" @click="editingDomain = null">Cancel</button>
        </div>
      </Card>

      <Card v-if="dnsResult" padding="sm">
        <p class="text-sm font-medium">DNS: {{ dnsResult.domain }}</p>
        <p class="text-xs text-surface-muted">
          {{ dnsResult.resolves ? dnsResult.addresses.join(', ') : dnsResult.message || 'Does not resolve' }}
          <span v-if="dnsResult.points_to_server !== null"> · points here: {{ dnsResult.points_to_server ? 'yes' : 'no' }}</span>
        </p>
      </Card>

      <div v-if="loading" class="text-sm text-surface-muted">Loading domains…</div>

      <div v-else-if="!domains.length" class="rounded-xl border border-dashed border-surface-border p-8 text-center text-sm text-surface-muted">
        No domains registered yet.
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="domain in domains"
          :key="domain.id"
          class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-surface-border bg-surface-raised px-4 py-3"
        >
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-slate-900 dark:text-white">{{ domain.name }}</span>
              <Badge size="sm">{{ domain.domain_type }}</Badge>
              <Badge :variant="domain.enabled ? 'success' : 'neutral'" size="sm">{{ domain.enabled ? 'Enabled' : 'Disabled' }}</Badge>
              <Badge :variant="dnsBadge(domain).variant" size="sm">{{ dnsBadge(domain).label }}</Badge>
              <Badge v-if="domain.nginx_enabled !== null" :variant="domain.nginx_enabled ? 'info' : 'warning'" size="sm">
                nginx {{ domain.nginx_enabled ? 'on' : 'off' }}
              </Badge>
            </div>
            <p class="mt-1 text-xs text-surface-muted">
              <span v-if="domain.application_id">app: {{ domain.application_id }}</span>
              <span v-if="domain.document_root"> · {{ domain.document_root }}</span>
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs"
              :disabled="!!actionKey"
              @click="checkDns(domain)"
            >
              Check DNS
            </button>
            <button
              v-if="canWrite"
              type="button"
              class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs"
              :disabled="!!actionKey"
              @click="startEdit(domain)"
            >
              Edit
            </button>
            <button
              v-if="canWrite"
              type="button"
              class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs"
              :disabled="!!actionKey"
              @click="toggleEnabled(domain)"
            >
              {{ domain.enabled ? 'Disable' : 'Enable' }}
            </button>
            <button
              v-if="canWrite"
              type="button"
              class="rounded-lg border border-red-500/30 px-2.5 py-1.5 text-xs text-red-600"
              :disabled="!!actionKey"
              @click="removeDomain(domain)"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>
