<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { platformAdminApi } from '@/api'

type CapacityDashboard = {
  display_name: string
  hostname: string
  checked_at?: string | null
  live: {
    cpu_percent?: number
    ram_percent?: number
    ram_used_gb?: number
    ram_total_gb?: number
    disk_percent?: number
    disk_used_gb?: number
    disk_free_gb?: number
    load_average?: number[]
    uptime_seconds?: number
    process_count?: number
  }
  policy: {
    cpu?: {
      total?: number
      system_reserve?: number
      committed?: number
      available?: number
      actual_percent?: number
    }
    ram?: {
      total_gb?: number
      system_reserve_gb?: number
      committed_gb?: number
      available_gb?: number
      actual_used_gb?: number
      actual_percent?: number
    }
    storage?: {
      total_gb?: number
      system_reserve_gb?: number
      committed_gb?: number
      available_gb?: number
      actual_used_gb?: number
      actual_free_gb?: number
      actual_percent?: number
      min_free_gb?: number
    }
    note?: string
  }
  counts: Record<string, number>
  ops: Record<string, number>
  host_pressure: { level?: string; used_pct?: number; free_gb?: number }
  selling_paused?: boolean
  note?: string
}

const dash = ref<CapacityDashboard | null>(null)
const loading = ref(true)
const error = ref('')

function fmtUptime(sec?: number) {
  if (sec == null || !Number.isFinite(sec)) return '—'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function pctBar(n?: number) {
  return Math.min(100, Math.max(0, Math.round(n || 0)))
}

const load1 = computed(() => dash.value?.live?.load_average?.[0] ?? 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listCapacity()
    dash.value = data as CapacityDashboard
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load capacity.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <DashboardLayout>
    <div class="cap">
      <header class="top">
        <div>
          <p class="kicker">Hosting operations</p>
          <h1>{{ dash?.display_name || 'Shared Node 01' }}</h1>
          <p class="lede">
            {{ dash?.hostname || '—' }}
            <span v-if="dash?.selling_paused" class="pill warn">Selling paused</span>
            <span v-else class="pill ok">Accepting packs</span>
          </p>
        </div>
        <button type="button" class="btn" @click="load">Refresh</button>
      </header>

      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="error" class="err">{{ error }}</p>

      <template v-else-if="dash">
        <section class="grid live">
          <article>
            <p class="label">CPU</p>
            <p class="value">{{ dash.live.cpu_percent ?? '—' }}%</p>
            <div class="bar"><i :style="{ width: pctBar(dash.live.cpu_percent) + '%' }" /></div>
          </article>
          <article>
            <p class="label">RAM</p>
            <p class="value">{{ dash.live.ram_percent ?? '—' }}%</p>
            <p class="hint">{{ dash.live.ram_used_gb }} / {{ dash.live.ram_total_gb }} GB live</p>
            <div class="bar"><i :style="{ width: pctBar(dash.live.ram_percent) + '%' }" /></div>
          </article>
          <article>
            <p class="label">Disk</p>
            <p class="value">{{ dash.live.disk_percent ?? '—' }}%</p>
            <p class="hint">{{ dash.live.disk_free_gb }} GB free</p>
            <div class="bar"><i :style="{ width: pctBar(dash.live.disk_percent) + '%' }" /></div>
          </article>
          <article>
            <p class="label">Load</p>
            <p class="value">{{ load1 }}</p>
            <p class="hint">1 / 5 / 15 — {{ (dash.live.load_average || []).join(' · ') || '—' }}</p>
          </article>
          <article>
            <p class="label">Uptime</p>
            <p class="value">{{ fmtUptime(dash.live.uptime_seconds) }}</p>
            <p class="hint">{{ dash.live.process_count ?? 0 }} processes</p>
          </article>
        </section>

        <section class="panel">
          <h2>Capacity policy</h2>
          <p class="muted">{{ dash.policy.note || dash.note }}</p>
          <div class="policy">
            <div>
              <h3>CPU</h3>
              <dl>
                <div><dt>Total</dt><dd>{{ dash.policy.cpu?.total }} vCPU</dd></div>
                <div><dt>System reserve</dt><dd>{{ dash.policy.cpu?.system_reserve }}</dd></div>
                <div><dt>Committed</dt><dd>{{ Number(dash.policy.cpu?.committed || 0).toFixed(2) }}</dd></div>
                <div><dt>Available</dt><dd>{{ Number(dash.policy.cpu?.available || 0).toFixed(2) }}</dd></div>
                <div><dt>Actual use</dt><dd>{{ dash.policy.cpu?.actual_percent }}%</dd></div>
              </dl>
            </div>
            <div>
              <h3>RAM</h3>
              <dl>
                <div><dt>Total</dt><dd>{{ dash.policy.ram?.total_gb }} GB</dd></div>
                <div><dt>System reserve</dt><dd>{{ dash.policy.ram?.system_reserve_gb }} GB</dd></div>
                <div><dt>Committed</dt><dd>{{ Number(dash.policy.ram?.committed_gb || 0).toFixed(2) }} GB</dd></div>
                <div><dt>Available</dt><dd>{{ Number(dash.policy.ram?.available_gb || 0).toFixed(2) }} GB</dd></div>
                <div><dt>Actual use</dt><dd>{{ dash.policy.ram?.actual_used_gb }} GB ({{ dash.policy.ram?.actual_percent }}%)</dd></div>
              </dl>
            </div>
            <div>
              <h3>Disk</h3>
              <dl>
                <div><dt>Total</dt><dd>{{ dash.policy.storage?.total_gb }} GB</dd></div>
                <div><dt>System reserve</dt><dd>{{ dash.policy.storage?.system_reserve_gb }} GB</dd></div>
                <div><dt>Committed</dt><dd>{{ dash.policy.storage?.committed_gb }} GB</dd></div>
                <div><dt>Available</dt><dd>{{ dash.policy.storage?.available_gb }} GB</dd></div>
                <div><dt>Actual free</dt><dd>{{ dash.policy.storage?.actual_free_gb }} GB</dd></div>
              </dl>
            </div>
          </div>
        </section>

        <section class="grid counts">
          <article v-for="(label, key) in {
            customers: 'Customers',
            environments: 'Hosting environments',
            applications: 'Applications',
            databases: 'Databases',
            mailboxes: 'Mailboxes',
          }" :key="key">
            <p class="label">{{ label }}</p>
            <p class="value">{{ dash.counts[key] ?? 0 }}</p>
          </article>
        </section>

        <section class="grid ops">
          <article v-for="(label, key) in {
            provisioning_jobs: 'Provisioning jobs',
            failed_provisioning: 'Failed provisioning',
            ssl_problems: 'SSL problems',
            backup_problems: 'Backup problems',
            disk_alerts: 'Disk alerts',
            suspended_accounts: 'Suspended accounts',
          }" :key="key">
            <p class="label">{{ label }}</p>
            <p class="value" :class="{ hot: (dash.ops[key] || 0) > 0 && key !== 'provisioning_jobs' }">
              {{ dash.ops[key] ?? 0 }}
            </p>
          </article>
        </section>

        <p class="muted foot">
          Host pressure: {{ dash.host_pressure.level || 'ok' }}
          · {{ dash.host_pressure.used_pct }}% used
          · {{ dash.host_pressure.free_gb }} GB free
          <template v-if="dash.checked_at"> · checked {{ dash.checked_at }}</template>
        </p>
      </template>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.cap {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.25rem 1rem 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem;
}
.kicker {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0f766e;
}
h1 {
  margin: 0.2rem 0 0;
  font-size: 1.45rem;
  color: #0f172a;
}
.lede {
  margin: 0.35rem 0 0;
  color: #64748b;
  font-size: 0.9rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.pill {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
}
.pill.ok { background: #ccfbf1; color: #0f766e; }
.pill.warn { background: #ffedd5; color: #c2410c; }
.btn {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 0.55rem;
  padding: 0.45rem 0.9rem;
  font-size: 0.86rem;
  cursor: pointer;
}
.muted { color: #64748b; font-size: 0.88rem; }
.err { color: #dc2626; }
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
}
@media (min-width: 800px) {
  .live { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .counts, .ops { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
article, .panel {
  border: 1px solid #e2e8f0;
  border-radius: 0.85rem;
  background: #fff;
  padding: 0.85rem 0.95rem;
}
.label {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #64748b;
}
.value {
  margin: 0.25rem 0 0;
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
}
.value.hot { color: #c2410c; }
.hint { margin: 0.15rem 0 0; font-size: 0.75rem; color: #94a3b8; }
.bar {
  margin-top: 0.55rem;
  height: 0.35rem;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: #0f766e;
}
.panel h2 {
  margin: 0;
  font-size: 1rem;
  color: #0f172a;
}
.policy {
  display: grid;
  gap: 1rem;
  margin-top: 0.85rem;
}
@media (min-width: 800px) {
  .policy { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.policy h3 {
  margin: 0 0 0.45rem;
  font-size: 0.85rem;
  color: #0f766e;
}
dl { margin: 0; display: grid; gap: 0.35rem; }
dl > div {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.82rem;
}
dt { color: #64748b; }
dd { margin: 0; font-weight: 650; color: #0f172a; }
.foot { margin: 0; }
</style>
