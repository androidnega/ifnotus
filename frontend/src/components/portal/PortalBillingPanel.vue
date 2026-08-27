<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import type { CustomerDashboard, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planAccentFromPrice, type PlanColorTier } from '@/lib/theme'
import { visibleStacks } from '@/lib/planMatrix'

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

const changePlanIdModel = computed({
  get: () => props.changePlanId,
  set: (v: string) => emit('update:changePlanId', v),
})
const topUpCreditsModel = computed({
  get: () => props.topUpCredits,
  set: (v: number) => emit('update:topUpCredits', v),
})

const invoices = computed(() => props.dash.orders || [])

function planName(planId: string) {
  return props.plans.find((p) => p.id === planId)?.name ?? 'Plan'
}

function planFor(planId: string) {
  return props.plans.find((p) => p.id === planId)
}

function accentFor(planId: string) {
  const p = planFor(planId)
  return planAccentFromPrice(Number(p?.price_monthly || 0), props.planColors, p?.features)
}

function expiryLabel(iso?: string | null) {
  if (!iso) return 'No expiry'
  return new Date(iso).toLocaleDateString()
}

function stacksLine(plan: HostingPlan | undefined) {
  if (!plan) return ''
  return visibleStacks(plan)
    .filter((s) => s.level === 'yes')
    .map((s) => s.label)
    .slice(0, 6)
    .join(' · ')
}

function goNewOrder() {
  void router.push({ name: 'portal-account-plans' })
}
</script>

<template>
  <section class="billing-panel">
    <div class="billing-head">
      <div class="p-banner" role="note">
        <strong>Billing.</strong>
        Subscriptions, invoices, and credits for your account.
      </div>
      <div class="billing-actions">
        <button type="button" class="btn-primary" @click="goNewOrder">New order</button>
      </div>
    </div>

    <p v-if="billingMsg" class="billing-message">{{ billingMsg }}</p>

    <div class="billing-grid">
      <div class="panel-card">
        <div class="card-head">
          <h2>Subscriptions</h2>
          <span class="count">{{ dash.subscriptions.length }}</span>
        </div>

        <p v-if="!dash.subscriptions.length" class="muted">
          No active subscription yet. Use <strong>New order</strong> to buy hosting.
        </p>

        <div v-else class="sub-list" role="list">
          <div v-for="sub in dash.subscriptions" :key="sub.id" class="sub-row" role="listitem">
            <div class="sub-main">
              <p class="title">
                <span class="dot" :style="{ background: accentFor(sub.plan_id) }" />
                {{ planName(sub.plan_id) }}
              </p>
              <p class="muted sub-meta">
                {{ formatCpu(sub.cpu_allocated) }} vCPU · {{ formatRamGb(sub.ram_allocated) }}
                <span class="sep">·</span> expires {{ expiryLabel(sub.expires_at) }}
                <span v-if="sub.billing_term_months" class="sep">·</span>
                <span v-if="sub.billing_term_months">{{ sub.billing_term_months }}-mo term</span>
              </p>
              <p v-if="stacksLine(planFor(sub.plan_id))" class="muted stacks">
                {{ stacksLine(planFor(sub.plan_id)) }}
              </p>
            </div>

            <div class="sub-right">
              <span class="status" :class="sub.status">{{ sub.status }}</span>
            </div>

            <div class="sub-actions">
              <div class="sub-actions-left">
                <button type="button" class="btn-primary" @click="emit('renew', sub.id)">
                  Renew {{ sub.billing_term_months && sub.billing_term_months !== 1 ? `${sub.billing_term_months} months` : '1 month' }}
                </button>
                <button
                  type="button"
                  class="btn-ghost"
                  @click="emit('toggleRenew', sub.id, !sub.auto_renew)"
                >
                  {{ sub.auto_renew ? 'Disable auto-renew' : 'Enable auto-renew' }}
                </button>
              </div>

              <div class="sub-actions-right">
                <select v-model="changePlanIdModel" class="select">
                  <option value="">Change plan…</option>
                  <option v-for="p in plans" :key="p.id" :value="p.id" :disabled="p.id === sub.plan_id">
                    {{ p.name }} — GHS {{ p.price_monthly }}
                  </option>
                </select>
                <button type="button" class="btn-ghost" @click="emit('changePlan', sub.id)">Apply</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="billing-side">
        <div class="panel-card">
          <h2>AI credits</h2>
          <p class="balance">{{ dash.credits.credits_remaining }}</p>
          <p class="muted">
            ≈
            {{
              (
                dash.credits.tokens_remaining ?? dash.credits.credits_remaining * 12000
              ).toLocaleString()
            }}
            tokens left. Short editor chats usually cost 1 credit; heavy runs cap at 2.
          </p>

          <div class="actions">
            <select v-model.number="topUpCreditsModel" class="select">
              <option :value="10">10 — GHS 10</option>
              <option :value="20">20 — GHS 20</option>
              <option :value="50">50 — GHS 50</option>
              <option :value="100">100 — GHS 100</option>
            </select>
            <button type="button" class="btn-primary" @click="emit('buyCredits')">
              Buy credits
            </button>
          </div>
        </div>

        <div class="panel-card">
          <h2>Invoices</h2>
          <p v-if="dash.momo" class="muted">
            Pay the IFNOTUS <strong>{{ dash.momo.network }} merchant</strong> number
            <strong>{{ dash.momo.number }}</strong>
            ({{ dash.momo.account_name }}). Open an invoice to pay, then share the transaction ID.
          </p>

          <p v-if="!invoices.length" class="muted mt">No invoices yet. Start a new order.</p>

          <div v-else class="inv-list" role="list">
            <div v-for="inv in invoices" :key="inv.id" class="inv-row" role="listitem">
              <div class="inv-main">
                <p class="inv-title">
                  {{ inv.invoice_number || inv.id.slice(0, 8) }}
                </p>
                <p class="muted inv-meta">
                  {{ inv.currency }} {{ inv.total_price }}
                  <span v-if="inv.domain_name"> · {{ inv.domain_name }}</span>
                  <span class="sep">·</span> {{ inv.payment_status }}
                  <span v-if="inv.provisioning_status === 'active'"> · live</span>
                  <span
                    v-else-if="
                      inv.provisioning_status === 'pending' || inv.payment_status === 'submitted'
                    "
                  >
                    · awaiting activation
                  </span>
                </p>
              </div>

              <div class="inv-right">
                <span class="status" :class="inv.payment_status">{{
                  inv.payment_status === 'paid'
                    ? 'Paid'
                    : inv.payment_status === 'submitted'
                      ? 'Awaiting confirm'
                      : inv.payment_status === 'pending'
                        ? 'Pending'
                        : inv.payment_status
                }}</span>
                <RouterLink class="btn-primary" :to="`/account/invoice/${inv.id}`">
                  {{ inv.payment_status === 'paid' ? 'View receipt' : 'Open invoice' }}
                </RouterLink>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.billing-panel { display: flex; flex-direction: column; gap: 1rem; width: 100%; }

.billing-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.p-banner {
  flex: 1 1 auto;
  padding: 0.85rem 1rem;
  border-radius: 0.9rem;
  background: color-mix(in srgb, var(--if-plan) 10%, var(--if-surface));
  border: 1px solid color-mix(in srgb, var(--if-plan) 25%, var(--if-border));
  font-size: 0.86rem;
  line-height: 1.45;
}
.p-banner strong { color: var(--p-accent, var(--if-plan)); }

.billing-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 0.65rem; }
.billing-message {
  margin: 0;
  padding: 0.7rem 1rem;
  border-radius: 0.85rem;
  border: 1px solid var(--if-border);
  background: color-mix(in srgb, var(--if-primary) 10%, var(--if-surface));
  color: var(--if-ink);
  font-size: 0.86rem;
}

.billing-grid {
  display: grid;
  gap: 1rem;
  align-items: start;
}
@media (min-width: 980px) {
  .billing-grid { grid-template-columns: minmax(0, 1fr) minmax(18rem, 26rem); }
}

.billing-side { display: flex; flex-direction: column; gap: 1rem; }

.panel-card {
  background: var(--if-surface);
  border: 1px solid var(--if-border);
  border-radius: 1rem;
  padding: 1.15rem 1.2rem;
  box-shadow: var(--shadow-card);
}

.panel-card h2 { margin: 0; font-size: 1.02rem; font-weight: 700; color: var(--if-ink); }

.card-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.count {
  min-width: 1.7rem;
  height: 1.7rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--p-accent, var(--if-primary));
  color: #fff;
  font-size: 0.72rem;
  font-weight: 800;
}

.muted { color: var(--if-muted); font-size: 0.84rem; margin: 0; }
.mt { margin-top: 0.75rem; }
.sep { padding: 0 0.35rem; color: color-mix(in srgb, var(--if-muted) 80%, transparent); }

.sub-list { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 0.85rem; }
.sub-row {
  border: 1px solid var(--if-border);
  border-radius: 0.95rem;
  padding: 1rem;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}
@media (min-width: 640px) {
  .sub-row { grid-template-columns: 1fr auto; align-items: start; }
}

.sub-main { min-width: 0; }
.title {
  margin: 0;
  font-weight: 750;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; display: inline-block; }

.sub-meta { margin-top: 0.35rem; line-height: 1.4; }
.stacks { margin-top: 0.35rem; font-size: 0.78rem; line-height: 1.35; }

.sub-right { display: flex; justify-content: flex-start; }
@media (min-width: 640px) {
  .sub-right { justify-content: flex-end; }
}

.status {
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.22rem 0.55rem;
  border-radius: 999px;
  background: #eef1f4;
  color: #5a6570;
  white-space: nowrap;
}
.status.active, .status.paid, .status.submitted, .status.ok { background: #e7f8ee; color: #0f7a45; }
.status.pending, .status.open { background: #fff4e5; color: #b54708; }

.sub-actions {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
@media (min-width: 800px) {
  .sub-actions { grid-column: 1 / -1; }
}
.sub-actions-left { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.sub-actions-right { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.85rem;
  align-items: center;
}

.balance {
  margin: 0.55rem 0 0.25rem;
  font-family: Sora, sans-serif;
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: var(--if-ink);
}

.inv-list { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 0.85rem; }
.inv-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
  padding: 1rem;
  border: 1px solid var(--if-border);
  border-radius: 0.95rem;
}
@media (min-width: 640px) {
  .inv-row { grid-template-columns: 1fr auto; align-items: center; }
}
.inv-title { margin: 0; font-weight: 800; }
.inv-meta { margin-top: 0.35rem; line-height: 1.4; }
.inv-right { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; justify-content: flex-start; }
@media (min-width: 640px) {
  .inv-right { justify-content: flex-end; }
}

.select {
  border: 1px solid var(--if-border);
  border-radius: 0.65rem;
  padding: 0.45rem 0.65rem;
  font: inherit;
  background: #fff;
}

.btn-primary, .btn-ghost {
  border: none;
  cursor: pointer;
  border-radius: 0.7rem;
  font: inherit;
  font-weight: 700;
  padding: 0.55rem 0.95rem;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.btn-primary { background: var(--p-accent, var(--if-primary)); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--if-primary-hover, #16304d); transform: translateY(-1px); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.btn-ghost { background: transparent; border: 1px solid var(--if-border); color: var(--if-ink); }
.btn-ghost:hover { background: color-mix(in srgb, var(--if-surface) 75%, white); }
</style>
