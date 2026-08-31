<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import type { CustomerDashboard, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import type { PlanColorTier } from '@/lib/theme'
import { sshHeadline } from '@/lib/planMatrix'
import { packItems } from '@/lib/planPack'
import { customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'

const props = defineProps<{
  dash: CustomerDashboard
  plans: HostingPlan[]
  planColors: PlanColorTier[]
  billingMsg: string
  changePlanId: string
  topUpCredits: number
  hasLiveHosting?: boolean
}>()

const emit = defineEmits<{
  'update:changePlanId': [string]
  'update:topUpCredits': [number]
  renew: [string]
  toggleRenew: [string, boolean]
  changePlan: [string]
  buyCredits: []
  openInvoice: [string]
}>()

const router = useRouter()

const topUpCreditsModel = computed({
  get: () => props.topUpCredits,
  set: (v: number) => emit('update:topUpCredits', v),
})

const invoices = computed(() => props.dash.orders || [])

const activeSub = computed(() => props.dash.subscriptions?.[0] || null)
const currentPlan = computed(() => props.plans.find((p) => p.id === activeSub.value?.plan_id) || null)

const sortedPlans = computed(() =>
  [...props.plans].sort((a, b) => Number(a.price_monthly) - Number(b.price_monthly)),
)

const upgradingSubId = ref<string | null>(null)
const selectedUpgradePlan = ref<HostingPlan | null>(null)
const upgradeModalOpen = ref(false)
const upgradeBusy = ref(false)
const upgradeMsg = ref('')

function planName(planId: string) {
  return props.plans.find((p) => p.id === planId)?.name ?? 'Personal Hosting'
}

function expiryLabel(iso?: string | null) {
  if (!iso) return 'No expiry'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function priceLabel(plan: HostingPlan) {
  const n = Number(plan.price_monthly)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function formatInvoiceItem(inv: any) {
  const kind = (inv.order_kind || '').toLowerCase()
  if (kind === 'panel_theme' || kind === 'theme' || Number(inv.total_price || 0) <= 5) {
    const themeName = inv.meta_json?.theme_name || 'Ember Panel'
    return `Hosting Panel Theme (${themeName})`
  }
  if (kind === 'credits') {
    return 'AI Developer Credits'
  }
  if (kind === 'renewal') {
    return `Hosting Renewal — ${inv.domain_name || 'Service'}`
  }
  if (kind === 'upgrade') {
    return `Plan Upgrade — ${inv.domain_name || 'Service'}`
  }
  if (inv.domain_name) {
    return `Hosting — ${inv.domain_name}`
  }
  return 'Hosting Package'
}

function planHighlights(plan: HostingPlan) {
  return packItems(plan).slice(0, 4)
}

function isCurrentPlan(plan: HostingPlan) {
  return activeSub.value?.plan_id === plan.id
}

function startUpgrade(plan: HostingPlan) {
  if (isCurrentPlan(plan)) return
  if (!activeSub.value) {
    void router.push({ name: 'portal-account-plans', query: { plan: plan.slug } })
    return
  }
  selectedUpgradePlan.value = plan
  upgradingSubId.value = activeSub.value.id
  upgradeMsg.value = ''
  upgradeModalOpen.value = true
}

async function confirmPlanChange() {
  if (!upgradingSubId.value || !selectedUpgradePlan.value) return
  upgradeBusy.value = true
  upgradeMsg.value = ''
  try {
    const { data } = await customersApi.changePlan(upgradingSubId.value, selectedUpgradePlan.value.id)
    if (data.order_id) {
      upgradeModalOpen.value = false
      await router.push(`/account/invoice/${data.order_id}`)
      return
    }
    upgradeModalOpen.value = false
    emit('changePlan', upgradingSubId.value)
  } catch (e: unknown) {
    upgradeMsg.value = getApiErrorMessage(e, 'Could not change plan.')
  } finally {
    upgradeBusy.value = false
  }
}

function goNewOrder(planSlug?: string) {
  if (planSlug) {
    void router.push({ name: 'portal-account-plans', query: { plan: planSlug } })
    return
  }
  void router.push({ name: 'portal-account-plans' })
}
</script>

<template>
  <section class="billing-page">
    <!-- Header banner -->
    <header class="billing-hero-header">
      <div class="hero-text-wrap">
        <div class="kicker-pill">
          <i class="fa-solid fa-credit-card" aria-hidden="true" />
          <span>PLANS, SUBSCRIPTIONS &amp; BILLING</span>
        </div>
        <h1 class="hero-title">Hosting Plans &amp; Billing</h1>
        <p class="hero-sub">
          Manage your personal hosting packages, seamlessly upgrade or switch tiers, renew services, and view all invoices.
        </p>
      </div>

      <!-- Quick Action buttons -->
      <div class="hero-actions">
        <button type="button" class="btn-new-order" @click="goNewOrder()">
          <i class="fa-solid fa-cart-plus" aria-hidden="true" />
          <span>Order new plan</span>
        </button>
      </div>
    </header>

    <div v-if="billingMsg" class="billing-alert">
      <i class="fa-solid fa-circle-info" aria-hidden="true" />
      <span>{{ billingMsg }}</span>
    </div>

    <!-- Active Subscription Overview Highlight Card -->
    <div v-if="activeSub" class="active-sub-hero-card">
      <div class="active-sub-head">
        <div class="active-sub-info">
          <span class="active-sub-tag">CURRENT ACTIVE PLAN</span>
          <h2 class="active-sub-name">{{ planName(activeSub.plan_id) }}</h2>
          <p class="active-sub-specs">
            <span><i class="fa-solid fa-microchip" /> {{ formatCpu(activeSub.cpu_allocated) }} vCPU</span>
            <span><i class="fa-solid fa-memory" /> {{ formatRamGb(activeSub.ram_allocated) }} RAM</span>
            <span v-if="currentPlan?.storage_gb"><i class="fa-solid fa-hard-drive" /> {{ currentPlan.storage_gb }} GB SSD</span>
            <span><i class="fa-solid fa-calendar-check" /> Renews {{ expiryLabel(activeSub.expires_at) }}</span>
          </p>
        </div>

        <div class="active-sub-actions">
          <span class="status-badge" :class="activeSub.status">{{ activeSub.status }}</span>
          <div class="action-btn-group">
            <button type="button" class="btn-renew-hero" @click="emit('renew', activeSub.id)">
              <i class="fa-solid fa-arrows-rotate" aria-hidden="true" />
              <span>Renew Subscription</span>
            </button>
            <button
              type="button"
              class="btn-autorenew-toggle"
              :class="{ active: activeSub.auto_renew }"
              @click="emit('toggleRenew', activeSub.id, !activeSub.auto_renew)"
            >
              {{ activeSub.auto_renew ? 'Auto-renew enabled' : 'Enable auto-renew' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- MAIN INTERACTIVE HOSTING PLANS CATALOG & UPGRADE MATRIX -->
    <div class="plans-catalog-section">
      <div class="section-title-row">
        <div>
          <h2 class="section-title">Available Personal Hosting Plans</h2>
          <p class="section-sub">Upgrade or downgrade your active hosting environment anytime with automated resource provisioning.</p>
        </div>
      </div>

      <div class="plans-interactive-grid">
        <article
          v-for="p in sortedPlans"
          :key="p.id"
          class="plan-card"
          :class="{
            'is-active-tier': isCurrentPlan(p),
            'is-popular': p.id === sortedPlans[Math.min(1, sortedPlans.length - 1)]?.id,
          }"
        >
          <div class="plan-card-head">
            <div class="plan-badge-row">
              <span v-if="isCurrentPlan(p)" class="badge-current">
                <i class="fa-solid fa-circle-check" /> Active Tier
              </span>
              <span v-else-if="p.id === sortedPlans[Math.min(1, sortedPlans.length - 1)]?.id" class="badge-popular">
                Most Popular
              </span>
              <span v-else class="badge-tier">Tier</span>
            </div>
            <h3 class="plan-name">{{ p.name }}</h3>
            <p class="plan-ssh">{{ sshHeadline(p) }}</p>
          </div>

          <div class="plan-pricing">
            <span class="currency">GHS</span>
            <span class="amount">{{ priceLabel(p) }}</span>
            <span class="period">/ month</span>
          </div>

          <!-- Specs Matrix -->
          <div class="plan-metrics-grid">
            <div class="metric-box">
              <span class="metric-k"><i class="fa-solid fa-microchip" /> CPU</span>
              <strong class="metric-v">{{ formatCpu(p.cpu_cores) }} vCPU</strong>
            </div>
            <div class="metric-box">
              <span class="metric-k"><i class="fa-solid fa-memory" /> RAM</span>
              <strong class="metric-v">{{ formatRamGb(p.ram_gb) }}</strong>
            </div>
            <div class="metric-box">
              <span class="metric-k"><i class="fa-solid fa-hard-drive" /> Disk</span>
              <strong class="metric-v">{{ p.storage_gb }} GB</strong>
            </div>
            <div class="metric-box">
              <span class="metric-k"><i class="fa-solid fa-robot" /> AI</span>
              <strong class="metric-v">{{ p.ai_credits }} Credits</strong>
            </div>
          </div>

          <!-- Included Highlights -->
          <ul class="plan-features-list">
            <li v-for="item in planHighlights(p)" :key="item.id">
              <i class="fa-solid fa-check text-emerald-500" aria-hidden="true" />
              <span><strong>{{ item.label }}</strong> — {{ item.detail }}</span>
            </li>
          </ul>

          <!-- Action Button: Upgrade / Switch / Current -->
          <div class="plan-card-foot">
            <button
              v-if="isCurrentPlan(p)"
              type="button"
              class="btn-plan-action current"
              disabled
            >
              <i class="fa-solid fa-check" aria-hidden="true" />
              <span>Current Active Plan</span>
            </button>
            <button
              v-else-if="activeSub"
              type="button"
              class="btn-plan-action upgrade"
              @click="startUpgrade(p)"
            >
              <span>{{ Number(p.price_monthly) > Number(currentPlan?.price_monthly || 0) ? 'Upgrade to ' + p.name : 'Switch to ' + p.name }}</span>
              <i class="fa-solid fa-arrow-right" aria-hidden="true" />
            </button>
            <button
              v-else
              type="button"
              class="btn-plan-action select"
              @click="goNewOrder(p.slug)"
            >
              <span>Select {{ p.name }}</span>
              <i class="fa-solid fa-arrow-right" aria-hidden="true" />
            </button>
          </div>
        </article>
      </div>
    </div>

    <!-- LOWER SECTION: INVOICES & AI CREDITS -->
    <div class="billing-lower-grid">
      <!-- Invoices Ledger Card -->
      <article class="billing-box invoices-card">
        <div class="box-head">
          <div class="box-title-wrap">
            <h2 class="box-title"><i class="fa-solid fa-receipt text-amber-500" /> Invoices &amp; Receipts</h2>
            <span class="badge-count">{{ invoices.length }}</span>
          </div>
          <p class="box-desc">All payment records, transaction statuses, and official VAT receipts.</p>
        </div>

        <div v-if="!invoices.length" class="empty-state">
          <i class="fa-solid fa-receipt empty-icon" />
          <p>No invoices generated yet.</p>
        </div>

        <div v-else class="invoices-table-wrap">
          <table class="invoices-table">
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Domain / Item</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inv in invoices" :key="inv.id">
                <td class="cell-mono font-bold">{{ inv.invoice_number || inv.id.slice(0, 8) }}</td>
                <td>{{ formatInvoiceItem(inv) }}</td>
                <td class="cell-price">{{ inv.currency }} {{ Number(inv.total_price).toFixed(2) }}</td>
                <td>
                  <span class="status-pill" :class="inv.payment_status">
                    {{ inv.payment_status === 'paid' ? 'Paid' : inv.payment_status === 'submitted' ? 'Awaiting Confirm' : 'Pending' }}
                  </span>
                </td>
                <td>
                  <RouterLink :to="`/account/invoice/${inv.id}`" class="btn-invoice-link">
                    {{ inv.payment_status === 'paid' ? 'View Receipt' : 'Pay Invoice' }}
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <!-- AI Tokens & Credits Box -->
      <article class="billing-box credits-card">
        <div class="box-head">
          <h2 class="box-title"><i class="fa-solid fa-wand-magic-sparkles text-pink-500" /> AI Developer Credits</h2>
          <p class="box-desc">AI tokens used for architecture assistance, log parsing, and coding assistance.</p>
        </div>

        <div class="credits-balance-row">
          <div class="credits-num-box">
            <span class="credits-k">Remaining Credits</span>
            <span class="credits-v">{{ dash.credits?.credits_remaining ?? 0 }}</span>
          </div>
          <div class="tokens-num-box">
            <span class="tokens-k">Est. Token Pool</span>
            <span class="tokens-v">
              {{ (dash.credits?.tokens_remaining ?? (dash.credits?.credits_remaining ?? 0) * 12000).toLocaleString() }}
            </span>
          </div>
        </div>

        <div class="credits-topup-form">
          <label class="topup-label">Top up AI tokens:</label>
          <div class="topup-row">
            <select v-model.number="topUpCreditsModel" class="topup-select">
              <option :value="10">10 Credits (120,000 tokens) — GHS 10</option>
              <option :value="20">20 Credits (240,000 tokens) — GHS 20</option>
              <option :value="50">50 Credits (600,000 tokens) — GHS 50</option>
              <option :value="100">100 Credits (1,200,000 tokens) — GHS 100</option>
            </select>
            <button type="button" class="btn-topup-action" @click="emit('buyCredits')">
              <span>Top Up</span>
            </button>
          </div>
        </div>
      </article>
    </div>

    <!-- PLAN UPGRADE / CHANGE CONFIRMATION MODAL -->
    <div v-if="upgradeModalOpen && selectedUpgradePlan" class="modal-backdrop" @click.self="upgradeModalOpen = false">
      <div class="modal-card">
        <div class="modal-head">
          <div class="modal-badge">
            <i class="fa-solid fa-arrows-split-up-and-left" />
            <span>CONFIRM PLAN CHANGE</span>
          </div>
          <button type="button" class="btn-close-modal" @click="upgradeModalOpen = false">
            <i class="fa-solid fa-xmark" />
          </button>
        </div>

        <div class="modal-body">
          <h3 class="modal-title">Switch to {{ selectedUpgradePlan.name }}</h3>
          <p class="modal-sub">
            Your hosting environment will be upgraded with {{ formatCpu(selectedUpgradePlan.cpu_cores) }} vCPU, {{ formatRamGb(selectedUpgradePlan.ram_gb) }} RAM, and {{ selectedUpgradePlan.storage_gb }} GB SSD storage.
          </p>

          <div class="upgrade-comparison-box">
            <div class="cmp-row">
              <span class="cmp-k">Current Plan:</span>
              <span class="cmp-v">{{ planName(activeSub?.plan_id || '') }} (GHS {{ currentPlan?.price_monthly }}/mo)</span>
            </div>
            <div class="cmp-row highlight">
              <span class="cmp-k">New Plan:</span>
              <span class="cmp-v font-bold text-emerald-600 dark:text-emerald-400">
                {{ selectedUpgradePlan.name }} (GHS {{ selectedUpgradePlan.price_monthly }}/mo)
              </span>
            </div>
          </div>

          <div v-if="upgradeMsg" class="modal-alert">{{ upgradeMsg }}</div>
        </div>

        <div class="modal-foot">
          <button type="button" class="btn-cancel" @click="upgradeModalOpen = false">Cancel</button>
          <button
            type="button"
            class="btn-confirm-upgrade"
            :disabled="upgradeBusy"
            @click="confirmPlanChange"
          >
            <i v-if="upgradeBusy" class="fa-solid fa-spinner fa-spin" />
            <span>{{ upgradeBusy ? 'Applying changes…' : 'Confirm & Generate Invoice' }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.billing-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
  min-width: 0;
}

/* Hero header */
.billing-hero-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1.25rem;
  padding: 1.35rem 1.5rem;
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1.15rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.hero-text-wrap {
  max-width: 42rem;
}

.kicker-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent, #1e3a5f);
  background: color-mix(in srgb, var(--p-accent, #1e3a5f) 10%, transparent);
  padding: 0.2rem 0.65rem;
  border-radius: 9999px;
  margin-bottom: 0.5rem;
}

.hero-title {
  margin: 0;
  font-size: 1.65rem;
  font-weight: 850;
  color: var(--p-ink, #0f172a);
  letter-spacing: -0.025em;
  line-height: 1.2;
}

.hero-sub {
  margin: 0.45rem 0 0;
  font-size: 0.88rem;
  color: var(--p-muted, #64748b);
  line-height: 1.5;
}

.btn-new-order {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--p-accent, #1e3a5f);
  color: #ffffff;
  border: none;
  font-weight: 750;
  font-size: 0.86rem;
  padding: 0.65rem 1.25rem;
  border-radius: 0.65rem;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(30, 58, 95, 0.2);
  transition: all 0.15s ease;
}

.btn-new-order:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

.billing-alert {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.85rem 1.15rem;
  border-radius: 0.75rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  font-size: 0.86rem;
  font-weight: 600;
}

/* Active Sub Highlight Card */
.active-sub-hero-card {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 2px solid var(--p-border, #cbd5e1);
  border-radius: 1.15rem;
  padding: 1.25rem 1.5rem;
}

.active-sub-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1.25rem;
}

.active-sub-tag {
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #059669;
  text-transform: uppercase;
}

.active-sub-name {
  margin: 0.25rem 0 0.35rem;
  font-size: 1.35rem;
  font-weight: 850;
  color: #0f172a;
}

.active-sub-specs {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.82rem;
  color: #475569;
  font-weight: 600;
}

.active-sub-specs span {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.active-sub-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
}

.status-badge {
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.25rem 0.65rem;
  border-radius: 9999px;
  background: #dcfce7;
  color: #166534;
}

.action-btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.btn-renew-hero {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: #0f172a;
  color: #ffffff;
  border: none;
  font-size: 0.82rem;
  font-weight: 750;
  padding: 0.5rem 0.95rem;
  border-radius: 0.55rem;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-renew-hero:hover {
  background: #1e293b;
}

.btn-autorenew-toggle {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 0.8rem;
  font-weight: 650;
  padding: 0.5rem 0.85rem;
  border-radius: 0.55rem;
  cursor: pointer;
}

/* Plans Catalog Matrix */
.plans-catalog-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.section-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 800;
  color: var(--p-ink, #0f172a);
}

.section-sub {
  margin: 0.25rem 0 0;
  font-size: 0.84rem;
  color: var(--p-muted, #64748b);
}

.plans-interactive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  gap: 1rem;
}

.plan-card {
  background: var(--p-surface, #ffffff);
  border: 1.5px solid var(--p-border, #e2e8f0);
  border-radius: 1.15rem;
  padding: 1.25rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  transition: all 0.2s ease;
  position: relative;
}

.plan-card:hover {
  border-color: #94a3b8;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.06);
}

.plan-card.is-active-tier {
  border-color: #059669;
  background: #fdfdfd;
  box-shadow: 0 0 0 1px #059669;
}

.plan-card.is-popular {
  border-color: var(--p-accent, #1e3a5f);
}

.plan-card-head {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.plan-badge-row {
  margin-bottom: 0.25rem;
}

.badge-current {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
}

.badge-popular {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #ffffff;
  background: var(--p-accent, #1e3a5f);
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
}

.badge-tier {
  font-size: 0.68rem;
  font-weight: 750;
  text-transform: uppercase;
  color: #64748b;
  background: #f1f5f9;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
}

.plan-name {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 850;
  color: var(--p-ink, #0f172a);
}

.plan-ssh {
  margin: 0;
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--p-muted, #64748b);
}

.plan-pricing {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  margin: -0.25rem 0 0;
}

.currency {
  font-size: 0.85rem;
  font-weight: 750;
  color: #64748b;
}

.amount {
  font-size: 1.85rem;
  font-weight: 900;
  color: var(--p-ink, #0f172a);
  letter-spacing: -0.03em;
}

.period {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 600;
}

.plan-metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
  background: #f8fafc;
  padding: 0.65rem;
  border-radius: 0.65rem;
  border: 1px solid #e2e8f0;
}

.metric-box {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.metric-k {
  font-size: 0.65rem;
  font-weight: 750;
  color: #64748b;
  text-transform: uppercase;
}

.metric-v {
  font-size: 0.82rem;
  font-weight: 800;
  color: #0f172a;
}

.plan-features-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}

.plan-features-list li {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.78rem;
  line-height: 1.4;
  color: #334155;
}

.plan-features-list li i {
  margin-top: 0.15rem;
  font-size: 0.75rem;
}

.plan-card-foot {
  margin-top: auto;
}

.btn-plan-action {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  border-radius: 0.65rem;
  padding: 0.65rem;
  font-size: 0.84rem;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.15s ease;
  border: none;
}

.btn-plan-action.current {
  background: #ecfdf5;
  color: #059669;
  border: 1.5px solid #a7f3d0;
  cursor: default;
}

.btn-plan-action.upgrade {
  background: var(--p-accent, #1e3a5f);
  color: #ffffff;
}

.btn-plan-action.upgrade:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

.btn-plan-action.select {
  background: #0f172a;
  color: #ffffff;
}

.btn-plan-action.select:hover {
  background: #1e293b;
}

/* Lower Section: Invoices & Credits */
.billing-lower-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.25rem;
}

@media (min-width: 900px) {
  .billing-lower-grid {
    grid-template-columns: 1.5fr 1fr;
  }
}

.billing-box {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1.15rem;
  padding: 1.35rem 1.4rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.box-title-wrap {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.box-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--p-ink, #0f172a);
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.badge-count {
  font-size: 0.7rem;
  font-weight: 800;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
  background: #f1f5f9;
  color: #475569;
}

.box-desc {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  color: var(--p-muted, #64748b);
}

.empty-state {
  padding: 2rem 1rem;
  text-align: center;
  color: #94a3b8;
  font-size: 0.84rem;
}

.empty-icon {
  font-size: 1.8rem;
  margin-bottom: 0.5rem;
  display: block;
  opacity: 0.6;
}

.invoices-table-wrap {
  overflow-x: auto;
}

.invoices-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  text-align: left;
}

.invoices-table th {
  padding: 0.6rem 0.75rem;
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #64748b;
  border-bottom: 1.5px solid #e2e8f0;
}

.invoices-table td {
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.cell-mono {
  font-family: ui-monospace, monospace;
}

.cell-price {
  font-weight: 750;
  color: #0f172a;
}

.status-pill {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
}

.status-pill.paid {
  background: #ecfdf5;
  color: #059669;
}

.status-pill.submitted {
  background: #eff6ff;
  color: #2563eb;
}

.status-pill.pending {
  background: #fffbeb;
  color: #d97706;
}

.btn-invoice-link {
  font-size: 0.75rem;
  font-weight: 750;
  color: var(--p-accent, #1e3a5f);
  text-decoration: underline;
}

/* AI Credits Box */
.credits-balance-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.credits-num-box,
.tokens-num-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.credits-k,
.tokens-k {
  font-size: 0.68rem;
  font-weight: 750;
  text-transform: uppercase;
  color: #64748b;
}

.credits-v,
.tokens-v {
  font-size: 1.25rem;
  font-weight: 900;
  color: #0f172a;
}

.credits-topup-form {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.topup-label {
  font-size: 0.76rem;
  font-weight: 750;
  color: #334155;
}

.topup-row {
  display: flex;
  gap: 0.5rem;
}

.topup-select {
  flex: 1;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.8rem;
  color: #1e293b;
  outline: none;
}

.btn-topup-action {
  background: #0f172a;
  color: #ffffff;
  border: none;
  font-size: 0.8rem;
  font-weight: 750;
  padding: 0.45rem 0.95rem;
  border-radius: 0.55rem;
  cursor: pointer;
  white-space: nowrap;
}

/* Modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 999;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  padding: 1rem;
}

.modal-card {
  width: min(100%, 30rem);
  background: #ffffff;
  border-radius: 1.15rem;
  padding: 1.5rem;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.16);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  color: var(--p-accent, #1e3a5f);
  background: #eff6ff;
  padding: 0.2rem 0.6rem;
  border-radius: 9999px;
}

.btn-close-modal {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
}

.modal-title {
  margin: 0 0 0.35rem;
  font-size: 1.3rem;
  font-weight: 850;
  color: #0f172a;
}

.modal-sub {
  margin: 0;
  font-size: 0.84rem;
  color: #64748b;
  line-height: 1.5;
}

.upgrade-comparison-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.85rem 1rem;
  margin-top: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.cmp-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
}

.cmp-k {
  color: #64748b;
  font-weight: 650;
}

.cmp-v {
  color: #0f172a;
  font-weight: 700;
}

.modal-alert {
  margin-top: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 0.55rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  font-size: 0.8rem;
  font-weight: 600;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.65rem;
  margin-top: 0.5rem;
}

.btn-cancel {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  font-weight: 700;
  font-size: 0.82rem;
  padding: 0.55rem 1rem;
  border-radius: 0.55rem;
  cursor: pointer;
}

.btn-confirm-upgrade {
  background: var(--p-accent, #1e3a5f);
  color: #ffffff;
  border: none;
  font-weight: 750;
  font-size: 0.82rem;
  padding: 0.55rem 1.15rem;
  border-radius: 0.55rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}

/* ================= DARK THEME OVERRIDES ================= */
:global(.dark) .billing-hero-header,
:global(.dark) .plan-card,
:global(.dark) .billing-box,
:global(.dark) .modal-card {
  background: #111827;
  border-color: #1f2937;
  color: #f9fafb;
}

:global(.dark) .hero-title,
:global(.dark) .section-title,
:global(.dark) .plan-name,
:global(.dark) .box-title,
:global(.dark) .modal-title,
:global(.dark) .amount,
:global(.dark) .credits-v,
:global(.dark) .tokens-v,
:global(.dark) .cell-price,
:global(.dark) .metric-v {
  color: #f9fafb;
}

:global(.dark) .active-sub-hero-card {
  background: linear-gradient(135deg, #111827 0%, #1f2937 100%);
  border-color: #374151;
}

:global(.dark) .active-sub-name {
  color: #f9fafb;
}

:global(.dark) .active-sub-specs {
  color: #9ca3af;
}

:global(.dark) .plan-metrics-grid,
:global(.dark) .credits-num-box,
:global(.dark) .tokens-num-box,
:global(.dark) .upgrade-comparison-box {
  background: #1f2937;
  border-color: #374151;
}

:global(.dark) .plan-features-list li {
  color: #cbd5e1;
}

:global(.dark) .topup-select {
  background: #1f2937;
  border-color: #374151;
  color: #f9fafb;
}

:global(.dark) .invoices-table th {
  border-bottom-color: #374151;
  color: #9ca3af;
}

:global(.dark) .invoices-table td {
  border-bottom-color: #1f2937;
  color: #e5e7eb;
}

:global(.dark) .badge-tier {
  background: #1f2937;
  color: #9ca3af;
}
</style>
