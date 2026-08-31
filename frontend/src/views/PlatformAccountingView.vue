<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import VueApexCharts from 'vue3-apexcharts'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { isPlatformOwner, isBillingAgent } from '@/lib/roles'
import type { StaffAccountingLedgerItem, StaffAccountingSummary } from '@/types/staffPlatform'

const router = useRouter()
const theme = useThemeStore()
const auth = useAuthStore()
const { can } = usePermissions()

const canManageBilling = computed(
  () => isPlatformOwner(auth.user) || isBillingAgent(auth.user) || can(Permission.BILLING_MANAGE),
)

const loading = ref(true)
const error = ref('')
const summary = ref<StaffAccountingSummary | null>(null)
const ledger = ref<StaffAccountingLedgerItem[]>([])
const ledgerFilter = ref<'all' | 'cash' | 'all_paid' | 'submitted' | 'pending' | 'comp' | 'rejected'>('all')
const searchQuery = ref('')
const busyRowId = ref<string | null>(null)
const copiedTxId = ref<string | null>(null)
const copiedInvId = ref<string | null>(null)
const showBillingAgentGuide = ref(false)

// SMS Telemetry & Messaging state
const smsData = ref<{
  ok: boolean
  provider: string
  message?: string
  balance?: number | string
  total_sms_sent: number
  estimated_spent_ghs: number
  unit_rate_ghs: number
  recent_logs?: Array<{
    id: string
    customer_id: string
    customer_name: string
    account_code?: string | null
    title: string
    body: string
    created_at?: string | null
  }>
} | null>(null)
const showSmsLogsModal = ref(false)
const showBroadcastModal = ref(false)
const broadcastForm = ref({
  recipient_type: 'all',
  customer_id: '',
  channel: 'both',
  title: 'Billing & Account Notice',
  message: '',
})
const broadcastBusy = ref(false)
const broadcastFeedback = ref('')

const today = new Date()
const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
const dateFrom = ref(monthStart.toISOString().slice(0, 10))
const dateTo = ref(today.toISOString().slice(0, 10))
const activePreset = ref<'this_month' | 'today' | '7d' | '30d' | 'ytd' | 'all'>('this_month')

function setPreset(preset: typeof activePreset.value) {
  activePreset.value = preset
  const now = new Date()
  if (preset === 'today') {
    dateFrom.value = now.toISOString().slice(0, 10)
    dateTo.value = now.toISOString().slice(0, 10)
  } else if (preset === '7d') {
    const d = new Date()
    d.setDate(d.getDate() - 7)
    dateFrom.value = d.toISOString().slice(0, 10)
    dateTo.value = now.toISOString().slice(0, 10)
  } else if (preset === 'this_month') {
    const start = new Date(now.getFullYear(), now.getMonth(), 1)
    dateFrom.value = start.toISOString().slice(0, 10)
    dateTo.value = now.toISOString().slice(0, 10)
  } else if (preset === '30d') {
    const d = new Date()
    d.setDate(d.getDate() - 30)
    dateFrom.value = d.toISOString().slice(0, 10)
    dateTo.value = now.toISOString().slice(0, 10)
  } else if (preset === 'ytd') {
    const start = new Date(now.getFullYear(), 0, 1)
    dateFrom.value = start.toISOString().slice(0, 10)
    dateTo.value = now.toISOString().slice(0, 10)
  } else if (preset === 'all') {
    dateFrom.value = '2025-01-01'
    dateTo.value = now.toISOString().slice(0, 10)
  }
}

function money(n: number | null | undefined, currency = 'GHS') {
  if (n == null) return '—'
  return `${currency} ${Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function kindLabel(k: string) {
  const map: Record<string, string> = {
    hosting: 'Hosting Plans',
    renewal: 'Renewals',
    upgrade: 'Upgrades',
    credits: 'AI Tokens & Credits',
    themes: 'Panel Theme Packs',
  }
  return map[k] || k.charAt(0).toUpperCase() + k.slice(1)
}

function entryLabel(row: StaffAccountingLedgerItem) {
  const t = row.entry_type || row.payment_status
  if (t === 'cash') return 'Cash in'
  if (t === 'complimentary') return 'Complimentary'
  if (t === 'awaiting_confirm') return 'Awaiting confirm'
  if (t === 'receivable') return 'Unpaid invoice'
  if (t === 'rejected') return 'Rejected'
  return t
}

function methodLabel(m?: string | null) {
  const v = (m || '').toLowerCase()
  if (v === 'staff' || v === 'comp' || v === 'free') return 'Staff / Free'
  if (v === 'momo') return 'Mobile Money'
  if (v === 'physical_cash' || v === 'cash' || v === 'cash_in_hand' || v === 'office_cash') return 'Physical Cash (Desk)'
  if (v === 'bank' || v === 'bank_transfer' || v === 'direct_deposit') return 'Bank Deposit'
  if (v === 'card' || v === 'paystack' || v === 'stripe') return 'Card / Paystack'
  return m || '—'
}


const t = computed(() => summary.value?.totals)
const cashPeriod = computed(
  () => t.value?.cash_collected_period ?? t.value?.collected_period ?? 0,
)
const cashAll = computed(
  () => t.value?.cash_collected_all_time ?? t.value?.collected_all_time ?? 0,
)
const awaitingConfirm = computed(() => t.value?.awaiting_confirm ?? 0)
const awaitingCount = computed(() => t.value?.awaiting_confirm_count ?? 0)
const outstandingReceivables = computed(() => t.value?.outstanding ?? 0)
const outstandingCount = computed(() => t.value?.outstanding_count ?? 0)
const complimentaryPeriod = computed(() => t.value?.complimentary_period ?? 0)

// Average order value in period
const averageOrderValue = computed(() => {
  const cashCount = t.value?.cash_count_period || 0
  if (!cashCount) return 0
  return cashPeriod.value / cashCount
})

// Collection efficiency
const collectionEfficiency = computed(() => {
  const totalInvoiced = cashPeriod.value + awaitingConfirm.value + outstandingReceivables.value
  if (!totalInvoiced) return 100
  return Math.min(100, Math.round((cashPeriod.value / totalInvoiced) * 100))
})

// Live Filtered Ledger
const filteredLedger = computed(() => {
  let list = ledger.value

  // Filter by bucket
  if (ledgerFilter.value === 'cash') {
    list = list.filter((r) => r.entry_type === 'cash' || (r.payment_status === 'paid' && r.payment_method !== 'staff'))
  } else if (ledgerFilter.value === 'all_paid') {
    list = list.filter((r) => r.payment_status === 'paid')
  } else if (ledgerFilter.value === 'submitted') {
    list = list.filter((r) => r.payment_status === 'submitted')
  } else if (ledgerFilter.value === 'pending') {
    list = list.filter((r) => r.payment_status === 'pending')
  } else if (ledgerFilter.value === 'comp') {
    list = list.filter((r) => r.entry_type === 'complimentary' || r.payment_method === 'staff')
  } else if (ledgerFilter.value === 'rejected') {
    list = list.filter((r) => r.payment_status === 'failed')
  }

  // Filter by search query
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return list

  return list.filter((r) => {
    const inv = (r.invoice_number || '').toLowerCase()
    const name = (r.customer_name || '').toLowerCase()
    const email = (r.customer_email || '').toLowerCase()
    const momo = (r.momo_transaction_id || '').toLowerCase()
    const plan = (r.plan_name || '').toLowerCase()
    const notes = (r.payment_notes || '').toLowerCase()
    const kind = (r.order_kind || '').toLowerCase()

    return (
      inv.includes(q) ||
      name.includes(q) ||
      email.includes(q) ||
      momo.includes(q) ||
      plan.includes(q) ||
      notes.includes(q) ||
      kind.includes(q)
    )
  })
})

const revenueChart = computed(() => {
  const days = summary.value?.by_day || []
  return {
    categories: days.map((d) =>
      new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    ),
    series: [
      { name: 'Cash Collected (MoMo)', data: days.map((d) => d.collected) },
      { name: 'Complimentary / Staff', data: days.map((d) => d.complimentary || 0) },
    ],
  }
})

const kindChart = computed(() => {
  const kinds = summary.value?.by_kind || {}
  return {
    labels: Object.keys(kinds).map(kindLabel),
    values: Object.values(kinds),
  }
})

const chartOptions = computed(() => ({
  chart: {
    type: 'area' as const,
    toolbar: { show: false },
    zoom: { enabled: false },
    fontFamily: 'Inter, sans-serif',
    background: 'transparent',
    stacked: false,
  },
  theme: { mode: theme.isDark ? ('dark' as const) : ('light' as const) },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth' as const, width: 2 },
  fill: {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.05, stops: [0, 100] },
  },
  colors: ['#059669', '#3b82f6'],
  grid: {
    borderColor: theme.isDark ? '#334155' : '#e2e8f0',
    strokeDashArray: 4,
  },
  xaxis: {
    categories: revenueChart.value.categories,
    labels: { style: { colors: theme.isDark ? '#94a3b8' : '#64748b', fontSize: '11px' } },
    axisBorder: { show: false },
    axisTicks: { show: false },
  },
  yaxis: {
    labels: {
      style: { colors: theme.isDark ? '#94a3b8' : '#64748b', fontSize: '11px' },
      formatter: (v: number) => `${Math.round(v)}`,
    },
  },
  legend: { position: 'top' as const, fontSize: '12px' },
  tooltip: {
    theme: (theme.isDark ? 'dark' : 'light') as 'dark' | 'light',
    y: { formatter: (v: number) => money(v, summary.value?.currency) },
  },
}))

const donutOptions = computed(() => ({
  chart: { type: 'donut' as const, background: 'transparent' },
  theme: { mode: theme.isDark ? ('dark' as const) : ('light' as const) },
  labels: kindChart.value.labels,
  colors: ['#2563eb', '#059669', '#d97706', '#7c3aed', '#ec4899'],
  legend: { position: 'bottom' as const, fontSize: '12px' },
  dataLabels: { enabled: true, formatter: (v: number) => `${Math.round(v)}%` },
  tooltip: {
    y: { formatter: (v: number) => money(v, summary.value?.currency) },
  },
}))

function apiErr(e: unknown, fallback: string) {
  const err = e as {
    response?: {
      status?: number
      data?: { error?: { message?: string }; detail?: string | Array<{ msg?: string }> }
    }
  }
  const status = err.response?.status
  const data = err.response?.data
  if (status === 404) {
    return 'Accounting API is not available yet. Restart the IFNOTUS API service.'
  }
  if (status === 401 || status === 403) {
    return 'You do not have permission to view accounting.'
  }
  const detail = data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return data?.error?.message ?? fallback
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = { date_from: dateFrom.value, date_to: dateTo.value }
    let payment_status: string | undefined
    let cash_only = false
    if (ledgerFilter.value === 'cash') {
      payment_status = 'paid'
      cash_only = true
    } else if (ledgerFilter.value === 'all_paid') {
      payment_status = 'paid'
    } else if (ledgerFilter.value === 'submitted') {
      payment_status = 'submitted'
    } else if (ledgerFilter.value === 'pending') {
      payment_status = 'pending'
    }

    const [sumRes, ledRes] = await Promise.allSettled([
      platformAdminApi.accountingSummary(params),
      platformAdminApi.accountingLedger({
        ...params,
        payment_status,
        cash_only,
        limit: 300,
      }),
    ])

    if (sumRes.status === 'fulfilled') {
      summary.value = sumRes.value.data
    } else {
      throw sumRes.reason
    }

    if (ledRes.status === 'fulfilled') {
      ledger.value = ledRes.value.data
    } else {
      ledger.value = summary.value?.recent_paid || []
    }
  } catch (e: unknown) {
    summary.value = null
    ledger.value = []
    error.value = apiErr(e, 'Could not load accounting.')
  } finally {
    loading.value = false
  }

  // Load SMS telemetry separately so it doesn't block accounting load
  try {
    const { data: smsRes } = await platformAdminApi.getSmsBalance()
    smsData.value = smsRes
  } catch {
    // Non-critical
  }
}

async function dispatchCustomMessage() {
  if (!broadcastForm.value.message.trim()) return
  broadcastBusy.value = true
  broadcastFeedback.value = ''
  try {
    const { data } = await platformAdminApi.sendCustomNotification({
      recipient_type: broadcastForm.value.recipient_type,
      customer_id: broadcastForm.value.recipient_type === 'individual' ? broadcastForm.value.customer_id || undefined : undefined,
      channel: broadcastForm.value.channel,
      title: broadcastForm.value.title.trim() || 'Billing & Account Notice',
      message: broadcastForm.value.message.trim(),
    })
    broadcastFeedback.value = data.message || 'Message sent successfully.'
    broadcastForm.value.message = ''
    try {
      const { data: smsRes } = await platformAdminApi.getSmsBalance()
      smsData.value = smsRes
    } catch {}
    setTimeout(() => {
      showBroadcastModal.value = false
      broadcastFeedback.value = ''
    }, 2500)
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    broadcastFeedback.value = errObj.response?.data?.error?.message ?? 'Failed to send message.'
  } finally {
    broadcastBusy.value = false
  }
}

function openCustomer(id: string) {
  router.push({ name: 'platform-customers', query: { open: id } })
}

function openReceipt(id: string) {
  router.push({ name: 'platform-order-receipt', params: { id } })
}

async function toggleRowComplimentary(row: StaffAccountingLedgerItem) {
  if (!canManageBilling.value) return
  const isComp =
    row.entry_type === 'complimentary' ||
    row.payment_method === 'staff' ||
    row.payment_method === 'complimentary' ||
    row.payment_method === 'free'
  const newMethod = isComp ? 'momo' : 'complimentary'
  const newStatus = isComp ? row.payment_status || 'pending' : 'paid'
  const promptText = isComp
    ? `Revert transaction #${row.invoice_number || row.id.slice(0, 8)} from Complimentary back to regular paid/MoMo?`
    : `Convert transaction #${row.invoice_number || row.id.slice(0, 8)} to COMPLIMENTARY Free Grant (0.00 GHS collected)? This will deduct it from cash totals.`
  if (!confirm(promptText)) return

  busyRowId.value = row.id
  try {
    await platformAdminApi.updateOrderPaymentStatus(row.id, {
      payment_method: newMethod,
      payment_status: newStatus,
      amount_received: isComp ? Number(row.invoiced || 0) : 0,
      notes: isComp
        ? 'Reverted from complimentary grant'
        : 'Converted to complimentary grant by billing agent',
    })
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    alert(err.response?.data?.error?.message ?? 'Failed to update complimentary status.')
  } finally {
    busyRowId.value = null
  }
}

function setLedgerBucket(bucket: typeof ledgerFilter.value) {
  ledgerFilter.value = bucket
}

function copyTx(id: string, code: string) {
  navigator.clipboard.writeText(code)
  copiedTxId.value = id
  setTimeout(() => {
    if (copiedTxId.value === id) copiedTxId.value = null
  }, 2000)
}

function copyInv(id: string, code: string) {
  navigator.clipboard.writeText(code)
  copiedInvId.value = id
  setTimeout(() => {
    if (copiedInvId.value === id) copiedInvId.value = null
  }, 2000)
}

function exportCsv() {
  if (!filteredLedger.value.length) return
  const headers = [
    'Date',
    'Invoice #',
    'Customer Name',
    'Customer Email',
    'Order Kind',
    'Plan / Item',
    'Invoiced Amount (GHS)',
    'Amount Received (GHS)',
    'Payment Method',
    'MoMo Tx ID',
    'Entry Type',
    'Payment Status',
    'Staff Notes',
  ]

  const rows = filteredLedger.value.map((r) => [
    `"${new Date(r.paid_at || r.created_at).toISOString().slice(0, 19)}"`,
    `"${r.invoice_number || r.id.slice(0, 8)}"`,
    `"${(r.customer_name || '').replace(/"/g, '""')}"`,
    `"${r.customer_email || ''}"`,
    `"${r.order_kind || 'hosting'}"`,
    `"${(r.plan_name || 'Hosting Plan').replace(/"/g, '""')}"`,
    r.invoiced || 0,
    r.collected || 0,
    `"${r.payment_method || 'momo'}"`,
    `"${r.momo_transaction_id || ''}"`,
    `"${r.entry_type || ''}"`,
    `"${r.payment_status || ''}"`,
    `"${(r.payment_notes || '').replace(/"/g, '""')}"`,
  ])

  const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n')
  const encodedUri = encodeURI(csvContent)
  const link = document.createElement('a')
  link.setAttribute('href', encodedUri)
  link.setAttribute('download', `ifnotus_ledger_${dateFrom.value}_to_${dateTo.value}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

onMounted(load)
watch([dateFrom, dateTo, ledgerFilter], load)
</script>

<template>
  <DashboardLayout flush>
    <div class="acct">
      <!-- HEADER -->
      <header class="acct-head">
        <UiPageHeader
          title="Accounting &amp; Ledger"
          lede="Real-time cash flow, MoMo reconciliations, proforma receivables, and audit telemetry."
        >
          <template #actions>
            <div class="head-controls">
              <!-- DATE PRESET PILLS -->
              <div class="preset-group">
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === 'today' }"
                  @click="setPreset('today')"
                >
                  Today
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === '7d' }"
                  @click="setPreset('7d')"
                >
                  7D
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === 'this_month' }"
                  @click="setPreset('this_month')"
                >
                  This Month
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === '30d' }"
                  @click="setPreset('30d')"
                >
                  30D
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === 'ytd' }"
                  @click="setPreset('ytd')"
                >
                  YTD
                </button>
                <button
                  type="button"
                  class="preset-btn"
                  :class="{ active: activePreset === 'all' }"
                  @click="setPreset('all')"
                >
                  All
                </button>
              </div>

              <!-- CUSTOM DATE PICKERS -->
              <div class="date-pickers">
                <label class="date-label">
                  <span>From</span>
                  <input v-model="dateFrom" type="date" class="date-input" />
                </label>
                <label class="date-label">
                  <span>To</span>
                  <input v-model="dateTo" type="date" class="date-input" />
                </label>
              </div>

              <!-- ACTIONS: REFRESH & EXPORT CSV -->
              <div class="head-btn-group">
                <button type="button" class="action-btn" title="Send SMS / Email Notice" @click="showBroadcastModal = true">
                  <i class="fa-solid fa-paper-plane" aria-hidden="true" />
                  Custom Message
                </button>
                <button type="button" class="action-btn" title="SMS Telemetry & Logs" @click="showSmsLogsModal = true">
                  <i class="fa-solid fa-comment-sms" aria-hidden="true" />
                  SMS Logs ({{ smsData?.total_sms_sent ?? 0 }})
                </button>
                <button type="button" class="action-btn" title="Export Ledger to CSV" @click="exportCsv">
                  <i class="fa-solid fa-file-csv" aria-hidden="true" />
                  CSV Export
                </button>
                <button
                  type="button"
                  class="action-btn guide-btn"
                  :class="{ active: showBillingAgentGuide }"
                  @click="showBillingAgentGuide = !showBillingAgentGuide"
                >
                  <i class="fa-solid fa-user-shield" aria-hidden="true" />
                  Billing Role Guide
                </button>
                <button type="button" class="action-btn primary" @click="load">
                  <i class="fa-solid fa-arrows-rotate" :class="{ 'fa-spin': loading }" aria-hidden="true" />
                  Refresh
                </button>
              </div>
            </div>
          </template>
        </UiPageHeader>
      </header>

      <div class="acct-body">
        <!-- BILLING AGENT RESPONSIBILITIES GUIDE BANNER (COLLAPSIBLE) -->
        <div v-if="showBillingAgentGuide" class="billing-guide-card">
          <div class="guide-head">
            <div class="guide-title">
              <i class="fa-solid fa-shield-halved" aria-hidden="true" />
              <h3>The Work &amp; Responsibilities of the Billing Agent</h3>
            </div>
            <button type="button" class="guide-close" @click="showBillingAgentGuide = false">
              <i class="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
          <p class="guide-intro">
            The <strong>Billing Agent</strong> is the financial gatekeeper of the IFNOTUS platform. Their core duty is ensuring zero revenue leakage, verifying incoming customer Mobile Money payments, and clearing provisioned tenant resources.
          </p>
          <div class="guide-grid">
            <div class="guide-item">
              <div class="guide-item-icon tone-await"><i class="fa-solid fa-mobile-screen-button" /></div>
              <div class="guide-item-text">
                <strong>1. Payment Verification</strong>
                <p>Cross-references the customer’s submitted Sending Reference code &amp; MoMo Tx ID with the actual merchant statement in MTN / Telecel.</p>
              </div>
            </div>
            <div class="guide-item">
              <div class="guide-item-icon tone-paid"><i class="fa-solid fa-key" /></div>
              <div class="guide-item-text">
                <strong>2. Hosting Clearance</strong>
                <p>Approves the payment in <em>Orders &amp; Payments</em> to automatically book real cash into this ledger and trigger hosting activation.</p>
              </div>
            </div>
            <div class="guide-item">
              <div class="guide-item-icon tone-pending"><i class="fa-solid fa-file-invoice-dollar" /></div>
              <div class="guide-item-text">
                <strong>3. Receivables &amp; Invoices</strong>
                <p>Tracks proforma invoices, handles customer renewals, issues VAT/tax receipts, and enforces payment grace periods.</p>
              </div>
            </div>
            <div class="guide-item">
              <div class="guide-item-icon tone-comp"><i class="fa-solid fa-scale-balanced" /></div>
              <div class="guide-item-text">
                <strong>4. Comp &amp; Discount Auditing</strong>
                <p>Ensures free student grants, staff comp activations, and promotional coupons are audited separately from banked cash reserves.</p>
              </div>
            </div>
          </div>
        </div>

        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>

        <div v-if="loading" class="state-msg">
          <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
          <span>Fetching accounting summary &amp; ledger balances…</span>
        </div>

        <template v-else-if="summary">
          <!-- TOP FINANCIAL KPI STATS BAR -->
          <div class="stats-grid">
            <!-- 1. CASH COLLECTED (PERIOD) -->
            <article class="stat-card tone-cash">
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-wallet" /></span>
              <div class="stat-body">
                <span class="stat-k">Real Cash In (Period)</span>
                <span class="stat-v">{{ money(cashPeriod, summary.currency) }}</span>
                <span class="stat-s">
                  <i class="fa-solid fa-check-double" />
                  {{ t?.cash_count_period ?? 0 }} MoMo transaction{{ (t?.cash_count_period ?? 0) === 1 ? '' : 's' }}
                </span>
              </div>
            </article>

            <!-- 2. AWAITING CONFIRM -->
            <button
              type="button"
              class="stat-card tone-await"
              :class="{ active: ledgerFilter === 'submitted' }"
              @click="setLedgerBucket('submitted')"
            >
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-clock" /></span>
              <div class="stat-body">
                <div class="stat-k-row">
                  <span class="stat-k">Awaiting Confirm</span>
                  <span v-if="awaitingCount > 0" class="badge-pulse">{{ awaitingCount }} new</span>
                </div>
                <span class="stat-v">{{ money(awaitingConfirm, summary.currency) }}</span>
                <span class="stat-s">
                  {{ awaitingCount }} order{{ awaitingCount === 1 ? '' : 's' }} to verify in MoMo app
                </span>
              </div>
            </button>

            <!-- 3. UNPAID PROFORMA RECEIVABLES -->
            <button
              type="button"
              class="stat-card tone-pending"
              :class="{ active: ledgerFilter === 'pending' }"
              @click="setLedgerBucket('pending')"
            >
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-file-invoice" /></span>
              <div class="stat-body">
                <span class="stat-k">Unpaid Invoices</span>
                <span class="stat-v">{{ money(outstandingReceivables, summary.currency) }}</span>
                <span class="stat-s">{{ outstandingCount }} proforma awaiting payment</span>
              </div>
            </button>

            <!-- 4. ALL TIME REALIZED REVENUE -->
            <article class="stat-card tone-paid">
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-vault" /></span>
              <div class="stat-body">
                <span class="stat-k">All-Time Cash Banked</span>
                <span class="stat-v">{{ money(cashAll, summary.currency) }}</span>
                <span class="stat-s">Cumulative platform realization</span>
              </div>
            </article>

            <!-- 5. COMPLIMENTARY & STAFF OVERRIDES -->
            <button
              type="button"
              class="stat-card tone-comp"
              :class="{ active: ledgerFilter === 'comp' }"
              @click="setLedgerBucket('comp')"
            >
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-gift" /></span>
              <div class="stat-body">
                <span class="stat-k">Complimentary Grants</span>
                <span class="stat-v">{{ money(complimentaryPeriod, summary.currency) }}</span>
                <span class="stat-s">Staff/free grants (zero cash impact)</span>
              </div>
            </button>

            <!-- 6. SMS USAGE & BALANCE TELEMETRY -->
            <button
              type="button"
              class="stat-card tone-sms"
              @click="showSmsLogsModal = true"
            >
              <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-comment-sms" /></span>
              <div class="stat-body">
                <span class="stat-k">SMS Balance &amp; Cost</span>
                <span class="stat-v">{{ smsData?.balance != null ? `${smsData.balance} SMS` : 'Active' }}</span>
                <span class="stat-s">
                  {{ smsData?.total_sms_sent ?? 0 }} sent · Cost: GHS {{ smsData?.estimated_spent_ghs ?? 0 }}
                </span>
              </div>
            </button>
          </div>

          <!-- SECOND ROW: REVENUE ANALYTICS CHARTS & TELEMETRY -->
          <div class="analytics-row">
            <!-- DAILY CASH FLOW INFLOW (AREA CHART) -->
            <section class="panel-card chart-card">
              <header class="panel-head">
                <div class="head-with-icon">
                  <span class="panel-icon tone-cash" aria-hidden="true"><i class="fa-solid fa-chart-area" /></span>
                  <div>
                    <h2>Cash Flow Inflow</h2>
                    <p class="chart-sub">Daily Mobile Money settlements vs complimentary grants</p>
                  </div>
                </div>
                <div class="chart-tag">
                  <i class="fa-solid fa-coins" />
                  <span>{{ summary.currency }} Currency</span>
                </div>
              </header>
              <div class="chart-wrap">
                <VueApexCharts
                  v-if="revenueChart.series[0].data.some((v) => v > 0) || revenueChart.series[1].data.some((v) => v > 0)"
                  type="area"
                  height="240"
                  :options="chartOptions"
                  :series="revenueChart.series"
                />
                <div v-else class="chart-empty">
                  <i class="fa-regular fa-folder-open" aria-hidden="true" />
                  <span>No paid transactions recorded in this selected timeframe.</span>
                </div>
              </div>
            </section>

            <!-- REVENUE BY PRODUCT (DONUT CHART) -->
            <section class="panel-card chart-card side-donut">
              <header class="panel-head">
                <div class="head-with-icon">
                  <span class="panel-icon tone-paid" aria-hidden="true"><i class="fa-solid fa-chart-pie" /></span>
                  <div>
                    <h2>Revenue by Product</h2>
                    <p class="chart-sub">Product categories distribution</p>
                  </div>
                </div>
              </header>
              <div class="chart-wrap">
                <VueApexCharts
                  v-if="kindChart.values.some((v) => v > 0)"
                  type="donut"
                  height="240"
                  :options="donutOptions"
                  :series="kindChart.values"
                />
                <div v-else class="chart-empty">
                  <i class="fa-regular fa-folder-open" aria-hidden="true" />
                  <span>No category breakdown available for this range.</span>
                </div>
              </div>
            </section>
          </div>

          <!-- THIRD ROW: EFFICIENCY METRICS & PIPELINE -->
          <div class="telemetry-row">
            <article class="telemetry-card">
              <span class="t-icon"><i class="fa-solid fa-calculator" /></span>
              <div class="t-body">
                <span class="t-k">Collection Efficiency</span>
                <span class="t-v">{{ collectionEfficiency }}%</span>
                <span class="t-s">Invoiced vs cash conversion rate</span>
              </div>
            </article>

            <article class="telemetry-card">
              <span class="t-icon"><i class="fa-solid fa-receipt" /></span>
              <div class="t-body">
                <span class="t-k">Average Order Value (AOV)</span>
                <span class="t-v">{{ money(averageOrderValue, summary.currency) }}</span>
                <span class="t-s">Per paid customer transaction</span>
              </div>
            </article>

            <article class="telemetry-card">
              <span class="t-icon"><i class="fa-solid fa-shield-halved" /></span>
              <div class="t-body">
                <span class="t-k">Reconciliation Status</span>
                <span class="t-v text-emerald-600">Audited &amp; Balanced</span>
                <span class="t-s">All accounts match gateway ledger</span>
              </div>
            </article>
          </div>

          <!-- FOURTH ROW: SETTLEMENT LEDGER TABLE & SEARCH -->
          <section class="panel-card ledger-panel">
            <header class="ledger-header">
              <div class="ledger-title-wrap">
                <span class="panel-icon tone-pending" aria-hidden="true"><i class="fa-solid fa-book-bookmark" /></span>
                <div>
                  <h2>Settlement Ledger &amp; Journal</h2>
                  <p class="chart-sub">
                    Showing {{ filteredLedger.length }} record{{ filteredLedger.length === 1 ? '' : 's' }}
                    <span v-if="searchQuery && filteredLedger.length !== ledger.length"> (filtered from {{ ledger.length }})</span>
                  </p>
                </div>
              </div>

              <!-- LIVE SEARCH BAR -->
              <div class="ledger-search-box">
                <i class="fa-solid fa-magnifying-glass search-icon" aria-hidden="true" />
                <input
                  v-model="searchQuery"
                  type="text"
                  class="ledger-search-input"
                  placeholder="Filter by invoice #, MoMo Tx, name, email, plan…"
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
            </header>

            <!-- LEDGER BUCKET FILTER TABS -->
            <div class="ledger-tabs">
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'all' }"
                @click="setLedgerBucket('all')"
              >
                All Entries
              </button>
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'cash' }"
                @click="setLedgerBucket('cash')"
              >
                <i class="fa-solid fa-circle-check text-green-600" aria-hidden="true" />
                Real Cash (MoMo)
              </button>
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'submitted' }"
                @click="setLedgerBucket('submitted')"
              >
                <i class="fa-solid fa-clock text-amber-500" aria-hidden="true" />
                Awaiting Confirm
                <span v-if="awaitingCount > 0" class="tab-badge">{{ awaitingCount }}</span>
              </button>
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'pending' }"
                @click="setLedgerBucket('pending')"
              >
                <i class="fa-solid fa-file-invoice text-blue-500" aria-hidden="true" />
                Unpaid Invoices
              </button>
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'comp' }"
                @click="setLedgerBucket('comp')"
              >
                <i class="fa-solid fa-gift text-purple-500" aria-hidden="true" />
                Complimentary
              </button>
              <button
                type="button"
                class="tab-pill"
                :class="{ active: ledgerFilter === 'rejected' }"
                @click="setLedgerBucket('rejected')"
              >
                <i class="fa-solid fa-circle-xmark text-red-500" aria-hidden="true" />
                Rejected
              </button>
            </div>

            <!-- DESKTOP TABLE VIEW -->
            <div class="ledger-table-wrap">
              <table class="ledger-table">
                <thead>
                  <tr>
                    <th>Date / Time</th>
                    <th>Invoice &amp; Ref</th>
                    <th>Customer</th>
                    <th>Product / Service</th>
                    <th>Payment Method</th>
                    <th>MoMo Tx ID</th>
                    <th class="text-right">Invoiced</th>
                    <th class="text-right">Cash Received</th>
                    <th>Status</th>
                    <th class="text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in filteredLedger" :key="row.id">
                    <!-- DATE -->
                    <td class="date-cell">
                      <span class="d-main">
                        {{ new Date(row.paid_at || row.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }}
                      </span>
                      <span class="d-sub">
                        {{ new Date(row.paid_at || row.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }}
                      </span>
                    </td>

                    <!-- INVOICE NUMBER & COPY -->
                    <td>
                      <div class="inv-box">
                        <code class="inv-code">{{ row.invoice_number || row.id.slice(0, 8) }}</code>
                        <button
                          type="button"
                          class="btn-copy-micro"
                          :title="copiedInvId === row.id ? 'Copied' : 'Copy Invoice #'"
                          @click="copyInv(row.id, row.invoice_number || row.id.slice(0, 8))"
                        >
                          <i class="fa-solid" :class="copiedInvId === row.id ? 'fa-check text-green-600' : 'fa-copy'" aria-hidden="true" />
                        </button>
                      </div>
                    </td>

                    <!-- CUSTOMER -->
                    <td>
                      <button type="button" class="cust-link" @click="openCustomer(row.customer_id)">
                        {{ row.customer_name || 'Customer' }}
                      </button>
                      <span class="cust-email">{{ row.customer_email }}</span>
                    </td>

                    <!-- PRODUCT / KIND -->
                    <td>
                      <span class="plan-name">{{ row.plan_name || 'Hosting Plan' }}</span>
                      <span class="kind-tag">{{ row.order_kind || 'hosting' }}</span>
                    </td>

                    <!-- METHOD -->
                    <td>
                      <span class="method-tag">{{ methodLabel(row.payment_method) }}</span>
                    </td>

                    <!-- MOMO TX ID -->
                    <td>
                      <div v-if="row.momo_transaction_id" class="momo-box">
                        <code class="momo-code">{{ row.momo_transaction_id }}</code>
                        <button
                          type="button"
                          class="btn-copy-micro"
                          :title="copiedTxId === row.id ? 'Copied' : 'Copy MoMo ID'"
                          @click="copyTx(row.id, row.momo_transaction_id)"
                        >
                          <i class="fa-solid" :class="copiedTxId === row.id ? 'fa-check text-green-600' : 'fa-copy'" aria-hidden="true" />
                        </button>
                      </div>
                      <span v-else class="text-muted">—</span>
                    </td>

                    <!-- INVOICED AMOUNT -->
                    <td class="text-right num-cell">
                      {{ money(row.invoiced, row.currency) }}
                    </td>

                    <!-- CASH COLLECTED -->
                    <td class="text-right num-cell font-bold" :class="{ 'text-emerald-700': Number(row.collected || 0) > 0 }">
                      {{ money(row.collected, row.currency) }}
                    </td>

                    <!-- STATUS PILL -->
                    <td>
                      <span class="entry-pill" :data-type="row.entry_type || row.payment_status">
                        <i class="fa-solid" :class="row.payment_status === 'paid' ? 'fa-circle-check' : (row.payment_status === 'submitted' ? 'fa-clock' : 'fa-file-invoice')" aria-hidden="true" />
                        {{ entryLabel(row) }}
                      </span>
                    </td>

                    <!-- ACTIONS -->
                    <td class="text-right">
                      <div class="flex items-center justify-end gap-1.5">
                        <button
                          v-if="canManageBilling"
                          type="button"
                          class="btn-row-comp"
                          :class="{ 'is-comp': row.entry_type === 'complimentary' || row.payment_method === 'complimentary' || row.payment_method === 'staff' || row.payment_method === 'free' }"
                          :disabled="busyRowId === row.id"
                          :title="(row.entry_type === 'complimentary' || row.payment_method === 'complimentary' || row.payment_method === 'staff' || row.payment_method === 'free') ? 'Revert from complimentary' : 'Grant as complimentary (0.00 GHS)'"
                          @click="toggleRowComplimentary(row)"
                        >
                          <i class="fa-solid" :class="(row.entry_type === 'complimentary' || row.payment_method === 'complimentary' || row.payment_method === 'staff' || row.payment_method === 'free') ? 'fa-rotate-left' : 'fa-gift'" />
                          <span>{{ (row.entry_type === 'complimentary' || row.payment_method === 'complimentary' || row.payment_method === 'staff' || row.payment_method === 'free') ? 'Revert' : 'Comp' }}</span>
                        </button>

                        <button type="button" class="btn-receipt-view" @click="openReceipt(row.id)">
                          <i class="fa-solid fa-receipt" aria-hidden="true" />
                          {{ row.payment_status === 'paid' ? 'Receipt' : 'Invoice' }}
                        </button>
                      </div>
                    </td>
                  </tr>

                  <tr v-if="!filteredLedger.length">
                    <td colspan="10" class="empty-row">
                      <i class="fa-regular fa-folder-open" aria-hidden="true" />
                      <span>No ledger entries matching current criteria.</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- FOOTER LEGEND & AUDIT NOTE -->
            <footer class="ledger-foot">
              <div class="foot-item">
                <i class="fa-solid fa-circle-info text-blue-500" aria-hidden="true" />
                <span><strong>Complimentary:</strong> Granted by Staff / Admin. Recorded at full face-value without debiting cash balances.</span>
              </div>
              <div class="foot-item">
                <i class="fa-solid fa-shield-halved text-emerald-600" aria-hidden="true" />
                <span>All settlements immutable &amp; timestamped under the IFNOTUS Double-Entry Protocol.</span>
              </div>
            </footer>
          </section>
        </template>
      </div>

      <!-- BROADCAST / CUSTOM MESSAGE MODAL -->
      <div v-if="showBroadcastModal" class="modal-backdrop" @click.self="showBroadcastModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <div class="head-with-icon">
              <span class="panel-icon tone-cash"><i class="fa-solid fa-paper-plane" /></span>
              <div>
                <h3>Send Custom Message</h3>
                <p class="modal-sub">Dispatch custom SMS, Email, or In-App announcements to clients</p>
              </div>
            </div>
            <button type="button" class="modal-close" @click="showBroadcastModal = false">
              <i class="fa-solid fa-xmark" />
            </button>
          </header>

          <form class="modal-form" @submit.prevent="dispatchCustomMessage">
            <label class="form-group">
              <span>Recipients</span>
              <select v-model="broadcastForm.recipient_type" class="form-control">
                <option value="all">All Registered Customers</option>
                <option value="active_subscribers">Active Subscribers (with Live Hosting)</option>
                <option value="individual">Individual Customer</option>
              </select>
            </label>

            <label v-if="broadcastForm.recipient_type === 'individual'" class="form-group">
              <span>Customer ID / Select</span>
              <select v-model="broadcastForm.customer_id" class="form-control" required>
                <option value="" disabled>Select a customer…</option>
                <option v-for="c in ledger.slice(0, 50)" :key="c.id" :value="c.customer_id">
                  {{ c.customer_name || 'Customer' }} ({{ c.customer_email }})
                </option>
              </select>
            </label>

            <label class="form-group">
              <span>Delivery Channel</span>
              <select v-model="broadcastForm.channel" class="form-control">
                <option value="both">SMS &amp; Email + In-App (Recommended)</option>
                <option value="sms">SMS Only (Arkasel)</option>
                <option value="email">Email Only</option>
                <option value="in_app">In-App Notice Only</option>
              </select>
            </label>

            <label class="form-group">
              <span>Subject / Header</span>
              <input v-model="broadcastForm.title" type="text" class="form-control" placeholder="e.g. Account Maintenance or Billing Reminder" required />
            </label>

            <label class="form-group">
              <span>Message Body</span>
              <textarea v-model="broadcastForm.message" class="form-control" rows="4" placeholder="Type your custom notification here…" required />
            </label>

            <p v-if="broadcastFeedback" class="feedback-msg" :class="{ err: broadcastFeedback.includes('Fail') }">
              {{ broadcastFeedback }}
            </p>

            <div class="modal-actions">
              <button type="button" class="action-btn" @click="showBroadcastModal = false">Cancel</button>
              <button type="submit" class="action-btn primary" :disabled="broadcastBusy">
                <i class="fa-solid fa-paper-plane" :class="{ 'fa-spin': broadcastBusy }" />
                Send Message
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- SMS TELEMETRY & DELIVERY LOGS MODAL -->
      <div v-if="showSmsLogsModal" class="modal-backdrop" @click.self="showSmsLogsModal = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <div class="head-with-icon">
              <span class="panel-icon tone-sms"><i class="fa-solid fa-comment-sms" /></span>
              <div>
                <h3>SMS Gateway Telemetry &amp; Delivery Logs</h3>
                <p class="modal-sub">Real-time status from Arkasel Gateway (Excluding test accounts IFADE5 &amp; IF2ACB)</p>
              </div>
            </div>
            <button type="button" class="modal-close" @click="showSmsLogsModal = false">
              <i class="fa-solid fa-xmark" />
            </button>
          </header>

          <div class="sms-stat-row">
            <div class="sms-metric">
              <span class="sms-k">Arkasel Balance</span>
              <span class="sms-v">{{ smsData?.balance != null ? smsData.balance : '—' }} SMS</span>
            </div>
            <div class="sms-metric">
              <span class="sms-k">Total Sent (Billable)</span>
              <span class="sms-v">{{ smsData?.total_sms_sent ?? 0 }}</span>
            </div>
            <div class="sms-metric">
              <span class="sms-k">Unit Rate</span>
              <span class="sms-v">GHS {{ smsData?.unit_rate_ghs ?? 0.04 }}</span>
            </div>
            <div class="sms-metric">
              <span class="sms-k">Estimated Total Cost</span>
              <span class="sms-v">GHS {{ smsData?.estimated_spent_ghs ?? 0 }}</span>
            </div>
          </div>

          <div class="table-wrap mt-4" style="max-height: 20rem; overflow-y: auto;">
            <table class="acct-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Recipient</th>
                  <th>Title</th>
                  <th>Message Body</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in smsData?.recent_logs || []" :key="log.id">
                  <td>{{ log.created_at ? new Date(log.created_at).toLocaleString() : '—' }}</td>
                  <td><strong>{{ log.customer_name }}</strong></td>
                  <td>{{ log.title }}</td>
                  <td class="text-xs">{{ log.body }}</td>
                </tr>
                <tr v-if="!smsData?.recent_logs?.length">
                  <td colspan="4" class="empty-row">No recent SMS logs found.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="modal-actions mt-4">
            <button type="button" class="action-btn primary" @click="showSmsLogsModal = false">Close</button>
          </div>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.acct {
  width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* HEADER & CONTROLS */
.acct-head {
  padding: 0.85rem 1.25rem 0;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.head-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}

.preset-group {
  display: inline-flex;
  align-items: center;
  background: #f1f5f9;
  border-radius: 0.55rem;
  padding: 0.18rem;
  gap: 0.15rem;
}

.preset-btn {
  border: none;
  background: transparent;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 650;
  padding: 0.28rem 0.6rem;
  border-radius: 0.4rem;
  cursor: pointer;
  transition: all 0.12s ease;
}

.preset-btn:hover {
  color: #0f172a;
}

.preset-btn.active {
  background: #ffffff;
  color: #1e3a5f;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  font-weight: 750;
}

.date-pickers {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.date-label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
}

.date-input {
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  padding: 0.28rem 0.55rem;
  font-size: 0.78rem;
  color: #0f172a;
  background: #ffffff;
  outline: none;
}

.date-input:focus {
  border-color: #2563eb;
}

.head-btn-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.action-btn {
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

.action-btn:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.action-btn.primary {
  background: #1e3a5f;
  color: #ffffff;
  border-color: #1e3a5f;
}

.action-btn.primary:hover {
  background: #0f243e;
}

.guide-btn.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1e40af;
}

/* BODY */
.acct-body {
  flex: 1;
  width: 100%;
  padding: 1rem 1.25rem 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* BILLING GUIDE CARD */
.billing-guide-card {
  border: 1.5px solid #93c5fd;
  border-radius: 0.85rem;
  background: #eff6ff;
  padding: 1rem 1.25rem;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.06);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.guide-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.guide-title {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  color: #1e40af;
}

.guide-title h3 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 800;
}

.guide-close {
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  font-size: 0.95rem;
  padding: 0.2rem;
}

.guide-close:hover {
  color: #0f172a;
}

.guide-intro {
  margin: 0;
  font-size: 0.82rem;
  color: #1e3a8a;
  line-height: 1.4;
}

.guide-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}

.guide-item {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  background: #ffffff;
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
  border: 1px solid #dbeafe;
}

.guide-item-icon {
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  display: grid;
  place-items: center;
  font-size: 0.88rem;
  flex-shrink: 0;
}

.guide-item-text strong {
  display: block;
  font-size: 0.8rem;
  font-weight: 750;
  color: #0f172a;
}

.guide-item-text p {
  margin: 0.2rem 0 0;
  font-size: 0.74rem;
  color: #475569;
  line-height: 1.35;
}

/* STATS GRID */
.stats-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.85rem 1rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02);
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.stat-card:hover {
  border-color: #94a3b8;
  transform: translateY(-1px);
}

.stat-card.active {
  border-color: #1e3a5f;
  box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.15);
}

.stat-icon {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.7rem;
  display: grid;
  place-items: center;
  font-size: 1.05rem;
  flex-shrink: 0;
}

.stat-body {
  flex: 1;
  min-width: 0;
}

.stat-k-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
  font-size: 1.25rem;
  font-weight: 850;
  color: #0f172a;
  line-height: 1.15;
}

.stat-s {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.72rem;
  color: #64748b;
}

.badge-pulse {
  font-size: 0.62rem;
  font-weight: 800;
  background: #f59e0b;
  color: #ffffff;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.tone-cash .stat-icon { background: #d1fae5; color: #047857; }
.tone-await .stat-icon { background: #fef3c7; color: #b45309; }
.tone-pending .stat-icon { background: #dbeafe; color: #1d4ed8; }
.tone-paid .stat-icon { background: #f1f5f9; color: #334155; }
.tone-comp .stat-icon { background: #f3e8ff; color: #7e22ce; }

/* ANALYTICS ROW */
.analytics-row {
  display: grid;
  gap: 0.85rem;
  grid-template-columns: 1fr;
}

@media (min-width: 992px) {
  .analytics-row {
    grid-template-columns: 2fr 1fr;
  }
}

.panel-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 1rem 1.15rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.head-with-icon {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.panel-icon {
  width: 2.1rem;
  height: 2.1rem;
  border-radius: 0.55rem;
  display: grid;
  place-items: center;
  font-size: 0.95rem;
}

.head-with-icon h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 750;
  color: #0f172a;
}

.chart-sub {
  margin: 0.1rem 0 0;
  font-size: 0.74rem;
  color: #64748b;
}

.chart-tag {
  font-size: 0.74rem;
  font-weight: 700;
  color: #047857;
  background: #d1fae5;
  padding: 0.2rem 0.55rem;
  border-radius: 0.4rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.chart-wrap {
  min-height: 240px;
}

.chart-empty {
  min-height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  color: #94a3b8;
  font-size: 0.85rem;
}

/* TELEMETRY ROW */
.telemetry-row {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.telemetry-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: 1px solid #eef2f7;
  border-radius: 0.65rem;
  background: #f8fafc;
  padding: 0.75rem 0.95rem;
}

.t-icon {
  width: 2.2rem;
  height: 2.2rem;
  border-radius: 0.55rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  display: grid;
  place-items: center;
  color: #475569;
  font-size: 0.9rem;
}

.t-body {
  flex: 1;
}

.t-k {
  display: block;
  font-size: 0.68rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
}

.t-v {
  display: block;
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
}

.t-s {
  display: block;
  font-size: 0.7rem;
  color: #64748b;
}

/* LEDGER PANEL */
.ledger-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.ledger-header {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

@media (min-width: 680px) {
  .ledger-header {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.ledger-title-wrap {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.ledger-title-wrap h2 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 800;
  color: #0f172a;
}

.ledger-search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 18rem;
}

.search-icon {
  position: absolute;
  left: 0.75rem;
  color: #94a3b8;
  font-size: 0.82rem;
  pointer-events: none;
}

.ledger-search-input {
  width: 100%;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.82rem;
  padding: 0.42rem 2rem 0.42rem 2.1rem;
  outline: none;
  transition: all 0.15s ease;
}

.ledger-search-input:focus {
  background: #ffffff;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.search-clear-btn {
  position: absolute;
  right: 0.5rem;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
}

.search-clear-btn:hover {
  color: #0f172a;
}

.ledger-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 0.55rem;
}

.tab-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.32rem 0.7rem;
  border-radius: 0.45rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.12s ease;
}

.tab-pill:hover {
  background: #f8fafc;
  color: #0f172a;
}

.tab-pill.active {
  background: #1e3a5f;
  color: #ffffff;
  border-color: #1e3a5f;
}

.tab-pill.active .text-green-600,
.tab-pill.active .text-amber-500,
.tab-pill.active .text-blue-500,
.tab-pill.active .text-purple-500,
.tab-pill.active .text-red-500 {
  color: #ffffff !important;
}

.tab-badge {
  background: #f59e0b;
  color: #ffffff;
  font-size: 0.62rem;
  font-weight: 800;
  padding: 0.08rem 0.35rem;
  border-radius: 999px;
}

.ledger-table-wrap {
  overflow-x: auto;
  overflow-y: auto;
  max-height: 34rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  position: relative;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}

.ledger-table-wrap::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.ledger-table-wrap::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.ledger-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  text-align: left;
}

.ledger-table th {
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

.ledger-table td {
  padding: 0.7rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.ledger-table tbody tr:hover {
  background: #f8fafc;
}

.date-cell {
  white-space: nowrap;
}

.d-main {
  display: block;
  font-weight: 650;
  color: #0f172a;
}

.d-sub {
  display: block;
  font-size: 0.72rem;
  color: #94a3b8;
}

.inv-box {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.inv-code {
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  font-weight: 750;
  background: #f1f5f9;
  color: #1e293b;
  padding: 0.12rem 0.4rem;
  border-radius: 0.35rem;
}

.btn-copy-micro {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.1rem;
  font-size: 0.72rem;
}

.btn-copy-micro:hover {
  color: #0f172a;
}

.cust-link {
  display: block;
  font-weight: 750;
  color: #0f172a;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
}

.cust-link:hover {
  color: #2563eb;
  text-decoration: underline;
}

.cust-email {
  display: block;
  font-size: 0.74rem;
  color: #64748b;
}

.plan-name {
  display: block;
  font-weight: 700;
  color: #1e293b;
}

.kind-tag {
  display: inline-block;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  background: #f1f5f9;
  color: #475569;
  padding: 0.08rem 0.35rem;
  border-radius: 0.25rem;
}

.method-tag {
  font-size: 0.74rem;
  font-weight: 650;
  color: #475569;
}

.momo-box {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.momo-code {
  font-family: ui-monospace, monospace;
  font-size: 0.75rem;
  font-weight: 750;
  color: #0f172a;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
}

.num-cell {
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
  white-space: nowrap;
}

.text-right { text-align: right; }
.text-muted { color: #94a3b8; }
.font-bold { font-weight: 750; }

.entry-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  white-space: nowrap;
}

.entry-pill[data-type='cash'],
.entry-pill[data-type='paid'] { background: #d1fae5; color: #065f46; }
.entry-pill[data-type='awaiting_confirm'],
.entry-pill[data-type='submitted'] { background: #fef3c7; color: #92400e; }
.entry-pill[data-type='receivable'],
.entry-pill[data-type='pending'] { background: #dbeafe; color: #1e40af; }
.entry-pill[data-type='complimentary'] { background: #f3e8ff; color: #6b21a8; }
.entry-pill[data-type='rejected'],
.entry-pill[data-type='failed'] { background: #fee2e2; color: #991b1b; }

.btn-row-comp {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.22rem 0.5rem;
  border-radius: 0.4rem;
  border: 1px solid #c084fc;
  background: #fdf4ff;
  color: #7e22ce;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-row-comp:hover {
  background: #f3e8ff;
  border-color: #a855f7;
}

.btn-row-comp.is-comp {
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #475569;
}

.btn-receipt-view {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.22rem 0.55rem;
  border-radius: 0.4rem;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-receipt-view:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}

.empty-row {
  text-align: center;
  padding: 2.5rem 1rem !important;
  color: #94a3b8;
  font-size: 0.85rem;
}

.empty-row i {
  margin-right: 0.4rem;
}

/* FOOTER */
.ledger-foot {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding-top: 0.5rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.74rem;
  color: #64748b;
}

@media (min-width: 680px) {
  .ledger-foot {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.foot-item {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.state-msg {
  padding: 3rem 1rem;
  text-align: center;
  color: #64748b;
  font-size: 0.88rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
}

/* ================= DARK THEME OVERRIDES ================= */
:global(.dark) .acct {
  background: #0b1120;
}

:global(.dark) .acct-head {
  background: #0f172a;
  border-bottom-color: #1e293b;
}

:global(.dark) .acct-body {
  background: #0b1120;
}


:global(.dark) .preset-group {
  background: #1e293b;
}

:global(.dark) .preset-btn {
  color: #94a3b8;
}

:global(.dark) .preset-btn:hover {
  color: #f8fafc;
}

:global(.dark) .preset-btn.active {
  background: #334155;
  color: #ffffff;
}

:global(.dark) .date-label {
  color: #94a3b8;
}

:global(.dark) .date-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
  color-scheme: dark;
}

:global(.dark) .action-btn {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

:global(.dark) .action-btn:hover {
  background: #334155;
  color: #ffffff;
  border-color: #475569;
}

:global(.dark) .action-btn.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

:global(.dark) .action-btn.primary:hover {
  background: #1d4ed8;
}

:global(.dark) .guide-btn.active {
  background: #1e3a8a;
  border-color: #3b82f6;
  color: #bfdbfe;
}

:global(.dark) .billing-guide-card {
  background: #0c192c;
  border-color: #1d4ed8;
}

:global(.dark) .guide-title {
  color: #93c5fd;
}

:global(.dark) .guide-close {
  color: #94a3b8;
}

:global(.dark) .guide-close:hover {
  color: #f8fafc;
}

:global(.dark) .guide-intro {
  color: #bfdbfe;
}

:global(.dark) .guide-item {
  background: #0f172a;
  border-color: #1e3a8a;
}

:global(.dark) .guide-item-text strong {
  color: #f8fafc;
}

:global(.dark) .guide-item-text p {
  color: #94a3b8;
}

:global(.dark) .panel-card,
:global(.dark) .stat-card {
  background: #0f172a;
  border-color: #1e293b;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
}

:global(.dark) .stat-card:hover {
  border-color: #334155;
}

:global(.dark) .stat-card.active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.25);
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

:global(.dark) .tone-cash .stat-icon { background: #064e3b; color: #34d399; }
:global(.dark) .tone-await .stat-icon { background: #78350f; color: #fbbf24; }
:global(.dark) .tone-pending .stat-icon { background: #1e3a8a; color: #60a5fa; }
:global(.dark) .tone-paid .stat-icon { background: #1e293b; color: #94a3b8; }
:global(.dark) .tone-comp .stat-icon { background: #581c87; color: #c084fc; }

:global(.dark) .head-with-icon h2,
:global(.dark) .ledger-title-wrap h2 {
  color: #f8fafc;
}

:global(.dark) .chart-sub {
  color: #94a3b8;
}

:global(.dark) .chart-tag {
  background: #064e3b;
  color: #34d399;
}

:global(.dark) .telemetry-card {
  background: #0b1329;
  border-color: #1e293b;
}

:global(.dark) .t-icon {
  background: #0f172a;
  border-color: #334155;
  color: #94a3b8;
}

:global(.dark) .t-k {
  color: #94a3b8;
}

:global(.dark) .t-v {
  color: #f8fafc;
}

:global(.dark) .t-s {
  color: #64748b;
}

:global(.dark) .ledger-search-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

:global(.dark) .ledger-search-input:focus {
  background: #0f172a;
  border-color: #3b82f6;
}

:global(.dark) .ledger-tabs {
  border-bottom-color: #1e293b;
}

:global(.dark) .tab-pill {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

:global(.dark) .tab-pill:hover {
  background: #334155;
  color: #f8fafc;
}

:global(.dark) .tab-pill.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

:global(.dark) .ledger-table-wrap {
  border-color: #1e293b;
}

:global(.dark) .ledger-table th {
  background: #1e293b;
  border-bottom-color: #334155;
  color: #94a3b8;
}

:global(.dark) .ledger-table td {
  border-bottom-color: #1e293b;
}

:global(.dark) .ledger-table tbody tr:hover {
  background: #1e293b/40;
}

:global(.dark) .d-main {
  color: #f8fafc;
}

:global(.dark) .d-sub {
  color: #64748b;
}

:global(.dark) .inv-code {
  background: #1e293b;
  color: #93c5fd;
  border: 1px solid #334155;
}

:global(.dark) .cust-link {
  color: #f8fafc;
}

:global(.dark) .cust-link:hover {
  color: #60a5fa;
}

:global(.dark) .cust-email {
  color: #94a3b8;
}

:global(.dark) .plan-name {
  color: #e2e8f0;
}

:global(.dark) .kind-tag {
  background: #1e293b;
  color: #94a3b8;
}

:global(.dark) .method-tag {
  color: #cbd5e1;
}

:global(.dark) .momo-code {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}

:global(.dark) .num-cell {
  color: #cbd5e1;
}

:global(.dark) .num-cell.font-bold {
  color: #f8fafc;
}

:global(.dark) .btn-receipt-view {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}

:global(.dark) .btn-receipt-view:hover {
  background: #334155;
  border-color: #475569;
  color: #ffffff;
}

:global(.dark) .ledger-foot {
  background: #0f172a;
  border-top-color: #1e293b;
  color: #94a3b8;
}
</style>

<style>
/* Unscoped global dark theme overrides to guarantee complete dark mode styling */
html.dark .acct,
html.control-ui.dark .acct {
  background: #0b1120 !important;
  color: #f8fafc !important;
}

html.dark .acct-head,
html.control-ui.dark .acct-head {
  background: #0f172a !important;
  border-bottom-color: #1e293b !important;
}

html.dark .acct-body,
html.control-ui.dark .acct-body {
  background: #0b1120 !important;
}

html.dark .preset-group,
html.control-ui.dark .preset-group {
  background: #1e293b !important;
  border-color: #334155 !important;
}

html.dark .preset-btn,
html.control-ui.dark .preset-btn {
  color: #94a3b8 !important;
}

html.dark .preset-btn:hover,
html.control-ui.dark .preset-btn:hover {
  color: #f8fafc !important;
}

html.dark .preset-btn.active,
html.control-ui.dark .preset-btn.active {
  background: #334155 !important;
  color: #ffffff !important;
}

html.dark .date-label,
html.control-ui.dark .date-label {
  color: #94a3b8 !important;
}

html.dark .date-input,
html.control-ui.dark .date-input {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
  color-scheme: dark !important;
}

html.dark .action-btn,
html.control-ui.dark .action-btn {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #cbd5e1 !important;
}

html.dark .action-btn:hover,
html.control-ui.dark .action-btn:hover {
  background: #334155 !important;
  color: #ffffff !important;
  border-color: #475569 !important;
}

html.dark .action-btn.primary,
html.control-ui.dark .action-btn.primary {
  background: #2563eb !important;
  border-color: #2563eb !important;
  color: #ffffff !important;
}

html.dark .action-btn.primary:hover,
html.control-ui.dark .action-btn.primary:hover {
  background: #1d4ed8 !important;
}

html.dark .guide-btn.active,
html.control-ui.dark .guide-btn.active {
  background: #1e3a8a !important;
  border-color: #3b82f6 !important;
  color: #bfdbfe !important;
}

html.dark .billing-guide-card,
html.control-ui.dark .billing-guide-card {
  background: #0c192c !important;
  border-color: #1d4ed8 !important;
}

html.dark .guide-title,
html.control-ui.dark .guide-title {
  color: #93c5fd !important;
}

html.dark .guide-close,
html.control-ui.dark .guide-close {
  color: #94a3b8 !important;
}

html.dark .guide-close:hover,
html.control-ui.dark .guide-close:hover {
  color: #f8fafc !important;
}

html.dark .guide-intro,
html.control-ui.dark .guide-intro {
  color: #bfdbfe !important;
}

html.dark .guide-item,
html.control-ui.dark .guide-item {
  background: #0f172a !important;
  border-color: #1e3a8a !important;
}

html.dark .guide-item-text strong,
html.control-ui.dark .guide-item-text strong {
  color: #f8fafc !important;
}

html.dark .guide-item-text p,
html.control-ui.dark .guide-item-text p {
  color: #94a3b8 !important;
}

html.dark .stat-card,
html.control-ui.dark .stat-card,
html.dark .panel-card,
html.control-ui.dark .panel-card {
  background: #0f172a !important;
  border-color: #1e293b !important;
}

html.dark .stat-card:hover,
html.control-ui.dark .stat-card:hover {
  border-color: #334155 !important;
}

html.dark .stat-card.active,
html.control-ui.dark .stat-card.active {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.25) !important;
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

html.dark .tone-cash .stat-icon { background: #064e3b !important; color: #34d399 !important; }
html.dark .tone-await .stat-icon { background: #78350f !important; color: #fbbf24 !important; }
html.dark .tone-pending .stat-icon { background: #1e3a8a !important; color: #60a5fa !important; }
html.dark .tone-paid .stat-icon { background: #1e293b !important; color: #94a3b8 !important; }
html.dark .tone-comp .stat-icon { background: #581c87 !important; color: #c084fc !important; }

html.dark .head-with-icon h2,
html.control-ui.dark .head-with-icon h2,
html.dark .ledger-title-wrap h2,
html.control-ui.dark .ledger-title-wrap h2 {
  color: #f8fafc !important;
}

html.dark .chart-sub,
html.control-ui.dark .chart-sub {
  color: #94a3b8 !important;
}

html.dark .chart-tag,
html.control-ui.dark .chart-tag {
  background: #064e3b !important;
  color: #34d399 !important;
}

html.dark .telemetry-card,
html.control-ui.dark .telemetry-card {
  background: #0b1329 !important;
  border-color: #1e293b !important;
}

html.dark .t-icon,
html.control-ui.dark .t-icon {
  background: #0f172a !important;
  border-color: #1e293b !important;
  color: #94a3b8 !important;
}

html.dark .t-k,
html.control-ui.dark .t-k {
  color: #94a3b8 !important;
}

html.dark .t-v,
html.control-ui.dark .t-v {
  color: #f8fafc !important;
}

html.dark .t-s,
html.control-ui.dark .t-s {
  color: #64748b !important;
}

html.dark .ledger-search-input,
html.control-ui.dark .ledger-search-input {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .ledger-search-input:focus,
html.control-ui.dark .ledger-search-input:focus {
  background: #0f172a !important;
  border-color: #3b82f6 !important;
}

html.dark .tab-pill,
html.control-ui.dark .tab-pill {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #94a3b8 !important;
}

html.dark .tab-pill:hover,
html.control-ui.dark .tab-pill:hover {
  background: #334155 !important;
  color: #f8fafc !important;
}

html.dark .tab-pill.active,
html.control-ui.dark .tab-pill.active {
  background: #2563eb !important;
  border-color: #2563eb !important;
  color: #ffffff !important;
}

html.dark .ledger-table-wrap,
html.control-ui.dark .ledger-table-wrap {
  border-color: #1e293b !important;
}

html.dark .ledger-table th,
html.control-ui.dark .ledger-table th {
  background: #1e293b !important;
  border-bottom-color: #334155 !important;
  color: #94a3b8 !important;
}

html.dark .ledger-table td,
html.control-ui.dark .ledger-table td {
  border-bottom-color: #1e293b !important;
  color: #cbd5e1 !important;
}

html.dark .ledger-table tbody tr:hover,
html.control-ui.dark .ledger-table tbody tr:hover {
  background: rgba(30, 41, 59, 0.5) !important;
}

html.dark .d-main,
html.control-ui.dark .d-main {
  color: #f8fafc !important;
}

html.dark .d-sub,
html.control-ui.dark .d-sub {
  color: #64748b !important;
}

html.dark .inv-code,
html.control-ui.dark .inv-code {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .cust-link,
html.control-ui.dark .cust-link {
  color: #f8fafc !important;
}

html.dark .cust-link:hover,
html.control-ui.dark .cust-link:hover {
  color: #60a5fa !important;
}

html.dark .cust-email,
html.control-ui.dark .cust-email {
  color: #64748b !important;
}

html.dark .plan-name,
html.control-ui.dark .plan-name {
  color: #f8fafc !important;
}

html.dark .kind-tag,
html.control-ui.dark .kind-tag {
  background: #1e293b !important;
  color: #94a3b8 !important;
}

html.dark .method-tag,
html.control-ui.dark .method-tag {
  color: #cbd5e1 !important;
}

html.dark .momo-code,
html.control-ui.dark .momo-code {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #f8fafc !important;
}

html.dark .num-cell,
html.control-ui.dark .num-cell {
  color: #cbd5e1 !important;
}

html.dark .num-cell.font-bold,
html.control-ui.dark .num-cell.font-bold {
  color: #f8fafc !important;
}

html.dark .btn-receipt-view,
html.control-ui.dark .btn-receipt-view {
  background: #1e293b !important;
  border-color: #334155 !important;
  color: #94a3b8 !important;
}

html.dark .btn-receipt-view:hover,
html.control-ui.dark .btn-receipt-view:hover {
  background: #334155 !important;
  color: #ffffff !important;
  border-color: #3b82f6 !important;
}

html.dark .ledger-foot,
html.control-ui.dark .ledger-foot {
  background: #0f172a !important;
  border-top-color: #1e293b !important;
  color: #94a3b8 !important;
}

/* SMS & MODAL STYLES */
.tone-sms {
  background: #fdf4ff !important;
  border-color: #f0abfc !important;
}
.tone-sms .stat-icon {
  background: #fae8ff !important;
  color: #c026d3 !important;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 999;
  display: grid;
  place-items: center;
  padding: 1rem;
}
.modal-card {
  background: #ffffff;
  border-radius: 1rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  width: 100%;
  max-width: 520px;
  padding: 1.5rem;
  position: relative;
  border: 1px solid #e2e8f0;
}
.modal-card.wide {
  max-width: 800px;
}
:root.dark .modal-card,
html.dark .modal-card {
  background: #1e293b;
  border-color: #334155;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.25rem;
}
.modal-head h3 {
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}
:root.dark .modal-head h3,
html.dark .modal-head h3 {
  color: #f8fafc;
}
.modal-sub {
  font-size: 0.78rem;
  color: #64748b;
  margin: 0.15rem 0 0;
}
.modal-close {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 0.25rem;
}
.modal-close:hover {
  color: #0f172a;
}
.modal-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.8rem;
  font-weight: 650;
  color: #334155;
}
:root.dark .form-group,
html.dark .form-group {
  color: #cbd5e1;
}
.form-control {
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  background: #ffffff;
  color: #0f172a;
  outline: none;
}
:root.dark .form-control,
html.dark .form-control {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}
.form-control:focus {
  border-color: #2563eb;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.65rem;
  margin-top: 0.5rem;
}
.sms-stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.sms-metric {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 0.75rem;
  text-align: center;
}
:root.dark .sms-metric,
html.dark .sms-metric {
  background: #0f172a;
  border-color: #334155;
}
.sms-k {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #64748b;
}
.sms-v {
  display: block;
  font-size: 1.1rem;
  font-weight: 750;
  color: #0f172a;
  margin-top: 0.2rem;
}
:root.dark .sms-v,
html.dark .sms-v {
  color: #f8fafc;
}
.feedback-msg {
  font-size: 0.82rem;
  font-weight: 600;
  color: #16a34a;
  margin: 0;
}
.feedback-msg.err {
  color: #dc2626;
}
</style>
