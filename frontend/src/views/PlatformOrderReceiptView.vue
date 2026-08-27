<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import type { CustomerOrder } from '@/types/platform'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const order = ref<CustomerOrder | null>(null)
const planName = ref('')
const customerName = ref('')
const customerEmail = ref('')
const customerPhone = ref('')
const documentKind = ref<'invoice' | 'receipt'>('invoice')
const supportHours = ref('Monday–Saturday, 08:00–20:00 GMT')
const supportWhatsapp = ref('+233541069241')

const isPaid = computed(() => (order.value?.payment_status || '').toLowerCase() === 'paid')
const isReceipt = computed(() => documentKind.value === 'receipt' || isPaid.value)

const statusLabel = computed(() => {
  const s = (order.value?.payment_status || 'pending').toLowerCase()
  if (s === 'submitted') return 'Awaiting confirmation'
  if (s === 'paid') return 'Paid'
  if (s === 'pending') return 'Pending payment'
  if (s === 'failed') return 'Rejected'
  return s.charAt(0).toUpperCase() + s.slice(1)
})

const invoiceNo = computed(
  () => order.value?.invoice_number || order.value?.id.slice(0, 8).toUpperCase() || '—',
)

const issuedOn = computed(() => {
  if (!order.value?.created_at) return '—'
  return new Date(order.value.created_at).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
})

const paidOn = computed(() => {
  if (!order.value?.paid_at) return ''
  return new Date(order.value.paid_at).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
})

const lineDescription = computed(() => {
  const kind = (order.value?.order_kind || 'hosting').toLowerCase()
  if (kind === 'renewal') return '30-day subscription renewal'
  if (kind === 'upgrade') return 'Plan upgrade — 30 days'
  if (kind === 'credits') return 'AI Engineer credits top-up'
  return '30-day managed hosting subscription'
})

function money(value: number | string | undefined | null) {
  return Number(value || 0).toFixed(2)
}

function printDoc() {
  window.print()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.getOrderInvoice(String(route.params.id))
    order.value = data.order
    planName.value = data.plan_name || ''
    customerName.value = data.customer_name || ''
    customerEmail.value = data.customer_email || ''
    customerPhone.value = data.customer_phone || ''
    documentKind.value = data.document_kind === 'receipt' ? 'receipt' : 'invoice'
    supportHours.value = data.support_hours || supportHours.value
    supportWhatsapp.value = data.support_whatsapp || supportWhatsapp.value
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load receipt.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <DashboardLayout>
    <div class="receipt-page">
      <UiPageHeader
        class="no-print"
        :title="isReceipt ? 'Payment receipt' : 'Invoice (pending)'"
        :lede="
          isReceipt
            ? 'Accepted as paid by IFNOTUS. Customer and staff can keep this as proof of payment.'
            : 'Not yet accepted as paid. Same document becomes a receipt after confirmation.'
        "
      >
        <template #actions>
          <button type="button" class="btn-ghost" @click="router.push({ name: 'platform-orders' })">
            Orders
          </button>
          <button type="button" class="btn-ghost" @click="router.push({ name: 'platform-accounting' })">
            Accounting
          </button>
          <button type="button" class="btn-primary" @click="printDoc">Save PDF</button>
        </template>
      </UiPageHeader>

      <UiAlert v-if="error" variant="error" class="no-print">{{ error }}</UiAlert>
      <p v-else-if="loading" class="state no-print">Loading…</p>

      <article v-else-if="order" class="sheet" :aria-label="isReceipt ? 'Receipt' : 'Invoice'">
        <header class="sheet-head">
          <div class="brand-block">
            <div class="brand-mark" aria-hidden="true">IF</div>
            <div>
              <p class="brand-name">IFNOTUS</p>
              <p class="brand-tag">Hosting · Accra, Ghana</p>
              <p class="brand-web">ifnotus.space · support@ifnotus.space</p>
            </div>
          </div>
          <div class="sheet-title-block">
            <p class="sheet-kind">{{ isReceipt ? 'Official receipt' : 'Proforma / tax invoice' }}</p>
            <h2 class="sheet-invoice-title">{{ isReceipt ? 'RECEIPT' : 'INVOICE' }}</h2>
            <p class="sheet-no"># {{ invoiceNo }}</p>
            <span class="status-pill" :data-s="order.payment_status">{{ statusLabel }}</span>
          </div>
        </header>

        <div class="meta-grid">
          <div class="meta-card">
            <p class="meta-label">Bill to</p>
            <p class="meta-strong">{{ customerName || 'Customer' }}</p>
            <p v-if="customerEmail" class="meta-line">{{ customerEmail }}</p>
            <p v-if="customerPhone" class="meta-line">{{ customerPhone }}</p>
          </div>
          <div class="meta-card meta-card-right">
            <p class="meta-label">{{ isReceipt ? 'Receipt details' : 'Invoice details' }}</p>
            <dl class="meta-dl">
              <div><dt>Issue date</dt><dd>{{ issuedOn }}</dd></div>
              <div v-if="paidOn"><dt>Paid on</dt><dd>{{ paidOn }}</dd></div>
              <div v-if="order.domain_name"><dt>Site</dt><dd>{{ order.domain_name }}</dd></div>
              <div><dt>Currency</dt><dd>{{ order.currency }}</dd></div>
            </dl>
          </div>
        </div>

        <table class="items-table">
          <thead>
            <tr>
              <th>Description</th>
              <th>Qty</th>
              <th>Unit price</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>{{ planName || 'Hosting plan' }}</strong>
                <span class="item-hint">{{ lineDescription }}</span>
              </td>
              <td>1</td>
              <td>{{ order.currency }} {{ money(order.plan_price ?? order.total_price) }}</td>
              <td class="amt">{{ order.currency }} {{ money(order.plan_price ?? order.total_price) }}</td>
            </tr>
            <tr v-if="Number(order.domain_price || 0) > 0">
              <td>
                <strong>Domain registration</strong>
                <span v-if="order.domain_name" class="item-hint">{{ order.domain_name }}</span>
              </td>
              <td>1</td>
              <td>{{ order.currency }} {{ money(order.domain_price) }}</td>
              <td class="amt">{{ order.currency }} {{ money(order.domain_price) }}</td>
            </tr>
          </tbody>
        </table>

        <div class="totals-row">
          <div class="totals-box">
            <div class="totals-line">
              <span>Subtotal</span>
              <span>{{ order.currency }} {{ money(order.total_price) }}</span>
            </div>
            <div class="totals-line totals-grand">
              <span>{{ isReceipt ? 'Amount paid' : 'Total due' }}</span>
              <strong>{{ order.currency }} {{ money(order.total_price) }}</strong>
            </div>
          </div>
        </div>

        <p v-if="order.momo_transaction_id" class="sheet-note">
          MoMo transaction ID: <code>{{ order.momo_transaction_id }}</code>
        </p>
        <p v-if="order.provisioning_status === 'active'" class="sheet-live">Hosting is active.</p>

        <footer class="sheet-foot">
          <div>
            <p>IFNOTUS · Accra, Ghana</p>
            <p>Support {{ supportHours }} · WhatsApp {{ supportWhatsapp }}</p>
          </div>
          <p class="sheet-thanks">
            {{ isReceipt ? 'Payment accepted. Thank you.' : 'Awaiting payment confirmation.' }}
          </p>
        </footer>
      </article>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.receipt-page {
  max-width: 48rem;
  margin: 0 auto;
  padding: 1rem 1rem 2.5rem;
}
.state { color: #64748b; }
.btn-primary,
.btn-ghost {
  border-radius: 0.65rem;
  padding: 0.5rem 0.9rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary {
  border: none;
  background: #2563eb;
  color: #fff;
}
.btn-ghost {
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #334155;
}
.sheet {
  margin-top: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #fff;
  padding: 1.5rem 1.35rem 1.25rem;
}
.sheet-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 1rem;
}
.brand-block { display: flex; gap: 0.75rem; align-items: center; }
.brand-mark {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.65rem;
  background: #0f172a;
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 0.85rem;
}
.brand-name { margin: 0; font-weight: 800; letter-spacing: 0.04em; }
.brand-tag,
.brand-web { margin: 0.1rem 0 0; font-size: 0.75rem; color: #64748b; }
.sheet-title-block { text-align: right; }
.sheet-kind {
  margin: 0;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #64748b;
  font-weight: 700;
}
.sheet-invoice-title {
  margin: 0.15rem 0;
  font-size: 1.65rem;
  letter-spacing: 0.06em;
  color: #0f172a;
}
.sheet-no { margin: 0; font-family: ui-monospace, monospace; color: #475569; }
.status-pill {
  display: inline-block;
  margin-top: 0.4rem;
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.7rem;
  font-weight: 700;
  background: #f1f5f9;
  color: #334155;
}
.status-pill[data-s='paid'] { background: #dcfce7; color: #166534; }
.status-pill[data-s='submitted'] { background: #fef3c7; color: #92400e; }
.status-pill[data-s='pending'] { background: #e2e8f0; color: #475569; }
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin: 1.1rem 0;
}
.meta-label {
  margin: 0 0 0.35rem;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
  font-weight: 700;
}
.meta-strong { margin: 0; font-weight: 700; }
.meta-line { margin: 0.15rem 0 0; font-size: 0.85rem; color: #475569; }
.meta-card-right { text-align: right; }
.meta-dl { margin: 0; }
.meta-dl > div {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  font-size: 0.85rem;
}
.meta-dl dt { color: #64748b; }
.meta-dl dd { margin: 0; font-weight: 600; }
.items-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}
.items-table th {
  text-align: left;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
  padding: 0.45rem 0.35rem;
}
.items-table td {
  border-bottom: 1px solid #f1f5f9;
  padding: 0.7rem 0.35rem;
  vertical-align: top;
}
.item-hint {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.78rem;
  color: #64748b;
}
.amt { text-align: right; font-weight: 600; }
.totals-row { display: flex; justify-content: flex-end; margin-top: 1rem; }
.totals-box {
  min-width: 14rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.75rem 0.9rem;
  background: #f8fafc;
}
.totals-line {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.88rem;
}
.totals-grand {
  margin-top: 0.45rem;
  padding-top: 0.45rem;
  border-top: 1px solid #e2e8f0;
  font-size: 1rem;
}
.sheet-note,
.sheet-live {
  margin: 0.85rem 0 0;
  font-size: 0.85rem;
  color: #475569;
}
.sheet-live { color: #166534; font-weight: 600; }
.sheet-foot {
  margin-top: 1.25rem;
  padding-top: 0.85rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  font-size: 0.78rem;
  color: #64748b;
}
.sheet-thanks { margin: 0; font-weight: 600; color: #334155; }
@media (max-width: 640px) {
  .meta-grid { grid-template-columns: 1fr; }
  .meta-card-right,
  .sheet-title-block { text-align: left; }
  .meta-dl > div { justify-content: flex-start; }
}
@media print {
  .no-print { display: none !important; }
  .receipt-page { padding: 0; max-width: none; }
  .sheet { border: none; border-radius: 0; padding: 0; }
}
</style>
