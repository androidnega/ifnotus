<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import VueApexCharts from 'vue3-apexcharts'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import { useThemeStore } from '@/stores/theme'
import type { StaffAccountingLedgerItem, StaffAccountingSummary } from '@/types/staffPlatform'

const router = useRouter()
const theme = useThemeStore()
const loading = ref(true)
const error = ref('')
const summary = ref<StaffAccountingSummary | null>(null)
const ledger = ref<StaffAccountingLedgerItem[]>([])
const ledgerFilter = ref<'cash' | 'all_paid' | 'submitted' | 'pending' | 'all'>('cash')

const today = new Date()
const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
const dateFrom = ref(monthStart.toISOString().slice(0, 10))
const dateTo = ref(today.toISOString().slice(0, 10))

function money(n: number | null | undefined, currency = 'GHS') {
  if (n == null) return '—'
  return `${currency} ${Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function kindLabel(k: string) {
  const map: Record<string, string> = {
    hosting: 'New hosting',
    renewal: 'Renewals',
    upgrade: 'Upgrades',
    credits: 'AI credits',
  }
  return map[k] || k
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
  if (v === 'staff' || v === 'comp' || v === 'free') return 'Staff / free'
  if (v === 'momo') return 'Mobile Money'
  return m || '—'
}

const t = computed(() => summary.value?.totals)
const cashPeriod = computed(
  () => t.value?.cash_collected_period ?? t.value?.collected_period ?? 0,
)
const cashAll = computed(
  () => t.value?.cash_collected_all_time ?? t.value?.collected_all_time ?? 0,
)

const revenueChart = computed(() => {
  const days = summary.value?.by_day || []
  return {
    categories: days.map((d) =>
      new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    ),
    series: [
      { name: 'Cash collected', data: days.map((d) => d.collected) },
      { name: 'Complimentary', data: days.map((d) => d.complimentary || 0) },
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
    gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05, stops: [0, 100] },
  },
  colors: ['#059669', '#94a3b8'],
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
  colors: ['#2563eb', '#059669', '#d97706', '#7c3aed'],
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
        limit: 200,
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
}

function openOrders(filter?: string) {
  router.push({ name: 'platform-orders', query: filter ? { status: filter } : {} })
}

function openCustomer(id: string) {
  router.push({ name: 'platform-customers', query: { open: id } })
}

function openReceipt(id: string) {
  router.push({ name: 'platform-order-receipt', params: { id } })
}

function setLedgerBucket(bucket: typeof ledgerFilter.value) {
  ledgerFilter.value = bucket
}

onMounted(load)
watch([dateFrom, dateTo, ledgerFilter], load)
</script>

<template>
  <DashboardLayout>
    <div class="acct">
      <UiPageHeader title="Accounting" lede="Paid vs pending. Open a receipt or invoice anytime.">
        <template #actions>
          <div class="acct-tools">
            <label class="tool">
              <span>From</span>
              <input v-model="dateFrom" type="date" />
            </label>
            <label class="tool">
              <span>To</span>
              <input v-model="dateTo" type="date" />
            </label>
            <button type="button" class="ds-btn-ghost text-sm tool-btn" @click="load">
              <i class="fa-solid fa-arrows-rotate" aria-hidden="true" />
              Refresh
            </button>
            <button type="button" class="ds-btn-ghost text-sm tool-btn" @click="openOrders('submitted')">
              <i class="fa-solid fa-check-double" aria-hidden="true" />
              Confirm
            </button>
          </div>
        </template>
      </UiPageHeader>

      <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>
      <p v-if="loading" class="muted">
        <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
        Loading accounting…
      </p>

      <template v-else-if="summary">
        <div class="money-buckets">
          <button
            type="button"
            class="stat-card tone-paid"
            :class="{ on: ledgerFilter === 'all_paid' || ledgerFilter === 'cash' }"
            @click="setLedgerBucket('all_paid')"
          >
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-circle-check" /></span>
            <div class="stat-body">
              <span class="stat-k">Paid</span>
              <span class="stat-v">{{ money(cashAll, summary.currency) }}</span>
              <span class="stat-s">Accepted · {{ t?.cash_count_period ?? 0 }} this period</span>
            </div>
          </button>
          <button
            type="button"
            class="stat-card tone-await"
            :class="{ on: ledgerFilter === 'submitted' }"
            @click="setLedgerBucket('submitted')"
          >
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-clock" /></span>
            <div class="stat-body">
              <span class="stat-k">Awaiting</span>
              <span class="stat-v">{{ money(t?.awaiting_confirm, summary.currency) }}</span>
              <span class="stat-s">{{ t?.awaiting_confirm_count || 0 }} to confirm</span>
            </div>
          </button>
          <button
            type="button"
            class="stat-card tone-pending"
            :class="{ on: ledgerFilter === 'pending' }"
            @click="setLedgerBucket('pending')"
          >
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-file-invoice" /></span>
            <div class="stat-body">
              <span class="stat-k">Pending</span>
              <span class="stat-v">{{ money(t?.outstanding, summary.currency) }}</span>
              <span class="stat-s">{{ t?.outstanding_count || 0 }} unpaid</span>
            </div>
          </button>
          <article class="stat-card tone-cash static">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-wallet" /></span>
            <div class="stat-body">
              <span class="stat-k">Cash (period)</span>
              <span class="stat-v">{{ money(cashPeriod, summary.currency) }}</span>
              <span class="stat-s">MoMo in range</span>
            </div>
          </article>
        </div>

        <div class="charts">
          <section class="panel-card">
            <header class="panel-head">
              <span class="panel-icon tone-cash" aria-hidden="true"><i class="fa-solid fa-chart-area" /></span>
              <div>
                <h2>Cash collected</h2>
                <p class="chart-sub">Daily cash in this range</p>
              </div>
            </header>
            <VueApexCharts
              v-if="revenueChart.series[0].data.some((v) => v > 0) || revenueChart.series[1].data.some((v) => v > 0)"
              type="area"
              height="220"
              :options="chartOptions"
              :series="revenueChart.series"
            />
            <p v-else class="chart-empty">
              <i class="fa-regular fa-folder-open" aria-hidden="true" />
              No paid activity in this period.
            </p>
          </section>
          <section class="panel-card">
            <header class="panel-head">
              <span class="panel-icon tone-paid" aria-hidden="true"><i class="fa-solid fa-chart-pie" /></span>
              <div>
                <h2>By product</h2>
                <p class="chart-sub">Cash only</p>
              </div>
            </header>
            <VueApexCharts
              v-if="kindChart.values.some((v) => v > 0)"
              type="donut"
              height="220"
              :options="donutOptions"
              :series="kindChart.values"
            />
            <p v-else class="chart-empty">
              <i class="fa-regular fa-folder-open" aria-hidden="true" />
              No cash in period.
            </p>
          </section>
        </div>

        <section class="panel-card ledger-card">
          <div class="ledger-head">
            <header class="panel-head">
              <span class="panel-icon tone-pending" aria-hidden="true"><i class="fa-solid fa-book" /></span>
              <div>
                <h2>Ledger</h2>
                <p class="chart-sub">Settlements in this view</p>
              </div>
            </header>
            <select v-model="ledgerFilter" class="ledger-filter">
              <option value="cash">Paid — cash (MoMo)</option>
              <option value="all_paid">Paid — all</option>
              <option value="submitted">Awaiting confirm</option>
              <option value="pending">Pending invoices</option>
              <option value="all">Everything</option>
            </select>
          </div>

          <div class="ledger-cards" aria-label="Ledger cards">
            <article v-for="row in ledger" :key="`c-${row.id}`" class="led-card" :data-t="row.entry_type || row.payment_status">
              <header class="led-card-head">
                <div class="led-title">
                  <span class="led-badge" aria-hidden="true">
                    <i
                      class="fa-solid"
                      :class="
                        (row.payment_status || '').toLowerCase() === 'paid'
                          ? 'fa-receipt'
                          : (row.payment_status || '').toLowerCase() === 'submitted'
                            ? 'fa-clock'
                            : 'fa-file-invoice-dollar'
                      "
                    />
                  </span>
                  <div class="min0">
                    <p class="led-inv">{{ row.invoice_number || row.id.slice(0, 8) }}</p>
                    <button type="button" class="link led-who" @click="openCustomer(row.customer_id)">
                      {{ row.customer_name || row.customer_email }}
                    </button>
                  </div>
                </div>
                <span class="pill" :data-t="row.entry_type || row.payment_status">
                  {{ entryLabel(row) }}
                </span>
              </header>
              <p class="led-meta">
                <i class="fa-solid fa-box" aria-hidden="true" />
                {{ kindLabel(row.order_kind) }} · {{ row.plan_name }}
              </p>
              <div class="led-money">
                <div class="led-money-cell">
                  <span class="led-k"><i class="fa-solid fa-file-lines" aria-hidden="true" /> Invoiced</span>
                  <span>{{ money(row.invoiced, row.currency) }}</span>
                </div>
                <div class="led-money-cell">
                  <span class="led-k"><i class="fa-solid fa-coins" aria-hidden="true" /> Cash</span>
                  <strong v-if="row.collected != null" class="cash">{{ money(row.collected, row.currency) }}</strong>
                  <span v-else-if="row.complimentary != null" class="comp">{{ money(row.complimentary, row.currency) }}*</span>
                  <span v-else class="muted">—</span>
                </div>
              </div>
              <p v-if="row.momo_transaction_id" class="led-momo">
                <i class="fa-solid fa-mobile-screen" aria-hidden="true" />
                <code>{{ row.momo_transaction_id }}</code>
              </p>
              <footer class="led-card-foot">
                <span class="muted">
                  <i class="fa-regular fa-calendar" aria-hidden="true" />
                  {{
                    row.paid_at
                      ? new Date(row.paid_at).toLocaleString()
                      : new Date(row.created_at).toLocaleString()
                  }}
                </span>
                <button type="button" class="btn-doc" @click="openReceipt(row.id)">
                  <i
                    class="fa-solid"
                    :class="(row.payment_status || '').toLowerCase() === 'paid' ? 'fa-receipt' : 'fa-file-invoice'"
                    aria-hidden="true"
                  />
                  {{ (row.payment_status || '').toLowerCase() === 'paid' ? 'Receipt' : 'Invoice' }}
                </button>
              </footer>
            </article>
            <p v-if="!ledger.length" class="empty">
              <i class="fa-regular fa-folder-open" aria-hidden="true" />
              No entries in this view.
            </p>
          </div>

          <div class="ledger-wrap">
            <table class="ledger-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Invoice</th>
                  <th>Customer</th>
                  <th>Product</th>
                  <th>Invoiced</th>
                  <th>Cash in</th>
                  <th class="hide-md">Channel</th>
                  <th class="hide-md">MoMo ID</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in ledger" :key="row.id">
                  <td class="nowrap">
                    {{
                      row.paid_at
                        ? new Date(row.paid_at).toLocaleString()
                        : new Date(row.created_at).toLocaleString()
                    }}
                  </td>
                  <td><code>{{ row.invoice_number || row.id.slice(0, 8) }}</code></td>
                  <td>
                    <button type="button" class="link" @click="openCustomer(row.customer_id)">
                      {{ row.customer_name || row.customer_email }}
                    </button>
                  </td>
                  <td>{{ kindLabel(row.order_kind) }} · {{ row.plan_name }}</td>
                  <td>{{ money(row.invoiced, row.currency) }}</td>
                  <td>
                    <strong v-if="row.collected != null" class="cash">{{ money(row.collected, row.currency) }}</strong>
                    <span v-else-if="row.complimentary != null" class="comp">{{ money(row.complimentary, row.currency) }}*</span>
                    <span v-else class="muted">—</span>
                  </td>
                  <td class="hide-md">{{ methodLabel(row.payment_method) }}</td>
                  <td class="hide-md">
                    <code v-if="row.momo_transaction_id">{{ row.momo_transaction_id }}</code>
                    <span v-else class="muted">—</span>
                  </td>
                  <td>
                    <span class="pill" :data-t="row.entry_type || row.payment_status">
                      {{ entryLabel(row) }}
                    </span>
                  </td>
                  <td>
                    <button type="button" class="btn-doc" @click="openReceipt(row.id)">
                      <i
                        class="fa-solid"
                        :class="(row.payment_status || '').toLowerCase() === 'paid' ? 'fa-receipt' : 'fa-file-invoice'"
                        aria-hidden="true"
                      />
                      {{
                        (row.payment_status || '').toLowerCase() === 'paid'
                          ? 'Receipt'
                          : 'Invoice'
                      }}
                    </button>
                  </td>
                </tr>
                <tr v-if="!ledger.length">
                  <td colspan="10" class="empty">No entries in this view.</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="legend">
            <i class="fa-solid fa-circle-info" aria-hidden="true" />
            Complimentary = staff activation (not cash).
          </p>
        </section>
      </template>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.acct {
  width: 100%;
  max-width: 72rem;
  margin: 0 auto;
  padding: 0.75rem 0.75rem 2rem;
  box-sizing: border-box;
}
@media (min-width: 640px) {
  .acct { padding: 1rem 1rem 2.5rem; }
}

.acct-tools {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  width: 100%;
}
@media (min-width: 720px) {
  .acct-tools {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    width: auto;
    gap: 0.65rem;
  }
}
.tool {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  min-width: 0;
}
.tool input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.45rem 0.55rem;
  font-size: 0.85rem;
  background: #fff;
  box-sizing: border-box;
}
.tool-btn {
  width: 100%;
  justify-content: center;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
@media (min-width: 720px) {
  .tool-btn { width: auto; }
}

.muted { color: #64748b; font-size: 0.875rem; }
.muted i { margin-right: 0.35rem; }

.money-buckets {
  display: grid;
  gap: 0.65rem;
  grid-template-columns: 1fr;
  margin: 0.75rem 0 1rem;
}
@media (min-width: 520px) {
  .money-buckets { grid-template-columns: 1fr 1fr; }
}
@media (min-width: 960px) {
  .money-buckets { grid-template-columns: repeat(4, 1fr); }
}

.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #fff;
  padding: 0.9rem 1rem;
  cursor: pointer;
  min-width: 0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}
.stat-card:hover:not(.static) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
}
.stat-card.static { cursor: default; }
.stat-card.on {
  border-color: #93c5fd;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.16);
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
  font-size: clamp(1rem, 3.2vw, 1.25rem);
  font-weight: 800;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  word-break: break-word;
  line-height: 1.2;
}
.stat-s {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.72rem;
  color: #64748b;
  line-height: 1.35;
}

.tone-paid .stat-icon,
.panel-icon.tone-paid {
  background: #dcfce7;
  color: #15803d;
}
.tone-await .stat-icon {
  background: #fef3c7;
  color: #b45309;
}
.tone-pending .stat-icon,
.panel-icon.tone-pending {
  background: #e0e7ff;
  color: #4338ca;
}
.tone-cash .stat-icon,
.panel-icon.tone-cash {
  background: #d1fae5;
  color: #047857;
}
.tone-paid { background: linear-gradient(180deg, #f0fdf4 0%, #fff 70%); }
.tone-await { background: linear-gradient(180deg, #fffbeb 0%, #fff 70%); }
.tone-pending { background: linear-gradient(180deg, #eef2ff 0%, #fff 70%); }
.tone-cash { background: linear-gradient(180deg, #ecfdf5 0%, #fff 70%); border-color: #a7f3d0; }

.charts {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr;
  margin-bottom: 1rem;
}
@media (min-width: 900px) {
  .charts { grid-template-columns: 1.4fr 1fr; gap: 1rem; margin-bottom: 1.25rem; }
}

.panel-card {
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #fff;
  padding: 0.9rem 1rem 1.05rem;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.panel-head {
  display: flex;
  align-items: flex-start;
  gap: 0.7rem;
  margin-bottom: 0.35rem;
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
.panel-head h2,
.ledger-head h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}
.chart-sub {
  margin: 0.15rem 0 0;
  font-size: 0.78rem;
  color: #64748b;
}
.chart-empty {
  padding: 1.75rem 1rem;
  text-align: center;
  color: #94a3b8;
  font-size: 0.85rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.45rem;
}
.chart-empty i { font-size: 1.35rem; opacity: 0.8; }

.ledger-head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
@media (min-width: 640px) {
  .ledger-head {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
  }
}
.ledger-filter {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.5rem 0.65rem;
  font-size: 0.85rem;
  background: #fff;
  box-sizing: border-box;
}
@media (min-width: 640px) {
  .ledger-filter { width: auto; min-width: 12.5rem; }
}

.ledger-cards {
  display: grid;
  gap: 0.7rem;
}
.led-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.9rem;
  padding: 0.85rem 0.9rem;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  border-left: 3px solid #cbd5e1;
}
.led-card[data-t='cash'],
.led-card[data-t='paid'] { border-left-color: #10b981; }
.led-card[data-t='awaiting_confirm'],
.led-card[data-t='submitted'] { border-left-color: #f59e0b; }
.led-card[data-t='receivable'],
.led-card[data-t='pending'] { border-left-color: #6366f1; }
.led-card[data-t='complimentary'] { border-left-color: #94a3b8; }
.led-card[data-t='rejected'] { border-left-color: #ef4444; }

.led-card-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: flex-start;
}
.led-title {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  min-width: 0;
}
.led-badge {
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
.led-inv {
  margin: 0;
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  font-weight: 700;
  color: #0f172a;
}
.led-who {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.84rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.led-meta {
  margin: 0.55rem 0 0;
  font-size: 0.75rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.led-money {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  margin-top: 0.65rem;
}
.led-money-cell {
  border: 1px solid #eef2f7;
  border-radius: 0.65rem;
  background: #f8fafc;
  padding: 0.5rem 0.6rem;
  font-size: 0.85rem;
  font-weight: 600;
}
.led-k {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-bottom: 0.2rem;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94a3b8;
}
.led-momo {
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.led-card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.7rem;
  padding-top: 0.6rem;
  border-top: 1px solid #eef2f7;
  font-size: 0.72rem;
}
.led-card-foot .muted {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-doc {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 0.5rem;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
}
.btn-doc:hover { background: #dbeafe; }

.ledger-wrap {
  display: none;
  overflow: auto;
  max-height: 28rem;
  -webkit-overflow-scrolling: touch;
}
@media (min-width: 900px) {
  .ledger-cards { display: none; }
  .ledger-wrap { display: block; }
}

.ledger-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.ledger-table th {
  text-align: left;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  padding: 0.5rem 0.65rem;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 1;
}
.ledger-table td {
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: top;
}
@media (max-width: 1100px) {
  .hide-md { display: none; }
}
.nowrap { white-space: nowrap; }
.link {
  border: 0;
  background: none;
  color: #2563eb;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  text-align: left;
}
.cash { color: #047857; }
.comp { color: #64748b; }
.pill {
  display: inline-flex;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.65rem;
  font-weight: 700;
  background: #f1f5f9;
  white-space: nowrap;
}
.pill[data-t='cash'] { background: #d1fae5; color: #065f46; }
.pill[data-t='complimentary'] { background: #e2e8f0; color: #475569; }
.pill[data-t='awaiting_confirm'] { background: #fef3c7; color: #92400e; }
.pill[data-t='receivable'] { background: #e0e7ff; color: #3730a3; }
.pill[data-t='rejected'] { background: #fee2e2; color: #991b1b; }
.empty {
  text-align: center;
  padding: 1.5rem 1rem;
  color: #64748b;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
}
.legend {
  margin: 0.7rem 0 0;
  font-size: 0.72rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.dark .panel-card,
.dark .tool input,
.dark .ledger-filter,
.dark .ledger-table th,
.dark .stat-card,
.dark .led-card,
.dark .led-money-cell {
  background: #0f172a;
  border-color: #334155;
  color: #e2e8f0;
}
.dark .tone-paid,
.dark .tone-await,
.dark .tone-pending,
.dark .tone-cash {
  background: #0f172a;
}
.dark .stat-v,
.dark .panel-head h2,
.dark .ledger-head h2,
.dark .led-inv { color: #f8fafc; }
.dark .btn-doc {
  background: rgba(37, 99, 235, 0.15);
  border-color: #1e3a5f;
  color: #93c5fd;
}
</style>
