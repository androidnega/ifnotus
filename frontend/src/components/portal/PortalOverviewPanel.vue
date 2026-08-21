<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { IconDatabase, IconDeploy, IconFolder, IconGlobe } from '@/components/icons'

const router = useRouter()

const props = defineProps<{
  dash: CustomerDashboard
  activeEnv: CustomerEnvironment | null
  activePlan: HostingPlan | null
  usagePct: number
  usageStatus: '' | 'ok' | 'warning' | 'over'
  usageInfo: string
  healthInfo: string
  firstName?: string
}>()

const emit = defineEmits<{
  openPanel: ['site' | 'billing' | 'ai' | 'support']
  selectEnv: [string]
  openSiteTab: [string]
}>()

const env = computed(() => props.activeEnv)
const plan = computed(() => props.activePlan)

const activeSub = computed(() => {
  const subId = env.value?.subscription_id
  const subs = props.dash.subscriptions || []
  if (subId) return subs.find((s) => s.id === subId) || null
  return subs.find((s) => s.status === 'active') || subs[0] || null
})

function healthLabel(status?: string | null) {
  const s = (status || '').toLowerCase()
  if (s === 'healthy') return 'Online'
  if (s === 'degraded') return 'Needs attention'
  if (s === 'checking') return 'Checking'
  if (s === 'unhealthy' || s === 'offline' || s === 'critical' || s === 'warning') return 'Offline'
  if (env.value?.status === 'suspended') return 'Suspended'
  if (env.value?.status === 'terminated') return 'Closed'
  return 'Unknown'
}

function healthClass(status?: string | null) {
  const s = (status || '').toLowerCase()
  if (env.value?.status === 'suspended' || env.value?.status === 'terminated') return 'bad'
  if (s === 'healthy') return 'ok'
  if (s === 'degraded' || s === 'checking' || s === 'warning') return 'warn'
  if (s === 'unhealthy' || s === 'offline' || s === 'critical') return 'bad'
  return ''
}

function publicSiteUrl(domain: string) {
  return `https://${domain}`
}

function openSite(tab: string) {
  emit('openPanel', 'site')
  emit('openSiteTab', tab)
}

function openFilesManager() {
  const id = env.value?.id
  if (!id) {
    openSite('stack')
    return
  }
  const href = `/account/files?env=${encodeURIComponent(id)}`
  window.open(href, `ifnotus-files-${id}`)
}

function openHostingPanel() {
  const id = env.value?.id
  if (!id) {
    openSite('stack')
    return
  }
  void router.push({ name: 'hosting-panel', params: { environmentId: id } })
}

const spec = computed(() => {
  const e = env.value
  const p = plan.value
  const cpu = formatCpu(e?.cpu_limit ?? p?.cpu_cores ?? 0)
  const ram = formatRamGb(e?.ram_limit_gb ?? p?.ram_gb ?? 0)
  const disk = e?.storage_limit_gb ?? p?.storage_gb ?? 0
  return { cpu, ram, disk }
})

const greeting = computed(() => props.firstName || props.dash.customer.full_name?.split(' ')[0] || 'there')

const pendingOrder = computed(() =>
  (props.dash.orders || []).find((o) =>
    ['pending', 'submitted'].includes(String(o.payment_status || '').toLowerCase()),
  ),
)

const expiresLabel = computed(() => {
  const at = activeSub.value?.expires_at
  if (!at) return null
  return new Date(at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
})
</script>

<template>
  <section class="home">
    <header class="hero">
      <div>
        <h1>Hello, {{ greeting }}</h1>
        <p class="lede">
          <template v-if="env?.domain">Your site and package at a glance.</template>
          <template v-else>Order a package to get your site, SSL, and mailbox tools.</template>
        </p>
      </div>
      <button
        v-if="dash.unread_notifications"
        type="button"
        class="note-pill"
        @click="emit('openPanel', 'support')"
      >
        {{ dash.unread_notifications }} new notice{{ dash.unread_notifications === 1 ? '' : 's' }}
      </button>
    </header>

    <div v-if="!dash.environments.length" class="card empty">
      <p class="kicker">Your account</p>
      <h2>{{ pendingOrder ? 'Finish payment to activate hosting' : 'No hosting yet' }}</h2>
      <p class="hint">
        <template v-if="pendingOrder">
          Pay invoice {{ pendingOrder.invoice_number || pendingOrder.id.slice(0, 8) }}
          ({{ pendingOrder.currency }} {{ pendingOrder.total_price }}). After we confirm Mobile Money,
          your site tools unlock here.
        </template>
        <template v-else>
          This is a normal account. Use Billing → New order to buy hosting (pack + domain in one checkout), then pay the invoice.
        </template>
      </p>
      <button type="button" class="btn-primary" @click="emit('openPanel', 'billing')">
        {{ pendingOrder ? 'Open billing' : 'Billing & new order' }}
      </button>
    </div>

    <template v-else-if="env">
      <div v-if="pendingOrder" class="banner">
        <div>
          <strong>Payment pending</strong>
          <p>Invoice {{ pendingOrder.invoice_number || pendingOrder.id.slice(0, 8) }} ·
            {{ pendingOrder.currency }} {{ pendingOrder.total_price }}</p>
        </div>
        <button type="button" class="btn-ghost" @click="emit('openPanel', 'billing')">Open billing</button>
      </div>

      <div class="layout">
        <article class="card site">
          <div class="site-top">
            <div class="site-copy">
              <p class="kicker">{{ plan?.name || 'Your site' }}</p>
              <h2 class="domain" :title="env.domain || undefined">{{ env.domain || 'Your site' }}</h2>
              <p class="spec">
                {{ spec.cpu }} vCPU · {{ spec.ram }} · {{ spec.disk }} GB disk
              </p>
            </div>
            <span class="status" :class="healthClass(env.health_status)">{{ healthLabel(env.health_status) }}</span>
          </div>

          <div class="meters">
            <div class="meter">
              <div class="disk-row">
                <span>Disk</span>
                <span>{{ Math.min(100, Math.round(usagePct)) }}% of {{ spec.disk }} GB</span>
              </div>
              <div class="bar" :class="usageStatus"><i :style="{ width: Math.min(100, usagePct) + '%' }" /></div>
            </div>
          </div>

          <p class="hint">{{ usageInfo || healthInfo || 'Your site is ready.' }}</p>

          <div class="actions">
            <button type="button" class="btn-primary" @click="openHostingPanel">Manage Hosting</button>
            <a
              v-if="env.domain"
              class="btn-ghost"
              :href="publicSiteUrl(env.domain)"
              target="_blank"
              rel="noopener"
            >Open site</a>
          </div>

          <div v-if="dash.environments.length > 1" class="switch">
            <button
              v-for="item in dash.environments"
              :key="item.id"
              type="button"
              :class="{ on: item.id === env.id }"
              @click="emit('selectEnv', item.id)"
            >
              {{ item.domain || 'Site' }}
            </button>
          </div>
        </article>

        <aside class="side-stack">
          <article class="card compact">
            <p class="kicker">Package</p>
            <p class="compact-title">{{ plan?.name || 'Hosting' }}</p>
            <ul class="facts">
              <li><span>Status</span><strong>{{ activeSub?.status || env.status || '—' }}</strong></li>
              <li v-if="expiresLabel"><span>Renews / expires</span><strong>{{ expiresLabel }}</strong></li>
              <li>
                <span>AI tokens</span>
                <strong>{{ (dash.credits?.tokens_remaining ?? (dash.credits?.credits_remaining ?? 0) * 12000).toLocaleString() }}</strong>
              </li>
            </ul>
            <button type="button" class="linkish" @click="emit('openPanel', 'billing')">Billing &amp; renewals</button>
          </article>

          <article class="card compact">
            <p class="kicker">Need help?</p>
            <p class="compact-title">Support</p>
            <p class="hint tight">Ask IFNOTUS about your site, email, or invoice — no terminal needed.</p>
            <button type="button" class="linkish" @click="emit('openPanel', 'support')">Open tickets</button>
          </article>
        </aside>
      </div>

      <div class="shortcuts">
        <button type="button" @click="openSite('stack')"><IconDeploy :size="18" /> Apps</button>
        <button type="button" @click="openFilesManager"><IconFolder :size="18" /> Files</button>
        <button type="button" @click="openSite('database')"><IconDatabase :size="18" /> Database</button>
        <button type="button" @click="openSite('protect')"><IconGlobe :size="18" /> Domain</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  min-width: 0;
}
.hero {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}
.hero h1 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: clamp(1.45rem, 2.4vw, 1.85rem);
  font-weight: 700;
  letter-spacing: -0.035em;
  color: var(--p-ink);
}
.lede {
  margin: 0.35rem 0 0;
  max-width: 34rem;
  color: var(--p-muted);
  font-size: 0.92rem;
  line-height: 1.45;
}
.note-pill {
  border: 1px solid color-mix(in srgb, var(--p-accent) 28%, var(--p-border));
  background: var(--p-accent-soft);
  color: var(--p-accent);
  border-radius: 999px;
  padding: 0.35rem 0.8rem;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
}
.layout {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1.55fr) minmax(14rem, 0.85fr);
    align-items: start;
  }
}
.side-stack {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.card {
  background: var(--p-surface);
  border: 1px solid var(--p-border);
  border-radius: 1.15rem;
  padding: 1.25rem 1.35rem;
  box-shadow: 0 1px 2px rgb(22 26 29 / 0.03), 0 8px 20px rgb(22 26 29 / 0.03);
  min-width: 0;
}
.card.compact { padding: 1.05rem 1.1rem; }
.card.empty { max-width: 28rem; }
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.85rem 1.05rem;
  border-radius: 0.95rem;
  border: 1px solid #f6d9a8;
  background: #fff8eb;
  color: #7a4b0a;
}
.banner p { margin: 0.15rem 0 0; font-size: 0.84rem; }
.kicker {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent);
}
.domain,
.compact-title,
h2 {
  margin: 0.25rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--p-ink);
}
.domain {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  font-size: clamp(1.05rem, 2vw, 1.35rem);
}
.spec, .hint {
  margin: 0.4rem 0 0;
  color: var(--p-muted);
  font-size: 0.88rem;
  line-height: 1.45;
}
.hint.tight { margin-top: 0.35rem; }
.site-top {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}
.site-copy { min-width: 0; flex: 1; }
.status {
  flex-shrink: 0;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}
.status.ok { background: #e7f8ee; color: #0f7a45; }
.status.warn { background: #fff4e5; color: #b54708; }
.status.bad { background: #feeceb; color: #b42318; }
.meters { margin-top: 1.1rem; }
.disk-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--p-muted);
}
.bar {
  margin-top: 0.4rem;
  height: 0.42rem;
  border-radius: 999px;
  background: var(--p-border);
  overflow: hidden;
}
.bar i { display: block; height: 100%; background: var(--p-accent); }
.bar.warning i { background: #d97706; }
.bar.over i { background: #b42318; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1.15rem; }
.btn-primary, .btn-ghost {
  border-radius: 0.6rem;
  font-size: 0.86rem;
  font-weight: 650;
  padding: 0.55rem 1rem;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.btn-primary { border: none; background: var(--p-accent); color: #fff; }
.btn-ghost { border: 1px solid var(--p-border); background: transparent; color: var(--p-ink); }
.facts {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.facts li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.82rem;
  color: var(--p-muted);
}
.facts strong { color: var(--p-ink); font-weight: 650; text-align: right; }
.linkish {
  margin-top: 0.85rem;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--p-accent);
  font-size: 0.84rem;
  font-weight: 700;
  cursor: pointer;
  text-align: left;
}
.switch { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 1rem; }
.switch button {
  border: 1px solid var(--p-border);
  background: transparent;
  border-radius: 999px;
  padding: 0.25rem 0.7rem;
  font-size: 0.75rem;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.switch button.on {
  border-color: var(--p-accent);
  background: var(--p-accent-soft);
  color: var(--p-accent);
  font-weight: 700;
}
.shortcuts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
}
@media (min-width: 640px) {
  .shortcuts { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
.shortcuts button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  padding: 0.85rem 0.6rem;
  border: 1px solid var(--p-border);
  border-radius: 0.95rem;
  background: var(--p-surface);
  font-size: 0.84rem;
  font-weight: 650;
  color: var(--p-ink);
  cursor: pointer;
}
.shortcuts button:hover {
  border-color: color-mix(in srgb, var(--p-accent) 40%, var(--p-border));
}
</style>
