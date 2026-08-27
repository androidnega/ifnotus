<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { StaffOrderItem } from '@/types/staffPlatform'

const route = useRoute()
const router = useRouter()
const { can } = usePermissions()
const canConfirm = computed(() => can(Permission.CUSTOMERS_MANAGE))
const orders = ref<StaffOrderItem[]>([])
const paymentFilter = ref('submitted')
const confirmNotes = ref('')
const loading = ref(true)
const error = ref('')
const success = ref('')
const busyId = ref('')
const amountByOrder = ref<Record<string, string>>({})
const acctTotals = ref<{
  awaiting_confirm: number
  awaiting_confirm_count: number
  outstanding: number
  collected_period: number
} | null>(null)

const filterTabs = [
  { id: 'submitted', label: 'Awaiting confirm', icon: 'fa-clock' },
  { id: 'paid', label: 'Paid', icon: 'fa-circle-check' },
  { id: 'pending', label: 'Unpaid', icon: 'fa-file-invoice' },
  { id: 'failed', label: 'Rejected', icon: 'fa-circle-xmark' },
  { id: '', label: 'All', icon: 'fa-list' },
] as const

const awaitingCount = computed(
  () => orders.value.filter((o) => o.payment_status === 'submitted').length,
)

function money(n: number | string, currency = 'GHS') {
  return `${currency} ${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

async function loadSummary() {
  try {
    const { data } = await platformAdminApi.accountingSummary()
    acctTotals.value = data.totals
  } catch {
    acctTotals.value = null
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listOrders({
      payment_status: paymentFilter.value || undefined,
    })
    orders.value = data
    for (const o of data) {
      if (amountByOrder.value[o.id] == null) {
        amountByOrder.value[o.id] = String(o.total_price)
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load orders.'
  } finally {
    loading.value = false
  }
}

function openCustomer(id: string) {
  router.push({ name: 'platform-customers', query: { open: id } })
}

function openReceipt(id: string) {
  router.push({ name: 'platform-order-receipt', params: { id } })
}

function provisionLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'Hosting live'
  if (s === 'queued' || s === 'pending' || s === 'running') return 'Setting up…'
  if (s === 'failed') return 'Setup failed'
  if (s === 'n/a') return '—'
  return status || '—'
}

function paymentLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'submitted') return 'Awaiting confirmation'
  if (s === 'paid') return 'Paid'
  if (s === 'pending') return 'Invoice unpaid'
  if (s === 'failed') return 'Rejected'
  return status
}

function paymentIcon(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'submitted') return 'fa-clock'
  if (s === 'paid') return 'fa-circle-check'
  if (s === 'pending') return 'fa-file-invoice'
  if (s === 'failed') return 'fa-circle-xmark'
  return 'fa-receipt'
}

function provisionIcon(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'fa-server'
  if (s === 'failed') return 'fa-triangle-exclamation'
  if (s === 'queued' || s === 'pending' || s === 'running') return 'fa-spinner fa-spin'
  return 'fa-minus'
}

function orderCardTone(o: StaffOrderItem) {
  const pay = (o.payment_status || '').toLowerCase()
  if (pay === 'paid' && (o.provisioning_status || '').toLowerCase() === 'active') return 'live'
  if (pay === 'submitted') return 'submitted'
  if (pay === 'pending') return 'pending'
  if (pay === 'failed') return 'failed'
  if ((o.provisioning_status || '').toLowerCase() === 'failed') return 'failed'
  return pay || 'pending'
}

onMounted(() => {
  const s = route.query.status
  if (typeof s === 'string' && s) paymentFilter.value = s
  void loadSummary()
  void load()
})

watch(paymentFilter, load)

async function confirmPay(o: StaffOrderItem) {
  const expected = Number(o.total_price)
  const typed = (amountByOrder.value[o.id] || '').trim()
  const amount = typed ? Number(typed) : expected
  if (Number.isNaN(amount)) {
    error.value = 'Enter a valid amount received.'
    return
  }
  if (
    !confirm(
      `Confirm MoMo GHS ${amount} for ${o.invoice_number || o.id.slice(0, 8)}?\n\nThis will mark payment paid and activate hosting now. Wait until it finishes.`,
    )
  ) {
    return
  }
  busyId.value = o.id
  error.value = ''
  success.value = ''
  try {
    const { data } = await platformAdminApi.confirmOrderPayment(o.id, {
      amount_received: amount,
      notes: confirmNotes.value || undefined,
    })
    const status = (data?.provisioning_status || '').toLowerCase()
    if (status === 'active') {
      success.value = `Payment confirmed — hosting is live for ${o.customer_name || o.customer_email}.`
    } else if (status === 'failed') {
      error.value = 'Payment confirmed but hosting setup failed. Use Retry setup.'
    } else {
      success.value = `Payment confirmed. Hosting status: ${data?.provisioning_status || 'queued'}.`
    }
    confirmNotes.value = ''
    await load()
    await loadSummary()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not confirm payment.'
  } finally {
    busyId.value = ''
  }
}

async function retryProvision(o: StaffOrderItem) {
  if (!confirm(`Retry hosting setup for ${o.invoice_number || o.customer_email}? Wait until it finishes.`)) {
    return
  }
  busyId.value = o.id
  error.value = ''
  success.value = ''
  try {
    const { data } = await platformAdminApi.retryOrderProvision(o.id)
    const status = (data?.provisioning_status || '').toLowerCase()
    success.value =
      status === 'active'
        ? `Hosting is live for ${o.customer_name || o.customer_email}.`
        : `Retry finished with status: ${data?.provisioning_status}.`
    await load()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not retry setup.'
  } finally {
    busyId.value = ''
  }
}

async function rejectPay(o: StaffOrderItem) {
  if (!confirm(`Reject payment for ${o.invoice_number || o.customer_email}?`)) return
  busyId.value = o.id
  error.value = ''
  try {
    await platformAdminApi.rejectOrderPayment(o.id, {
      notes: confirmNotes.value || undefined,
    })
    success.value = 'Payment rejected.'
    await load()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not reject payment.'
  } finally {
    busyId.value = ''
  }
}
</script>

<template>
  <DashboardLayout flush>
    <div class="orders">
      <header class="orders-head">
        <UiPageHeader
          title="Orders & payments"
          lede="Confirm MoMo, activate hosting, and keep every payment on record."
        >
          <template #actions>
            <button type="button" class="head-btn" @click="router.push({ name: 'platform-accounting' })">
              <i class="fa-solid fa-chart-line" aria-hidden="true" />
              Accounting
            </button>
          </template>
        </UiPageHeader>
      </header>

      <div class="orders-body">
        <div v-if="acctTotals" class="stats-bar">
          <article class="stat-card tone-cash static">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-wallet" /></span>
            <div class="stat-body">
              <span class="stat-k">Collected this month</span>
              <span class="stat-v">{{ money(acctTotals.collected_period) }}</span>
              <span class="stat-s">MoMo &amp; cash in period</span>
            </div>
          </article>
          <article class="stat-card tone-await static">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-clock" /></span>
            <div class="stat-body">
              <span class="stat-k">Awaiting confirm</span>
              <span class="stat-v">{{ money(acctTotals.awaiting_confirm) }}</span>
              <span class="stat-s">{{ acctTotals.awaiting_confirm_count }} payment{{ acctTotals.awaiting_confirm_count === 1 ? '' : 's' }}</span>
            </div>
          </article>
          <article class="stat-card tone-pending static">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-file-invoice" /></span>
            <div class="stat-body">
              <span class="stat-k">Outstanding</span>
              <span class="stat-v">{{ money(acctTotals.outstanding) }}</span>
              <span class="stat-s">Unpaid invoices</span>
            </div>
          </article>
        </div>

        <section class="panel-card filters-card">
          <header class="panel-head">
            <span class="panel-icon tone-pending" aria-hidden="true"><i class="fa-solid fa-filter" /></span>
            <div>
              <h2>Filter orders</h2>
              <p class="panel-sub">Payment status</p>
            </div>
          </header>
          <div class="filter-tabs">
            <button
              v-for="tab in filterTabs"
              :key="tab.id || 'all'"
              type="button"
              class="filter-tab"
              :class="{ on: paymentFilter === tab.id }"
              @click="paymentFilter = tab.id"
            >
              <i class="fa-solid" :class="tab.icon" aria-hidden="true" />
              {{ tab.label }}
            </button>
          </div>
          <p v-if="paymentFilter === 'submitted' && !loading" class="flow-count">
            <i class="fa-solid fa-bell" aria-hidden="true" />
            {{ awaitingCount }} payment{{ awaitingCount === 1 ? '' : 's' }} waiting for confirmation
          </p>
        </section>

        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>
        <UiAlert v-else-if="success" tone="ok">{{ success }}</UiAlert>

        <section class="panel-card orders-panel">
          <header class="panel-head">
            <span class="panel-icon tone-cash" aria-hidden="true"><i class="fa-solid fa-cart-shopping" /></span>
            <div>
              <h2>Orders</h2>
              <p class="panel-sub">{{ loading ? 'Loading…' : `${orders.length} in this view` }}</p>
            </div>
          </header>

          <p v-if="loading" class="state-msg">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            Loading orders…
          </p>

          <div v-else class="order-list">
            <article
              v-for="o in orders"
              :key="o.id"
              class="order-card"
              :data-tone="orderCardTone(o)"
            >
              <header class="order-head">
                <div class="order-title">
                  <span class="order-badge" aria-hidden="true">
                    <i class="fa-solid" :class="paymentIcon(o.payment_status)" />
                  </span>
                  <div class="min0">
                    <p v-if="o.invoice_number" class="order-inv">{{ o.invoice_number }}</p>
                    <button type="button" class="order-who" @click="openCustomer(o.customer_id)">
                      <i class="fa-solid fa-user" aria-hidden="true" />
                      {{ o.customer_name || 'Customer' }}
                    </button>
                    <p class="order-email">{{ o.customer_email }}</p>
                  </div>
                </div>
                <div class="order-amount">
                  <span class="amount-k"><i class="fa-solid fa-coins" aria-hidden="true" /> Total</span>
                  <p class="price">{{ o.currency }} {{ o.total_price }}</p>
                  <button type="button" class="receipt-link" @click="openReceipt(o.id)">
                    <i class="fa-solid fa-file-invoice" aria-hidden="true" />
                    {{ o.payment_status === 'paid' ? 'View receipt' : 'View invoice' }}
                  </button>
                </div>
              </header>

              <p class="order-plan">
                <i class="fa-solid fa-box" aria-hidden="true" />
                {{ o.plan_name || 'Plan' }}
                <span v-if="o.domain_name"> · <i class="fa-solid fa-globe" aria-hidden="true" /> {{ o.domain_name }}</span>
                <span class="kind"> · {{ o.order_kind || 'hosting' }}</span>
              </p>

              <div class="order-badges">
                <span class="badge" :data-s="o.payment_status">
                  <i class="fa-solid" :class="paymentIcon(o.payment_status)" aria-hidden="true" />
                  {{ paymentLabel(o.payment_status) }}
                </span>
                <span class="badge" :data-p="o.provisioning_status">
                  <i class="fa-solid" :class="provisionIcon(o.provisioning_status)" aria-hidden="true" />
                  {{ provisionLabel(o.provisioning_status) }}
                </span>
              </div>

              <div class="order-meta">
                <span v-if="o.momo_transaction_id" class="meta-item momo">
                  <i class="fa-solid fa-mobile-screen" aria-hidden="true" />
                  <code>{{ o.momo_transaction_id }}</code>
                </span>
                <span v-if="o.customer_phone" class="meta-item">
                  <i class="fa-solid fa-phone" aria-hidden="true" />
                  {{ o.customer_phone }}
                </span>
                <span class="meta-item">
                  <i class="fa-regular fa-calendar" aria-hidden="true" />
                  {{ new Date(o.created_at).toLocaleString() }}
                </span>
              </div>

              <div
                v-if="canConfirm && o.payment_status !== 'paid' && o.payment_status !== 'failed'"
                class="activate-panel"
              >
                <p class="step-title">
                  <i class="fa-solid fa-bolt" aria-hidden="true" />
                  Confirm payment &amp; activate hosting
                </p>
                <div class="activate-row">
                  <label>
                    <span><i class="fa-solid fa-coins" aria-hidden="true" /> Amount received (GHS)</span>
                    <input
                      v-model="amountByOrder[o.id]"
                      type="text"
                      inputmode="decimal"
                      :placeholder="String(o.total_price)"
                    />
                  </label>
                  <label>
                    <span><i class="fa-solid fa-note-sticky" aria-hidden="true" /> Staff note (optional)</span>
                    <input v-model="confirmNotes" type="text" placeholder="Checked in MoMo app" />
                  </label>
                </div>
                <div class="activate-actions">
                  <button
                    type="button"
                    class="btn-go"
                    :disabled="busyId === o.id"
                    @click="confirmPay(o)"
                  >
                    <i
                      class="fa-solid"
                      :class="busyId === o.id ? 'fa-spinner fa-spin' : 'fa-check-double'"
                      aria-hidden="true"
                    />
                    {{ busyId === o.id ? 'Confirming & activating…' : 'Confirm & activate' }}
                  </button>
                  <button
                    type="button"
                    class="btn-reject"
                    :disabled="busyId === o.id"
                    @click="rejectPay(o)"
                  >
                    <i class="fa-solid fa-xmark" aria-hidden="true" />
                    Reject
                  </button>
                </div>
                <p class="hint">
                  <i class="fa-solid fa-circle-info" aria-hidden="true" />
                  Button stays busy until hosting is live. Do not close the page.
                </p>
              </div>

              <div
                v-else-if="canConfirm && o.payment_status === 'paid' && o.provisioning_status !== 'active' && o.provisioning_status !== 'n/a'"
                class="activate-panel warn"
              >
                <p class="step-title">
                  <i class="fa-solid fa-triangle-exclamation" aria-hidden="true" />
                  Hosting not live yet
                </p>
                <p class="hint">Payment is paid but setup did not finish. Retry once.</p>
                <button
                  type="button"
                  class="btn-go"
                  :disabled="busyId === o.id"
                  @click="retryProvision(o)"
                >
                  <i
                    class="fa-solid"
                    :class="busyId === o.id ? 'fa-spinner fa-spin' : 'fa-arrows-rotate'"
                    aria-hidden="true"
                  />
                  {{ busyId === o.id ? 'Retrying setup…' : 'Retry setup' }}
                </button>
              </div>

              <div v-else-if="o.payment_status === 'paid' && o.provisioning_status === 'active'" class="done-line">
                <i class="fa-solid fa-circle-check" aria-hidden="true" />
                Paid and hosting live.
                <button type="button" class="linkish" @click="openReceipt(o.id)">
                  <i class="fa-solid fa-receipt" aria-hidden="true" />
                  Receipt
                </button>
                <button type="button" class="linkish" @click="openCustomer(o.customer_id)">
                  <i class="fa-solid fa-user" aria-hidden="true" />
                  Open customer
                </button>
              </div>
            </article>

            <div v-if="!orders.length" class="empty">
              <i class="fa-regular fa-folder-open" aria-hidden="true" />
              <p>No orders in this view.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.orders {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
}
.orders-head {
  flex-shrink: 0;
  padding: 1rem 1.15rem 0.85rem;
  border-bottom: 1px solid #e2e8f0;
  background: var(--if-surface, #fff);
}
.dark .orders-head {
  border-bottom-color: #334155;
  background: #0f172a;
}
.orders-head :deep(.ui-page-header) { margin: 0; }
.orders-head :deep(h1) { font-size: 1.15rem; }
.head-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  background: #fff;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.45rem 0.75rem;
  cursor: pointer;
}
.head-btn:hover { background: #f8fafc; border-color: #94a3b8; }
.dark .head-btn {
  background: #1e293b;
  border-color: #475569;
  color: #e2e8f0;
}

.orders-body {
  flex: 1 1 auto;
  min-width: 0;
  padding: 1rem 1.15rem 1.75rem;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.stats-bar {
  display: grid;
  gap: 0.65rem;
  grid-template-columns: 1fr;
}
@media (min-width: 640px) {
  .stats-bar { grid-template-columns: repeat(3, 1fr); }
}

.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #fff;
  padding: 0.9rem 1rem;
  min-width: 0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.stat-icon {
  flex: 0 0 auto;
  width: 2.4rem;
  height: 2.4rem;
  border-radius: 0.75rem;
  display: grid;
  place-items: center;
  font-size: 1rem;
}
.stat-body { min-width: 0; flex: 1; }
.stat-k {
  display: block;
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
}
.stat-v {
  display: block;
  margin-top: 0.2rem;
  font-size: clamp(1rem, 2.5vw, 1.2rem);
  font-weight: 800;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.stat-s {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.72rem;
  color: #64748b;
}
.tone-cash .stat-icon { background: #d1fae5; color: #047857; }
.tone-await .stat-icon { background: #fef3c7; color: #b45309; }
.tone-pending .stat-icon { background: #e0e7ff; color: #4338ca; }
.tone-cash { background: linear-gradient(180deg, #ecfdf5 0%, #fff 70%); border-color: #a7f3d0; }
.tone-await { background: linear-gradient(180deg, #fffbeb 0%, #fff 70%); border-color: #fcd34d; }
.tone-pending { background: linear-gradient(180deg, #eef2ff 0%, #fff 70%); }

.panel-card {
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #fff;
  padding: 0.9rem 1rem 1.05rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.panel-head {
  display: flex;
  align-items: flex-start;
  gap: 0.7rem;
  margin-bottom: 0.65rem;
}
.panel-icon {
  width: 2.15rem;
  height: 2.15rem;
  border-radius: 0.65rem;
  display: grid;
  place-items: center;
  font-size: 0.9rem;
  flex: 0 0 auto;
}
.panel-head h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}
.panel-sub {
  margin: 0.15rem 0 0;
  font-size: 0.78rem;
  color: #64748b;
}

.filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 650;
  padding: 0.38rem 0.8rem;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.filter-tab.on {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.flow-count {
  margin: 0.75rem 0 0;
  font-size: 0.8rem;
  font-weight: 650;
  color: #b45309;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.state-msg {
  margin: 0;
  padding: 1.5rem 1rem;
  text-align: center;
  color: #64748b;
  font-size: 0.875rem;
}
.state-msg i { margin-right: 0.35rem; }

.order-list {
  display: grid;
  gap: 0.75rem;
}

.order-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.9rem;
  background: #fff;
  padding: 0.9rem 1rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  border-left: 3px solid #cbd5e1;
}
.order-card[data-tone='live'] { border-left-color: #10b981; }
.order-card[data-tone='submitted'] { border-left-color: #f59e0b; }
.order-card[data-tone='pending'] { border-left-color: #6366f1; }
.order-card[data-tone='failed'] { border-left-color: #ef4444; }

.order-head {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr;
}
@media (min-width: 720px) {
  .order-head {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: start;
  }
}
.order-title {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  min-width: 0;
}
.order-badge {
  width: 2rem;
  height: 2rem;
  border-radius: 0.55rem;
  background: #f1f5f9;
  color: #475569;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 0.85rem;
}
.min0 { min-width: 0; }
.order-inv {
  margin: 0;
  font-family: ui-monospace, monospace;
  font-size: 0.76rem;
  font-weight: 700;
  color: #64748b;
}
.order-who {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.15rem;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  font-weight: 650;
  color: #0f172a;
  font-size: 0.92rem;
  text-align: left;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.order-who:hover { color: #2563eb; }
.order-email {
  margin: 0.15rem 0 0;
  font-size: 0.78rem;
  color: #64748b;
  overflow-wrap: anywhere;
}
.order-amount { text-align: left; }
@media (min-width: 720px) {
  .order-amount { text-align: right; }
}
.amount-k {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94a3b8;
}
.price {
  margin: 0.15rem 0 0;
  font-size: 1.1rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
}
.receipt-link {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.35rem;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 0.5rem;
  padding: 0.28rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
}
.receipt-link:hover { background: #dbeafe; }

.order-plan {
  margin: 0.65rem 0 0;
  font-size: 0.78rem;
  color: #64748b;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}
.kind { color: #94a3b8; }

.order-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.55rem;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border-radius: 999px;
  padding: 0.22rem 0.6rem;
  font-size: 0.68rem;
  font-weight: 650;
  background: #f1f5f9;
  color: #334155;
}
.badge[data-s='submitted'] { background: #fef3c7; color: #92400e; }
.badge[data-s='paid'] { background: #d1fae5; color: #065f46; }
.badge[data-s='failed'] { background: #fee2e2; color: #991b1b; }
.badge[data-p='active'] { background: #dbeafe; color: #1e40af; }
.badge[data-p='failed'] { background: #fee2e2; color: #991b1b; }
.badge[data-p='queued'],
.badge[data-p='pending'],
.badge[data-p='running'] { background: #ffedd5; color: #9a3412; }

.order-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  margin-top: 0.6rem;
  padding-top: 0.6rem;
  border-top: 1px solid #eef2f7;
  font-size: 0.75rem;
  color: #64748b;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.momo code {
  font-size: 0.72rem;
  color: #047857;
  background: #ecfdf5;
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
}

.activate-panel {
  margin-top: 0.85rem;
  padding: 0.85rem 0.9rem;
  border-radius: 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.activate-panel.warn {
  background: #fff7ed;
  border-color: #fed7aa;
}
.step-title {
  margin: 0 0 0.55rem;
  font-size: 0.82rem;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.activate-row {
  display: grid;
  gap: 0.55rem;
  grid-template-columns: 1fr;
}
@media (min-width: 560px) {
  .activate-row { grid-template-columns: 1fr 1fr; }
}
.activate-row label span {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.activate-row label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.68rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.activate-row input {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.5rem 0.65rem;
  font-size: 0.875rem;
  background: #fff;
  color: inherit;
}
.activate-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.btn-go,
.btn-reject {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.btn-go {
  border: 0;
  border-radius: 0.55rem;
  background: #2563eb;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 650;
  padding: 0.55rem 1rem;
  cursor: pointer;
}
.btn-go:disabled { opacity: 0.55; cursor: wait; }
.btn-reject {
  border: 1px solid #fecaca;
  border-radius: 0.55rem;
  background: #fff;
  color: #b91c1c;
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.5rem 0.85rem;
  cursor: pointer;
}
.hint {
  margin: 0.55rem 0 0;
  font-size: 0.75rem;
  color: #64748b;
  display: flex;
  align-items: flex-start;
  gap: 0.35rem;
}
.done-line {
  margin-top: 0.75rem;
  padding-top: 0.65rem;
  border-top: 1px solid #d1fae5;
  font-size: 0.8rem;
  color: #065f46;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  font-weight: 650;
}
.linkish {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border: 0;
  background: none;
  color: #2563eb;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}

.empty {
  text-align: center;
  padding: 2.5rem 1rem;
  color: #94a3b8;
  font-size: 0.9rem;
  border: 1px dashed #cbd5e1;
  border-radius: 0.85rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.45rem;
}
.empty i { font-size: 1.5rem; opacity: 0.85; }
.empty p { margin: 0; }

.dark .stat-card,
.dark .panel-card,
.dark .order-card,
.dark .activate-panel,
.dark .activate-row input,
.dark .filter-tab,
.dark .head-btn {
  background: #0f172a;
  border-color: #334155;
  color: #e2e8f0;
}
.dark .stat-v,
.dark .panel-head h2,
.dark .order-who,
.dark .price,
.dark .step-title { color: #f8fafc; }
.dark .filter-tab.on {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.dark .receipt-link {
  background: #1e3a8a;
  border-color: #1d4ed8;
  color: #bfdbfe;
}
</style>
