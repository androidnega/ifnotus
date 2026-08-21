<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
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
    <div class="p-banner" role="note">
      <strong>Billing.</strong>
      Subscriptions, invoices, and credits stay on this login — same pattern as a classic client area.
    </div>

    <!-- UltraHost-style: New Order from account (checkout collects domain / student surname there) -->
    <div class="panel-card order-cta">
      <div>
        <h2>Order hosting</h2>
        <p class="muted mt">
          Pick a pack, choose a domain (or student address) during checkout, then pay the invoice.
          Surname for student sites is only asked in that flow — not after hosting is live.
        </p>
      </div>
      <button type="button" class="btn-primary" @click="goNewOrder">New order</button>
    </div>

    <div class="panel-card">
      <div class="card-head">
        <h2>Subscriptions</h2>
        <span class="count">{{ dash.subscriptions.length }}</span>
      </div>
      <p v-if="!dash.subscriptions.length" class="muted mt">
        No active subscription yet. Use <strong>New order</strong> to buy hosting.
      </p>
      <ul v-else class="sub-list">
        <li v-for="sub in dash.subscriptions" :key="sub.id" class="sub-card">
          <div class="sub-top">
            <div>
              <p class="title">
                <span class="dot" :style="{ background: accentFor(sub.plan_id) }" />
                {{ planName(sub.plan_id) }}
              </p>
              <p class="muted">
                {{ formatCpu(sub.cpu_allocated) }} vCPU · {{ formatRamGb(sub.ram_allocated) }} ·
                expires {{ expiryLabel(sub.expires_at) }}
              </p>
              <p v-if="stacksLine(planFor(sub.plan_id))" class="muted stacks">
                {{ stacksLine(planFor(sub.plan_id)) }}
              </p>
            </div>
            <span class="status" :class="sub.status">{{ sub.status }}</span>
          </div>
          <div class="actions">
            <button type="button" class="btn-primary" @click="emit('renew', sub.id)">Renew 30 days</button>
            <button type="button" class="btn-ghost" @click="emit('toggleRenew', sub.id, !sub.auto_renew)">
              {{ sub.auto_renew ? 'Disable auto-renew' : 'Enable auto-renew' }}
            </button>
          </div>
          <div class="actions">
            <select v-model="changePlanIdModel" class="select">
              <option value="">Change plan…</option>
              <option
                v-for="p in plans"
                :key="p.id"
                :value="p.id"
                :disabled="p.id === sub.plan_id"
              >
                {{ p.name }} — GHS {{ p.price_monthly }}
              </option>
            </select>
            <button type="button" class="btn-ghost" @click="emit('changePlan', sub.id)">Apply</button>
          </div>
        </li>
      </ul>
      <p v-if="billingMsg" class="msg mt">{{ billingMsg }}</p>
    </div>

    <div class="panel-card">
      <h2>AI credits</h2>
      <p class="balance">{{ dash.credits.credits_remaining }}</p>
      <p class="muted">
        ≈ {{ (dash.credits.tokens_remaining ?? dash.credits.credits_remaining * 12000).toLocaleString() }} tokens left.
        Short editor chats usually cost 1 credit; heavy runs cap at 2.
      </p>
      <div class="actions mt">
        <select v-model.number="topUpCreditsModel" class="select">
          <option :value="10">10 — GHS 10</option>
          <option :value="20">20 — GHS 20</option>
          <option :value="50">50 — GHS 50</option>
          <option :value="100">100 — GHS 100</option>
        </select>
        <button type="button" class="btn-primary" @click="emit('buyCredits')">Buy credits</button>
      </div>
    </div>

    <div class="panel-card">
      <h2>Invoices</h2>
      <p v-if="dash.momo" class="muted mt">
        Pay the IFNOTUS <strong>{{ dash.momo.network }} merchant</strong> number
        <strong>{{ dash.momo.number }}</strong>
        ({{ dash.momo.account_name }}). Open an invoice to pay, then share the transaction ID.
      </p>
      <p v-if="!invoices.length" class="muted mt">No invoices yet. Start a new order.</p>
      <ul v-else class="sub-list">
        <li v-for="inv in invoices" :key="inv.id" class="sub-card">
          <div class="sub-top">
            <div>
              <p class="title">{{ inv.invoice_number || inv.id.slice(0, 8) }}</p>
              <p class="muted">
                {{ inv.currency }} {{ inv.total_price }}
                <span v-if="inv.domain_name"> · {{ inv.domain_name }}</span>
                · {{ inv.payment_status }}
                <span v-if="inv.provisioning_status === 'active'"> · live</span>
                <span v-else-if="inv.provisioning_status === 'pending' || inv.payment_status === 'submitted'">
                  · awaiting activation
                </span>
              </p>
            </div>
            <span class="status" :class="inv.payment_status">{{ inv.payment_status }}</span>
          </div>
          <div class="actions">
            <button type="button" class="btn-primary" @click="emit('openInvoice', inv.id)">Open invoice</button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.billing-panel { display: flex; flex-direction: column; gap: 1rem; }
.p-banner {
  padding: 0.85rem 1rem;
  border-radius: 0.85rem;
  background: color-mix(in srgb, var(--if-plan) 10%, var(--if-surface));
  border: 1px solid color-mix(in srgb, var(--if-plan) 25%, var(--if-border));
  font-size: 0.84rem;
  line-height: 1.45;
}
.p-banner strong { color: var(--p-accent, var(--if-plan)); }
.panel-card {
  background: var(--if-surface);
  border: 1px solid var(--if-border);
  border-radius: 1rem;
  padding: 1.15rem 1.2rem;
  box-shadow: var(--shadow-card);
}
.order-cta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.panel-card h2 { margin: 0; font-size: 1.02rem; font-weight: 650; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.count {
  min-width: 1.5rem;
  height: 1.5rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--p-accent, var(--if-plan));
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
}
.sub-list { list-style: none; margin: 0.85rem 0 0; padding: 0; display: grid; gap: 0.75rem; }
.sub-card {
  border: 1px solid var(--if-border);
  border-radius: 0.85rem;
  padding: 0.95rem 1rem;
}
.sub-top { display: flex; justify-content: space-between; gap: 0.75rem; align-items: flex-start; }
.title {
  margin: 0;
  font-weight: 650;
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; display: inline-block; }
.status {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  background: #eef1f4;
  color: #5a6570;
}
.status.active, .status.paid, .status.submitted { background: #e7f8ee; color: #0f7a45; }
.actions { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; align-items: center; }
.balance {
  margin: 0.65rem 0 0.25rem;
  font-family: Sora, sans-serif;
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: var(--if-ink);
}
.muted { color: var(--if-muted); font-size: 0.84rem; margin: 0; }
.stacks { margin-top: 0.35rem; font-size: 0.78rem; line-height: 1.35; }
.msg { color: var(--if-ink); font-size: 0.84rem; margin: 0; }
.mt { margin-top: 0.75rem; }
.select { border: 1px solid var(--if-border); border-radius: 0.65rem; padding: 0.45rem 0.65rem; font: inherit; background: #fff; }
.btn-primary, .btn-ghost {
  border: none;
  cursor: pointer;
  border-radius: 0.7rem;
  font: inherit;
  font-weight: 650;
  padding: 0.5rem 0.85rem;
}
.btn-primary { background: var(--p-accent, var(--if-primary)); color: #fff; }
.btn-ghost { background: transparent; border: 1px solid var(--if-border); color: var(--if-ink); }
</style>
