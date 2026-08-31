<script setup lang="ts">
import { onMounted, ref, computed, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { useAuthStore } from '@/stores/auth'
import { isPlatformOwner } from '@/lib/roles'
import type { StaffOrderItem } from '@/types/staffPlatform'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { can } = usePermissions()
const canConfirm = computed(() => isPlatformOwner(auth.user) || can(Permission.BILLING_MANAGE))
const canOps = computed(() => isPlatformOwner(auth.user) || can(Permission.PLATFORM_OPS))
const canSeeBilling = computed(() => isPlatformOwner(auth.user) || can(Permission.BILLING_VIEW))
const canEditSubdomain = computed(() => isPlatformOwner(auth.user) || can(Permission.DOMAINS_WRITE))
const orders = ref<StaffOrderItem[]>([])
const paymentFilter = ref('submitted')
const searchQuery = ref('')
const confirmNotes = ref('')
const loading = ref(true)
const error = ref('')
const success = ref('')
const busyId = ref('')
const copiedId = ref<string | null>(null)
const copiedPhoneId = ref<string | null>(null)
const copiedRefId = ref<string | null>(null)
const amountByOrder = ref<Record<string, string>>({})
const domainByOrder = ref<Record<string, string>>({})
const paymentMethodByOrder = ref<Record<string, string>>({})
const editingDomainId = ref<string | null>(null)

const showNoteHelp = ref(false)

// Provisioning progress simulation
const progressPercent = ref(0)
const progressStage = ref('')
let progressInterval: number | null = null

const acctTotals = ref<{
  awaiting_confirm: number
  awaiting_confirm_count: number
  outstanding: number
  outstanding_count: number
  collected_period: number
  paid_count_period: number
  failed_count: number
} | null>(null)

const filterTabs = [
  { id: 'submitted', label: 'Awaiting confirm', icon: 'fa-clock' },
  { id: 'paid', label: 'Paid', icon: 'fa-circle-check' },
  { id: 'pending', label: 'Unpaid invoices', icon: 'fa-file-invoice' },
  { id: 'failed', label: 'Rejected', icon: 'fa-circle-xmark' },
  { id: '', label: 'All orders', icon: 'fa-list' },
] as const

function tabBadgeCount(tabId: string): number {
  if (!acctTotals.value) return 0
  if (tabId === 'submitted') return acctTotals.value.awaiting_confirm_count || 0
  if (tabId === 'paid') return acctTotals.value.paid_count_period || 0
  if (tabId === 'pending') return acctTotals.value.outstanding_count || 0
  if (tabId === 'failed') return acctTotals.value.failed_count || 0
  return 0
}

const awaitingCount = computed(
  () => orders.value.filter((o) => o.payment_status === 'submitted').length,
)

// LIVE SEARCH FILTER
const filteredOrders = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return orders.value

  return orders.value.filter((o) => {
    const inv = (o.invoice_number || '').toLowerCase()
    const momo = (o.momo_transaction_id || '').toLowerCase()
    const payRef = (o.paystack_reference || '').toLowerCase()
    const name = (o.customer_name || '').toLowerCase()
    const email = (o.customer_email || '').toLowerCase()
    const phone = (o.customer_phone || '').toLowerCase()
    const dom = (o.domain_name || domainByOrder.value[o.id] || '').toLowerCase()
    const plan = (o.plan_name || '').toLowerCase()
    const id = (o.id || '').toLowerCase()
    const amount = String(o.total_price || '')

    return (
      inv.includes(q) ||
      momo.includes(q) ||
      payRef.includes(q) ||
      name.includes(q) ||
      email.includes(q) ||
      phone.includes(q) ||
      dom.includes(q) ||
      plan.includes(q) ||
      id.includes(q) ||
      amount.includes(q)
    )
  })
})

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
      if (domainByOrder.value[o.id] == null) {
        domainByOrder.value[o.id] = o.domain_name || ''
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load orders.'
  } finally {
    loading.value = false
  }
}

function setFilter(tabId: string) {
  paymentFilter.value = tabId
  void router.replace({
    query: {
      ...route.query,
      status: tabId || undefined,
    },
  })
}

function copyRef(id: string, code: string) {
  navigator.clipboard.writeText(code)
  copiedRefId.value = id
  setTimeout(() => {
    if (copiedRefId.value === id) copiedRefId.value = null
  }, 2000)
}

function copyMomo(id: string, code: string) {
  navigator.clipboard.writeText(code)
  copiedId.value = id
  setTimeout(() => {
    if (copiedId.value === id) copiedId.value = null
  }, 2000)
}

function copyPhone(id: string, phone: string) {
  navigator.clipboard.writeText(phone)
  copiedPhoneId.value = id
  setTimeout(() => {
    if (copiedPhoneId.value === id) copiedPhoneId.value = null
  }, 2000)
}

function toggleDomainEdit(orderId: string) {
  editingDomainId.value = editingDomainId.value === orderId ? null : orderId
}

function openCustomer(id: string) {
  router.push({ name: 'platform-customers', query: { open: id } })
}

function openReceipt(id: string) {
  router.push({ name: 'platform-order-receipt', params: { id } })
}

function provisionLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'Live'
  if (s === 'queued' || s === 'pending' || s === 'running') return 'Setting up…'
  if (s === 'failed') return 'Failed'
  if (s === 'n/a') return '—'
  return status || '—'
}

function paymentLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'submitted') return 'Awaiting confirm'
  if (s === 'paid') return 'Paid'
  if (s === 'pending') return 'Unpaid'
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

function isStudentPlan(o: StaffOrderItem) {
  const name = (o.plan_name || '').toLowerCase()
  return name.includes('student') || name.includes('starter') || name.includes('free')
}

function startProgressSimulation() {
  progressPercent.value = 8
  progressStage.value = 'Validating MoMo payment & ledger entry…'
  
  if (progressInterval) clearInterval(progressInterval)
  progressInterval = window.setInterval(() => {
    if (progressPercent.value < 28) {
      progressPercent.value += 4
      progressStage.value = 'Validating MoMo payment & ledger entry…'
    } else if (progressPercent.value < 55) {
      progressPercent.value += 3
      progressStage.value = 'Allocating Linux user & ISPConfig webroot…'
    } else if (progressPercent.value < 80) {
      progressPercent.value += 2
      progressStage.value = 'Configuring Nginx vhost, DNS records & SSL certs…'
    } else if (progressPercent.value < 95) {
      progressPercent.value += 1
      progressStage.value = 'Provisioning customer mailbox & fPanel alias…'
    }
  }, 600)
}

function stopProgressSimulation(finalSuccess = true) {
  if (progressInterval) {
    clearInterval(progressInterval)
    progressInterval = null
  }
  if (finalSuccess) {
    progressPercent.value = 100
    progressStage.value = 'Hosting is now live and fully provisioned!'
  }
}

onMounted(() => {
  const s = route.query.status
  if (typeof s === 'string' && s) {
    paymentFilter.value = s
  }
  void loadSummary()
  void load()
})

onUnmounted(() => {
  if (progressInterval) clearInterval(progressInterval)
})

watch(
  () => route.query.status,
  (s) => {
    if (typeof s === 'string') {
      paymentFilter.value = s
    } else if (s === undefined && paymentFilter.value !== '') {
      paymentFilter.value = ''
    }
  },
)

watch(paymentFilter, load)

async function confirmPay(o: StaffOrderItem) {
  const expected = Number(o.total_price)
  const typed = (amountByOrder.value[o.id] || '').trim()
  const domain = (domainByOrder.value[o.id] || '').trim()
  const method = paymentMethodByOrder.value[o.id] || 'momo'
  const isComp = method === 'complimentary' || method === 'free'
  const amount = isComp ? (typed ? Number(typed) : 0) : (typed ? Number(typed) : expected)
  const methodLabel = isComp ? 'Complimentary Free Grant (0.00 GHS)' : (method === 'physical_cash' ? 'Physical Cash (Office Desk)' : (method === 'bank' ? 'Bank Deposit' : 'Mobile Money'))

  if (Number.isNaN(amount)) {
    error.value = 'Enter a valid amount received.'
    return
  }
  if (
    !confirm(
      `Confirm ${methodLabel} GHS ${amount} for ${o.invoice_number || o.id.slice(0, 8)}?${domain ? `\nDomain/Subdomain: ${domain}` : ''}\n\nThis will accept the billing and mark payment as paid. The hosting operator will activate hosting once accepted.`,
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
      domain_name: domain || undefined,
      payment_method: method,
    })
    const status = (data?.provisioning_status || '').toLowerCase()
    if (status === 'active') {
      success.value = `Payment verified (${methodLabel}) — hosting is active on ${domain || o.domain_name || 'domain'}.`
    } else {
      success.value = `Billing accepted & payment confirmed (${methodLabel}). Order is ready for hosting activation by the hosting operator.`
    }
    confirmNotes.value = ''
    editingDomainId.value = null
    await load()
    await loadSummary()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not confirm payment.'
  } finally {
    busyId.value = ''
  }
}

async function activateHosting(o: StaffOrderItem) {
  const domain = (domainByOrder.value[o.id] || o.domain_name || 'hosting').trim()
  if (!confirm(`Activate and provision hosting for ${domain} (${o.invoice_number || o.customer_email})?`)) {
    return
  }
  busyId.value = o.id
  error.value = ''
  success.value = ''
  startProgressSimulation()
  try {
    const { data } = await platformAdminApi.activateOrderHosting(o.id)
    stopProgressSimulation(true)
    const status = (data?.provisioning_status || '').toLowerCase()
    success.value =
      status === 'active'
        ? `Hosting successfully activated and live on ${domain}!`
        : `Activation queued. Status: ${data?.provisioning_status}.`
    await load()
  } catch (e: unknown) {
    stopProgressSimulation(false)
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not activate hosting.'
  } finally {
    setTimeout(() => {
      busyId.value = ''
      progressPercent.value = 0
    }, 1200)
  }
}

async function retryProvision(o: StaffOrderItem) {
  if (!confirm(`Retry hosting setup for ${o.invoice_number || o.customer_email}?`)) {
    return
  }
  busyId.value = o.id
  error.value = ''
  success.value = ''
  startProgressSimulation()
  try {
    const { data } = await platformAdminApi.retryOrderProvision(o.id)
    stopProgressSimulation(true)
    const status = (data?.provisioning_status || '').toLowerCase()
    success.value =
      status === 'active'
        ? `Hosting is live for ${o.customer_name || o.customer_email}.`
        : `Retry finished with status: ${data?.provisioning_status}.`
    await load()
  } catch (e: unknown) {
    stopProgressSimulation(false)
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not retry setup.'
  } finally {
    setTimeout(() => {
      busyId.value = ''
      progressPercent.value = 0
    }, 1200)
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
    success.value = 'Payment marked as rejected.'
    await load()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not reject payment.'
  } finally {
    busyId.value = ''
  }
}

async function toggleComplimentaryStatus(o: StaffOrderItem) {
  const currentMethod = (o.payment_method || '').toLowerCase()
  const isComp = currentMethod === 'staff' || currentMethod === 'complimentary' || currentMethod === 'free'
  const newMethod = isComp ? 'momo' : 'complimentary'
  const promptText = isComp
    ? `Switch invoice ${o.invoice_number || o.id.slice(0, 8)} from Complimentary back to regular paid?`
    : `Grant invoice ${o.invoice_number || o.id.slice(0, 8)} as Complimentary Free Grant? This will remove it from cash revenue and track it under complimentary accounting.`

  if (!confirm(promptText)) return
  busyId.value = o.id
  error.value = ''
  try {
    await platformAdminApi.updateOrderPaymentStatus(o.id, {
      payment_method: newMethod,
      amount_received: isComp ? Number(o.total_price) : 0,
      notes: isComp ? 'Reverted from complimentary grant' : 'Converted to complimentary grant by billing agent',
    })
    success.value = `Order payment method updated to ${newMethod}.`
    await load()
    await loadSummary()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not update payment method.'
  } finally {
    busyId.value = ''
  }
}
</script>

<template>
  <DashboardLayout flush>
    <div class="orders">
      <!-- HEADER -->
      <header class="orders-head">
        <UiPageHeader
          title="Orders &amp; Payments"
          lede="Confirm MoMo transactions, customize student subdomains, and activate tenant hosting."
        >
          <template #actions>
            <button type="button" class="head-btn" @click="load">
              <i class="fa-solid fa-arrows-rotate" :class="{ 'fa-spin': loading }" aria-hidden="true" />
              Refresh
            </button>
            <button v-if="canSeeBilling" type="button" class="head-btn" @click="router.push({ name: 'platform-accounting' })">
              <i class="fa-solid fa-chart-line" aria-hidden="true" />
              Accounting
            </button>
          </template>
        </UiPageHeader>
      </header>

      <div class="orders-body">
        <!-- FINANCIAL METRICS STATS BAR (VISIBLE ONLY TO BILLING AUTHORIZED ROLES) -->
        <div v-if="acctTotals && canSeeBilling" class="stats-bar">
          <article class="stat-card tone-await">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-clock" /></span>
            <div class="stat-body">
              <span class="stat-k">Awaiting Confirm</span>
              <span class="stat-v">{{ money(acctTotals.awaiting_confirm) }}</span>
              <span class="stat-s">{{ acctTotals.awaiting_confirm_count }} MoMo submission{{ acctTotals.awaiting_confirm_count === 1 ? '' : 's' }} to verify</span>
            </div>
          </article>
          <article class="stat-card tone-cash">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-wallet" /></span>
            <div class="stat-body">
              <span class="stat-k">Collected this month</span>
              <span class="stat-v">{{ money(acctTotals.collected_period) }}</span>
              <span class="stat-s">{{ acctTotals.paid_count_period }} completed &amp; active hosting{{ acctTotals.paid_count_period === 1 ? '' : 's' }}</span>
            </div>
          </article>
          <article class="stat-card tone-pending">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-file-invoice" /></span>
            <div class="stat-body">
              <span class="stat-k">Unpaid Invoices</span>
              <span class="stat-v">{{ money(acctTotals.outstanding) }}</span>
              <span class="stat-s">{{ acctTotals.outstanding_count }} proforma awaiting payment</span>
            </div>
          </article>
        </div>

        <!-- SEARCH AND FILTER BAR -->
        <section class="panel-card filters-card">
          <!-- TOP ROW: LIVE SEARCH INPUT -->
          <div class="search-bar-wrap">
            <div class="search-input-box">
              <i class="fa-solid fa-magnifying-glass search-icon" aria-hidden="true" />
              <input
                v-model="searchQuery"
                type="text"
                class="search-input"
                placeholder="Live search by Sending Ref (e.g. IF7578), MoMo Tx ID, customer name, email, phone, domain…"
              />
              <button
                v-if="searchQuery"
                type="button"
                class="search-clear-btn"
                title="Clear search"
                @click="searchQuery = ''"
              >
                <i class="fa-solid fa-xmark" aria-hidden="true" />
              </button>
            </div>
            <div v-if="searchQuery" class="search-match-tag">
              <span>Found <strong>{{ filteredOrders.length }}</strong> match{{ filteredOrders.length === 1 ? '' : 'es' }}</span>
            </div>
          </div>

          <!-- BOTTOM ROW: TABS & QUEUE SUMMARY -->
          <div class="filters-row">
            <div class="filter-tabs">
              <button
                v-for="tab in filterTabs"
                :key="tab.id || 'all'"
                type="button"
                class="filter-tab"
                :class="{ on: paymentFilter === tab.id }"
                @click="setFilter(tab.id)"
              >
                <i class="fa-solid" :class="tab.icon" aria-hidden="true" />
                <span>{{ tab.label }}</span>
                <span
                  v-if="tabBadgeCount(tab.id) > 0"
                  class="tab-badge"
                  :class="{ 'badge-sub': tab.id === 'submitted', 'badge-unpaid': tab.id === 'pending' }"
                >
                  {{ tabBadgeCount(tab.id) }}
                </span>
              </button>
            </div>
            <p v-if="paymentFilter === 'submitted' && !loading" class="flow-count">
              <i class="fa-solid fa-bolt" aria-hidden="true" />
              <span><strong>{{ awaitingCount }}</strong> order{{ awaitingCount === 1 ? '' : 's' }} ready for clearance</span>
            </p>
          </div>
        </section>

        <!-- ALERTS -->
        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>
        <UiAlert v-else-if="success" tone="ok">{{ success }}</UiAlert>

        <!-- ORDERS LIST -->
        <section class="panel-card orders-panel">
          <header class="panel-head">
            <div class="panel-head-text">
              <h2>Order Queue</h2>
              <p class="panel-sub">
                {{ loading ? 'Loading orders…' : `${filteredOrders.length} order records in view` }}
                <span v-if="searchQuery && orders.length !== filteredOrders.length"> (filtered from {{ orders.length }})</span>
              </p>
            </div>
          </header>

          <div v-if="loading" class="state-msg">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <span>Fetching order records…</span>
          </div>

          <div v-else-if="filteredOrders.length" class="order-list">
            <article
              v-for="o in filteredOrders"
              :key="o.id"
              class="order-card-slim"
              :class="{ 'is-paid': o.payment_status === 'paid', 'is-active': o.provisioning_status === 'active' }"
            >
              <!-- TOP STRIP: INVOICE & CUSTOMER INFO + AMOUNT -->
              <div class="card-main-row">
                <!-- CUSTOMER & INVOICE -->
                <div class="customer-info-block">
                  <div class="inv-chip-row">
                    <span class="inv-badge">{{ o.invoice_number || o.id.slice(0, 8) }}</span>
                    <span class="kind-badge">{{ o.order_kind || 'hosting' }}</span>
                    <span class="date-badge">
                      <i class="fa-regular fa-clock" aria-hidden="true" />
                      {{ new Date(o.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }}
                    </span>
                  </div>

                  <div class="customer-details">
                    <button type="button" class="customer-name-btn" @click="openCustomer(o.customer_id)">
                      <i class="fa-solid fa-user-circle" aria-hidden="true" />
                      <span>{{ o.customer_name || 'Customer' }}</span>
                    </button>
                    <span class="divider">·</span>
                    <a :href="`mailto:${o.customer_email}`" class="customer-email">
                      <i class="fa-solid fa-envelope" aria-hidden="true" />
                      {{ o.customer_email }}
                    </a>
                    <span v-if="o.customer_phone" class="divider">·</span>
                    <div v-if="o.customer_phone" class="customer-phone-wrap">
                      <a :href="`tel:${o.customer_phone}`" class="customer-phone">
                        <i class="fa-solid fa-phone" aria-hidden="true" />
                        {{ o.customer_phone }}
                      </a>
                      <button
                        type="button"
                        class="btn-mini-copy"
                        :title="copiedPhoneId === o.id ? 'Copied' : 'Copy Phone'"
                        @click="copyPhone(o.id, o.customer_phone)"
                      >
                        <i class="fa-solid" :class="copiedPhoneId === o.id ? 'fa-check text-green-600' : 'fa-copy'" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                </div>

                <!-- PRICE & STATUS PILLS -->
                <div class="amount-status-block">
                  <div v-if="canSeeBilling" class="price-box">
                    <span class="price-val">{{ o.currency }} {{ o.total_price }}</span>
                    <button
                      v-if="canConfirm"
                      type="button"
                      class="btn-comp-tag"
                      :class="{ 'is-comp': ['staff', 'complimentary', 'free'].includes((o.payment_method || '').toLowerCase()) }"
                      :disabled="busyId === o.id"
                      :title="['staff', 'complimentary', 'free'].includes((o.payment_method || '').toLowerCase()) ? 'Complimentary Grant (Click to revert)' : 'Click to make Complimentary Grant'"
                      @click="toggleComplimentaryStatus(o)"
                    >
                      <i class="fa-solid" :class="['staff', 'complimentary', 'free'].includes((o.payment_method || '').toLowerCase()) ? 'fa-gift' : 'fa-hand-holding-heart'" />
                      <span>{{ ['staff', 'complimentary', 'free'].includes((o.payment_method || '').toLowerCase()) ? 'Comp' : 'Make Comp' }}</span>
                    </button>
                    <button type="button" class="btn-receipt-view" @click="openReceipt(o.id)">
                      <i class="fa-solid fa-file-invoice" aria-hidden="true" />
                      {{ o.payment_status === 'paid' ? 'Receipt' : 'Invoice' }}
                    </button>
                  </div>
                  <div v-else class="price-box">
                    <span class="price-val" style="font-size: 0.85rem; color: #475569; font-weight: 600;">{{ o.plan_name || 'Hosting Order' }}</span>
                  </div>
                  <div class="status-pills">
                    <span class="status-pill" :data-s="o.payment_status">
                      <i class="fa-solid" :class="paymentIcon(o.payment_status)" aria-hidden="true" />
                      {{ paymentLabel(o.payment_status) }}
                    </span>
                    <span class="status-pill" :data-p="o.provisioning_status">
                      <i class="fa-solid" :class="provisionIcon(o.provisioning_status)" aria-hidden="true" />
                      {{ provisionLabel(o.provisioning_status) }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- MIDDLE STRIP: PLAN & DOMAIN + CONDITIONAL REFERENCES -->
              <div class="card-meta-row">
                <!-- LEFT SIDE: PLAN & DOMAIN/SUBDOMAIN -->
                <div class="meta-item-group">
                  <span class="plan-tag">
                    <i class="fa-solid fa-box-archive" aria-hidden="true" />
                    {{ o.plan_name || 'Hosting Plan' }}
                  </span>

                  <!-- SUBDOMAIN / DOMAIN TAG + EDIT CONTROLS (HOSTING OPERATOR / OWNER ONLY) -->
                  <div class="domain-manager-wrap">
                    <div v-if="editingDomainId !== o.id" class="domain-pill">
                      <i class="fa-solid fa-globe" aria-hidden="true" />
                      <span class="domain-text">{{ domainByOrder[o.id] || o.domain_name || 'No domain assigned' }}</span>
                      <button
                        v-if="canEditSubdomain && o.payment_status !== 'paid'"
                        type="button"
                        class="btn-edit-subdomain"
                        :title="isStudentPlan(o) ? 'Customize student subdomain' : 'Edit domain name'"
                        @click="toggleDomainEdit(o.id)"
                      >
                        <i class="fa-solid fa-pen" aria-hidden="true" />
                        <span>Edit</span>
                      </button>
                    </div>

                    <!-- INLINE SUBDOMAIN EDITOR -->
                    <div v-else class="domain-edit-form">
                      <div class="domain-input-wrap">
                        <i class="fa-solid fa-pen-nib" aria-hidden="true" />
                        <input
                          v-model="domainByOrder[o.id]"
                          type="text"
                          class="domain-input"
                          placeholder="e.g. kwame.ifnotus.space or domain.com"
                          @keyup.enter="editingDomainId = null"
                        />
                      </div>
                      <button type="button" class="btn-domain-done" @click="editingDomainId = null">
                        <i class="fa-solid fa-check" aria-hidden="true" /> Save
                      </button>
                    </div>
                  </div>
                </div>

                <!-- RIGHT SIDE: REFERENCES (SHOWN CLEANLY ONLY WHEN RELEVANT OR EXPANDED) -->
                <div class="references-cluster">
                  <!-- SENDING REFERENCE (SHOWN ONLY IF UNPAID/SUBMITTED TO AVOID CLUTTER ON PAID LIST) -->
                  <div
                    v-if="o.payment_status !== 'paid'"
                    class="sending-ref-card"
                    :title="'Expected Mobile Money transfer reference code: ' + (o.invoice_number || o.id.slice(0, 8))"
                  >
                    <span class="ref-k">
                      <i class="fa-solid fa-key" aria-hidden="true" />
                      Ref:
                    </span>
                    <code class="ref-v">{{ o.invoice_number || o.id.slice(0, 8) }}</code>
                    <button
                      type="button"
                      class="btn-copy-ref"
                      :title="copiedRefId === o.id ? 'Copied to clipboard' : 'Copy Sending Reference'"
                      @click="copyRef(o.id, o.invoice_number || o.id.slice(0, 8))"
                    >
                      <i class="fa-solid" :class="copiedRefId === o.id ? 'fa-check text-green-500' : 'fa-copy'" aria-hidden="true" />
                      <span>{{ copiedRefId === o.id ? 'Copied' : 'Copy' }}</span>
                    </button>
                  </div>

                  <!-- RECEIVED MOMO TRANSACTION ID -->
                  <div v-if="o.momo_transaction_id" class="momo-pill">
                    <span class="momo-k"><i class="fa-solid fa-mobile-screen-button" aria-hidden="true" /> MoMo Tx:</span>
                    <code class="momo-v">{{ o.momo_transaction_id }}</code>
                    <button
                      type="button"
                      class="btn-copy-momo"
                      :title="copiedId === o.id ? 'Copied to clipboard' : 'Copy MoMo ID'"
                      @click="copyMomo(o.id, o.momo_transaction_id)"
                    >
                      <i class="fa-solid" :class="copiedId === o.id ? 'fa-check text-green-500' : 'fa-copy'" aria-hidden="true" />
                      <span>{{ copiedId === o.id ? 'Copied' : 'Copy' }}</span>
                    </button>
                  </div>
                </div>
              </div>

              <!-- ACTION PANEL: CONFIRM & ACTIVATE (WHEN SUBMITTED / PENDING) -->
              <div
                v-if="canConfirm && o.payment_status !== 'paid' && o.payment_status !== 'failed'"
                class="action-box"
              >
                <!-- LIVE PROGRESS BAR LOADING (SHOWN DURING ACTIVATION) -->
                <div v-if="busyId === o.id" class="activation-progress-box">
                  <div class="progress-meta">
                    <span class="progress-title">
                      <i class="fa-solid fa-arrows-rotate fa-spin" aria-hidden="true" />
                      {{ progressStage || 'Provisioning hosting environment…' }}
                    </span>
                    <span class="progress-num">{{ progressPercent }}%</span>
                  </div>
                  <div class="progress-track">
                    <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
                  </div>
                  <p class="progress-sub">Creating ISPConfig webroot, assigning database, issuing SSL SANs and mapping fPanel.</p>
                </div>

                <!-- CONTROLS WHEN IDLE -->
                <div v-else class="action-box-inner">
                  <div class="action-inputs-grid">
                    <!-- PAYMENT CHANNEL / PHYSICAL CASH SELECTION -->
                    <div class="input-col">
                      <label class="compact-label">
                        <span><i class="fa-solid fa-money-bill-transfer" aria-hidden="true" /> Payment Method</span>
                        <select
                          v-model="paymentMethodByOrder[o.id]"
                          class="compact-input compact-select"
                        >
                          <option :value="undefined">Mobile Money (MTN / Telecel)</option>
                          <option value="momo">Mobile Money (MTN / Telecel)</option>
                          <option value="physical_cash">Physical Cash (In-Person / Desk)</option>
                          <option value="bank">Direct Bank Deposit / Transfer</option>
                          <option value="complimentary">Complimentary / Free Grant (0.00 GHS)</option>
                        </select>

                      </label>
                    </div>

                    <!-- AMOUNT RECEIVED -->
                    <div class="input-col">
                      <label class="compact-label">
                        <span><i class="fa-solid fa-coins" aria-hidden="true" /> Amount Received (GHS)</span>
                        <input
                          v-model="amountByOrder[o.id]"
                          type="text"
                          inputmode="decimal"
                          class="compact-input"
                          :placeholder="String(o.total_price)"
                        />
                      </label>
                    </div>

                    <!-- STAFF NOTE WITH EXPLANATION TRIGGER -->
                    <div class="input-col span-full">
                      <label class="compact-label">
                        <span class="label-with-help">
                          <i class="fa-solid fa-clipboard-check" aria-hidden="true" /> Staff Note (Optional)
                          <button
                            type="button"
                            class="help-btn"
                            title="What is a Staff Note?"
                            @click="showNoteHelp = !showNoteHelp"
                          >
                            <i class="fa-regular fa-circle-question" aria-hidden="true" />
                          </button>
                        </span>
                        <input
                          v-model="confirmNotes"
                          type="text"
                          class="compact-input"
                          :placeholder="paymentMethodByOrder[o.id] === 'physical_cash' ? 'e.g. Received GHS cash in hand at front desk' : 'e.g. Verified in MTN MoMo app tx#5820'"
                        />
                      </label>
                    </div>
                  </div>


                  <!-- STAFF NOTE EXPLANATION CALLOUT -->
                  <div v-if="showNoteHelp" class="note-help-box">
                    <div class="note-help-content">
                      <i class="fa-solid fa-info-circle text-blue-500" aria-hidden="true" />
                      <div>
                        <strong>What is a Staff Note?</strong>
                        <p>
                          A Staff Note is an internal audit entry recorded on this transaction. It is only visible to
                          operators and administrators (e.g., recording the phone agent name or MoMo statement ID). It is
                          <strong>never visible to the customer</strong>.
                        </p>
                      </div>
                    </div>
                    <button type="button" class="close-help-btn" @click="showNoteHelp = false">Dismiss</button>
                  </div>

                  <!-- ACTION BUTTONS (BILLING AGENT / OWNER) -->
                  <div class="action-buttons-row">
                    <button
                      type="button"
                      class="btn-action-activate"
                      :disabled="busyId === o.id"
                      @click="confirmPay(o)"
                    >
                      <i class="fa-solid fa-check-double" aria-hidden="true" />
                      Accept Billing &amp; Confirm Payment
                    </button>
                    <button
                      type="button"
                      class="btn-action-reject"
                      :disabled="busyId === o.id"
                      @click="rejectPay(o)"
                    >
                      <i class="fa-solid fa-xmark" aria-hidden="true" />
                      Reject
                    </button>
                    <span v-if="isStudentPlan(o)" class="student-helper-tip">
                      <i class="fa-solid fa-graduation-cap" aria-hidden="true" />
                      Student plan: billing acceptance will queue for hosting operator activation.
                    </span>
                  </div>
                </div>
              </div>

              <!-- ACTION: ACTIVATE HOSTING (FOR HOSTING OPERATOR / OPS ONCE BILLING IS ACCEPTED) -->
              <div
                v-else-if="canOps && o.payment_status === 'paid' && o.provisioning_status !== 'active' && o.provisioning_status !== 'n/a'"
                class="action-box ok"
              >
                <div v-if="busyId === o.id" class="activation-progress-box">
                  <div class="progress-meta">
                    <span class="progress-title">
                      <i class="fa-solid fa-arrows-rotate fa-spin" aria-hidden="true" />
                      Activating server infrastructure &amp; domain…
                    </span>
                    <span class="progress-num">{{ progressPercent }}%</span>
                  </div>
                  <div class="progress-track">
                    <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
                  </div>
                </div>
                <div v-else class="retry-row" style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
                  <div class="retry-text">
                    <i class="fa-solid fa-circle-check text-emerald-500" aria-hidden="true" />
                    <span><strong>Billing Accepted &amp; Verified.</strong> Ready for server infrastructure &amp; domain activation.</span>
                  </div>
                  <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <button
                      type="button"
                      class="btn-action-activate"
                      :disabled="busyId === o.id"
                      @click="activateHosting(o)"
                    >
                      <i class="fa-solid fa-rocket" aria-hidden="true" />
                      {{ o.order_kind === 'domain' ? 'Activate Domain' : 'Activate Hosting' }}
                    </button>
                    <button
                      v-if="o.provisioning_status === 'failed'"
                      type="button"
                      class="btn-action-retry"
                      :disabled="busyId === o.id"
                      @click="retryProvision(o)"
                    >
                      <i class="fa-solid fa-arrows-rotate" aria-hidden="true" />
                      Retry Setup
                    </button>
                  </div>
                </div>
              </div>

              <!-- STATUS: PAID & ACTIVE -->
              <div v-else-if="o.payment_status === 'paid' && o.provisioning_status === 'active'" class="active-footer">
                <div class="active-left">
                  <i class="fa-solid fa-circle-check" aria-hidden="true" />
                  <span>Hosting environment live on <strong>{{ o.domain_name || 'assigned domain' }}</strong></span>
                </div>
                <div class="active-right">
                  <button v-if="canSeeBilling" type="button" class="btn-micro-link" :disabled="busyId === o.id" title="Toggle Complimentary Grant status" @click="toggleComplimentaryStatus(o)">
                    <i class="fa-solid fa-gift" aria-hidden="true" />
                    {{ ['staff', 'complimentary', 'free'].includes((o.payment_method || '').toLowerCase()) ? 'Comp Active' : 'Make Comp' }}
                  </button>
                  <button type="button" class="btn-micro-link" @click="openReceipt(o.id)">
                    <i class="fa-solid fa-receipt" aria-hidden="true" /> Receipt
                  </button>
                  <button type="button" class="btn-micro-link" @click="openCustomer(o.customer_id)">
                    <i class="fa-solid fa-user" aria-hidden="true" /> Customer
                  </button>
                </div>
              </div>
            </article>
          </div>

          <!-- EMPTY STATE -->
          <div v-else class="empty-state">
            <div class="empty-icon-wrap">
              <i class="fa-regular fa-folder-open" aria-hidden="true" />
            </div>
            <h3 v-if="searchQuery">No matching orders found</h3>
            <h3 v-else>No orders found</h3>
            <p v-if="searchQuery">No orders matched "{{ searchQuery }}".</p>
            <p v-else>There are no orders matching the current filter.</p>
            <button v-if="searchQuery" type="button" class="btn-clear-filter" @click="searchQuery = ''">
              Clear search query
            </button>
            <button v-else-if="paymentFilter !== ''" type="button" class="btn-clear-filter" @click="setFilter('')">
              View all orders
            </button>
          </div>
        </section>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.orders {
  width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.orders-head {
  padding: 0.85rem 1.25rem 0;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.head-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  background: #ffffff;
  color: #334155;
  font-size: 0.8rem;
  font-weight: 650;
  padding: 0.45rem 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.head-btn:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.orders-body {
  flex: 1;
  width: 100%;
  padding: 1rem 1.25rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

/* STATS BAR */
.stats-bar {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.8rem 1rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02);
}

.stat-icon {
  width: 2.35rem;
  height: 2.35rem;
  border-radius: 0.65rem;
  display: grid;
  place-items: center;
  font-size: 0.95rem;
  flex-shrink: 0;
}

.stat-body {
  flex: 1;
  min-width: 0;
}

.stat-k {
  display: block;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
}

.stat-v {
  display: block;
  margin-top: 0.15rem;
  font-size: 1.2rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.15;
}

.stat-s {
  display: block;
  font-size: 0.72rem;
  color: #64748b;
}

.tone-await .stat-icon { background: #fef3c7; color: #b45309; }
.tone-cash .stat-icon { background: #d1fae5; color: #047857; }
.tone-pending .stat-icon { background: #e0e7ff; color: #4338ca; }

/* FILTER & SEARCH CARD */
.filters-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.75rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

/* LIVE SEARCH BAR */
.search-bar-wrap {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.search-input-box {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 0.75rem;
  color: #94a3b8;
  font-size: 0.85rem;
  pointer-events: none;
}

.search-input {
  width: 100%;
  border-radius: 0.55rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.85rem;
  padding: 0.48rem 2.25rem 0.48rem 2.25rem;
  outline: none;
  transition: all 0.15s ease;
}

.search-input:focus {
  background: #ffffff;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.search-input::placeholder {
  color: #94a3b8;
}

.search-clear-btn {
  position: absolute;
  right: 0.65rem;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
  border-radius: 0.3rem;
  display: grid;
  place-items: center;
}

.search-clear-btn:hover {
  color: #0f172a;
  background: #e2e8f0;
}

.search-match-tag {
  font-size: 0.76rem;
  color: #1e40af;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 0.25rem 0.6rem;
  border-radius: 0.45rem;
  white-space: nowrap;
}

.filters-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
}

.filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.38rem 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  font-size: 0.78rem;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.12s ease;
}

.filter-tab:hover {
  background: #f8fafc;
  color: #0f172a;
  border-color: #94a3b8;
}

.filter-tab.on {
  background: #1e3a5f;
  color: #ffffff;
  border-color: #1e3a5f;
}

.tab-badge {
  background: #64748b;
  color: #ffffff;
  font-size: 0.62rem;
  font-weight: 800;
  padding: 0.08rem 0.38rem;
  border-radius: 999px;
}

.tab-badge.badge-sub {
  background: #f59e0b;
  color: #ffffff;
}

.tab-badge.badge-unpaid {
  background: #3b82f6;
  color: #ffffff;
}

.filter-tab.on .tab-badge {
  background: #ffffff;
  color: #1e3a5f;
}

.flow-count {
  margin: 0;
  padding: 0.3rem 0.65rem;
  border-radius: 0.45rem;
  background: #f1f5f9;
  color: #334155;
  font-size: 0.78rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

/* ORDERS PANEL */
.orders-panel {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.9rem 1.1rem;
}

.panel-head {
  margin-bottom: 0.75rem;
}

.panel-head-text h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 750;
  color: #0f172a;
}

.panel-sub {
  margin: 0.15rem 0 0;
  font-size: 0.76rem;
  color: #64748b;
}

.state-msg {
  padding: 2.5rem 1rem;
  text-align: center;
  color: #64748b;
  font-size: 0.88rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
}

/* SLIM CLEAN ORDER CARDS */
.order-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.order-card-slim {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.85rem 1rem;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  transition: all 0.15s ease;
}

.order-card-slim:hover {
  border-color: #cbd5e1;
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.04);
}

.order-card-slim.is-paid {
  border-color: #e2e8f0;
  background: #ffffff;
}

.order-card-slim.is-active {
  border-left: 3.5px solid #10b981;
}

/* TOP STRIP */
.card-main-row {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

@media (min-width: 680px) {
  .card-main-row {
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
  }
}

.customer-info-block {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.inv-chip-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.inv-badge {
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  font-weight: 750;
  color: #1e293b;
  background: #f1f5f9;
  padding: 0.12rem 0.45rem;
  border-radius: 0.35rem;
}

.kind-badge {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.4rem;
  border-radius: 0.3rem;
  background: #e2e8f0;
  color: #475569;
}

.date-badge {
  font-size: 0.72rem;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.customer-details {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
  font-size: 0.84rem;
}

.customer-name-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: 0.92rem;
  font-weight: 750;
  color: #0f172a;
}

.customer-name-btn:hover {
  color: #2563eb;
  text-decoration: underline;
}

.customer-email {
  color: #475569;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.8rem;
}

.customer-email:hover {
  color: #2563eb;
  text-decoration: underline;
}

.customer-phone-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.customer-phone {
  color: #047857;
  text-decoration: none;
  font-weight: 650;
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.8rem;
}

.customer-phone:hover {
  text-decoration: underline;
}

.btn-mini-copy {
  border: none;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  padding: 0.12rem 0.3rem;
  border-radius: 0.25rem;
  font-size: 0.68rem;
  display: inline-flex;
  align-items: center;
}

.btn-mini-copy:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.divider {
  color: #cbd5e1;
}

/* AMOUNT & STATUS */
.amount-status-block {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

@media (min-width: 680px) {
  .amount-status-block {
    flex-direction: column;
    align-items: flex-end;
    gap: 0.35rem;
  }
}

.price-box {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}

.price-val {
  font-size: 1.15rem;
  font-weight: 850;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.btn-comp-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.24rem 0.5rem;
  border-radius: 0.4rem;
  border: 1px solid #c084fc;
  background: #fdf4ff;
  color: #7e22ce;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-comp-tag:hover {
  background: #f3e8ff;
  border-color: #a855f7;
}

.btn-comp-tag.is-comp {
  border-color: #818cf8;
  background: #e0e7ff;
  color: #3730a3;
}

.btn-receipt-view {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.24rem 0.55rem;
  border-radius: 0.4rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-receipt-view:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}

.status-pills {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.14rem 0.48rem;
  border-radius: 999px;
  font-size: 0.66rem;
  font-weight: 750;
  background: #f1f5f9;
  color: #475569;
}

.status-pill[data-s='submitted'] { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
.status-pill[data-s='paid'] { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.status-pill[data-s='failed'] { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
.status-pill[data-s='pending'] { background: #f8fafc; color: #64748b; border: 1px solid #e2e8f0; }

.status-pill[data-p='active'] { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.status-pill[data-p='failed'] { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
.status-pill[data-p='queued'],
.status-pill[data-p='pending'],
.status-pill[data-p='running'] { background: #fff7ed; color: #9a3412; border: 1px solid #fed7aa; }

/* MIDDLE STRIP: PLAN & DOMAIN/MOMO & KEYED OUT SENDING REF */
.card-meta-row {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

@media (min-width: 768px) {
  .card-meta-row {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.meta-item-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.plan-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  font-weight: 750;
  color: #1e293b;
}

.domain-manager-wrap {
  display: inline-flex;
  align-items: center;
}

.domain-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  padding: 0.15rem 0.5rem;
  border-radius: 0.4rem;
}

.domain-text {
  font-family: ui-monospace, monospace;
}

.btn-edit-subdomain {
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
  font-size: 0.7rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  margin-left: 0.2rem;
}

.btn-edit-subdomain:hover {
  background: #dbeafe;
  color: #1e40af;
}

.domain-edit-form {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.domain-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.domain-input-wrap i {
  position: absolute;
  left: 0.45rem;
  font-size: 0.7rem;
  color: #64748b;
  pointer-events: none;
}

.domain-input {
  border: 1px solid #2563eb;
  border-radius: 0.4rem;
  padding: 0.22rem 0.5rem 0.22rem 1.45rem;
  font-size: 0.78rem;
  font-family: ui-monospace, monospace;
  color: #0f172a;
  outline: none;
  width: 14rem;
  background: #ffffff;
}

.domain-input:focus {
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.btn-domain-done {
  border: none;
  background: #2563eb;
  color: #ffffff;
  border-radius: 0.4rem;
  padding: 0.25rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.btn-domain-done:hover {
  background: #1d4ed8;
}

/* REFERENCES CLUSTER: KEYED OUT SENDING REF & MOMO TX */
.references-cluster {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.sending-ref-card {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 0.15rem 0.45rem;
  border-radius: 0.35rem;
}

.ref-k {
  font-size: 0.68rem;
  font-weight: 800;
  color: #1e40af;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}

.ref-v {
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  font-weight: 800;
  color: #1e3a8a;
  background: #ffffff;
  padding: 0.05rem 0.3rem;
  border-radius: 0.25rem;
  border: 1px solid #dbeafe;
}

.btn-copy-ref {
  border: none;
  background: #dbeafe;
  color: #1e40af;
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
  font-size: 0.68rem;
  font-weight: 750;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  transition: all 0.12s ease;
}

.btn-copy-ref:hover {
  background: #bfdbfe;
  color: #172554;
}

.momo-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 0.15rem 0.45rem;
  border-radius: 0.35rem;
}

.momo-k {
  font-size: 0.68rem;
  font-weight: 700;
  color: #64748b;
}

.momo-v {
  font-family: ui-monospace, monospace;
  font-size: 0.76rem;
  font-weight: 800;
  color: #0f172a;
}

.btn-copy-momo {
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0.08rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.68rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}

.btn-copy-momo:hover {
  background: #f1f5f9;
  color: #0f172a;
}

/* ACTION BOX */
.action-box {
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.action-box.warn {
  background: #fff7ed;
  border-color: #fed7aa;
}

.action-box-inner {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.action-inputs-grid {
  display: grid;
  gap: 0.65rem;
  grid-template-columns: 1fr;
}

@media (min-width: 680px) {
  .action-inputs-grid {
    grid-template-columns: 1.2fr 1fr;
  }
  .action-inputs-grid .span-full {
    grid-column: 1 / -1;
  }
}

.compact-select {
  cursor: pointer;
}


.compact-label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.compact-label span {
  font-size: 0.72rem;
  font-weight: 700;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.label-with-help {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.help-btn {
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
}

.help-btn:hover {
  color: #2563eb;
}

.compact-input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #ffffff;
  padding: 0.42rem 0.65rem;
  font-size: 0.82rem;
  color: #0f172a;
  outline: none;
}

.compact-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.note-help-box {
  padding: 0.55rem 0.75rem;
  border-radius: 0.5rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.65rem;
}

.note-help-content {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #1e3a8a;
}

.note-help-content strong {
  display: block;
  font-size: 0.78rem;
  margin-bottom: 0.15rem;
}

.note-help-content p {
  margin: 0;
  line-height: 1.35;
}

.close-help-btn {
  border: none;
  background: transparent;
  color: #1e40af;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.close-help-btn:hover {
  text-decoration: underline;
}

.action-buttons-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.btn-action-activate {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.52rem 1.1rem;
  border: none;
  border-radius: 0.5rem;
  background: #059669;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-action-activate:hover:not(:disabled) {
  background: #047857;
  transform: translateY(-1px);
}

.btn-action-activate:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.btn-action-reject {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.52rem 0.95rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  background: #ffffff;
  color: #dc2626;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-action-reject:hover:not(:disabled) {
  background: #fee2e2;
  border-color: #fca5a5;
}

.student-helper-tip {
  font-size: 0.74rem;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

/* PROGRESS BAR LOADING COMPONENT */
.activation-progress-box {
  padding: 0.75rem 0.85rem;
  border-radius: 0.55rem;
  background: #ffffff;
  border: 1px solid #93c5fd;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.82rem;
  font-weight: 750;
  color: #1e3a8a;
}

.progress-title {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}

.progress-num {
  font-family: ui-monospace, monospace;
  font-size: 0.88rem;
  color: #2563eb;
}

.progress-track {
  width: 100%;
  height: 0.55rem;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #2563eb, #7c3aed, #059669);
  transition: width 0.35s ease-out;
}

.progress-sub {
  margin: 0;
  font-size: 0.72rem;
  color: #64748b;
}

/* RETRY ROW */
.retry-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
}

.retry-text {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  font-weight: 650;
  color: #9a3412;
}

.btn-action-retry {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.45rem 0.95rem;
  border: none;
  border-radius: 0.5rem;
  background: #d97706;
  color: #ffffff;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
}

.btn-action-retry:hover:not(:disabled) {
  background: #b45309;
}

/* ACTIVE FOOTER */
.active-footer {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding-top: 0.35rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.78rem;
  color: #059669;
}

@media (min-width: 600px) {
  .active-footer {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.active-left {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.active-right {
  display: flex;
  gap: 0.35rem;
}

.btn-micro-link {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  padding: 0.18rem 0.48rem;
  border-radius: 0.35rem;
  font-size: 0.72rem;
  font-weight: 650;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  transition: all 0.12s ease;
}

.btn-micro-link:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

/* EMPTY STATE */
.empty-state {
  padding: 3rem 1.5rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.45rem;
}

.empty-icon-wrap {
  width: 3rem;
  height: 3rem;
  border-radius: 0.75rem;
  background: #f1f5f9;
  color: #64748b;
  display: grid;
  place-items: center;
  font-size: 1.35rem;
  margin-bottom: 0.35rem;
}

.empty-state h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 750;
  color: #0f172a;
}

.empty-state p {
  margin: 0;
  font-size: 0.82rem;
  color: #64748b;
}

.btn-clear-filter {
  margin-top: 0.65rem;
  padding: 0.45rem 1rem;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #1e3a5f;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
}

.btn-clear-filter:hover {
  background: #f8fafc;
  border-color: #1e3a5f;
}

/* ================= DARK THEME OVERRIDES ================= */
:global(.dark) .orders {
  background: #0b1120;
}

:global(.dark) .orders-head {
  background: #0f172a;
  border-bottom-color: #1e293b;
}

:global(.dark) .orders-body {
  background: #0b1120;
}

:global(.dark) .compact-select {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
  color-scheme: dark;
}


:global(.dark) .head-btn {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

:global(.dark) .head-btn:hover {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .stat-card,
:global(.dark) .filters-card,
:global(.dark) .orders-panel {
  background: #0f172a;
  border-color: #1e293b;
}

:global(.dark) .stat-k {
  color: #94a3b8;
}

:global(.dark) .stat-v {
  color: #f8fafc;
}

:global(.dark) .stat-s {
  color: #64748b;
}

:global(.dark) .search-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

:global(.dark) .search-input:focus {
  background: #0b1329;
  border-color: #3b82f6;
}

:global(.dark) .search-match-tag {
  background: #1e3a8a;
  border-color: #3b82f6;
  color: #bfdbfe;
}

:global(.dark) .filter-tab {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

:global(.dark) .filter-tab:hover {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .filter-tab.on {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

:global(.dark) .flow-count {
  background: #1e293b;
  color: #cbd5e1;
}

:global(.dark) .panel-head-text h2 {
  color: #f8fafc;
}

:global(.dark) .panel-sub {
  color: #94a3b8;
}

:global(.dark) .order-card-slim {
  background: #0f172a;
  border-color: #1e293b;
}

:global(.dark) .order-card-slim:hover {
  border-color: #334155;
}

:global(.dark) .inv-badge {
  background: #1e293b;
  color: #93c5fd;
  border: 1px solid #334155;
}

:global(.dark) .kind-badge {
  background: #1e293b;
  color: #94a3b8;
}

:global(.dark) .customer-name-btn {
  color: #f8fafc;
}

:global(.dark) .customer-name-btn:hover {
  color: #60a5fa;
}

:global(.dark) .customer-email {
  color: #94a3b8;
}

:global(.dark) .btn-mini-copy {
  background: #1e293b;
  color: #94a3b8;
}

:global(.dark) .btn-mini-copy:hover {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .price-val {
  color: #f8fafc;
}

:global(.dark) .btn-receipt-view {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

:global(.dark) .btn-receipt-view:hover {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .card-meta-row {
  background: #0b1329;
  border-color: #1e293b;
}

:global(.dark) .plan-tag {
  color: #f8fafc;
}

:global(.dark) .domain-pill {
  background: #1e3a8a;
  border-color: #2563eb;
  color: #93c5fd;
}

:global(.dark) .domain-input {
  background: #0f172a;
  color: #f8fafc;
  border-color: #3b82f6;
}

:global(.dark) .sending-ref-card {
  background: #172554;
  border-color: #2563eb;
}

:global(.dark) .ref-k {
  color: #93c5fd;
}

:global(.dark) .ref-v {
  background: #0f172a;
  color: #60a5fa;
  border-color: #1d4ed8;
}

:global(.dark) .btn-copy-ref {
  background: #1e3a8a;
  color: #bfdbfe;
}

:global(.dark) .btn-copy-ref:hover {
  background: #2563eb;
  color: #ffffff;
}

:global(.dark) .momo-pill {
  background: #0f172a;
  border-color: #334155;
}

:global(.dark) .momo-k {
  color: #94a3b8;
}

:global(.dark) .momo-v {
  color: #f8fafc;
}

:global(.dark) .action-box {
  background: #0b1329;
  border-color: #1e293b;
}

:global(.dark) .compact-label span {
  color: #94a3b8;
}

:global(.dark) .compact-input {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

:global(.dark) .compact-input:focus {
  border-color: #3b82f6;
}

:global(.dark) .note-help-box {
  background: #0c192c;
  border-color: #1e3a8a;
}

:global(.dark) .note-help-content {
  color: #bfdbfe;
}

:global(.dark) .btn-action-reject {
  background: #1e293b;
  border-color: #7f1d1d;
  color: #f87171;
}

:global(.dark) .student-helper-tip {
  color: #94a3b8;
}

:global(.dark) .btn-micro-link {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

:global(.dark) .btn-micro-link:hover {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .empty-icon-wrap {
  background: #1e293b;
  color: #94a3b8;
}

:global(.dark) .empty-state h3 {
  color: #f8fafc;
}

:global(.dark) .empty-state p {
  color: #94a3b8;
}

:global(.dark) .btn-clear-filter {
  background: #1e293b;
  border-color: #334155;
  color: #93c5fd;
}
</style>

<style>
/* Unscoped global dark theme overrides to guarantee complete dark mode styling on Orders */
html.dark .orders,
html.control-ui.dark .orders {
  background: #0b1120 !important;
  color: #f8fafc !important;
}

html.dark .orders-head,
html.control-ui.dark .orders-head {
  background: #0f172a !important;
  border-bottom-color: #1e293b !important;
}

html.dark .orders-body,
html.control-ui.dark .orders-body {
  background: #0b1120 !important;
}

html.dark .compact-select,
html.control-ui.dark .compact-select {
  background: #0f172a !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
  color-scheme: dark !important;
}

html.dark .head-btn,
html.control-ui.dark .head-btn {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #cbd5e1 !important;
}

html.dark .head-btn:hover,
html.control-ui.dark .head-btn:hover {
  background: #334155 !important;
  color: #ffffff !important;
}

html.dark .stat-card,
html.control-ui.dark .stat-card,
html.dark .filters-card,
html.control-ui.dark .filters-card,
html.dark .orders-panel,
html.control-ui.dark .orders-panel {
  background: #0f172a !important;
  border-color: #1e293b !important;
}

html.dark .stat-k,
html.control-ui.dark .stat-k {
  color: #94a3b8 !important;
}

html.dark .stat-v,
html.control-ui.dark .stat-v {
  color: #f8fafc !important;
}

html.dark .stat-s,
html.control-ui.dark .stat-s {
  color: #64748b !important;
}

html.dark .search-input,
html.control-ui.dark .search-input {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .search-input:focus,
html.control-ui.dark .search-input:focus {
  background: #0b1329 !important;
  border-color: #3b82f6 !important;
}

html.dark .filter-tab,
html.control-ui.dark .filter-tab {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #94a3b8 !important;
}

html.dark .filter-tab:hover,
html.control-ui.dark .filter-tab:hover {
  background: #334155 !important;
  color: #ffffff !important;
}

html.dark .filter-tab.on,
html.control-ui.dark .filter-tab.on {
  background: #2563eb !important;
  border-color: #2563eb !important;
  color: #ffffff !important;
}

html.dark .panel-head-text h2,
html.control-ui.dark .panel-head-text h2 {
  color: #f8fafc !important;
}

html.dark .panel-sub,
html.control-ui.dark .panel-sub {
  color: #94a3b8 !important;
}

html.dark .order-card-slim,
html.control-ui.dark .order-card-slim {
  background: #0f172a !important;
  border-color: #1e293b !important;
}

html.dark .order-card-slim:hover,
html.control-ui.dark .order-card-slim:hover {
  border-color: #334155 !important;
}

html.dark .inv-badge,
html.control-ui.dark .inv-badge {
  background: #1e293b !important;
  color: #93c5fd !important;
  border: 1px solid #334155 !important;
}

html.dark .customer-name-btn,
html.control-ui.dark .customer-name-btn {
  color: #f8fafc !important;
}

html.dark .customer-email,
html.control-ui.dark .customer-email {
  color: #94a3b8 !important;
}

html.dark .price-val,
html.control-ui.dark .price-val {
  color: #f8fafc !important;
}

html.dark .card-meta-row,
html.control-ui.dark .card-meta-row {
  background: #0b1329 !important;
  border-color: #1e293b !important;
}

html.dark .plan-tag,
html.control-ui.dark .plan-tag {
  color: #e2e8f0 !important;
}

html.dark .sending-ref-card,
html.control-ui.dark .sending-ref-card,
.dark .sending-ref-card {
  background: #172554 !important;
  border-color: #1d4ed8 !important;
}

html.dark .ref-k,
html.control-ui.dark .ref-k,
.dark .ref-k {
  color: #bfdbfe !important;
}

html.dark .ref-v,
html.control-ui.dark .ref-v,
.dark .ref-v,
html.dark code.ref-v,
html.control-ui.dark code.ref-v,
.dark code.ref-v {
  background: #0f172a !important;
  color: #60a5fa !important;
  border: 1.5px solid #1d4ed8 !important;
  text-shadow: none !important;
}

html.dark .btn-copy-ref,
html.control-ui.dark .btn-copy-ref,
.dark .btn-copy-ref {
  background: #1e3a8a !important;
  color: #bfdbfe !important;
}

html.dark .btn-copy-ref:hover,
html.control-ui.dark .btn-copy-ref:hover,
.dark .btn-copy-ref:hover {
  background: #2563eb !important;
  color: #ffffff !important;
}

html.dark .momo-pill,
html.control-ui.dark .momo-pill,
.dark .momo-pill {
  background: #0f172a !important;
  border-color: #334155 !important;
}

html.dark .momo-k,
html.control-ui.dark .momo-k,
.dark .momo-k {
  color: #94a3b8 !important;
}

html.dark .momo-v,
html.control-ui.dark .momo-v,
.dark .momo-v,
html.dark code.momo-v,
html.control-ui.dark code.momo-v,
.dark code.momo-v {
  background: #1e293b !important;
  color: #f8fafc !important;
  border: 1px solid #334155 !important;
}

html.dark .btn-copy-momo,
html.control-ui.dark .btn-copy-momo,
.dark .btn-copy-momo {
  background: #1e293b !important;
  color: #94a3b8 !important;
}

html.dark .btn-copy-momo:hover,
html.control-ui.dark .btn-copy-momo:hover,
.dark .btn-copy-momo:hover {
  background: #334155 !important;
  color: #f8fafc !important;
}

html.dark .action-box,
html.control-ui.dark .action-box {
  background: #0b1329 !important;
  border-color: #1e293b !important;
}

html.dark .compact-input,
html.control-ui.dark .compact-input {
  background: #0f172a !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .note-help-box,
html.control-ui.dark .note-help-box {
  background: #0f172a !important;
  border-color: #1e3a8a !important;
}

html.dark .note-help-content,
html.control-ui.dark .note-help-content {
  color: #94a3b8 !important;
}
</style>
