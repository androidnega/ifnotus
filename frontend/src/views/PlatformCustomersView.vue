<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { platformAdminApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type {
  StaffAuditItem,
  StaffCustomerDetail,
  StaffCustomerListItem,
  StaffEnvHealth,
  StaffEnvLogs,
  StaffEnvStacks,
  StaffEnvUsage,
  StaffEnvironmentItem,
} from '@/types/staffPlatform'

const route = useRoute()
const { can } = usePermissions()
const canOps = computed(() => can(Permission.PLATFORM_OPS))
const canProvision = computed(() => can(Permission.SYSTEM_ADMIN))
const canTerminate = computed(() => can(Permission.SYSTEM_ADMIN))
const canGrantCredits = computed(
  () => can(Permission.PLATFORM_OPS) || can(Permission.SYSTEM_ADMIN),
)
const grantCredits = ref(50)
const grantNote = ref('')
const grantBusy = ref(false)
const provisionPlanId = ref('')
const provisionDomain = ref('')
const allPlans = ref<import('@/types/platform').HostingPlan[]>([])

const customers = ref<StaffCustomerListItem[]>([])
const selected = ref<StaffCustomerDetail | null>(null)
const activeEnvId = ref<string | null>(null)
const q = ref('')
const loading = ref(true)
const error = ref('')
const msg = ref('')
const busy = ref(false)
const showList = ref(true)

const health = ref<StaffEnvHealth | null>(null)
const usage = ref<StaffEnvUsage | null>(null)
const stacks = ref<StaffEnvStacks | null>(null)
const logs = ref<StaffEnvLogs | null>(null)
const installStackId = ref('wordpress')
const envTab = ref<'overview' | 'health' | 'stacks' | 'logs' | 'activity'>('overview')

const envTabs = [
  { id: 'overview' as const, label: 'Overview' },
  { id: 'health' as const, label: 'Health' },
  { id: 'stacks' as const, label: 'Stacks' },
  { id: 'logs' as const, label: 'Logs' },
  { id: 'activity' as const, label: 'Activity' },
]

const activeEnv = computed(() =>
  selected.value?.environments.find((e) => e.id === activeEnvId.value) || null,
)

function stackLabel(env: StaffEnvironmentItem) {
  const s = env.stack as { stack?: string; name?: string; installed_at?: string } | null
  if (!s) return 'No stack installed'
  const name = s.stack || s.name || 'stack'
  const when = s.installed_at ? ` · ${new Date(String(s.installed_at)).toLocaleDateString()}` : ''
  return `${name}${when}`
}

function currentStackName() {
  const cur = stacks.value?.current as { stack?: string; name?: string } | null | undefined
  return cur?.stack || cur?.name || 'none'
}

function shortDomain(domain?: string | null, id?: string) {
  if (domain) return domain
  return id ? id.slice(0, 8) : '—'
}

function checkValue(val: unknown) {
  if (val == null) return '—'
  if (typeof val === 'object') {
    try {
      return JSON.stringify(val)
    } catch {
      return String(val)
    }
  }
  return String(val)
}

function apiErr(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { error?: { message?: string } } } }
  return err.response?.data?.error?.message ?? fallback
}

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listCustomers({
      q: q.value.trim() || undefined,
    })
    customers.value = data
  } catch (e: unknown) {
    error.value = apiErr(e, 'Could not load customers.')
  } finally {
    loading.value = false
  }
}

async function openCustomer(id: string) {
  msg.value = ''
  health.value = null
  usage.value = null
  stacks.value = null
  logs.value = null
  try {
    const { data } = await platformAdminApi.getCustomer(id)
    selected.value = data
    activeEnvId.value = data.environments[0]?.id ?? null
    showList.value = false
    if (activeEnvId.value) await loadEnvPanel(activeEnvId.value)
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not open customer.')
  }
}

async function selectEnv(id: string) {
  activeEnvId.value = id
  envTab.value = 'overview'
  await loadEnvPanel(id)
}

async function loadEnvPanel(id: string) {
  if (!id) return
  try {
    const [u, s] = await Promise.all([
      platformAdminApi.getEnvironmentUsage(id),
      platformAdminApi.getEnvironmentStacks(id),
    ])
    usage.value = u.data
    stacks.value = s.data
    if (s.data.stacks?.length && !s.data.stacks.some((x) => x.id === installStackId.value)) {
      installStackId.value = s.data.stacks[0].id
    }
  } catch {
    /* keep prior */
  }
}

async function runHealth() {
  if (!activeEnvId.value || !canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.checkEnvironmentHealth(activeEnvId.value)
    health.value = data
    envTab.value = 'health'
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = data.summary || 'Health check completed.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Health check failed.')
  } finally {
    busy.value = false
  }
}

async function loadLogs() {
  if (!activeEnvId.value || !canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.getEnvironmentLogs(activeEnvId.value)
    logs.value = data
    envTab.value = 'logs'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not load logs.')
  } finally {
    busy.value = false
  }
}

async function suspendEnv(id: string) {
  if (!canOps.value || !confirm('Suspend this environment? Site goes offline; other tenants are untouched.')) return
  busy.value = true
  try {
    await platformAdminApi.suspendEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment suspended.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Suspend failed.')
  } finally {
    busy.value = false
  }
}

async function restoreEnv(id: string) {
  if (!canOps.value) return
  busy.value = true
  try {
    await platformAdminApi.restoreEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment restored.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Restore failed.')
  } finally {
    busy.value = false
  }
}

async function terminateEnv(id: string, domain?: string | null) {
  if (!canTerminate.value) return
  if (
    !confirm(
      `TERMINATE ${domain || id}?\n\nThis marks the site terminated and queues cleanup. Prefer Suspend for temporary issues.`,
    )
  ) {
    return
  }
  if (!confirm('Type confirmation: this cannot be undone from the customer portal. Continue?')) return
  busy.value = true
  try {
    await platformAdminApi.terminateEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment terminated.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Terminate failed.')
  } finally {
    busy.value = false
  }
}

async function clearEnvStack(id: string, domain?: string | null) {
  if (!canOps.value) return
  const label = domain || id
  if (
    !confirm(
      `Clear the stack install for ${label}?\n\nDeletes site files in that environment only and leaves a parking page.`,
    )
  ) {
    return
  }
  const dropDb = confirm('Also drop this environment’s MySQL database? (Cancel = keep database)')
  busy.value = true
  try {
    const { data } = await platformAdminApi.clearEnvironmentStack(id, dropDb)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = data.message || 'Installation cleared.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Clear failed.')
  } finally {
    busy.value = false
  }
}

async function repairFs(id: string) {
  if (!canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.repairEnvironmentFilesystem(id)
    msg.value = data.message || 'Permissions repaired.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Repair failed.')
  } finally {
    busy.value = false
  }
}

async function installStack() {
  if (!activeEnvId.value || !canOps.value || !installStackId.value) return
  if (!confirm(`Install ${installStackId.value} into this environment?`)) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.installEnvironmentStack(
      activeEnvId.value,
      installStackId.value,
      false,
    )
    msg.value = (data as { message?: string }).message || 'Install queued.'
    await loadEnvPanel(activeEnvId.value)
    if (selected.value) await openCustomer(selected.value.customer.id)
    envTab.value = 'stacks'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Install failed.')
  } finally {
    busy.value = false
  }
}

async function grantCreditsToCustomer() {
  if (!selected.value || !canGrantCredits.value) return
  const amount = Math.floor(Number(grantCredits.value) || 0)
  if (amount < 1) {
    msg.value = 'Enter at least 1 credit.'
    return
  }
  if (!confirm(`Add ${amount} AI credit(s) to ${selected.value.customer.full_name || selected.value.customer.email}?`)) {
    return
  }
  grantBusy.value = true
  try {
    const { data } = await platformAdminApi.grantCustomerCredits(selected.value.customer.id, {
      credits: amount,
      note: grantNote.value.trim() || undefined,
    })
    selected.value.credits_remaining = data.credits_remaining
    const row = customers.value.find((c) => c.id === selected.value?.customer.id)
    if (row) row.credits_remaining = data.credits_remaining
    grantNote.value = ''
    msg.value = data.message
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not grant credits.')
  } finally {
    grantBusy.value = false
  }
}

async function provisionHosting() {
  if (!selected.value || !provisionPlanId.value) return
  if (!confirm('Set up hosting for this customer now? They will get SMS and email when it is live.')) return
  busy.value = true
  try {
    const domain = provisionDomain.value.trim().toLowerCase()
    let name: string | undefined
    let ext: string | undefined
    if (domain && domain.includes('.')) {
      const i = domain.indexOf('.')
      name = domain
      ext = domain.slice(i)
    }
    await platformAdminApi.provisionCustomerHosting(selected.value.customer.id, {
      plan_id: provisionPlanId.value,
      domain_name: name,
      domain_extension: ext,
    })
    await openCustomer(selected.value.customer.id)
    msg.value = 'Hosting is being set up. The customer will be notified when it is ready.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not set up hosting.')
  } finally {
    busy.value = false
  }
}

const auditRows = computed<StaffAuditItem[]>(() => selected.value?.audit || [])

const envAuditRows = computed(() =>
  auditRows.value.filter(
    (r) => !r.target_id || r.target_id === activeEnv.value?.id || r.target_type !== 'environment',
  ),
)

onMounted(async () => {
  await loadList()
  try {
    const { data } = await platformAdminApi.listPlans(false)
    allPlans.value = data
    if (data[0]) provisionPlanId.value = data[0].id
  } catch {
    allPlans.value = []
  }
  const open = route.query.open
  if (typeof open === 'string' && open) await openCustomer(open)
})

watch(
  () => route.query.open,
  async (open) => {
    if (typeof open === 'string' && open) await openCustomer(open)
  },
)
</script>

<template>
  <DashboardLayout>
    <div class="cust">
      <header class="cust-head">
        <div class="cust-head-copy">
          <h1>Customers</h1>
          <p>Monitor subscriptions, stacks, health, and fix tenant issues without SSH.</p>
        </div>
        <form class="cust-search" @submit.prevent="loadList">
          <input v-model="q" type="search" placeholder="Search email or name" />
          <button type="submit">Search</button>
        </form>
      </header>

      <p v-if="loading" class="cust-muted">Loading…</p>
      <p v-else-if="error" class="cust-err">{{ error }}</p>

      <div v-else class="cust-layout" :class="{ 'has-detail': !!selected && !showList }">
        <aside class="cust-list" :class="{ 'is-hidden-mobile': selected && !showList }">
          <ul>
            <li v-for="c in customers" :key="c.id">
              <button
                type="button"
                class="cust-list-item"
                :class="{ on: selected?.customer.id === c.id }"
                @click="openCustomer(c.id)"
              >
                <span class="name" :title="c.full_name">{{ c.full_name }}</span>
                <span class="email" :title="c.email">{{ c.email }}</span>
                <span class="meta">{{ c.subscription_count }} sub · {{ c.environment_count }} env · {{ c.credits_remaining }} AI</span>
              </button>
            </li>
            <li v-if="!customers.length" class="cust-empty">No customers.</li>
          </ul>
        </aside>

        <section class="cust-detail" :class="{ 'is-hidden-mobile': !selected || showList }">
          <p v-if="msg" class="cust-toast">{{ msg }}</p>
          <p v-if="!selected" class="cust-muted">Select a customer to inspect environments and activity.</p>

          <template v-else>
            <button type="button" class="cust-back" @click="showList = true">← Customers</button>

            <div class="card">
              <div class="card-top">
                <div class="min0">
                  <h2 class="title" :title="selected.customer.full_name">{{ selected.customer.full_name }}</h2>
                  <p class="email-line" :title="selected.customer.email">{{ selected.customer.email }}</p>
                </div>
                <div class="chips">
                  <span class="chip">{{ selected.customer.email_verified ? 'Verified' : 'Unverified' }}</span>
                  <span class="chip">2FA {{ selected.customer.two_factor_enabled ? 'on' : 'off' }}</span>
                  <span class="chip">{{ selected.credits_remaining }} AI credits</span>
                </div>
              </div>
              <p v-if="selected.customer.phone || selected.customer.company" class="submeta">
                <span v-if="selected.customer.phone">{{ selected.customer.phone }}</span>
                <span v-if="selected.customer.phone && selected.customer.company"> · </span>
                <span v-if="selected.customer.company">{{ selected.customer.company }}</span>
              </p>

              <div class="split">
                <div class="min0">
                  <h3>Subscriptions</h3>
                  <ul class="stack-list">
                    <li v-for="s in selected.subscriptions" :key="s.id" class="mini-card">
                      <p class="mini-title" :title="s.plan_name || s.plan_id">{{ s.plan_name || s.plan_id }}</p>
                      <p class="mini-meta">{{ s.status }}</p>
                      <p class="mini-meta wrap">
                        {{ s.cpu_allocated }} vCPU · {{ s.ram_allocated }} GB · {{ s.storage_allocated }} GB
                        <span v-if="s.expires_at"> · exp {{ new Date(s.expires_at).toLocaleDateString() }}</span>
                        <span v-if="s.auto_renew"> · auto-renew</span>
                      </p>
                    </li>
                    <li v-if="!selected.subscriptions.length" class="cust-muted">None</li>
                  </ul>
                </div>
                <div class="min0">
                  <h3>Recent orders</h3>
                  <ul class="stack-list">
                    <li v-for="o in selected.orders.slice(0, 6)" :key="o.id" class="mini-card">
                      <p class="mini-title" :title="o.plan_name || o.plan_id">{{ o.plan_name || o.plan_id }}</p>
                      <p class="mini-meta wrap">
                        {{ o.payment_status }} / {{ o.provisioning_status }} · {{ o.currency }} {{ o.total_price }}
                      </p>
                    </li>
                    <li v-if="!selected.orders.length" class="cust-muted">None</li>
                  </ul>
                </div>
              </div>

              <div v-if="canGrantCredits" class="provision grant-credits">
                <h3>Give AI credits</h3>
                <p class="cust-muted">
                  Super admin or hosting can add credits manually (no invoice). Client sees the new balance in Billing / Dev Companion.
                </p>
                <div class="provision-row">
                  <input
                    v-model.number="grantCredits"
                    type="number"
                    min="1"
                    max="100000"
                    step="1"
                    placeholder="Credits"
                    aria-label="Credits to grant"
                  />
                  <input
                    v-model="grantNote"
                    placeholder="Optional note e.g. goodwill / support"
                  />
                  <button
                    type="button"
                    class="btn-primary"
                    :disabled="grantBusy || busy || !grantCredits || grantCredits < 1"
                    @click="grantCreditsToCustomer"
                  >
                    {{ grantBusy ? 'Adding…' : 'Add credits' }}
                  </button>
                </div>
                <p class="mini-meta">Current balance: {{ selected.credits_remaining }} credits</p>
              </div>

              <div v-if="canProvision" class="provision">
                <h3>Activate hosting</h3>
                <p class="cust-muted">Super admin only — provisions a plan and notifies the customer.</p>
                <div class="provision-row">
                  <select v-model="provisionPlanId">
                    <option v-for="p in allPlans" :key="p.id" :value="p.id">
                      {{ p.name }} — GHS {{ p.price_monthly }}
                    </option>
                  </select>
                  <input
                    v-model="provisionDomain"
                    placeholder="Optional domain e.g. studio.online"
                  />
                  <button
                    type="button"
                    class="btn-primary"
                    :disabled="busy || !provisionPlanId"
                    @click="provisionHosting"
                  >
                    Activate
                  </button>
                </div>
              </div>
            </div>

            <div class="env-layout">
              <div class="card env-picker">
                <h3>Environments</h3>
                <ul>
                  <li v-for="env in selected.environments" :key="env.id">
                    <button
                      type="button"
                      class="env-item"
                      :class="{ on: activeEnvId === env.id }"
                      @click="selectEnv(env.id)"
                    >
                      <span class="env-domain" :title="env.domain || env.id">{{ shortDomain(env.domain, env.id) }}</span>
                      <span class="env-meta">{{ env.status }} · {{ env.health_status }}</span>
                      <span class="env-stack" :title="stackLabel(env)">{{ stackLabel(env) }}</span>
                    </button>
                  </li>
                  <li v-if="!selected.environments.length" class="cust-empty">No environments.</li>
                </ul>
              </div>

              <div v-if="activeEnv" class="card env-panel min0">
                <div class="env-head">
                  <div class="min0">
                    <h3 class="env-title" :title="activeEnv.domain || activeEnv.id">
                      {{ shortDomain(activeEnv.domain, activeEnv.id) }}
                    </h3>
                    <div class="chips tight">
                      <span class="chip">{{ activeEnv.status }}</span>
                      <span class="chip">health {{ activeEnv.health_status }}</span>
                      <span class="chip">{{ activeEnv.cpu_limit }} vCPU</span>
                      <span class="chip">{{ activeEnv.ram_limit_gb }} GB RAM</span>
                      <span class="chip">{{ activeEnv.storage_limit_gb }} GB disk</span>
                      <span v-if="activeEnv.db_name" class="chip" :title="`${activeEnv.db_engine}:${activeEnv.db_name}`">
                        {{ activeEnv.db_engine }}:{{ activeEnv.db_name }}
                      </span>
                      <span v-if="activeEnv.ftp_username" class="chip">FTP {{ activeEnv.ftp_username }}</span>
                    </div>
                    <p class="env-stack-line" :title="stackLabel(activeEnv)">{{ stackLabel(activeEnv) }}</p>
                    <p
                      v-if="activeEnv.document_root"
                      class="path"
                      :title="activeEnv.document_root"
                    >{{ activeEnv.document_root }}</p>
                    <p v-if="activeEnv.created_at" class="cust-muted">
                      Created {{ new Date(activeEnv.created_at).toLocaleString() }}
                    </p>
                  </div>
                </div>

                <div v-if="canOps" class="actions">
                  <button type="button" class="btn" :disabled="busy" @click="runHealth">Live health</button>
                  <button type="button" class="btn" :disabled="busy" @click="loadLogs">Logs</button>
                  <button type="button" class="btn" :disabled="busy" @click="repairFs(activeEnv.id)">Repair permissions</button>
                  <button
                    type="button"
                    class="btn warn"
                    :disabled="busy || activeEnv.status === 'terminated'"
                    @click="clearEnvStack(activeEnv.id, activeEnv.domain)"
                  >
                    Clear install
                  </button>
                  <button
                    v-if="activeEnv.status !== 'suspended' && activeEnv.status !== 'terminated'"
                    type="button"
                    class="btn"
                    :disabled="busy"
                    @click="suspendEnv(activeEnv.id)"
                  >
                    Suspend
                  </button>
                  <button
                    v-if="activeEnv.status === 'suspended'"
                    type="button"
                    class="btn ok"
                    :disabled="busy"
                    @click="restoreEnv(activeEnv.id)"
                  >
                    Restore
                  </button>
                  <button
                    v-if="canTerminate && activeEnv.status !== 'terminated'"
                    type="button"
                    class="btn danger"
                    :disabled="busy"
                    @click="terminateEnv(activeEnv.id, activeEnv.domain)"
                  >
                    Terminate
                  </button>
                </div>

                <div class="tabs" role="tablist">
                  <button
                    v-for="t in envTabs"
                    :key="t.id"
                    type="button"
                    role="tab"
                    :class="{ on: envTab === t.id }"
                    @click="envTab = t.id"
                  >
                    {{ t.label }}
                  </button>
                </div>

                <div v-if="envTab === 'overview'" class="tab-body">
                  <p v-if="usage" class="wrap">
                    Storage
                    <strong>{{ usage.storage_used_gb.toFixed(2) }}</strong>
                    / {{ usage.storage_limit_gb }} GB ({{ usage.storage_pct.toFixed(0) }}%) ·
                    {{ usage.file_count }} files · {{ usage.storage_status }}
                  </p>
                  <p v-if="usage?.hard_exceeded" class="cust-err">Disk hard limit exceeded — suspend if they threaten the host.</p>
                  <p v-else-if="usage?.soft_warning" class="cust-warn">Disk soft warning — ask them to clean up or upgrade.</p>
                  <p v-if="usage?.message" class="cust-muted wrap">{{ usage.message }}</p>
                  <p class="cust-muted wrap">
                    Isolation {{ activeEnv.isolation_type }}
                    <span v-if="activeEnv.container_id"> · container {{ activeEnv.container_id.slice(0, 12) }}</span>
                  </p>
                </div>

                <div v-else-if="envTab === 'health'" class="tab-body">
                  <p v-if="!health" class="cust-muted">Run Live health to probe HTTP, docroot, and isolation.</p>
                  <template v-else>
                    <p class="wrap"><strong>{{ health.health_status }}</strong> — {{ health.summary }}</p>
                    <ul class="checks">
                      <li v-for="(val, key) in health.checks" :key="String(key)">
                        <span class="check-key">{{ key }}</span>
                        <span class="check-val">{{ checkValue(val) }}</span>
                      </li>
                    </ul>
                  </template>
                </div>

                <div v-else-if="envTab === 'stacks'" class="tab-body">
                  <p>Current: <strong>{{ currentStackName() }}</strong></p>
                  <pre v-if="stacks?.progress" class="progress-box">{{ JSON.stringify(stacks.progress, null, 2) }}</pre>
                  <div v-if="canOps" class="install-row">
                    <label>
                      Install stack
                      <select v-model="installStackId">
                        <option
                          v-for="s in stacks?.stacks || []"
                          :key="s.id"
                          :value="s.id"
                          :disabled="s.allowed === false"
                        >
                          {{ s.name }}
                        </option>
                      </select>
                    </label>
                    <button type="button" class="btn-primary" :disabled="busy" @click="installStack">Install</button>
                  </div>
                </div>

                <div v-else-if="envTab === 'logs'" class="tab-body">
                  <p v-if="!logs" class="cust-muted">Click Logs to load nginx/app output for this tenant only.</p>
                  <div v-else class="log-box">
                    <p v-for="(line, i) in logs.entries" :key="i">
                      <span class="log-src">[{{ line.source }}]</span> {{ line.message }}
                    </p>
                    <p v-if="!logs.entries.length" class="cust-muted">{{ logs.message || 'No log lines.' }}</p>
                  </div>
                </div>

                <div v-else class="tab-body">
                  <ul class="audit">
                    <li v-for="a in envAuditRows" :key="a.id">
                      <span class="when">{{ new Date(a.occurred_at).toLocaleString() }}</span>
                      <span class="wrap">{{ a.action }} · {{ a.result }}</span>
                    </li>
                    <li v-if="!envAuditRows.length" class="cust-muted">No audit events yet.</li>
                  </ul>
                </div>
              </div>
            </div>

            <div class="card">
              <h3>Customer activity</h3>
              <ul class="audit">
                <li v-for="a in auditRows" :key="a.id">
                  <span class="when">{{ new Date(a.occurred_at).toLocaleString() }}</span>
                  <span class="wrap">
                    <strong>{{ a.action }}</strong>
                    <template v-if="a.target_type"> · {{ a.target_type }}</template>
                    · {{ a.result }}
                  </span>
                </li>
                <li v-if="!auditRows.length" class="cust-muted">No activity recorded.</li>
              </ul>
            </div>
          </template>
        </section>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.cust {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding: 1rem 1rem 2rem;
  box-sizing: border-box;
}
@media (min-width: 768px) {
  .cust { padding: 1.25rem 1.5rem 2rem; }
}

.cust-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.85rem;
  margin-bottom: 1rem;
}
.cust-head-copy {
  min-width: 0;
  flex: 1 1 14rem;
}
.cust-head h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 650;
  color: var(--if-ink, #0f172a);
}
.cust-head p {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
  color: #64748b;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.cust-search {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  width: 100%;
  max-width: 22rem;
}
.cust-search input,
.cust-search button,
.provision-row select,
.provision-row input,
.install-row select {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.45rem 0.7rem;
  font-size: 0.875rem;
  background: #fff;
  color: inherit;
  min-width: 0;
}
.dark .cust-search input,
.dark .cust-search button,
.dark .provision-row select,
.dark .provision-row input,
.dark .install-row select,
.dark .card,
.dark .mini-card,
.dark .cust-toast {
  background: #0f172a;
  border-color: #334155;
}
.cust-search input { flex: 1 1 10rem; }
.cust-search button {
  cursor: pointer;
  white-space: nowrap;
}

.cust-layout {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  min-width: 0;
}
@media (min-width: 1100px) {
  .cust-layout {
    grid-template-columns: minmax(15rem, 17.5rem) minmax(0, 1fr);
  }
  .cust-back,
  .is-hidden-mobile { display: none !important; }
  .cust-list.is-hidden-mobile,
  .cust-detail.is-hidden-mobile { display: block !important; }
}

@media (max-width: 1099px) {
  .cust-list.is-hidden-mobile { display: none; }
  .cust-detail.is-hidden-mobile { display: none; }
}

.cust-list,
.card,
.cust-detail {
  min-width: 0;
  max-width: 100%;
}
.cust-list {
  border: 1px solid #e2e8f0;
  border-radius: 0.85rem;
  background: #fff;
  overflow: hidden;
}
.dark .cust-list { border-color: #334155; background: #0f172a; }
.cust-list ul {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: min(70vh, 40rem);
  overflow: auto;
}
.cust-list-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  width: 100%;
  text-align: left;
  padding: 0.8rem 0.95rem;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  background: transparent;
  cursor: pointer;
  min-width: 0;
}
.dark .cust-list-item { border-bottom-color: #1e293b; }
.cust-list-item:hover,
.cust-list-item.on { background: #f8fafc; }
.dark .cust-list-item:hover,
.dark .cust-list-item.on { background: #1e293b; }
.cust-list-item .name,
.cust-list-item .email,
.cust-list-item .meta,
.title,
.email-line,
.env-domain,
.env-title,
.env-stack,
.env-stack-line,
.mini-title,
.path,
.wrap,
.check-val,
.log-box p {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.cust-list-item .name,
.title,
.env-domain,
.env-title,
.mini-title,
.email-line {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cust-list-item .name { font-size: 0.9rem; font-weight: 600; color: #0f172a; }
.dark .cust-list-item .name { color: #f8fafc; }
.cust-list-item .email,
.cust-list-item .meta { font-size: 0.75rem; color: #64748b; }

.cust-detail { display: flex; flex-direction: column; gap: 1rem; min-width: 0; }
.cust-back {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: #1e3a5f;
  font-size: 0.85rem;
  font-weight: 650;
  cursor: pointer;
  padding: 0;
}
.cust-toast {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  background: #fff;
  font-size: 0.875rem;
  overflow-wrap: anywhere;
}
.cust-muted { margin: 0; font-size: 0.84rem; color: #64748b; }
.cust-err { margin: 0; font-size: 0.84rem; color: #b42318; }
.cust-warn { margin: 0; font-size: 0.84rem; color: #b54708; }
.cust-empty { padding: 1rem; font-size: 0.875rem; color: #64748b; }

.card {
  border: 1px solid #e2e8f0;
  border-radius: 0.85rem;
  background: #fff;
  padding: 1rem;
  overflow: hidden;
}
.dark .card { border-color: #334155; }
.card-top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}
.min0 { min-width: 0; }
.title { margin: 0; font-size: 1.1rem; font-weight: 650; max-width: 100%; }
.email-line { margin: 0.2rem 0 0; font-size: 0.8rem; color: #64748b; max-width: 100%; }
.submeta { margin: 0.45rem 0 0; font-size: 0.8rem; color: #64748b; overflow-wrap: anywhere; }

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  max-width: 100%;
}
.chips.tight { margin-top: 0.55rem; }
.chip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #334155;
  font-size: 0.72rem;
  font-weight: 650;
}
.dark .chip { background: #1e293b; color: #cbd5e1; }

.split {
  display: grid;
  gap: 1rem;
  margin-top: 1rem;
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 720px) {
  .split { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
h3 {
  margin: 0 0 0.55rem;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: #64748b;
}
.stack-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.mini-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 0.55rem 0.7rem;
  min-width: 0;
  overflow: hidden;
}
.dark .mini-card { border-color: #334155; }
.mini-title { margin: 0; font-size: 0.88rem; font-weight: 650; }
.mini-meta { margin: 0.2rem 0 0; font-size: 0.78rem; color: #64748b; }

.provision {
  margin-top: 1rem;
  padding-top: 0.85rem;
  border-top: 1px solid #e2e8f0;
}
.dark .provision { border-top-color: #334155; }
.provision-row,
.install-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.55rem;
  align-items: flex-end;
}
.provision-row select,
.provision-row input { flex: 1 1 10rem; max-width: 100%; }

.env-layout {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 900px) {
  .env-layout {
    grid-template-columns: minmax(12rem, 15rem) minmax(0, 1fr);
    align-items: start;
  }
}
.env-picker ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.env-item {
  width: 100%;
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  background: transparent;
  padding: 0.55rem 0.65rem;
  cursor: pointer;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.dark .env-item { border-color: #334155; }
.env-item.on,
.env-item:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}
.dark .env-item.on,
.dark .env-item:hover { background: #1e293b; }
.env-meta,
.env-stack { font-size: 0.72rem; color: #64748b; }
.env-stack {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-title { margin: 0; font-size: 1.05rem; font-weight: 650; }
.env-stack-line { margin: 0.45rem 0 0; font-size: 0.8rem; color: #64748b; }
.path {
  margin: 0.35rem 0 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  color: #94a3b8;
  line-height: 1.35;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.85rem;
}
.btn,
.btn-primary {
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #fff;
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
}
.dark .btn { background: #0f172a; border-color: #475569; color: #e2e8f0; }
.btn:disabled,
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.warn { border-color: #f59e0b; color: #92400e; }
.btn.ok { border-color: #34d399; color: #065f46; }
.btn.danger { border-color: #f87171; color: #b91c1c; }
.btn-primary {
  border: 0;
  background: #1e3a5f;
  color: #fff;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.9rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid #e2e8f0;
}
.dark .tabs { border-bottom-color: #334155; }
.tabs button {
  border: 0;
  background: transparent;
  border-radius: 0.4rem;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 650;
  color: #64748b;
  cursor: pointer;
}
.tabs button.on {
  background: #0f172a;
  color: #fff;
}
.dark .tabs button.on {
  background: #f8fafc;
  color: #0f172a;
}

.tab-body {
  margin-top: 0.85rem;
  font-size: 0.875rem;
  min-width: 0;
}
.checks {
  list-style: none;
  margin: 0.55rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.checks li {
  display: grid;
  grid-template-columns: minmax(5rem, 8rem) minmax(0, 1fr);
  gap: 0.5rem;
  font-size: 0.78rem;
}
@media (max-width: 520px) {
  .checks li { grid-template-columns: minmax(0, 1fr); }
}
.check-key { font-weight: 650; color: #475569; }
.check-val {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}
.progress-box,
.log-box {
  margin: 0.55rem 0 0;
  max-height: 16rem;
  overflow: auto;
  border-radius: 0.55rem;
  background: #020617;
  color: #e2e8f0;
  padding: 0.65rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  line-height: 1.4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.log-box p { margin: 0 0 0.25rem; }
.log-src { color: #94a3b8; }
.install-row label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #64748b;
  min-width: 0;
  flex: 1 1 12rem;
}
.audit {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 14rem;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.audit li {
  display: grid;
  grid-template-columns: minmax(7rem, 9.5rem) minmax(0, 1fr);
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #475569;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid #f1f5f9;
}
.dark .audit li { border-bottom-color: #1e293b; color: #94a3b8; }
@media (max-width: 560px) {
  .audit li { grid-template-columns: minmax(0, 1fr); }
}
.when { color: #94a3b8; white-space: nowrap; }
</style>
