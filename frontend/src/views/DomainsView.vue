<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { domainsApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { DnsCheckResponse, Domain } from '@/types/hosting'

const loading = ref(true)
const domains = ref<Domain[]>([])
const serverIp = ref<string | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionKey = ref<string | null>(null)
const dnsResult = ref<DnsCheckResponse | null>(null)
const showForm = ref(false)
const selectedId = ref<string | null>(null)

const form = ref({
  name: '',
  subdomain_label: '',
  domain_type: 'primary' as Domain['domain_type'],
  parent_domain_id: '',
})
const dnsForm = ref({ record_type: 'A', host: '@', value: '', ttl: 3600, priority: '' as string | number })

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.DOMAINS_WRITE))

const zones = computed(() =>
  domains.value.filter((d) => d.domain_type !== 'redirect'),
)
const primaryZones = computed(() =>
  domains.value.filter((d) => d.domain_type === 'primary' || d.domain_type === 'addon'),
)
const selected = computed(() => domains.value.find((d) => d.id === selectedId.value) || null)

function dnsLabel(domain: Domain) {
  if (domain.dns_points_here === true) return { cls: 'ok', text: 'Points here' }
  if (domain.dns_points_here === false) return { cls: 'bad', text: 'Mismatch' }
  return { cls: '', text: 'Not checked' }
}

async function load() {
  loading.value = true
  try {
    const d = await domainsApi.list()
    domains.value = d.data.domains
    serverIp.value = d.data.server_ip ?? null
    if (selectedId.value && !domains.value.some((x) => x.id === selectedId.value)) {
      selectedId.value = null
    }
    if (!selectedId.value && domains.value[0]) selectedId.value = domains.value[0].id
    if (serverIp.value && !dnsForm.value.value) dnsForm.value.value = serverIp.value
  } finally {
    loading.value = false
  }
}

function openCreate(type: Domain['domain_type']) {
  form.value = {
    name: '',
    subdomain_label: '',
    domain_type: type,
    parent_domain_id: primaryZones.value[0]?.id || '',
  }
  showForm.value = true
}

async function createZone() {
  actionKey.value = 'create'
  message.value = null
  try {
    await domainsApi.create({
      name: form.value.name || undefined,
      subdomain_label: form.value.subdomain_label || undefined,
      domain_type: form.value.domain_type,
      parent_domain_id: form.value.parent_domain_id || undefined,
      provision: false,
      create_docroot: false,
    })
    message.value = { type: 'ok', text: 'DNS zone added.' }
    showForm.value = false
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not add zone') }
  } finally {
    actionKey.value = null
  }
}

async function checkDns(domain: Domain) {
  selectedId.value = domain.id
  actionKey.value = `dns-${domain.id}`
  dnsResult.value = null
  try {
    const { data } = await domainsApi.dnsCheck(domain.id)
    dnsResult.value = data
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'DNS check failed') }
  } finally {
    actionKey.value = null
  }
}

async function removeZone(domain: Domain) {
  if (!confirm(`Remove DNS zone ${domain.name}?`)) return
  actionKey.value = `del-${domain.id}`
  try {
    await domainsApi.delete(domain.id)
    message.value = { type: 'ok', text: 'Zone removed.' }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Delete failed') }
  } finally {
    actionKey.value = null
  }
}

async function addDns() {
  if (!selected.value) return
  actionKey.value = 'dnsadd'
  try {
    const priority =
      dnsForm.value.priority === '' || dnsForm.value.priority === null
        ? undefined
        : Number(dnsForm.value.priority)
    await domainsApi.createDnsRecord(selected.value.id, {
      record_type: dnsForm.value.record_type,
      host: dnsForm.value.host || '@',
      value: dnsForm.value.value,
      ttl: Number(dnsForm.value.ttl) || 3600,
      priority,
    })
    dnsForm.value = { record_type: 'A', host: '@', value: serverIp.value || '', ttl: 3600, priority: '' }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not add record') }
  } finally {
    actionKey.value = null
  }
}

async function removeDns(recordId: string) {
  if (!selected.value) return
  try {
    await domainsApi.deleteDnsRecord(selected.value.id, recordId)
    await load()
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Could not delete record') }
  }
}

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="ctrl">
      <header class="head">
        <div>
          <p class="k">DNS</p>
          <h1>Zones</h1>
          <p class="muted">Nameservers, records, and checks — nothing else on this page.</p>
        </div>
        <div class="head-actions">
          <button type="button" class="ghost" :disabled="loading" @click="load">Refresh</button>
          <button v-if="canWrite" type="button" class="cta" @click="openCreate('primary')">Add zone</button>
          <button v-if="canWrite" type="button" class="ghost" @click="openCreate('subdomain')">Add subdomain</button>
        </div>
      </header>

      <article class="card ns">
        <p class="k">Nameservers</p>
        <p class="ns-line">ns1.ifnotus.space &nbsp;·&nbsp; ns2.ifnotus.space</p>
        <p class="muted">Point the domain here, then add A / MX / TXT records below.</p>
      </article>

      <p v-if="message" class="note" :class="message.type">{{ message.text }}</p>
      <p v-if="dnsResult" class="note" :class="dnsResult.points_to_server ? 'ok' : 'err'">
        {{ dnsResult.domain }}:
        {{ dnsResult.resolves ? dnsResult.addresses.join(', ') : dnsResult.message || 'Does not resolve' }}
        <span v-if="dnsResult.points_to_server !== null">
          · {{ dnsResult.points_to_server ? 'points here' : 'does not point here' }}
        </span>
      </p>

      <article v-if="showForm && canWrite" class="card">
        <header>
          <h2>{{ form.domain_type === 'subdomain' ? 'New subdomain' : 'New zone' }}</h2>
          <button type="button" class="ghost" @click="showForm = false">Cancel</button>
        </header>
        <div class="form-row">
          <label v-if="form.domain_type === 'subdomain'">
            Label
            <input v-model="form.subdomain_label" placeholder="blog" />
          </label>
          <label v-else>
            Hostname
            <input v-model="form.name" placeholder="example.com" />
          </label>
          <label v-if="form.domain_type === 'subdomain'">
            Parent zone
            <select v-model="form.parent_domain_id">
              <option value="">Select</option>
              <option v-for="p in primaryZones" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <button type="button" class="cta" :disabled="actionKey === 'create'" @click="createZone">
            {{ actionKey === 'create' ? 'Adding…' : 'Add DNS zone' }}
          </button>
        </div>
      </article>

      <div class="split">
        <article class="card">
          <header><h2>Zones</h2></header>
          <p v-if="loading" class="muted">Loading…</p>
          <ul v-else class="zones">
            <li
              v-for="zone in zones"
              :key="zone.id"
              :class="{ on: selectedId === zone.id }"
              @click="selectedId = zone.id"
            >
              <div>
                <strong>{{ zone.name }}</strong>
                <span class="pill" :class="dnsLabel(zone).cls">{{ dnsLabel(zone).text }}</span>
              </div>
              <div class="row-actions">
                <button type="button" class="ghost" @click.stop="checkDns(zone)">Check</button>
                <button v-if="canWrite" type="button" class="danger" @click.stop="removeZone(zone)">Remove</button>
              </div>
            </li>
            <li v-if="!zones.length" class="muted">No zones yet.</li>
          </ul>
        </article>

        <article class="card">
          <header>
            <h2>Records</h2>
            <span v-if="selected" class="muted">{{ selected.name }}</span>
          </header>
          <p v-if="!selected" class="muted">Select a zone to edit its records.</p>
          <template v-else>
            <div v-if="canWrite" class="dns-add">
              <select v-model="dnsForm.record_type">
                <option>A</option>
                <option>AAAA</option>
                <option>CNAME</option>
                <option>MX</option>
                <option>TXT</option>
                <option>NS</option>
                <option>CAA</option>
              </select>
              <input v-model="dnsForm.host" placeholder="@" />
              <input v-model="dnsForm.value" :placeholder="serverIp || 'value'" />
              <input v-model="dnsForm.ttl" type="number" placeholder="TTL" />
              <input v-if="dnsForm.record_type === 'MX'" v-model="dnsForm.priority" type="number" placeholder="Pri" />
              <button type="button" class="cta" :disabled="actionKey === 'dnsadd'" @click="addDns">Add</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Host</th>
                    <th>Value</th>
                    <th>TTL</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in selected.dns_records || []" :key="r.id">
                    <td>{{ r.record_type }}{{ r.priority != null ? ` ${r.priority}` : '' }}</td>
                    <td>{{ r.host }}</td>
                    <td>{{ r.value }}</td>
                    <td>{{ r.ttl }}</td>
                    <td>
                      <button v-if="canWrite" type="button" class="danger" @click="removeDns(r.id)">Remove</button>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-if="!(selected.dns_records || []).length" class="muted">No records in this zone yet.</p>
            </div>
          </template>
        </article>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.ctrl { display: flex; flex-direction: column; gap: 0.9rem; }
.head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 1rem; align-items: flex-end; }
.head h1 { margin: 0.15rem 0 0; font-size: 1.2rem; font-weight: 700; }
.head-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.k {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.muted { margin: 0.3rem 0 0; color: var(--color-text-muted); font-size: 0.8rem; }
.card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 0.9rem;
  box-shadow: var(--shadow-card);
  padding: 1rem 1.1rem 1.15rem;
}
.card header { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; margin-bottom: 0.75rem; }
.card h2 { margin: 0; font-size: 0.92rem; font-weight: 700; }
.ns-line { margin: 0.35rem 0 0; font-family: ui-monospace, monospace; font-size: 0.95rem; font-weight: 650; }
.note { margin: 0; padding: 0.7rem 0.9rem; border-radius: 0.75rem; font-size: 0.82rem; }
.note.ok { background: #ecfdf5; color: #047857; }
.note.err { background: #fef2f2; color: #b91c1c; }
.cta, .ghost, .danger {
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  border-radius: 0.65rem;
  padding: 0.45rem 0.8rem;
  font-size: 0.8rem;
  font-weight: 650;
  cursor: pointer;
}
.cta { background: #2563eb; border-color: #2563eb; color: #fff; }
.danger { color: #b91c1c; }
.split { display: grid; gap: 0.85rem; }
@media (min-width: 900px) { .split { grid-template-columns: 0.9fr 1.2fr; } }
.zones { list-style: none; margin: 0; padding: 0; }
.zones li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.7rem 0.55rem;
  border-radius: 0.65rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.zones li.on { background: color-mix(in srgb, var(--if-primary) 14%, var(--color-surface)); }
.zones strong { margin-right: 0.45rem; }
.pill {
  display: inline-block;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  background: var(--color-surface);
  color: var(--color-text-muted);
}
.pill.ok { background: #ecfdf5; color: #047857; }
.pill.bad { background: #fef2f2; color: #b91c1c; }
.row-actions { display: flex; gap: 0.3rem; }
.form-row, .dns-add {
  display: grid;
  gap: 0.5rem;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  align-items: end;
}
.form-row label, .dns-add {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
input, select {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 0.65rem;
  padding: 0.48rem 0.65rem;
  font-size: 0.84rem;
  background: var(--color-surface-raised);
}
.dns-add { margin-bottom: 0.75rem; }
.table-wrap { overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.78rem; font-family: ui-monospace, monospace; }
th { text-align: left; color: var(--color-text-muted); font-weight: 650; padding: 0.4rem 0.45rem; }
td { padding: 0.45rem; border-top: 1px solid var(--color-border); word-break: break-all; }
</style>
