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

// Modal state
const selectedOrder = ref<StaffOrderItem | null>(null)
const showDetailModal = ref(false)

// Pagination state
const currentPage = ref(1)
const pageSize = ref(20)
const pageSizeOptions = [10, 20, 50, 100]

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

const totalPages = computed(() => Math.max(1, Math.ceil(filteredOrders.value.length / pageSize.value)))

const paginatedOrders = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredOrders.value.slice(start, start + pageSize.value)
})

const showingStart = computed(() => {
  if (filteredOrders.value.length === 0) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const showingEnd = computed(() => {
  return Math.min(currentPage.value * pageSize.value, filteredOrders.value.length)
})

watch([searchQuery, paymentFilter, pageSize], () => {
  currentPage.value = 1
})

function goToPage(p: number) {
  if (p >= 1 && p <= totalPages.value) {
    currentPage.value = p
  }
}

function openOrderModal(o: StaffOrderItem) {
  selectedOrder.value = o
  showDetailModal.value = true
}

function closeOrderModal() {
  showDetailModal.value = false
  selectedOrder.value = null
  editingDomainId.value = null
}

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
    // Update selectedOrder if modal is open
    if (selectedOrder.value) {
      const found = data.find((x) => x.id === selectedOrder.value?.id)
      if (found) selectedOrder.value = found
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

function isCompOrder(o: StaffOrderItem) {
  const m = (o.payment_method || '').toLowerCase()
  return m === 'staff' || m === 'complimentary' || m === 'free'
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
  busyId.value = o.id
  error.value = ''
  startProgressSimulation()
  try {
    await platformAdminApi.retryOrderProvisioning(o.id)
    stopProgressSimulation(true)
    success.value = 'Provisioning retry dispatched successfully.'
    await load()
  } catch (e: unknown) {
    stopProgressSimulation(false)
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Retry failed.'
  } finally {
    setTimeout(() => {
      busyId.value = ''
      progressPercent.value = 0
    }, 1200)
  }
}

async function rejectPay(o: StaffOrderItem) {
  if (!confirm(`Reject submitted payment for order ${o.invoice_number || o.id.slice(0, 8)}? Customer will be asked to resubmit.`)) {
    return
  }
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

        <!-- ORDERS PANEL -->
        <section class="panel-card orders-panel">
          <header class="panel-head">
            <div class="panel-head-text">
              <h2>Order Queue</h2>
              <p class="panel-sub">
                {{ loading ? 'Loading orders…' : `${filteredOrders.length} order records in view` }}
                <span v-if="searchQuery && orders.length !== filteredOrders.length"> (filtered from {{ orders.length }})</span>
              </p>
            </div>

            <!-- TOP CONTROLS: PAGE SIZE SELECTOR -->
            <div v-if="filteredOrders.length > 0" class="panel-head-ctrls">
              <label class="page-size-label">
                <span>Show</span>
                <select v-model.number="pageSize" class="page-size-select">
                  <option v-for="sz in pageSizeOptions" :key="sz" :value="sz">{{ sz }}</option>
                </select>
                <span>per page</span>
              </label>
            </div>
          </header>

          <div v-if="loading" class="state-msg">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <span>Fetching order records…</span>
          </div>

          <!-- CLEAN DATA TABLE WITH SCROLL -->
          <div v-else-if="filteredOrders.length" class="orders-table-wrap">
            <table class="orders-table">
              <thead>
                <tr>
                  <th>Invoice &amp; Date</th>
                  <th>Customer</th>
                  <th>Plan &amp; Domain</th>
                  <th>MoMo Tx ID</th>
                  <th v-if="canSeeBilling" class="text-right">Amount</th>
                  <th>Payment</th>
                  <th>Hosting</th>
                  <th class="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="o in paginatedOrders"
                  :key="o.id"
                  class="order-row cursor-pointer"
                  :class="{ 'row-awaiting': o.payment_status === 'submitted', 'row-paid': o.payment_status === 'paid' }"
                  @click="openOrderModal(o)"
                >
                  <!-- INVOICE & DATE -->
                  <td class="cell-inv">
                    <div class="inv-chip-row">
                      <span class="inv-badge">{{ o.invoice_number || o.id.slice(0, 8) }}</span>
                      <span class="kind-badge">{{ o.order_kind || 'hosting' }}</span>
                    </div>
                    <span class="date-sub">
                      {{ new Date(o.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }}
                    </span>
                  </td>

                  <!-- CUSTOMER -->
                  <td class="cell-cust" @click.stop>
                    <button type="button" class="cust-name-link" @click="openCustomer(o.customer_id)">
                      {{ o.customer_name || 'Customer' }}
                    </button>
                    <div class="cust-sub-details">
                      <a :href="`mailto:${o.customer_email}`" class="cust-email-link" :title="o.customer_email">
                        {{ o.customer_email }}
                      </a>
                      <span v-if="o.customer_phone" class="cust-phone-inline">
                        · {{ o.customer_phone }}
                        <button
                          type="button"
                          class="btn-copy-micro"
                          :title="copiedPhoneId === o.id ? 'Copied' : 'Copy Phone'"
                          @click="copyPhone(o.id, o.customer_phone)"
                        >
                          <i class="fa-solid" :class="copiedPhoneId === o.id ? 'fa-check text-green-600' : 'fa-copy'" />
                        </button>
                      </span>
                    </div>
                  </td>

                  <!-- PLAN & DOMAIN -->
                  <td class="cell-plan">
                    <span class="plan-tag">{{ o.plan_name || 'Hosting' }}</span>
                    <div class="domain-tag-inline">
                      <i class="fa-solid fa-globe text-slate-400" />
                      <span class="font-mono text-xs text-slate-800 dark:text-slate-200">
                        {{ domainByOrder[o.id] || o.domain_name || 'No domain assigned' }}
                      </span>
                    </div>
                  </td>

                  <!-- MOMO TX ID -->
                  <td class="cell-momo" @click.stop>
                    <div v-if="o.momo_transaction_id" class="momo-inline-box">
                      <code class="momo-code">{{ o.momo_transaction_id }}</code>
                      <button
                        type="button"
                        class="btn-copy-micro"
                        :title="copiedId === o.id ? 'Copied' : 'Copy MoMo ID'"
                        @click="copyMomo(o.id, o.momo_transaction_id)"
                      >
                        <i class="fa-solid" :class="copiedId === o.id ? 'fa-check text-green-600' : 'fa-copy'" />
                      </button>
                    </div>
                    <span v-else class="text-surface-muted text-xs">—</span>
                  </td>

                  <!-- AMOUNT -->
                  <td v-if="canSeeBilling" class="cell-amount text-right">
                    <span class="font-bold text-slate-900 dark:text-white">
                      {{ o.currency }} {{ Number(o.total_price).toFixed(2) }}
                    </span>
                    <span
                      v-if="isCompOrder(o)"
                      class="comp-badge-pill block text-right"
                    >
                      Comp Grant
                    </span>
                  </td>

                  <!-- PAYMENT STATUS -->
                  <td class="cell-status">
                    <span class="status-pill" :data-s="o.payment_status">
                      <i class="fa-solid" :class="paymentIcon(o.payment_status)" aria-hidden="true" />
                      {{ paymentLabel(o.payment_status) }}
                    </span>
                  </td>

                  <!-- PROVISIONING STATUS -->
                  <td class="cell-status">
                    <span class="status-pill" :data-p="o.provisioning_status">
                      <i class="fa-solid" :class="provisionIcon(o.provisioning_status)" aria-hidden="true" />
                      {{ provisionLabel(o.provisioning_status) }}
                    </span>
                  </td>

                  <!-- ACTIONS -->
                  <td class="cell-actions text-right" @click.stop>
                    <div class="actions-group">
                      <button
                        type="button"
                        class="btn-tbl-primary"
                        title="View Full Details & Action Controls"
                        @click="openOrderModal(o)"
                      >
                        <i class="fa-solid fa-eye" />
                        <span>Details</span>
                      </button>

                      <button
                        v-if="canConfirm"
                        type="button"
                        class="btn-tbl-comp"
                        :class="{ 'is-comp': isCompOrder(o) }"
                        :disabled="busyId === o.id"
                        :title="isCompOrder(o) ? 'Complimentary Grant (Click to revert)' : 'Click to make Complimentary Grant'"
                        @click="toggleComplimentaryStatus(o)"
                      >
                        <i class="fa-solid" :class="isCompOrder(o) ? 'fa-gift' : 'fa-hand-holding-heart'" />
                        <span>{{ isCompOrder(o) ? 'Comp' : 'Make Comp' }}</span>
                      </button>

                      <button
                        type="button"
                        class="btn-tbl-receipt"
                        title="View Invoice / Receipt"
                        @click="openReceipt(o.id)"
                      >
                        <i class="fa-solid fa-file-invoice" />
                        <span>{{ o.payment_status === 'paid' ? 'Receipt' : 'Invoice' }}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
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

          <!-- PAGINATION FOOTER -->
          <footer v-if="filteredOrders.length > 0" class="panel-foot-pagination">
            <div class="pagination-info">
              Showing <strong>{{ showingStart }}</strong> – <strong>{{ showingEnd }}</strong> of <strong>{{ filteredOrders.length }}</strong> orders
            </div>

            <div v-if="totalPages > 1" class="pagination-controls">
              <button
                type="button"
                class="btn-page-nav"
                :disabled="currentPage === 1"
                @click="goToPage(currentPage - 1)"
              >
                <i class="fa-solid fa-chevron-left" /> Previous
              </button>

              <div class="page-numbers">
                <button
                  v-for="p in totalPages"
                  :key="p"
                  type="button"
                  class="btn-page-num"
                  :class="{ active: p === currentPage }"
                  @click="goToPage(p)"
                >
                  {{ p }}
                </button>
              </div>

              <button
                type="button"
                class="btn-page-nav"
                :disabled="currentPage === totalPages"
                @click="goToPage(currentPage + 1)"
              >
                Next <i class="fa-solid fa-chevron-right" />
              </button>
            </div>
          </footer>
        </section>
      </div>
    </div>

    <!-- CLEAN ORDER DETAILS MODAL -->
    <div v-if="showDetailModal && selectedOrder" class="modal-backdrop" @click.self="closeOrderModal">
      <div class="modal-dialog">
        <!-- MODAL HEADER -->
        <header class="modal-header">
          <div class="modal-title-wrap">
            <div class="modal-chips">
              <span class="inv-badge text-sm">{{ selectedOrder.invoice_number || selectedOrder.id.slice(0, 8) }}</span>
              <span class="kind-badge">{{ selectedOrder.order_kind || 'hosting' }}</span>
              <span class="date-badge">
                <i class="fa-regular fa-clock" />
                {{ new Date(selectedOrder.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }}
              </span>
            </div>
            <div class="modal-status-pills mt-1.5">
              <span class="status-pill" :data-s="selectedOrder.payment_status">
                <i class="fa-solid" :class="paymentIcon(selectedOrder.payment_status)" />
                {{ paymentLabel(selectedOrder.payment_status) }}
              </span>
              <span class="status-pill" :data-p="selectedOrder.provisioning_status">
                <i class="fa-solid" :class="provisionIcon(selectedOrder.provisioning_status)" />
                {{ provisionLabel(selectedOrder.provisioning_status) }}
              </span>
              <span v-if="isCompOrder(selectedOrder)" class="comp-badge-pill">
                <i class="fa-solid fa-gift" /> Complimentary Grant
              </span>
            </div>
          </div>
          <button type="button" class="modal-close-btn" title="Close modal (Esc)" @click="closeOrderModal">
            <i class="fa-solid fa-xmark" />
          </button>
        </header>

        <!-- MODAL BODY -->
        <div class="modal-body">
          <!-- GRID OF CARDS -->
          <div class="modal-grid">
            <!-- CUSTOMER INFO CARD -->
            <div class="modal-card">
              <h4 class="card-title">
                <i class="fa-solid fa-user-circle text-brand-600" /> Customer Information
              </h4>
              <div class="detail-rows">
                <div class="detail-row">
                  <span class="row-label">Full Name</span>
                  <span class="row-val font-semibold">{{ selectedOrder.customer_name || 'Customer' }}</span>
                </div>
                <div class="detail-row">
                  <span class="row-label">Email</span>
                  <div class="row-val-group">
                    <a :href="`mailto:${selectedOrder.customer_email}`" class="link-blue">{{ selectedOrder.customer_email }}</a>
                  </div>
                </div>
                <div v-if="selectedOrder.customer_phone" class="detail-row">
                  <span class="row-label">Phone</span>
                  <div class="row-val-group">
                    <a :href="`tel:${selectedOrder.customer_phone}`" class="link-blue">{{ selectedOrder.customer_phone }}</a>
                    <button
                      type="button"
                      class="btn-copy-micro"
                      :title="copiedPhoneId === selectedOrder.id ? 'Copied' : 'Copy Phone'"
                      @click="copyPhone(selectedOrder.id, selectedOrder.customer_phone)"
                    >
                      <i class="fa-solid" :class="copiedPhoneId === selectedOrder.id ? 'fa-check text-green-600' : 'fa-copy'" />
                    </button>
                  </div>
                </div>
                <div class="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                  <button type="button" class="btn-sub-link" @click="openCustomer(selectedOrder.customer_id)">
                    <i class="fa-solid fa-arrow-up-right-from-square" /> Open Customer Profile
                  </button>
                </div>
              </div>
            </div>

            <!-- HOSTING & DOMAIN DETAILS CARD -->
            <div class="modal-card">
              <h4 class="card-title">
                <i class="fa-solid fa-server text-indigo-600" /> Plan &amp; Domain
              </h4>
              <div class="detail-rows">
                <div class="detail-row">
                  <span class="row-label">Hosting Plan</span>
                  <span class="plan-tag">{{ selectedOrder.plan_name || 'Hosting Plan' }}</span>
                </div>
                <div class="detail-row">
                  <span class="row-label">Assigned Domain</span>
                  <div class="domain-manager-wrap">
                    <div v-if="editingDomainId !== selectedOrder.id" class="domain-pill">
                      <i class="fa-solid fa-globe" />
                      <span class="domain-text">{{ domainByOrder[selectedOrder.id] || selectedOrder.domain_name || 'No domain assigned' }}</span>
                      <button
                        v-if="canEditSubdomain && selectedOrder.payment_status !== 'paid'"
                        type="button"
                        class="btn-edit-subdomain"
                        :title="isStudentPlan(selectedOrder) ? 'Customize student subdomain' : 'Edit domain name'"
                        @click="toggleDomainEdit(selectedOrder.id)"
                      >
                        <i class="fa-solid fa-pen" />
                        <span>Edit</span>
                      </button>
                    </div>

                    <!-- INLINE SUBDOMAIN EDITOR -->
                    <div v-else class="domain-edit-form">
                      <div class="domain-input-wrap">
                        <input
                          v-model="domainByOrder[selectedOrder.id]"
                          type="text"
                          class="domain-input"
                          placeholder="e.g. kwame.ifnotus.space"
                          @keyup.enter="editingDomainId = null"
                        />
                      </div>
                      <button type="button" class="btn-domain-done" @click="editingDomainId = null">
                        <i class="fa-solid fa-check" /> Save
                      </button>
                    </div>
                  </div>
                </div>
                <div class="detail-row">
                  <span class="row-label">Order Type</span>
                  <span class="kind-badge">{{ selectedOrder.order_kind || 'hosting' }}</span>
                </div>
              </div>
            </div>

            <!-- PAYMENT & TRANSACTION DATA CARD -->
            <div class="modal-card span-full">
              <h4 class="card-title">
                <i class="fa-solid fa-money-bill-wave text-emerald-600" /> Payment &amp; Reference Verification
              </h4>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <!-- AMOUNT -->
                <div class="metric-mini-box">
                  <span class="metric-mini-label">Total Invoiced</span>
                  <span class="metric-mini-val">{{ selectedOrder.currency }} {{ Number(selectedOrder.total_price).toFixed(2) }}</span>
                </div>

                <!-- EXPECTED SENDING REF -->
                <div class="metric-mini-box">
                  <span class="metric-mini-label">Expected Sending Ref</span>
                  <div class="flex items-center justify-between gap-1 mt-0.5">
                    <code class="font-mono font-bold text-slate-800 dark:text-slate-200">{{ selectedOrder.invoice_number || selectedOrder.id.slice(0, 8) }}</code>
                    <button
                      type="button"
                      class="btn-copy-micro"
                      :title="copiedRefId === selectedOrder.id ? 'Copied' : 'Copy Ref'"
                      @click="copyRef(selectedOrder.id, selectedOrder.invoice_number || selectedOrder.id.slice(0, 8))"
                    >
                      <i class="fa-solid" :class="copiedRefId === selectedOrder.id ? 'fa-check text-green-600' : 'fa-copy'" />
                    </button>
                  </div>
                </div>

                <!-- RECEIVED MOMO TX ID -->
                <div class="metric-mini-box">
                  <span class="metric-mini-label">Customer Submitted MoMo Tx</span>
                  <div v-if="selectedOrder.momo_transaction_id" class="flex items-center justify-between gap-1 mt-0.5">
                    <code class="font-mono font-bold text-emerald-700 dark:text-emerald-400">{{ selectedOrder.momo_transaction_id }}</code>
                    <button
                      type="button"
                      class="btn-copy-micro"
                      :title="copiedId === selectedOrder.id ? 'Copied' : 'Copy MoMo ID'"
                      @click="copyMomo(selectedOrder.id, selectedOrder.momo_transaction_id)"
                    >
                      <i class="fa-solid" :class="copiedId === selectedOrder.id ? 'fa-check text-green-600' : 'fa-copy'" />
                    </button>
                  </div>
                  <span v-else class="text-surface-muted block mt-0.5">—</span>
                </div>
              </div>
            </div>
          </div>

          <!-- ACTION / WORKFLOW SECTION -->
          <div class="modal-action-section mt-4">
            <!-- AWAITING PAYMENT CONFIRMATION (BILLING AGENT / OWNER) -->
            <div
              v-if="canConfirm && selectedOrder.payment_status !== 'paid' && selectedOrder.payment_status !== 'failed'"
              class="action-box"
            >
              <div v-if="busyId === selectedOrder.id" class="activation-progress-box">
                <div class="progress-meta">
                  <span class="progress-title">
                    <i class="fa-solid fa-arrows-rotate fa-spin" />
                    {{ progressStage || 'Processing billing confirmation…' }}
                  </span>
                  <span class="progress-num">{{ progressPercent }}%</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
                </div>
              </div>

              <div v-else class="action-box-inner">
                <h4 class="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-2">
                  <i class="fa-solid fa-check-double text-indigo-500 mr-1" /> Clear Billing &amp; Confirm Payment
                </h4>
                <div class="action-inputs-grid">
                  <!-- PAYMENT METHOD -->
                  <div class="input-col">
                    <label class="compact-label">
                      <span><i class="fa-solid fa-money-bill-transfer" /> Payment Method</span>
                      <select
                        v-model="paymentMethodByOrder[selectedOrder.id]"
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
                      <span><i class="fa-solid fa-coins" /> Amount Received (GHS)</span>
                      <input
                        v-model="amountByOrder[selectedOrder.id]"
                        type="text"
                        inputmode="decimal"
                        class="compact-input"
                        :placeholder="String(selectedOrder.total_price)"
                      />
                    </label>
                  </div>

                  <!-- STAFF NOTE -->
                  <div class="input-col span-full">
                    <label class="compact-label">
                      <span class="label-with-help">
                        <i class="fa-solid fa-clipboard-check" /> Staff Note (Optional)
                        <button
                          type="button"
                          class="help-btn"
                          title="What is a Staff Note?"
                          @click="showNoteHelp = !showNoteHelp"
                        >
                          <i class="fa-regular fa-circle-question" />
                        </button>
                      </span>
                      <input
                        v-model="confirmNotes"
                        type="text"
                        class="compact-input"
                        :placeholder="paymentMethodByOrder[selectedOrder.id] === 'physical_cash' ? 'e.g. Received GHS cash in hand at desk' : 'e.g. Verified in MTN MoMo app tx#5820'"
                      />
                    </label>
                  </div>
                </div>

                <!-- HELP CALLOUT -->
                <div v-if="showNoteHelp" class="note-help-box">
                  <div class="note-help-content">
                    <i class="fa-solid fa-info-circle text-blue-500" />
                    <div>
                      <strong>What is a Staff Note?</strong>
                      <p>
                        A Staff Note is an internal audit entry recorded on this transaction. It is only visible to
                        staff operators and is never displayed to the customer.
                      </p>
                    </div>
                  </div>
                  <button type="button" class="close-help-btn" @click="showNoteHelp = false">Dismiss</button>
                </div>

                <!-- BUTTONS -->
                <div class="action-buttons-row mt-3">
                  <button
                    type="button"
                    class="btn-action-activate"
                    :disabled="busyId === selectedOrder.id"
                    @click="confirmPay(selectedOrder)"
                  >
                    <i class="fa-solid fa-check-double" />
                    Accept Billing &amp; Confirm Payment
                  </button>
                  <button
                    type="button"
                    class="btn-action-reject"
                    :disabled="busyId === selectedOrder.id"
                    @click="rejectPay(selectedOrder)"
                  >
                    <i class="fa-solid fa-xmark" />
                    Reject
                  </button>
                </div>
              </div>
            </div>

            <!-- READY FOR HOSTING ACTIVATION (HOSTING OPS) -->
            <div
              v-else-if="canOps && selectedOrder.payment_status === 'paid' && selectedOrder.provisioning_status !== 'active' && selectedOrder.provisioning_status !== 'n/a'"
              class="action-box ok"
            >
              <div v-if="busyId === selectedOrder.id" class="activation-progress-box">
                <div class="progress-meta">
                  <span class="progress-title">
                    <i class="fa-solid fa-arrows-rotate fa-spin" />
                    Activating server infrastructure &amp; domain…
                  </span>
                  <span class="progress-num">{{ progressPercent }}%</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
                </div>
              </div>
              <div v-else class="flex items-center justify-between gap-3 flex-wrap">
                <div class="text-xs">
                  <i class="fa-solid fa-circle-check text-emerald-500 mr-1" />
                  <strong>Billing Accepted &amp; Verified.</strong> Ready for server infrastructure &amp; domain activation.
                </div>
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="btn-action-activate"
                    :disabled="busyId === selectedOrder.id"
                    @click="activateHosting(selectedOrder)"
                  >
                    <i class="fa-solid fa-rocket" />
                    {{ selectedOrder.order_kind === 'domain' ? 'Activate Domain' : 'Activate Hosting' }}
                  </button>
                  <button
                    v-if="selectedOrder.provisioning_status === 'failed'"
                    type="button"
                    class="btn-action-retry"
                    :disabled="busyId === selectedOrder.id"
                    @click="retryProvision(selectedOrder)"
                  >
                    <i class="fa-solid fa-arrows-rotate" />
                    Retry Setup
                  </button>
                </div>
              </div>
            </div>

            <!-- LIVE & ACTIVE BANNER -->
            <div v-else-if="selectedOrder.payment_status === 'paid' && selectedOrder.provisioning_status === 'active'" class="active-banner">
              <div class="flex items-center gap-2">
                <i class="fa-solid fa-circle-check text-emerald-500 text-base" />
                <span class="text-xs font-medium text-slate-800 dark:text-slate-200">
                  Hosting environment live on <strong>{{ selectedOrder.domain_name || 'assigned domain' }}</strong>
                </span>
              </div>
              <div class="flex items-center gap-2">
                <button
                  v-if="canConfirm"
                  type="button"
                  class="btn-tbl-comp"
                  :class="{ 'is-comp': isCompOrder(selectedOrder) }"
                  :disabled="busyId === selectedOrder.id"
                  @click="toggleComplimentaryStatus(selectedOrder)"
                >
                  <i class="fa-solid" :class="isCompOrder(selectedOrder) ? 'fa-gift' : 'fa-hand-holding-heart'" />
                  <span>{{ isCompOrder(selectedOrder) ? 'Comp Active' : 'Make Comp' }}</span>
                </button>
                <a
                  v-if="selectedOrder.domain_name"
                  :href="`https://${selectedOrder.domain_name}`"
                  target="_blank"
                  rel="noopener"
                  class="btn-tbl-primary"
                >
                  <i class="fa-solid fa-arrow-up-right-from-square" />
                  <span>Visit Website</span>
                </a>
              </div>
            </div>
          </div>
        </div>

        <!-- MODAL FOOTER -->
        <footer class="modal-footer">
          <button type="button" class="btn-footer-receipt" @click="openReceipt(selectedOrder.id)">
            <i class="fa-solid fa-file-invoice" />
            <span>Open Receipt / Invoice</span>
          </button>
          <button type="button" class="btn-footer-close" @click="closeOrderModal">
            Close
          </button>
        </footer>
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
  left: 0.85rem;
  color: #94a3b8;
  font-size: 0.85rem;
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 0.55rem 2.2rem 0.55rem 2.35rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.6rem;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.15s ease;
}

.search-input:focus {
  outline: none;
  border-color: #6366f1;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.search-clear-btn {
  position: absolute;
  right: 0.75rem;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
  font-size: 0.8rem;
}

.search-clear-btn:hover {
  color: #ef4444;
}

.search-match-tag {
  font-size: 0.75rem;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  border-radius: 0.45rem;
  padding: 0.35rem 0.65rem;
  white-space: nowrap;
}

.filters-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-tabs {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  overflow-x: auto;
  padding-bottom: 0.1rem;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.55rem;
  background: #f8fafc;
  color: #64748b;
  font-size: 0.76rem;
  font-weight: 650;
  padding: 0.4rem 0.7rem;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.filter-tab:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.filter-tab.on {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
}

.tab-badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 0.1rem 0.35rem;
  border-radius: 999px;
  background: #334155;
  color: #f8fafc;
}

.badge-sub { background: #d97706; color: #ffffff; }
.badge-unpaid { background: #6366f1; color: #ffffff; }

.flow-count {
  font-size: 0.75rem;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 0.45rem;
  padding: 0.35rem 0.65rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

/* ORDERS PANEL */
.orders-panel {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
}

.panel-head {
  padding: 0.85rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.panel-head-text h2 {
  font-size: 0.95rem;
  font-weight: 750;
  color: #0f172a;
  margin: 0;
}

.panel-sub {
  font-size: 0.72rem;
  color: #64748b;
  margin: 0.1rem 0 0;
}

.page-size-label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: #64748b;
}

.page-size-select {
  padding: 0.2rem 0.4rem;
  font-size: 0.75rem;
  font-weight: 600;
  border: 1px solid #cbd5e1;
  border-radius: 0.4rem;
  background: #ffffff;
  color: #0f172a;
}

/* TABLE & SCROLL WRAPPER */
.orders-table-wrap {
  overflow-x: auto;
  overflow-y: auto;
  max-height: calc(100vh - 280px);
  min-height: 380px;
  position: relative;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}

.orders-table-wrap::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.orders-table-wrap::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.orders-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  text-align: left;
}

.orders-table th {
  position: sticky;
  top: 0;
  z-index: 5;
  padding: 0.65rem 0.85rem;
  font-size: 0.68rem;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.orders-table td {
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.order-row {
  transition: background 0.1s ease;
}

.order-row:hover {
  background: #f8fafc;
}

.order-row.row-awaiting {
  background: rgba(254, 243, 199, 0.25);
}

.order-row.row-awaiting:hover {
  background: rgba(254, 243, 199, 0.45);
}

.cell-inv {
  white-space: nowrap;
}

.inv-chip-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.inv-badge {
  font-family: ui-monospace, monospace;
  font-size: 0.75rem;
  font-weight: 750;
  color: #1e293b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 0.35rem;
  padding: 0.12rem 0.4rem;
}

.kind-badge {
  font-size: 0.65rem;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #6366f1;
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  border-radius: 0.35rem;
  padding: 0.1rem 0.35rem;
}

.date-sub {
  display: block;
  font-size: 0.7rem;
  color: #94a3b8;
  margin-top: 0.15rem;
}

.date-badge {
  font-size: 0.7rem;
  color: #64748b;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.cell-cust {
  min-width: 180px;
}

.cust-name-link {
  font-weight: 700;
  color: #0f172a;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
  font-size: 0.8rem;
}

.cust-name-link:hover {
  color: #4f46e5;
  text-decoration: underline;
}

.cust-sub-details {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.72rem;
  color: #64748b;
  margin-top: 0.1rem;
  flex-wrap: wrap;
}

.cust-email-link {
  color: #64748b;
  text-decoration: none;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cust-email-link:hover {
  color: #0f172a;
  text-decoration: underline;
}

.cust-phone-inline {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}

.btn-copy-micro {
  background: none;
  border: none;
  padding: 0.1rem 0.2rem;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.7rem;
  border-radius: 0.25rem;
}

.btn-copy-micro:hover {
  color: #4f46e5;
  background: #eef2ff;
}

.cell-plan {
  min-width: 160px;
}

.plan-tag {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 700;
  color: #0f172a;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 0.35rem;
  padding: 0.15rem 0.45rem;
}

.domain-tag-inline {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.15rem;
}

.cell-momo {
  white-space: nowrap;
}

.momo-inline-box {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.35rem;
  padding: 0.15rem 0.4rem;
}

.momo-code {
  font-family: ui-monospace, monospace;
  font-size: 0.72rem;
  font-weight: 700;
  color: #047857;
}

.comp-badge-pill {
  font-size: 0.65rem;
  font-weight: 750;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 0.35rem;
  padding: 0.08rem 0.35rem;
  display: inline-block;
  margin-top: 0.15rem;
}

/* STATUS PILLS */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.5rem;
  border-radius: 0.45rem;
  font-size: 0.68rem;
  font-weight: 750;
  white-space: nowrap;
  border: 1px solid transparent;
}

.status-pill[data-s="submitted"] { background: #fef3c7; color: #b45309; border-color: #fde68a; }
.status-pill[data-s="paid"] { background: #d1fae5; color: #047857; border-color: #a7f3d0; }
.status-pill[data-s="pending"] { background: #e0e7ff; color: #4338ca; border-color: #c7d2fe; }
.status-pill[data-s="failed"] { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }

.status-pill[data-p="active"] { background: #d1fae5; color: #047857; border-color: #a7f3d0; }
.status-pill[data-p="queued"],
.status-pill[data-p="pending"],
.status-pill[data-p="running"] { background: #e0e7ff; color: #4338ca; border-color: #c7d2fe; }
.status-pill[data-p="failed"] { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }
.status-pill[data-p="n/a"] { background: #f1f5f9; color: #64748b; border-color: #e2e8f0; }

/* ACTIONS GROUP */
.actions-group {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-tbl-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.35rem 0.6rem;
  border-radius: 0.45rem;
  background: #4f46e5;
  color: #ffffff;
  border: 1px solid #4338ca;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tbl-primary:hover {
  background: #4338ca;
}

.btn-tbl-comp {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.35rem 0.55rem;
  border-radius: 0.45rem;
  background: #ffffff;
  color: #b45309;
  border: 1px solid #fde68a;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tbl-comp:hover {
  background: #fef3c7;
}

.btn-tbl-comp.is-comp {
  background: #fef3c7;
  color: #b45309;
  border-color: #f59e0b;
}

.btn-tbl-receipt {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.7rem;
  font-weight: 650;
  padding: 0.35rem 0.55rem;
  border-radius: 0.45rem;
  background: #ffffff;
  color: #475569;
  border: 1px solid #cbd5e1;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tbl-receipt:hover {
  background: #f8fafc;
  color: #0f172a;
}

/* PAGINATION FOOTER */
.panel-foot-pagination {
  padding: 0.75rem 1rem;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.pagination-info {
  font-size: 0.75rem;
  color: #64748b;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-page-nav {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 650;
  padding: 0.35rem 0.65rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
}

.btn-page-nav:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-page-nav:not(:disabled):hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.page-numbers {
  display: flex;
  align-items: center;
  gap: 0.2rem;
}

.btn-page-num {
  width: 1.85rem;
  height: 1.85rem;
  display: grid;
  place-items: center;
  font-size: 0.75rem;
  font-weight: 700;
  border: 1px solid #e2e8f0;
  border-radius: 0.4rem;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
}

.btn-page-num:hover {
  background: #f8fafc;
}

.btn-page-num.active {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
}

/* MODAL */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 999;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  padding: 1rem;
  overflow-y: auto;
}

.modal-dialog {
  width: 100%;
  max-width: 680px;
  background: #ffffff;
  border-radius: 0.85rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  max-height: 90vh;
  overflow: hidden;
  animation: modalScale 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes modalScale {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.modal-chips {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.modal-status-pills {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.modal-close-btn {
  background: none;
  border: none;
  font-size: 1.1rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
  border-radius: 0.35rem;
}

.modal-close-btn:hover {
  color: #0f172a;
  background: #f1f5f9;
}

.modal-body {
  padding: 1.25rem;
  overflow-y: auto;
  flex: 1;
}

.modal-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.85rem;
}

@media (min-width: 600px) {
  .modal-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.span-full {
  grid-column: 1 / -1;
}

.modal-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  background: #f8fafc;
  padding: 0.85rem;
}

.card-title {
  font-size: 0.78rem;
  font-weight: 750;
  color: #0f172a;
  margin: 0 0 0.65rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.detail-rows {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.76rem;
}

.row-label {
  color: #64748b;
  font-weight: 500;
}

.row-val {
  color: #0f172a;
}

.row-val-group {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.link-blue {
  color: #4f46e5;
  text-decoration: none;
  font-weight: 600;
}

.link-blue:hover {
  text-decoration: underline;
}

.btn-sub-link {
  background: none;
  border: none;
  padding: 0;
  font-size: 0.72rem;
  font-weight: 650;
  color: #4f46e5;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.btn-sub-link:hover {
  text-decoration: underline;
}

.metric-mini-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.6rem 0.75rem;
}

.metric-mini-label {
  display: block;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #64748b;
}

.metric-mini-val {
  display: block;
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
  margin-top: 0.1rem;
}

/* DOMAIN PILL & INLINE EDIT */
.domain-manager-wrap {
  display: flex;
  align-items: center;
}

.domain-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: #0f172a;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.4rem;
  padding: 0.2rem 0.5rem;
}

.domain-text {
  font-family: ui-monospace, monospace;
  font-weight: 600;
}

.btn-edit-subdomain {
  background: none;
  border: none;
  color: #4f46e5;
  cursor: pointer;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
}

.btn-edit-subdomain:hover {
  background: #eef2ff;
}

.domain-edit-form {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.domain-input {
  padding: 0.2rem 0.4rem;
  font-size: 0.75rem;
  border: 1px solid #4f46e5;
  border-radius: 0.35rem;
  font-family: ui-monospace, monospace;
}

.btn-domain-done {
  padding: 0.2rem 0.45rem;
  font-size: 0.72rem;
  font-weight: 700;
  background: #4f46e5;
  color: #ffffff;
  border: none;
  border-radius: 0.35rem;
  cursor: pointer;
}

/* MODAL ACTION BOX */
.action-box {
  border: 1px solid #fde68a;
  background: #fffbeb;
  border-radius: 0.65rem;
  padding: 0.85rem;
}

.action-box.ok {
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.active-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.action-inputs-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.65rem;
}

.compact-label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.72rem;
  font-weight: 650;
  color: #475569;
}

.compact-input {
  padding: 0.4rem 0.6rem;
  font-size: 0.78rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #ffffff;
}

.compact-select {
  font-weight: 500;
}

.label-with-help {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.help-btn {
  background: none;
  border: none;
  color: #6366f1;
  cursor: pointer;
  padding: 0;
}

.note-help-box {
  margin-top: 0.5rem;
  padding: 0.55rem 0.75rem;
  border-radius: 0.5rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.note-help-content {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  font-size: 0.72rem;
  color: #1e3a8a;
}

.close-help-btn {
  font-size: 0.68rem;
  font-weight: 700;
  color: #2563eb;
  background: none;
  border: none;
  cursor: pointer;
}

.action-buttons-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.btn-action-activate {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 750;
  padding: 0.5rem 0.85rem;
  border-radius: 0.55rem;
  background: #047857;
  color: #ffffff;
  border: 1px solid #065f46;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-action-activate:hover {
  background: #065f46;
}

.btn-action-reject {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.5rem 0.85rem;
  border-radius: 0.55rem;
  background: #ffffff;
  color: #b91c1c;
  border: 1px solid #fecaca;
  cursor: pointer;
}

.btn-action-reject:hover {
  background: #fef2f2;
}

.btn-action-retry {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.5rem 0.85rem;
  border-radius: 0.55rem;
  background: #f59e0b;
  color: #ffffff;
  border: 1px solid #d97706;
  cursor: pointer;
}

.activation-progress-box {
  padding: 0.5rem 0;
}

.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.75rem;
  font-weight: 700;
  color: #0f172a;
}

.progress-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
  margin-top: 0.35rem;
}

.progress-fill {
  height: 100%;
  background: #4f46e5;
  transition: width 0.3s ease;
}

/* MODAL FOOTER */
.modal-footer {
  padding: 0.85rem 1.25rem;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: #f8fafc;
}

.btn-footer-receipt {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.45rem 0.85rem;
  border-radius: 0.55rem;
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
  cursor: pointer;
}

.btn-footer-receipt:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.btn-footer-close {
  padding: 0.45rem 1rem;
  font-size: 0.78rem;
  font-weight: 700;
  border-radius: 0.55rem;
  background: #0f172a;
  color: #ffffff;
  border: 1px solid #0f172a;
  cursor: pointer;
}

.btn-footer-close:hover {
  background: #1e293b;
}

/* EMPTY STATE */
.empty-state {
  padding: 3.5rem 1.5rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.empty-icon-wrap {
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 999px;
  background: #f1f5f9;
  display: grid;
  place-items: center;
  font-size: 1.5rem;
  color: #94a3b8;
  margin-bottom: 0.5rem;
}

.empty-state h3 {
  font-size: 1.05rem;
  font-weight: 750;
  color: #0f172a;
  margin: 0;
}

.empty-state p {
  font-size: 0.8rem;
  color: #64748b;
  margin: 0;
  max-width: 320px;
}

.btn-clear-filter {
  margin-top: 0.5rem;
  padding: 0.45rem 0.85rem;
  font-size: 0.78rem;
  font-weight: 700;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  color: #334155;
  cursor: pointer;
}

.state-msg {
  padding: 3rem;
  text-align: center;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  font-size: 0.85rem;
}

/* DARK MODE SUPPORT */
html.dark .orders-head,
html.control-ui.dark .orders-head {
  background: #0b1329;
  border-color: #1e293b;
}

html.dark .head-btn,
html.control-ui.dark .head-btn {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

html.dark .stat-card,
html.control-ui.dark .stat-card {
  background: #0f172a;
  border-color: #1e293b;
}

html.dark .stat-v,
html.control-ui.dark .stat-v {
  color: #f8fafc;
}

html.dark .filters-card,
html.dark .orders-panel,
html.control-ui.dark .filters-card,
html.control-ui.dark .orders-panel {
  background: #0f172a;
  border-color: #1e293b;
}

html.dark .panel-head,
html.dark .panel-foot-pagination,
html.control-ui.dark .panel-head,
html.control-ui.dark .panel-foot-pagination {
  border-color: #1e293b;
}

html.dark .panel-head-text h2,
html.control-ui.dark .panel-head-text h2 {
  color: #f8fafc;
}

html.dark .search-input,
html.control-ui.dark .search-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

html.dark .filter-tab,
html.control-ui.dark .filter-tab {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

html.dark .filter-tab.on,
html.control-ui.dark .filter-tab.on {
  background: #38bdf8;
  border-color: #38bdf8;
  color: #0f172a;
}

html.dark .orders-table th,
html.control-ui.dark .orders-table th {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

html.dark .orders-table td,
html.control-ui.dark .orders-table td {
  border-color: #1e293b;
}

html.dark .order-row:hover,
html.control-ui.dark .order-row:hover {
  background: #1e293b;
}

html.dark .inv-badge,
html.dark .plan-tag,
html.dark .momo-inline-box,
html.control-ui.dark .inv-badge,
html.control-ui.dark .plan-tag,
html.control-ui.dark .momo-inline-box {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

html.dark .cust-name-link,
html.control-ui.dark .cust-name-link {
  color: #f8fafc;
}

html.dark .btn-tbl-comp,
html.dark .btn-tbl-receipt,
html.dark .btn-page-nav,
html.dark .btn-page-num,
html.control-ui.dark .btn-tbl-comp,
html.control-ui.dark .btn-tbl-receipt,
html.control-ui.dark .btn-page-nav,
html.control-ui.dark .btn-page-num {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

html.dark .modal-dialog,
html.control-ui.dark .modal-dialog {
  background: #0f172a;
  border-color: #334155;
}

html.dark .modal-header,
html.dark .modal-footer,
html.control-ui.dark .modal-header,
html.control-ui.dark .modal-footer {
  border-color: #1e293b;
  background: #0b1329;
}

html.dark .modal-card,
html.dark .metric-mini-box,
html.control-ui.dark .modal-card,
html.control-ui.dark .metric-mini-box {
  background: #1e293b;
  border-color: #334155;
}

html.dark .card-title,
html.dark .row-val,
html.dark .metric-mini-val,
html.control-ui.dark .card-title,
html.control-ui.dark .row-val,
html.control-ui.dark .metric-mini-val {
  color: #f8fafc;
}

html.dark .compact-input,
html.control-ui.dark .compact-input {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}
</style>
