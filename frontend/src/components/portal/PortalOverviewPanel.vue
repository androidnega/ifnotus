<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import {
  barClassForTier,
  formatUpdatedAt,
  processPct,
  resourceStatusClass,
  resourceStatusLabel,
  resourceTier,
  type EnvUsageSnapshot,
} from '@/lib/resourceUsage'
import { tenantCpanelUrl, tenantMailUrl } from '@/lib/platformHosts'
import { openHostingFromAccount } from '@/lib/hostingDeepLink'
import {
  IconGlobe,
  IconServer,
  IconActivity,
  IconChevron,
} from '@/components/icons'

const props = defineProps<{
  dash: CustomerDashboard
  activeEnv: CustomerEnvironment | null
  activePlan: HostingPlan | null
  usagePct: number
  usageStatus: '' | 'ok' | 'warning' | 'over'
  usageInfo: string
  usageSnapshot?: EnvUsageSnapshot | null
  healthInfo: string
  firstName?: string
}>()

const emit = defineEmits<{
  openPanel: ['site' | 'billing' | 'ai' | 'support']
  selectEnv: [string]
  openSiteTab: [string]
}>()

const router = useRouter()
const copiedKey = ref<string | null>(null)

function copyToClip(key: string, text: string) {
  if (!text) return
  void navigator.clipboard.writeText(text)
  copiedKey.value = key
  setTimeout(() => {
    if (copiedKey.value === key) copiedKey.value = null
  }, 2500)
}

function openSiteTab(tab: string) {
  if (!env.value?.domain) {
    emit('openPanel', 'site')
    return
  }
  openHostingFromAccount(env.value.domain, tab, env.value.id)
}


const env = computed(() => props.activeEnv)
const plan = computed(() => props.activePlan)
const usage = computed(() => props.usageSnapshot || null)

const cpuPct = computed(() => {
  const p = usage.value?.cpu_usage_percent
  return p != null && !Number.isNaN(Number(p)) ? Math.min(100, Number(p)) : null
})
const memPct = computed(() => {
  const p = usage.value?.memory_pct
  return p != null && !Number.isNaN(Number(p)) ? Math.min(100, Number(p)) : null
})
const diskPct = computed(() => Math.min(100, Number(props.usagePct) || 0))
const procsPct = computed(() => processPct(usage.value))
const updatedLabel = computed(() => formatUpdatedAt(usage.value?.metrics_updated_at))
const rs = computed(() => usage.value?.resource_statuses || null)

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
  return 'Online'
}

function healthClass(status?: string | null) {
  const s = (status || '').toLowerCase()
  if (env.value?.status === 'suspended' || env.value?.status === 'terminated') return 'bad'
  if (s === 'healthy' || !s) return 'ok'
  if (s === 'degraded' || s === 'checking' || s === 'warning') return 'warn'
  if (s === 'unhealthy' || s === 'offline' || s === 'critical') return 'bad'
  return 'ok'
}

function publicSiteUrl(domain: string) {
  return `https://${domain}`
}

function openHostingPanel() {
  if (!env.value?.domain) {
    emit('openPanel', 'billing')
    return
  }
  openHostingFromAccount(env.value.domain, 'overview', env.value.id)
}

const spec = computed(() => {
  const e = env.value
  const p = plan.value
  const cpu = formatCpu(e?.cpu_limit ?? p?.cpu_cores ?? 0)
  const ram = formatRamGb(e?.ram_limit_gb ?? p?.ram_gb ?? 0)
  const disk = e?.storage_limit_gb ?? p?.storage_gb ?? 0
  return { cpu, ram, disk }
})

const panelUrl = computed(() => (env.value?.domain ? tenantCpanelUrl(env.value.domain) : null))
const mailUrl = computed(() => (env.value?.domain ? tenantMailUrl(env.value.domain) : null))

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

const isComplimentaryPlan = computed(() => {
  const price = Number(plan.value?.price_monthly ?? 0)
  const isFreeName = (plan.value?.name || '').toLowerCase().includes('free') || (plan.value?.name || '').toLowerCase().includes('trial')
  return Boolean(price === 0 && isFreeName && !pendingOrder.value && env.value)
})

</script>

<template>
  <section class="overview-section">
    <!-- Header -->
    <header class="page-top-header">
      <div class="header-titles">
        <h1 class="welcome-title">Hello, {{ greeting }}</h1>
        <p class="welcome-sub">{{ env?.domain ? 'Your site, server telemetry and package at a glance.' : 'Order a package to get your site, SSL, and mailbox tools.' }}</p>
      </div>

      <div v-if="dash.unread_notifications > 0" class="header-actions">
        <button type="button" class="support-badge-btn" @click="emit('openPanel', 'support')">
          <IconActivity :size="15" />
          <span>{{ dash.unread_notifications }} support {{ dash.unread_notifications === 1 ? 'reply' : 'replies' }}</span>
        </button>
      </div>
    </header>

    <!-- Empty State -->
    <div v-if="!dash.environments.length" class="overview-card empty-state-card">
      <div class="empty-icon-wrap">
        <IconServer :size="28" />
      </div>
      <h2>{{ pendingOrder ? 'Finish payment to activate hosting' : 'No hosting package active' }}</h2>
      <p class="empty-desc">
        <template v-if="pendingOrder">
          Pay invoice <strong>{{ pendingOrder.invoice_number || pendingOrder.id.slice(0, 8) }}</strong>
          ({{ pendingOrder.currency }} {{ pendingOrder.total_price }}). Once payment is approved, your site tools unlock automatically.
        </template>
        <template v-else>
          Get started with high-performance web hosting, isolated cPanel management, SSL and custom email accounts.
        </template>
      </p>
      <button type="button" class="btn-primary" @click="emit('openPanel', 'billing')">
        {{ pendingOrder ? 'Open Billing & Pay' : 'Browse Plans & Order' }}
      </button>
    </div>

    <!-- Active Account Overview -->
    <template v-else-if="env">
      <!-- HIGH-VISIBILITY PENDING INVOICE & SENDING REFERENCE CARD -->
      <div v-if="pendingOrder" class="pending-ref-hero-card">
        <div class="pending-ref-top">
          <div class="pending-ref-badge">
            <span class="ping-dot"></span>
            <strong>Action Required: Complete MoMo Payment</strong>
          </div>
          <span class="pending-amount-tag">{{ pendingOrder.currency }} {{ Number(pendingOrder.total_price).toFixed(2) }}</span>
        </div>
        <div class="pending-ref-mid">
          <div class="pending-ref-info">
            <p class="pending-ref-title">Your MoMo Sending Reference Code:</p>
            <div class="pending-ref-code-row">
              <code class="pending-ref-val">{{ pendingOrder.invoice_number || pendingOrder.id.slice(0, 8) }}</code>
              <button
                type="button"
                class="btn-copy-hero-ref"
                @click="copyToClip('hero_ref', pendingOrder.invoice_number || pendingOrder.id.slice(0, 8))"
              >
                <i class="fa-solid" :class="copiedKey === 'hero_ref' ? 'fa-check text-emerald-400' : 'fa-copy'" aria-hidden="true" />
                <span>{{ copiedKey === 'hero_ref' ? 'Copied Reference!' : 'Copy Reference Code' }}</span>
              </button>
            </div>
            <p class="pending-ref-tip">⚠️ Enter <strong>{{ pendingOrder.invoice_number || pendingOrder.id.slice(0, 8) }}</strong> in your phone's Mobile Money note/reference field to activate instantly.</p>
          </div>
          <button
            type="button"
            class="btn-open-invoice-hero"
            @click="router.push(`/account/invoice/${pendingOrder.id}`)"
          >
            <span>Open Invoice &amp; Pay</span>
            <IconChevron :size="15" />
          </button>
        </div>
      </div>

      <!-- COMPLIMENTARY FREE ACCOUNT BANNER -->
      <div v-else-if="isComplimentaryPlan" class="comp-plan-banner">
        <div class="comp-badge-pill">
          <i class="fa-solid fa-gift text-amber-500" aria-hidden="true" />
          <span>Complimentary Free Plan Active</span>
        </div>
        <p class="comp-desc">Your hosting environment is fully provisioned with 100% complimentary resources (0.00 GHS billing).</p>
      </div>

      <div class="overview-grid">
        <div class="main-column-wrap">
          <!-- Main Environment Card -->
          <article class="overview-card main-env-card">
            <!-- Site Header Row -->
            <div class="env-header-row">
              <div class="env-titles">
                <span class="plan-pill-tag">{{ plan?.name || (isComplimentaryPlan ? 'Free Tier Hosting' : 'Personal Hosting') }}</span>
                <h2 class="env-domain-heading">{{ env.domain || 'Your Site' }}</h2>
                <div class="env-meta-tags">
                  <span class="meta-spec-chip">{{ spec.cpu }} vCPU</span>
                  <span class="meta-spec-chip">{{ spec.ram }}</span>
                  <span class="meta-spec-chip">{{ spec.disk }} GB SSD</span>
                  <span v-if="env.hosting_name" class="meta-id-chip">ID: {{ env.hosting_name }}</span>
                </div>
              </div>
              <div class="env-status-badge" :class="healthClass(env.health_status)">
                <span class="status-pulse-dot"></span>
                <span>{{ healthLabel(env.health_status) }}</span>
              </div>
            </div>

            <!-- Telemetry & Resource Gauges -->
            <div class="gauges-container">
              <!-- CPU Meter -->
              <div v-if="cpuPct != null" class="gauge-item">
                <div class="gauge-head">
                  <div class="gauge-label-wrap">
                    <span class="gauge-name">CPU</span>
                    <span class="gauge-status-tag" :class="resourceStatusClass(rs?.cpu)">{{ resourceStatusLabel(rs?.cpu) }}</span>
                  </div>
                  <span class="gauge-value">
                    {{ usage?.cpu_usage_vcpu != null ? Number(usage.cpu_usage_vcpu).toFixed(2) : '0.00' }} / {{ formatCpu(env.cpu_limit) }} vCPU
                    <strong>{{ Math.round(cpuPct) }}%</strong>
                  </span>
                </div>
                <div class="gauge-track">
                  <div class="gauge-fill" :class="barClassForTier(resourceTier(cpuPct))" :style="{ width: `${Math.max(4, cpuPct)}%` }"></div>
                </div>
              </div>

              <!-- Memory Meter -->
              <div v-if="memPct != null" class="gauge-item">
                <div class="gauge-head">
                  <div class="gauge-label-wrap">
                    <span class="gauge-name">Memory</span>
                    <span class="gauge-status-tag" :class="resourceStatusClass(rs?.memory)">{{ resourceStatusLabel(rs?.memory) }}</span>
                  </div>
                  <span class="gauge-value">
                    {{ Math.round(usage?.memory_usage_mb || 0) }} / {{ Math.round(usage?.memory_limit_mb || Number(env.ram_limit_gb || 0) * 1024) }} MB
                    <strong>{{ Math.round(memPct) }}%</strong>
                  </span>
                </div>
                <div class="gauge-track">
                  <div class="gauge-fill" :class="barClassForTier(resourceTier(memPct))" :style="{ width: `${Math.max(4, memPct)}%` }"></div>
                </div>
              </div>

              <!-- Disk Meter -->
              <div class="gauge-item">
                <div class="gauge-head">
                  <div class="gauge-label-wrap">
                    <span class="gauge-name">Disk Storage</span>
                    <span class="gauge-status-tag" :class="resourceStatusClass(rs?.disk)">{{ resourceStatusLabel(rs?.disk) }}</span>
                  </div>
                  <span class="gauge-value">
                    {{ usage?.storage_used_gb != null ? usage.storage_used_gb : '0.001' }} / {{ spec.disk }} GB
                    <strong>{{ Math.round(diskPct) }}%</strong>
                  </span>
                </div>
                <div class="gauge-track">
                  <div class="gauge-fill" :class="usageStatus || barClassForTier(resourceTier(diskPct))" :style="{ width: `${Math.max(4, diskPct)}%` }"></div>
                </div>
              </div>

              <!-- Processes Meter -->
              <div v-if="procsPct != null" class="gauge-item">
                <div class="gauge-head">
                  <div class="gauge-label-wrap">
                    <span class="gauge-name">Processes</span>
                    <span class="gauge-status-tag" :class="resourceStatusClass(rs?.processes)">{{ resourceStatusLabel(rs?.processes) }}</span>
                  </div>
                  <span class="gauge-value">
                    {{ usage?.process_count ?? 2 }} / {{ usage?.process_limit ?? 40 }}
                    <strong>{{ Math.round(procsPct) }}%</strong>
                  </span>
                </div>
                <div class="gauge-track">
                  <div class="gauge-fill" :class="barClassForTier(resourceTier(procsPct))" :style="{ width: `${Math.max(4, procsPct)}%` }"></div>
                </div>
              </div>
            </div>

            <!-- Quick Telemetry Footnote -->
            <div class="telemetry-summary-line">
              <span>{{ usageInfo || healthInfo || 'Isolated tenant environment operating normally.' }}</span>
              <span v-if="updatedLabel" class="updated-time"> · Live Metrics Sync: {{ updatedLabel }}</span>
            </div>

            <!-- Service Endpoints Box -->
            <div v-if="env.domain" class="service-endpoints-box">
              <div class="endpoint-item">
                <span class="ep-key">Website:</span>
                <a :href="publicSiteUrl(env.domain)" target="_blank" rel="noopener" class="ep-val">{{ env.domain }}</a>
              </div>
              <div v-if="mailUrl" class="endpoint-item">
                <span class="ep-key">Mail:</span>
                <a :href="mailUrl" target="_blank" rel="noopener" class="ep-val">{{ mailUrl.replace(/^https:\/\//, '') }}</a>
              </div>
              <div v-if="panelUrl" class="endpoint-item">
                <span class="ep-key">Hosting panel:</span>
                <span class="ep-val ep-panel">{{ panelUrl.replace(/^https:\/\//, '') }}</span>
              </div>
            </div>

            <!-- Primary Actions -->
            <div class="action-buttons-row">
              <button type="button" class="btn-open-panel" @click="openHostingPanel">
                <IconServer :size="16" />
                <span>Open hosting panel</span>
              </button>
              <a
                v-if="env.domain"
                class="btn-open-site"
                :href="publicSiteUrl(env.domain)"
                target="_blank"
                rel="noopener"
              >
                <IconGlobe :size="16" />
                <span>Open site</span>
              </a>
            </div>

            <!-- Multi-Domain Environment Switcher -->
            <div v-if="dash.environments.length > 1" class="multi-env-switcher">
              <span class="switcher-label">Your Environments:</span>
              <div class="switcher-pills">
                <button
                  v-for="item in dash.environments"
                  :key="item.id"
                  type="button"
                  class="switcher-pill"
                  :class="{ active: item.id === env.id }"
                  @click="emit('selectEnv', item.id)"
                >
                  {{ item.domain || 'Site' }}
                </button>
              </div>
            </div>
          </article>
        </div>

        <!-- Right Side Information Column -->
        <aside class="overview-sidebar-col">
          <!-- Package Card -->
          <article class="overview-card side-info-card">
            <div class="card-kicker-row">
              <span class="kicker-label">PACKAGE</span>
            </div>
            <h3 class="side-card-title">{{ plan?.name || (isComplimentaryPlan ? 'Free Tier Hosting' : 'Personal Hosting') }}</h3>

            <div class="info-facts-list">
              <div class="fact-row">
                <span class="fact-label">Status</span>
                <span class="fact-val-badge active">{{ activeSub?.status || env.status || 'active' }}</span>
              </div>
              <div v-if="expiresLabel" class="fact-row">
                <span class="fact-label">Renews / expires</span>
                <span class="fact-val">{{ expiresLabel }}</span>
              </div>
              <div class="fact-row">
                <span class="fact-label">AI tokens</span>
                <span class="fact-val bold">{{ (dash.credits?.tokens_remaining ?? (dash.credits?.credits_remaining ?? 0) * 12000).toLocaleString() }}</span>
              </div>
            </div>

            <button type="button" class="side-action-link" @click="emit('openPanel', 'billing')">
              <span>Billing &amp; renewals</span>
              <IconChevron :size="14" />
            </button>
          </article>

          <!-- DNS & NAMESERVERS TELEMETRY CARD -->
          <article class="overview-card side-info-card">
            <div class="card-kicker-row">
              <span class="kicker-label">DNS &amp; NAMESERVERS</span>
            </div>
            <h3 class="side-card-title">Server Routing</h3>
            <p class="side-card-subtext">Set these nameservers at your domain registrar for automated DNS &amp; SSL.</p>

            <div class="dns-records-list">
              <div class="dns-row">
                <span class="dns-k">NS 1:</span>
                <code class="dns-v">ns1.ifnotus.space</code>
                <button type="button" class="btn-copy-dns" title="Copy NS 1" @click="copyToClip('ns1', 'ns1.ifnotus.space')">
                  <i class="fa-solid" :class="copiedKey === 'ns1' ? 'fa-check text-emerald-500' : 'fa-copy'" aria-hidden="true" />
                </button>
              </div>
              <div class="dns-row">
                <span class="dns-k">NS 2:</span>
                <code class="dns-v">ns2.ifnotus.space</code>
                <button type="button" class="btn-copy-dns" title="Copy NS 2" @click="copyToClip('ns2', 'ns2.ifnotus.space')">
                  <i class="fa-solid" :class="copiedKey === 'ns2' ? 'fa-check text-emerald-500' : 'fa-copy'" aria-hidden="true" />
                </button>
              </div>
            </div>
          </article>

          <!-- Support Card -->
          <article class="overview-card side-info-card">
            <div class="card-kicker-row">
              <span class="kicker-label">NEED HELP?</span>
            </div>
            <h3 class="side-card-title">Support</h3>
            <p class="side-card-subtext">Ask IFNOTUS about your site, email, or invoice — 24/7 direct assistance.</p>
            <button type="button" class="side-action-link" @click="emit('openPanel', 'support')">
              <span>Open tickets</span>
              <IconChevron :size="14" />
            </button>
          </article>
        </aside>
      </div>
    </template>

  </section>
</template>

<style scoped>
.overview-section {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 100%;
  min-width: 0;
}

/* Page Top Header */
.page-top-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.25rem;
}

.welcome-title {
  margin: 0;
  font-family: var(--ds-font-display, 'Sora', sans-serif);
  font-size: clamp(1.4rem, 2.4vw, 1.85rem);
  font-weight: 700;
  letter-spacing: -0.035em;
  color: var(--p-ink, #0f172a);
}

.welcome-sub {
  margin: 0.35rem 0 0;
  color: var(--p-muted, #64748b);
  font-size: 0.92rem;
  line-height: 1.45;
}

.support-badge-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border: 1px solid color-mix(in srgb, var(--p-accent, #1e3a5f) 25%, #e2e8f0);
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 8%, #ffffff);
  color: var(--p-accent, #1e3a5f);
  border-radius: 999px;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.support-badge-btn:hover {
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 14%, #ffffff);
  transform: translateY(-1px);
}

/* Pending Banner */
.pending-invoice-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.85rem;
  padding: 0.95rem 1.25rem;
  border-radius: 1rem;
  border: 1px solid #fed7aa;
  background: linear-gradient(135deg, #fffaf0 0%, #fff7ed 100%);
  color: #9a3412;
  box-shadow: 0 2px 6px rgba(234, 88, 12, 0.05);
}

.banner-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.92rem;
}

.banner-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: #ea580c;
  box-shadow: 0 0 0 3px rgba(234, 88, 12, 0.2);
}

.banner-desc {
  margin: 0.2rem 0 0;
  font-size: 0.84rem;
  color: #7c2d12;
}

.banner-action-btn {
  background: #ffffff;
  border: 1px solid #fdba74;
  color: #c2410c;
  padding: 0.45rem 1rem;
  border-radius: 0.6rem;
  font-size: 0.84rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.banner-action-btn:hover {
  background: #fff7ed;
  border-color: #ea580c;
}

/* Layout Grid */
.overview-grid {
  display: grid;
  gap: 1.25rem;
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 980px) {
  .overview-grid {
    grid-template-columns: minmax(0, 1.65fr) minmax(17rem, 0.85fr);
    align-items: start;
  }
}

/* Card Styles */
.overview-card {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1.25rem;
  padding: 1.45rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03), 0 8px 24px rgba(15, 23, 42, 0.04);
  min-width: 0;
}

.main-env-card {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* Env Header */
.env-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  border-bottom: 1px solid var(--p-border, #f1f5f9);
  padding-bottom: 1.15rem;
}

.plan-pill-tag {
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent, #1e3a5f);
  margin-bottom: 0.25rem;
}

.env-domain-heading {
  margin: 0;
  font-family: var(--ds-font-display, 'Sora', sans-serif);
  font-size: clamp(1.25rem, 2.2vw, 1.65rem);
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--p-ink, #0f172a);
  word-break: break-all;
}

.env-meta-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.5rem;
}

.meta-spec-chip, .meta-id-chip {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--p-muted, #64748b);
  background: color-mix(in srgb, var(--p-surface, #ffffff) 50%, #f1f5f9);
  border: 1px solid var(--p-border, #e2e8f0);
  padding: 0.18rem 0.55rem;
  border-radius: 0.45rem;
}

.meta-id-chip {
  color: var(--p-accent, #1e3a5f);
  font-weight: 700;
}

.env-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.28rem 0.75rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
  flex-shrink: 0;
}

.env-status-badge.ok {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.env-status-badge.warn {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}

.env-status-badge.bad {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.status-pulse-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: currentColor;
}

/* Gauges */
.gauges-container {
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}

.gauge-item {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.gauge-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.82rem;
}

.gauge-label-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.gauge-name {
  font-weight: 700;
  color: var(--p-ink, #1e293b);
}

.gauge-status-tag {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.12rem 0.45rem;
  border-radius: 0.35rem;
}

.gauge-status-tag.enforced {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.gauge-status-tag.reported {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.gauge-value {
  color: var(--p-muted, #64748b);
  font-variant-numeric: tabular-nums;
}

.gauge-value strong {
  color: var(--p-ink, #0f172a);
  margin-left: 0.25rem;
}

.gauge-track {
  height: 0.55rem;
  border-radius: 999px;
  background: var(--p-border, #f1f5f9);
  overflow: hidden;
  position: relative;
}

.gauge-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--p-accent, #1e3a5f);
  transition: width 0.4s ease;
}

.gauge-fill.tier-low {
  background: #0284c7;
}

.gauge-fill.tier-mid, .gauge-fill.warning {
  background: #f59e0b;
}

.gauge-fill.tier-high, .gauge-fill.over {
  background: #ef4444;
}

/* Footnote */
.telemetry-summary-line {
  font-size: 0.84rem;
  line-height: 1.45;
  color: var(--p-muted, #64748b);
  padding: 0.65rem 0.85rem;
  background: color-mix(in srgb, var(--p-surface, #ffffff) 60%, #f8fafc);
  border-radius: 0.65rem;
  border: 1px solid var(--p-border, #f1f5f9);
}

.updated-time {
  color: var(--p-muted, #94a3b8);
}

/* Endpoints Box */
.service-endpoints-box {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  background: #fafcff;
  border: 1px solid #e0eafc;
  border-radius: 0.75rem;
  padding: 0.85rem 1.05rem;
}

.endpoint-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.86rem;
}

.ep-key {
  color: #64748b;
  font-weight: 500;
  width: 6.5rem;
  flex-shrink: 0;
}

.ep-val {
  color: var(--p-accent, #1e3a5f);
  font-weight: 650;
  text-decoration: none;
  word-break: break-all;
}

.ep-val:hover {
  text-decoration: underline;
}

.ep-panel {
  color: #0f172a;
}

/* Action Buttons */
.action-buttons-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding-top: 0.25rem;
}

.btn-open-panel, .btn-open-site {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.68rem 1.25rem;
  border-radius: 0.65rem;
  font-size: 0.88rem;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.15s ease;
}

.btn-open-panel {
  border: none;
  background: var(--p-accent, #1e3a5f);
  color: #ffffff;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--p-accent, #1e3a5f) 25%, transparent);
}

.btn-open-panel:hover {
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 88%, black);
  transform: translateY(-1px);
}

.btn-open-site {
  border: 1px solid var(--p-border, #cbd5e1);
  background: var(--p-surface, #ffffff);
  color: var(--p-ink, #0f172a);
}

.btn-open-site:hover {
  border-color: var(--p-accent, #1e3a5f);
  color: var(--p-accent, #1e3a5f);
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 5%, #ffffff);
}

/* Multi-Environment Switcher */
.multi-env-switcher {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  border-top: 1px solid var(--p-border, #f1f5f9);
  padding-top: 0.95rem;
}

.switcher-label {
  font-size: 0.76rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--p-muted, #64748b);
}

.switcher-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.switcher-pill {
  border: 1px solid var(--p-border, #cbd5e1);
  background: var(--p-surface, #ffffff);
  color: var(--p-ink, #334155);
  border-radius: 999px;
  padding: 0.3rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.switcher-pill:hover {
  border-color: var(--p-accent, #1e3a5f);
  color: var(--p-accent, #1e3a5f);
}

.switcher-pill.active {
  background: var(--p-accent, #1e3a5f);
  border-color: var(--p-accent, #1e3a5f);
  color: #ffffff;
  font-weight: 700;
}

/* Right Sidebar Column */
.overview-sidebar-col {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.side-info-card {
  padding: 1.25rem;
}

.card-kicker-row {
  margin-bottom: 0.25rem;
}

.kicker-label {
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--p-muted, #64748b);
  text-transform: uppercase;
}

.side-card-title {
  margin: 0 0 0.85rem;
  font-family: var(--ds-font-display, 'Sora', sans-serif);
  font-size: 1.2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--p-ink, #0f172a);
}

.side-card-subtext {
  margin: 0 0 1rem;
  font-size: 0.86rem;
  line-height: 1.45;
  color: var(--p-muted, #64748b);
}

.info-facts-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  border-top: 1px solid var(--p-border, #f1f5f9);
  padding-top: 0.85rem;
  margin-bottom: 1rem;
}

.fact-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.84rem;
}

.fact-label {
  color: var(--p-muted, #64748b);
}

.fact-val {
  color: var(--p-ink, #0f172a);
  font-weight: 600;
  text-align: right;
}

.fact-val.bold {
  font-weight: 800;
  color: var(--p-accent, #1e3a5f);
}

.fact-val-badge {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: capitalize;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
}

.fact-val-badge.active {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.side-action-link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: transparent;
  border: none;
  padding: 0;
  color: var(--p-accent, #1e3a5f);
  font-size: 0.86rem;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.15s ease;
}

.side-action-link:hover {
  transform: translateX(2px);
  text-decoration: underline;
}

/* Empty Card */
.empty-state-card {
  text-align: center;
  padding: 3rem 1.5rem;
  max-width: 32rem;
  margin: 0 auto;
}

.empty-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 4rem;
  height: 4rem;
  border-radius: 1rem;
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 10%, #ffffff);
  color: var(--p-accent, #1e3a5f);
  margin-bottom: 1.25rem;
}

.empty-desc {
  color: var(--p-muted, #64748b);
  font-size: 0.92rem;
  line-height: 1.5;
  margin: 0.65rem 0 1.5rem;
}

/* ================= HERO PENDING REFERENCE CARD ================= */
.pending-ref-hero-card {
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
  border: 2px solid #f59e0b;
  border-radius: 1rem;
  padding: 1.15rem 1.35rem;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.15);
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.pending-ref-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.pending-ref-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.88rem;
  color: #92400e;
}

.ping-dot {
  width: 0.65rem;
  height: 0.65rem;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7);
  animation: pulse-orange 1.8s infinite;
}

@keyframes pulse-orange {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(245, 158, 11, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
}

.pending-amount-tag {
  background: #ffffff;
  color: #b45309;
  border: 1px solid #fde68a;
  padding: 0.25rem 0.65rem;
  border-radius: 0.5rem;
  font-weight: 800;
  font-size: 0.85rem;
}

.pending-ref-mid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: #ffffff;
  padding: 0.95rem 1.15rem;
  border-radius: 0.75rem;
  border: 1px solid #fde68a;
}

.pending-ref-title {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #78350f;
}

.pending-ref-code-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.pending-ref-val {
  font-family: var(--ds-font-mono, ui-monospace, monospace);
  font-size: 1.35rem;
  font-weight: 900;
  letter-spacing: 0.06em;
  color: #0f172a;
  background: #fffbeb;
  border: 1.5px solid #d97706;
  padding: 0.2rem 0.65rem;
  border-radius: 0.45rem;
}

.btn-copy-hero-ref {
  background: #d97706;
  color: #ffffff;
  border: none;
  font-weight: 750;
  font-size: 0.8rem;
  padding: 0.45rem 0.85rem;
  border-radius: 0.45rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  transition: background 0.15s;
}

.btn-copy-hero-ref:hover {
  background: #b45309;
}

.pending-ref-tip {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: #78350f;
}

.btn-open-invoice-hero {
  background: #0f172a;
  color: #ffffff;
  border: none;
  font-size: 0.86rem;
  font-weight: 750;
  padding: 0.65rem 1.15rem;
  border-radius: 0.65rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  transition: all 0.15s;
}

.btn-open-invoice-hero:hover {
  background: #1e293b;
  transform: translateY(-1px);
}

/* ================= COMPLIMENTARY BANNER ================= */
.comp-plan-banner {
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 0.85rem;
  padding: 0.85rem 1.15rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.comp-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.85rem;
  font-weight: 750;
  color: #166534;
}

.comp-desc {
  margin: 0;
  font-size: 0.78rem;
  color: #15803d;
}

/* ================= MAIN COLUMN & QUICK TOOLS ================= */
.main-column-wrap {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  min-width: 0;
}

.quick-tools-card {
  padding: 1.25rem;
}

.kicker-sub {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--p-muted, #64748b);
}

.tools-interactive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(13.5rem, 1fr));
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.tool-btn {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  border-color: #94a3b8;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.tool-icon-box {
  width: 2.35rem;
  height: 2.35rem;
  border-radius: 0.6rem;
  display: grid;
  place-items: center;
  font-size: 1.05rem;
  flex-shrink: 0;
}

.tone-blue { background: #eff6ff; color: #2563eb; }
.tone-orange { background: #fff7ed; color: #ea580c; }
.tone-purple { background: #faf5ff; color: #9333ea; }
.tone-green { background: #f0fdf4; color: #16a34a; }
.tone-pink { background: #fdf2f8; color: #db2777; }
.tone-indigo { background: #eef2ff; color: #4f46e5; }

.tool-text {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.tool-text strong {
  font-size: 0.84rem;
  font-weight: 750;
  color: #0f172a;
}

.tool-text span {
  font-size: 0.7rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ================= DNS & NAMESERVERS TELEMETRY ================= */
.dns-records-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.85rem;
}

.dns-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.4rem 0.65rem;
}

.dns-k {
  font-size: 0.7rem;
  font-weight: 750;
  color: #64748b;
  width: 3.2rem;
  flex-shrink: 0;
}

.dns-v {
  font-family: var(--ds-font-mono, ui-monospace, monospace);
  font-size: 0.78rem;
  font-weight: 750;
  color: #0f172a;
  flex: 1;
}

.btn-copy-dns {
  border: none;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.35rem;
  padding: 0.2rem 0.45rem;
  color: #475569;
  cursor: pointer;
  font-size: 0.72rem;
  display: grid;
  place-items: center;
  transition: all 0.15s;
}

.btn-copy-dns:hover {
  background: #f1f5f9;
  color: #0f172a;
}

/* ================= DARK THEME OVERRIDES ================= */
:global(.dark) .pending-ref-hero-card {
  background: linear-gradient(135deg, #1c1917 0%, #292524 100%);
  border-color: #f59e0b;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.2);
}

:global(.dark) .pending-ref-badge {
  color: #fcd34d;
}

:global(.dark) .pending-amount-tag {
  background: #0c0a09;
  color: #fbbf24;
  border-color: #78350f;
}

:global(.dark) .pending-ref-mid {
  background: #0c0a09;
  border-color: #78350f;
}

:global(.dark) .pending-ref-title {
  color: #fcd34d;
}

:global(.dark) .pending-ref-val {
  background: #1c1917;
  color: #fbbf24;
  border-color: #d97706;
}

:global(.dark) .btn-copy-hero-ref {
  background: #d97706;
  color: #ffffff;
}

:global(.dark) .btn-copy-hero-ref:hover {
  background: #b45309;
}

:global(.dark) .pending-ref-tip {
  color: #fde68a;
}

:global(.dark) .pending-ref-tip strong {
  color: #ffffff;
}

:global(.dark) .btn-open-invoice-hero {
  background: #f59e0b;
  color: #0c0a09;
}

:global(.dark) .btn-open-invoice-hero:hover {
  background: #d97706;
}

:global(.dark) .comp-plan-banner {
  background: #052e16;
  border-color: #166534;
}

:global(.dark) .comp-badge-pill {
  color: #86efac;
}

:global(.dark) .comp-desc {
  color: #4ade80;
}

:global(.dark) .tool-btn {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

:global(.dark) .tool-btn:hover {
  background: #334155;
  border-color: #475569;
}

:global(.dark) .tool-text strong {
  color: #f8fafc;
}

:global(.dark) .tool-text p {
  color: #94a3b8;
}

:global(.dark) .dns-row {
  background: #1e293b;
  border-color: #334155;
}

:global(.dark) .dns-k {
  color: #94a3b8;
}

:global(.dark) .dns-v {
  color: #f8fafc;
}

:global(.dark) .btn-copy-dns {
  background: #0f172a;
  border-color: #334155;
  color: #94a3b8;
}

:global(.dark) .btn-copy-dns:hover {
  background: #334155;
  color: #f8fafc;
}
</style>

<style>
/* Unscoped global dark theme overrides for Customer Portal Overview */
html.dark .pending-ref-hero-card {
  background: linear-gradient(135deg, #1c1917 0%, #292524 100%) !important;
  border-color: #f59e0b !important;
}

html.dark .pending-ref-badge {
  color: #fcd34d !important;
}

html.dark .pending-amount-tag {
  background: #0c0a09 !important;
  color: #fbbf24 !important;
  border-color: #78350f !important;
}

html.dark .pending-ref-mid {
  background: #0c0a09 !important;
  border-color: #78350f !important;
}

html.dark .pending-ref-title {
  color: #fcd34d !important;
}

html.dark .pending-ref-val {
  background: #1c1917 !important;
  color: #fbbf24 !important;
  border-color: #d97706 !important;
}

html.dark .btn-copy-hero-ref {
  background: #d97706 !important;
  color: #ffffff !important;
}

html.dark .btn-copy-hero-ref:hover {
  background: #b45309 !important;
}

html.dark .pending-ref-tip {
  color: #fde68a !important;
}

html.dark .btn-open-invoice-hero {
  background: #f59e0b !important;
  color: #0c0a09 !important;
}

html.dark .btn-open-invoice-hero:hover {
  background: #d97706 !important;
}

html.dark .tool-btn {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .tool-btn:hover {
  background: #334155 !important;
  border-color: #475569 !important;
}

html.dark .tool-text strong {
  color: #f8fafc !important;
}

html.dark .tool-text p {
  color: #94a3b8 !important;
}

html.dark .dns-row {
  background: #1e293b !important;
  border-color: #334155 !important;
}

html.dark .dns-k {
  color: #94a3b8 !important;
}

html.dark .dns-v {
  color: #f8fafc !important;
}

html.dark .btn-copy-dns {
  background: #0f172a !important;
  border-color: #334155 !important;
  color: #94a3b8 !important;
}

html.dark .btn-copy-dns:hover {
  background: #334155 !important;
  color: #f8fafc !important;
}
</style>

