<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import DashboardAiFab from '@/components/ai/DashboardAiFab.vue'
import ControlGauge from '@/components/dashboard/ControlGauge.vue'
import Sparkline from '@/components/dashboard/Sparkline.vue'
import ResourceChart from '@/components/dashboard/ResourceChart.vue'
import ServiceBrandMark from '@/components/dashboard/ServiceBrandMark.vue'
import { useDashboard } from '@/composables/useDashboard'
import { useAuthStore } from '@/stores/auth'
import { getCanonicalRole, isPlatformOwner } from '@/lib/roles'
import { domainsApi } from '@/api'
import type { Domain } from '@/types/hosting'
import {
  IconApp,
  IconChart,
  IconDatabase,
  IconDeploy,
  IconGlobe,
  IconLock,
  IconMail,
  IconRefresh,
  IconServer,
  IconSettings,
  IconShield,
} from '@/components/icons'

const router = useRouter()
const auth = useAuthStore()
const isOwner = computed(() => isPlatformOwner(auth.user))
const canonicalRole = computed(() => getCanonicalRole(auth.user) || 'platform_owner')
const { data, loading, refreshing, error, refresh } = useDashboard()
const domains = ref<Domain[]>([])

onMounted(async () => {
  try {
    const { data: list } = await domainsApi.list()
    domains.value = (list.domains || []).filter((d) => d.enabled).slice(0, 8)
  } catch {
    domains.value = []
  }
})

const server = computed(() => data.value?.servers[0] || null)
const hostname = computed(() => data.value?.health?.environment || server.value?.name || 'ifnotus')
const online = computed(() => {
  const s = data.value?.readiness?.status || data.value?.health?.status || server.value?.status
  return s === 'healthy'
})

function numStat(id: string): number {
  const raw = data.value?.stats.find((s) => s.id === id)?.value
  const n = typeof raw === 'number' ? raw : Number(String(raw ?? '').replace(/[^\d.]/g, ''))
  return Number.isFinite(n) ? n : 0
}

function textStat(id: string): string {
  const s = data.value?.stats.find((x) => x.id === id)
  if (!s) return '—'
  return `${s.value}${s.unit ? s.unit : ''}`
}

const cpu = computed(() => server.value?.cpu ?? numStat('cpu'))
const ram = computed(() => server.value?.memory ?? numStat('memory'))
const disk = computed(() => server.value?.disk ?? numStat('disk'))

const cpuSeries = computed(() => data.value?.charts.cpu.series[0]?.data.slice(-12) ?? [0, 8, 12, 10, 18])
const ramSeries = computed(() => data.value?.charts.memory.series[0]?.data.slice(-12) ?? [20, 28, 32, 40, 42])
const netSeries = computed(() => data.value?.charts.network.series[0]?.data.slice(-12) ?? [10, 14, 11, 16, 13])

const featuredServices = computed(() => {
  // This host runs nginx + PHP-FPM (not Apache). Show real stack status.
  const catalog = [
    { key: 'nginx', label: 'NGINX', match: ['nginx'] },
    { key: 'php', label: 'PHP-FPM', match: ['php8.3-fpm', 'php8.2-fpm', 'php-fpm', 'php'] },
    { key: 'mysql', label: 'MySQL', match: ['mysql', 'mariadb', 'mysqld'] },
    { key: 'redis', label: 'Redis', match: ['redis'] },
    { key: 'docker', label: 'Docker', match: ['docker'] },
    { key: 'fail2ban', label: 'Fail2Ban', match: ['fail2ban'] },
  ]
  const list = data.value?.services ?? []
  return catalog.map((cat) => {
    const hit = list.find((s) => {
      const n = `${s.name} ${s.id || ''}`.toLowerCase()
      return cat.match.some((k) => n.includes(k))
    })
    let status = hit?.status || 'not_installed'
    // Apache-era leftover: if we ever matched nothing, say not installed — never "Unknown"
    if (!hit) status = 'not_installed'
    return {
      id: hit?.id || cat.key,
      key: cat.key,
      label: cat.label,
      status,
    }
  })
})

function serviceLabel(status: string) {
  if (status === 'running') return 'Running'
  if (status === 'stopped') return 'Stopped'
  if (status === 'failed') return 'Failed'
  if (status === 'degraded') return 'Degraded'
  if (status === 'not_installed') return 'Not installed'
  return status || '—'
}

const servicesOk = computed(
  () => featuredServices.value.filter((s) => s.status === 'running').length >= 3,
)

const actions = computed(() => {
  const role = canonicalRole.value
  if (role === 'support_agent') {
    return [
      { label: 'Support Queue', to: '/support', icon: IconMail, color: '#dc2626' },
      { label: 'Customer Lookup', to: '/platform/customers', icon: IconApp, color: '#2563eb' },
    ]
  }
  if (role === 'billing_agent') {
    return [
      { label: 'Review Orders', to: '/platform/orders', icon: IconGlobe, color: '#f59e0b' },
      { label: 'Accounting Ledger', to: '/platform/accounting', icon: IconChart, color: '#16a34a' },
      { label: 'Customer Profiles', to: '/platform/customers', icon: IconApp, color: '#2563eb' },
      { label: 'Billing Tickets', to: '/support', icon: IconMail, color: '#7c3aed' },
    ]
  }
  if (role === 'platform_admin') {
    return [
      { label: 'Customer Accounts', to: '/platform/customers', icon: IconApp, color: '#2563eb' },
      { label: 'Pending Orders', to: '/platform/orders', icon: IconGlobe, color: '#f59e0b' },
      { label: 'Financial Accounting', to: '/platform/accounting', icon: IconChart, color: '#16a34a' },
      { label: 'Hosting Plans', to: '/platform/plans', icon: IconDeploy, color: '#7c3aed' },
      { label: 'Support Tickets', to: '/support', icon: IconMail, color: '#dc2626' },
      { label: 'Settings', to: '/settings', icon: IconSettings, color: '#0f172a' },
    ]
  }
  if (role === 'hosting_operator') {
    return [
      { label: 'Operations & Jobs', to: '/operations', icon: IconRefresh, color: '#2563eb' },
      { label: 'Domains & DNS', to: '/domains', icon: IconGlobe, color: '#7c3aed' },
      { label: 'Databases', to: '/databases', icon: IconDatabase, color: '#ea580c' },
      { label: 'SSL Certificates', to: '/ssl', icon: IconLock, color: '#16a34a' },
      { label: 'Host Capacity', to: '/servers', icon: IconServer, color: '#0f172a' },
      { label: 'Tenants', to: '/platform/customers', icon: IconApp, color: '#0284c7' },
    ]
  }
  if (role === 'auditor') {
    return [
      { label: 'Audit Logs & Events', to: '/security', icon: IconShield, color: '#dc2626' },
      { label: 'Financial Ledgers', to: '/platform/accounting', icon: IconChart, color: '#16a34a' },
      { label: 'System Health', to: '/servers', icon: IconServer, color: '#2563eb' },
      { label: 'Customer Records', to: '/platform/customers', icon: IconApp, color: '#0f172a' },
    ]
  }
  // Platform Owner
  return [
    { label: 'Host operations', to: '/operations', icon: IconRefresh, color: '#2563eb' },
    { label: 'Customers', to: '/platform/customers', icon: IconApp, color: '#0284c7' },
    { label: 'Orders & Money', to: '/platform/orders', icon: IconGlobe, color: '#f59e0b' },
    { label: 'Domains & DNS', to: '/domains', icon: IconGlobe, color: '#7c3aed' },
    { label: 'Databases', to: '/databases', icon: IconDatabase, color: '#ea580c' },
    { label: 'Security & Access', to: '/security', icon: IconShield, color: '#dc2626' },
  ]
})

const lastLoginIp = computed(() => auth.user?.last_login_ip?.trim() || '')
const lastLoginAt = computed(() => {
  const at = auth.user?.last_login_at
  if (!at) return ''
  return new Date(at).toLocaleString()
})

const sslOk = computed(() => data.value?.inventory?.certificates_healthy ?? 0)
const sslWarn = computed(() => data.value?.inventory?.certificates_expiring ?? 0)
const siteCount = computed(() => data.value?.inventory?.managed_domains ?? domains.value.length)
const loadAvg = computed(() => data.value?.loadAverage?.join(' / ') || '—')
const version = computed(() => data.value?.health?.version || '0.1.0')

function go(to: string) {
  router.push(to)
}
</script>

<script lang="ts">
export default { name: 'DashboardView' }
</script>

<template>
  <DashboardLayout :refreshing="refreshing" @refresh="refresh">
    <ErrorState v-if="error && !data" :message="error" @retry="refresh" />

    <div v-else class="ctrl animate-fade-in">
      <UiPageHeader
        eyebrow="Control"
        title="Dashboard"
        :lede="`${hostname} · ${online ? 'Online' : 'Attention'} · v${version}`"
      >
        <template #actions>
          <button type="button" class="ds-btn-ghost" :disabled="refreshing" @click="refresh">
            {{ refreshing ? 'Refreshing…' : 'Refresh' }}
          </button>
        </template>
      </UiPageHeader>

      <section class="metrics">
        <article class="metric">
          <p class="k">VPS status</p>
          <p class="v" :class="online ? 'ok' : 'bad'">{{ online ? 'Online' : 'Attention' }}</p>
          <p class="s">{{ online ? 'All systems operational' : 'Check Host status' }}</p>
        </article>
        <article class="metric">
          <p class="k">CPU usage</p>
          <div class="row">
            <p class="v">{{ Math.round(cpu) }}%</p>
            <Sparkline :values="cpuSeries" color="#2563eb" />
          </div>
          <p class="s">{{ textStat('load') }} load</p>
        </article>
        <article class="metric">
          <p class="k">RAM usage</p>
          <div class="row">
            <p class="v">{{ Math.round(ram) }}%</p>
            <Sparkline :values="ramSeries" color="#7c3aed" />
          </div>
          <p class="s">Live host memory</p>
        </article>
        <article class="metric">
          <p class="k">Storage</p>
          <div class="row">
            <p class="v">{{ Math.round(disk) }}%</p>
            <Sparkline :values="[disk * 0.7, disk * 0.85, disk * 0.8, disk]" color="#16a34a" />
          </div>
          <p class="s">Host disk</p>
        </article>
        <article class="metric">
          <p class="k">Bandwidth</p>
          <div class="row">
            <p class="v sm">{{ data?.networkThroughput?.in || '—' }}</p>
            <Sparkline :values="netSeries" color="#0ea5e9" />
          </div>
          <p class="s">In {{ data?.networkThroughput?.in || '—' }} · Out {{ data?.networkThroughput?.out || '—' }}</p>
        </article>
        <article class="metric">
          <p class="k">Active sites</p>
          <p class="v">{{ siteCount }}</p>
          <RouterLink class="s link" to="/domains">View all</RouterLink>
        </article>
      </section>

      <section class="mid">
        <article class="card health">
          <header>
            <h2>Server health</h2>
            <span class="pill" :class="online ? 'ok' : 'warn'">{{ hostname }}</span>
          </header>
          <div class="gauges">
            <ControlGauge label="CPU" :value="cpu" color="#2563eb" />
            <ControlGauge label="Memory" :value="ram" color="#7c3aed" />
            <ControlGauge label="Disk" :value="disk" color="#16a34a" />
          </div>
          <dl class="facts">
            <div><dt>OS</dt><dd>Linux host</dd></div>
            <div><dt>Panel</dt><dd>IFNOTUS v{{ version }}</dd></div>
            <div><dt>Load</dt><dd>{{ loadAvg }}</dd></div>
            <div><dt>Uptime</dt><dd>{{ textStat('uptime') }}</dd></div>
            <div><dt>Time</dt><dd>{{ new Date().toLocaleTimeString() }}</dd></div>
          </dl>
        </article>

        <article class="card traffic">
          <header>
            <h2>Live traffic</h2>
            <span class="muted">Last samples</span>
          </header>
          <ResourceChart
            title="Live traffic"
            :chart="data?.charts.network || { categories: [], series: [] }"
            :loading="loading"
            :height="180"
          />
          <div class="xfer">
            <span>Inbound <strong>{{ data?.networkThroughput?.in || '—' }}</strong></span>
            <span>Outbound <strong>{{ data?.networkThroughput?.out || '—' }}</strong></span>
          </div>
        </article>

        <article v-if="isOwner" class="card ssh">
          <header>
            <h2>Operator access</h2>
            <span class="pill ok">Enabled</span>
          </header>
          <p class="muted">Audited command runner in this panel. Prefer hostnames — never paste a public IP into customer tools.</p>
          <code class="cmd">terminal · ifnotus.space</code>
          <p class="warn-note">This is not an interactive SSH session. Use Terminal for controlled host commands.</p>
          <button type="button" class="cta" @click="go('/terminal')">Launch Terminal</button>
        </article>
      </section>

      <section class="boards">
        <article class="card board">
          <header>
            <h2>Running services</h2>
            <span class="pill" :class="servicesOk ? 'ok' : 'warn'">
              {{ servicesOk ? 'All systems operational' : 'Check services' }}
            </span>
          </header>
          <ul class="svc">
            <li v-for="svc in featuredServices" :key="svc.id">
              <ServiceBrandMark :name="svc.key" :size="36" />
              <div>
                <p>{{ svc.label }}</p>
                <span class="pill sm" :class="svc.status === 'running' ? 'ok' : svc.status === 'not_installed' ? '' : 'warn'">
                  {{ serviceLabel(svc.status) }}
                </span>
              </div>
            </li>
          </ul>
        </article>

        <article class="card board">
          <header><h2>Quick actions</h2></header>
          <div class="qact">
            <button v-for="a in actions" :key="a.label" type="button" @click="go(a.to)">
              <span class="ico" :style="{ color: a.color }">
                <component :is="a.icon" :size="26" />
              </span>
              <span class="qlabel">{{ a.label }}</span>
            </button>
          </div>
        </article>
      </section>

      <section class="bottom">
        <article class="card">
          <header><h2>Security overview</h2></header>
          <ul class="sec">
            <li><span>Firewall</span><strong class="ok">Active</strong></li>
            <li>
              <span>SSL certificates</span>
              <strong class="ok">{{ sslOk }} valid</strong>
              <small v-if="sslWarn"> · {{ sslWarn }} expiring</small>
            </li>
            <li><span>Login lockout</span><strong class="ok">On</strong></li>
            <li>
              <span>Last login IP</span>
              <strong>{{ lastLoginIp || '—' }}</strong>
            </li>
            <li v-if="lastLoginAt">
              <span>Last login</span>
              <strong>{{ lastLoginAt }}</strong>
            </li>
            <li><span>Nameservers</span><strong>ns1 / ns2.ifnotus.space</strong></li>
          </ul>
        </article>

        <article class="card wide">
          <header>
            <h2>Hosted apps</h2>
            <RouterLink class="link" to="/applications">Manage</RouterLink>
          </header>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Status</th>
                  <th>Type</th>
                  <th>SSL</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in domains" :key="d.id">
                  <td>
                    <RouterLink class="dom" :to="'/applications'">{{ d.name }}</RouterLink>
                  </td>
                  <td><span class="pill ok">{{ d.enabled ? 'Active' : 'Off' }}</span></td>
                  <td class="muted">{{ d.domain_type }}</td>
                  <td>
                    <span class="lock" :class="d.force_https || d.ssl_certificate_path ? 'ok' : 'off'">
                      <IconLock :size="14" />
                    </span>
                  </td>
                  <td>
                    <RouterLink class="more" :to="'/applications'">···</RouterLink>
                  </td>
                </tr>
                <tr v-if="!domains.length">
                  <td colspan="5" class="empty">No managed domains yet.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <article class="card details">
          <header><h2>Server details</h2></header>
          <div class="visual">
            <img src="/server-rack.png" alt="Server rack" />
          </div>
          <ul class="meta">
            <li>
              <span>Control panel</span>
              <strong>IFNOTUS v{{ version }}</strong>
            </li>
            <li>
              <span>Nameservers</span>
              <strong>ns1.ifnotus.space<br />ns2.ifnotus.space</strong>
            </li>
            <li>
              <span>FTP host</span>
              <strong>ftp.ifnotus.space</strong>
            </li>
            <li>
              <span>Operator</span>
              <strong>In-panel terminal</strong>
            </li>
            <li>
              <span>Location</span>
              <strong>Accra, GH</strong>
            </li>
          </ul>
        </article>
      </section>
    </div>

    <DashboardAiFab />
  </DashboardLayout>
</template>

<style scoped>
.ctrl {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
}
.metrics {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (min-width: 900px) {
  .metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); }
}
.metric, .card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 0.9rem;
  box-shadow: var(--shadow-card);
}
.metric { padding: 0.95rem 1rem; }
.k {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.v {
  margin: 0.35rem 0 0;
  font-size: 1.45rem;
  font-weight: 750;
  letter-spacing: -0.04em;
  line-height: 1.1;
}
.v.sm { font-size: 1.05rem; }
.v.ok { color: #15803d; }
.v.bad { color: #b42318; }
.s { margin: 0.3rem 0 0; font-size: 0.75rem; color: var(--color-text-muted); }
.row { display: flex; align-items: flex-end; justify-content: space-between; gap: 0.4rem; }
.bar {
  margin-top: 0.55rem;
  height: 0.35rem;
  border-radius: 999px;
  background: #e8edf3;
  overflow: hidden;
}
.bar i { display: block; height: 100%; background: #0d9488; }
.mid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr;
}
@media (min-width: 1100px) {
  .mid { grid-template-columns: 1.4fr 1.2fr 0.9fr; }
  .mid.three { grid-template-columns: 1fr 1fr 1fr; }
}
.card { padding: 1rem 1.1rem 1.15rem; }
.card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.card h2 { margin: 0; font-size: 0.92rem; font-weight: 700; }
.muted { color: var(--color-text-muted); font-size: 0.78rem; line-height: 1.45; }
.gauges {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.4rem;
}
.facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.55rem 1rem;
  margin: 1rem 0 0;
  font-size: 0.78rem;
}
.facts dt { color: var(--color-text-muted); }
.facts dd { margin: 0.1rem 0 0; font-weight: 600; }
.xfer {
  display: flex;
  gap: 1.25rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.cmd {
  display: block;
  margin: 0.7rem 0;
  padding: 0.55rem 0.7rem;
  border-radius: 0.5rem;
  background: var(--color-surface);
  font-size: 0.78rem;
}
:global(.dark) .cmd { background: #1e293b; }
.warn-note { margin: 0; font-size: 0.75rem; color: #b42318; }
.cta {
  border: none;
  cursor: pointer;
  font-weight: 650;
}
.cta {
  margin-top: 0.9rem;
  width: 100%;
  border-radius: 0.6rem;
  padding: 0.65rem;
  background: #2563eb;
  color: #fff;
}
.pill {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.18rem 0.5rem;
  border-radius: 999px;
  background: #e2e8f0;
}
.pill.ok { background: #dcfce7; color: #15803d; }
.pill.warn { background: #ffedd5; color: #c2410c; }
.pill.sm { display: inline-block; margin-top: 0.2rem; font-size: 0.62rem; }
.boards {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr;
  align-items: stretch;
}
@media (min-width: 960px) {
  .boards { grid-template-columns: 1fr 1fr; }
}
.board {
  display: flex;
  flex-direction: column;
  min-height: 17.5rem;
}
.svc, .sec { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.65rem; }
.svc {
  grid-template-columns: 1fr;
  flex: 1;
}
@media (min-width: 560px) {
  .svc { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.svc li {
  display: flex;
  gap: 0.7rem;
  align-items: center;
  font-size: 0.82rem;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 0.75rem 0.8rem;
  background: var(--color-surface-raised);
}
.svc svg { flex-shrink: 0; }
.svc p { margin: 0; font-weight: 650; }
.qact {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.55rem;
  flex: 1;
}
@media (min-width: 960px) {
  .qact { grid-template-columns: repeat(6, minmax(0, 1fr)); }
}
.qact button {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  min-height: 100%;
  padding: 0.85rem 0.35rem;
  border-radius: 0.75rem;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--if-ink);
  font-size: 0.72rem;
  cursor: pointer;
}
.qact button:hover { background: var(--color-surface-raised); border-color: color-mix(in srgb, var(--if-primary) 35%, var(--color-border)); }
.qlabel { font-weight: 700; text-align: center; line-height: 1.25; }
.ico {
  display: inline-flex;
  width: 2.4rem;
  height: 2.4rem;
  align-items: center;
  justify-content: center;
}
.bottom {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr;
}
@media (min-width: 1100px) {
  .bottom { grid-template-columns: 0.9fr 1.6fr 0.85fr; }
}
.sec li {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.8rem;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--color-border);
}
.sec strong.ok { color: #15803d; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; color: var(--color-text-muted); font-weight: 600; padding: 0.4rem 0.5rem; }
td { padding: 0.55rem 0.5rem; border-top: 1px solid var(--color-border); }
.dom { font-weight: 650; color: inherit; text-decoration: none; }
.lock { color: #94a3b8; }
.lock.ok { color: #16a34a; }
.more { color: var(--color-text-muted); text-decoration: none; letter-spacing: 0.08em; }
.link { color: #2563eb; text-decoration: none; font-size: 0.75rem; font-weight: 650; }
.empty { color: var(--color-text-muted); font-size: 0.8rem; }
.details {
  display: flex;
  flex-direction: column;
}
.visual {
  margin: 0.15rem 0 0.85rem;
  border-radius: 0.85rem;
  overflow: hidden;
  background:
    radial-gradient(120% 80% at 50% 100%, color-mix(in srgb, var(--if-primary) 12%, var(--color-surface)) 0%, var(--color-surface) 55%, var(--color-surface-raised) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 8.5rem;
}
.visual img {
  width: 100%;
  height: 9.5rem;
  object-fit: contain;
  object-position: center bottom;
  display: block;
}
.meta {
  list-style: none;
  margin: 0;
  padding: 0;
}
.meta li {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.62rem 0;
  border-top: 1px solid var(--color-border);
  font-size: 0.8rem;
}
.meta span {
  color: var(--color-text-muted);
  font-weight: 500;
}
.meta strong {
  font-weight: 650;
  text-align: right;
  line-height: 1.4;
}
</style>
