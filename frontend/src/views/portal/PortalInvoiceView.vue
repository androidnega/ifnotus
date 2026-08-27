<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import type { CustomerOrder } from '@/types/platform'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const msg = ref('')
const txn = ref('')
const method = ref('')
const busy = ref(false)
const order = ref<CustomerOrder | null>(null)
const planName = ref('')
const momo = ref<{ network: string; number: string; account_name: string } | null>(null)
const supportHours = ref('Monday–Saturday, 08:00–20:00 GMT')
const supportWhatsapp = ref('+233541069241')
const customerName = ref('')
const customerEmail = ref('')
const customerPhone = ref('')

const unpaid = computed(() => {
  const s = order.value?.payment_status
  return s === 'pending' || s === 'submitted'
})

const isReceipt = computed(() => (order.value?.payment_status || '').toLowerCase() === 'paid')

const docTitle = computed(() => (isReceipt.value ? 'RECEIPT' : 'INVOICE'))
const docKindLabel = computed(() =>
  isReceipt.value ? 'Official payment receipt' : 'Tax invoice / Proforma',
)

const statusLabel = computed(() => {
  const s = order.value?.payment_status || 'pending'
  if (s === 'submitted') return 'Awaiting confirmation'
  if (s === 'paid') return 'Paid'
  if (s === 'pending') return 'Pending payment'
  return s.charAt(0).toUpperCase() + s.slice(1)
})

const statusTone = computed(() => {
  const s = order.value?.payment_status
  if (s === 'paid') return 'ok'
  if (s === 'submitted') return 'submitted'
  return 'pending'
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

const dueOn = computed(() => {
  const exp = (order.value as { expires_at?: string | null })?.expires_at
  if (exp) {
    return new Date(exp).toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  }
  if (!order.value?.created_at) return '—'
  const d = new Date(order.value.created_at)
  d.setDate(d.getDate() + 7)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
})

const lineDescription = computed(() => {
  const kind = (order.value?.order_kind || 'hosting').toLowerCase()
  const months =
    Number(order.value?.billing_term_months || order.value?.meta_json?.billing_term_months || 1) || 1
  const label =
    order.value?.meta_json?.term_label ||
    (months === 1 ? '1 month' : `${months} months`)
  if (kind === 'renewal') return `${label} subscription renewal`
  if (kind === 'upgrade') return `Plan upgrade — ${label}`
  if (kind === 'credits') return 'AI Engineer credits top-up'
  return `${label} managed hosting subscription`
})

function money(value: number | string | undefined | null) {
  const n = Number(value || 0)
  return n.toFixed(2)
}

function printInvoice() {
  window.print()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [invoiceRes, meRes] = await Promise.all([
      customersApi.getInvoice(String(route.params.id)),
      customersApi.me().catch(() => null),
    ])
    const data = invoiceRes.data
    order.value = data.order
    planName.value = data.plan_name || ''
    momo.value = data.momo
    supportHours.value = data.support_hours || supportHours.value
    supportWhatsapp.value = data.support_whatsapp || supportWhatsapp.value
    if (data.customer_name) customerName.value = data.customer_name
    if (data.customer_email) customerEmail.value = data.customer_email
    if (data.customer_phone) customerPhone.value = data.customer_phone
    if (meRes?.data) {
      customerName.value = customerName.value || meRes.data.full_name || ''
      customerEmail.value = customerEmail.value || meRes.data.email || ''
      customerPhone.value = customerPhone.value || meRes.data.phone || ''
    }
    if (unpaid.value) method.value = 'momo'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load this invoice.'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!order.value) return
  const id = txn.value.trim()
  if (id.length < 6) {
    msg.value = 'Enter the Mobile Money transaction ID from the SMS after you pay.'
    return
  }
  busy.value = true
  msg.value = ''
  try {
    const { data } = await customersApi.submitMomo(order.value.id, id)
    order.value = { ...order.value, ...data }
    msg.value = 'Thanks. We’ll confirm this payment and activate your hosting.'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = err.response?.data?.error?.message ?? 'Could not submit the transaction ID.'
  } finally {
    busy.value = false
  }
}

function copyNumber() {
  if (!momo.value?.number) return
  void navigator.clipboard.writeText(momo.value.number)
  msg.value = 'Merchant number copied.'
}

onMounted(load)
</script>

<template>
  <PortalShell mode="app" profile-menu>
    <template #sidebar>
      <PortalAccountNav active="billing" />
    </template>

    <div class="invoice-page" :class="{ 'has-pay-panel': unpaid }">
      <nav class="steps no-print" aria-label="Checkout steps">
        <span class="step step-done"><span class="step-badge">✓</span> Pack</span>
        <span class="step-arrow" aria-hidden="true">→</span>
        <span class="step step-done"><span class="step-badge">✓</span> Domain</span>
        <span class="step-arrow" aria-hidden="true">→</span>
        <span class="step step-current"><span class="step-badge">3</span> Invoice</span>
      </nav>

      <p v-if="loading" class="state-card">Loading invoice…</p>
      <p v-else-if="error" class="state-card state-error">{{ error }}</p>

      <template v-else-if="order">
        <header class="page-head no-print">
          <div class="page-head-copy">
            <p class="eyebrow">{{ isReceipt ? 'Payment receipt' : 'Proforma invoice' }}</p>
            <h1>{{ isReceipt ? 'Your receipt' : 'Pay & activate' }}</h1>
            <p class="lede">
              <template v-if="isReceipt">
                IFNOTUS has accepted this payment. Save or print this receipt anytime.
              </template>
              <template v-else>
                Pay by Mobile Money, then share your transaction ID. Support {{ supportHours }} ·
                <a :href="`https://wa.me/${supportWhatsapp.replace(/\D/g, '')}`" target="_blank" rel="noopener">
                  WhatsApp {{ supportWhatsapp }}
                </a>
              </template>
            </p>
          </div>
          <button type="button" class="btn-pdf" @click="printInvoice">
            Save PDF
          </button>
        </header>

        <div class="invoice-layout">
          <article class="doc" aria-label="Invoice document">
            <!-- Print / PDF letterhead -->
            <div class="sheet">
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
                  <p class="sheet-kind">{{ docKindLabel }}</p>
                  <h2 class="sheet-invoice-title">{{ docTitle }}</h2>
                  <p class="sheet-no"># {{ invoiceNo }}</p>
                  <span class="status-pill" :class="statusTone">{{ statusLabel }}</span>
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
                    <div v-if="!isReceipt"><dt>Due date</dt><dd>{{ dueOn }}</dd></div>
                    <div v-if="paidOn"><dt>Paid on</dt><dd>{{ paidOn }}</dd></div>
                    <div v-if="order.domain_name"><dt>Site</dt><dd>{{ order.domain_name }}</dd></div>
                    <div><dt>Currency</dt><dd>{{ order.currency }}</dd></div>
                  </dl>
                </div>
              </div>

              <table class="items-table">
                <thead>
                  <tr>
                    <th class="col-desc">Description</th>
                    <th class="col-qty">Qty</th>
                    <th class="col-unit">Unit price</th>
                    <th class="col-amt">Amount</th>
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

              <section v-if="unpaid && momo" class="pay-box">
                <p class="pay-box-title">How to pay</p>
                <div class="pay-box-grid">
                  <div>
                    <p class="pay-k">Network</p>
                    <p class="pay-v">{{ momo.network }}</p>
                  </div>
                  <div>
                    <p class="pay-k">Merchant</p>
                    <p class="pay-v">{{ momo.account_name }}</p>
                  </div>
                  <div>
                    <p class="pay-k">Number</p>
                    <p class="pay-v mono">{{ momo.number }}</p>
                  </div>
                  <div>
                    <p class="pay-k">Reference</p>
                    <p class="pay-v mono">{{ invoiceNo }}</p>
                  </div>
                </div>
                <p class="pay-box-note">
                  Send exactly <strong>{{ order.currency }} {{ money(order.total_price) }}</strong>
                  and use the invoice number as the MoMo reference. Then share the transaction ID
                  in your IFNOTUS account to activate hosting.
                </p>
              </section>

              <p v-if="order.momo_transaction_id" class="sheet-note">
                Transaction ID on file: <span class="mono">{{ order.momo_transaction_id }}</span>
              </p>
              <p v-if="order.provisioning_status === 'active'" class="sheet-live">
                Hosting is active on this account.
              </p>

              <footer class="sheet-foot">
                <div>
                  <p>IFNOTUS · Accra, Ghana</p>
                  <p>Support {{ supportHours }} · WhatsApp {{ supportWhatsapp }}</p>
                </div>
                <p class="sheet-thanks">Thank you for choosing IFNOTUS.</p>
              </footer>
            </div>

            <button
              type="button"
              class="btn-ghost back-btn no-print"
              @click="router.push({ name: 'portal-dashboard', query: { panel: 'billing' } })"
            >
              Back to billing
            </button>
          </article>

          <aside v-if="unpaid" class="pay-panel no-print">
            <h2 class="pay-title">Payment</h2>

            <label class="field">
              <span class="field-label">Method</span>
              <select v-model="method" class="field-input">
                <option value="">Select payment method</option>
                <option value="momo">Mobile Money (direct transfer)</option>
              </select>
            </label>

            <div v-if="method === 'momo' && momo" class="pay-flow">
              <section class="merchant-card">
                <p class="merchant-kicker">Merchant Mobile Money</p>
                <p class="merchant-network">{{ momo.network }} · {{ momo.account_name }}</p>
                <p class="merchant-number">{{ momo.number }}</p>
                <p class="merchant-note">
                  Send <strong>{{ order.currency }} {{ money(order.total_price) }}</strong>
                  and use <strong>{{ invoiceNo }}</strong> as the reference.
                </p>
                <button type="button" class="btn-copy" @click="copyNumber">Copy merchant number</button>
              </section>

              <ol class="pay-steps">
                <li>Pay the merchant number from your MoMo wallet.</li>
                <li>Copy the transaction ID from the confirmation SMS.</li>
                <li>Paste it below so we can match and activate hosting.</li>
              </ol>

              <label class="field">
                <span class="field-label">Transaction ID</span>
                <input
                  v-model="txn"
                  class="field-input"
                  placeholder="e.g. 1234567890"
                  inputmode="numeric"
                  autocomplete="off"
                />
              </label>

              <button type="button" class="btn-primary" :disabled="busy" @click="submit">
                {{ busy ? 'Sending…' : 'I’ve paid — share ID' }}
              </button>

              <p v-if="msg" class="pay-msg" :class="{ ok: msg.includes('Thanks') || msg.includes('copied') }">
                {{ msg }}
              </p>
            </div>
          </aside>
        </div>
      </template>
    </div>
  </PortalShell>
</template>

<style scoped>
.invoice-page {
  width: 100%;
  max-width: 68rem;
  margin: 0 auto;
}

.invoice-page.has-pay-panel {
  padding-bottom: 5.5rem;
}

@media (min-width: 640px) {
  .invoice-page.has-pay-panel {
    padding-bottom: 1.5rem;
  }
}

.steps {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 1.25rem;
  font-size: 0.75rem;
  font-weight: 600;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.7rem;
  border-radius: 999px;
}
.step-done {
  background: #ecfdf5;
  color: #047857;
}
.step-current {
  background: var(--if-primary, #1e3a5f);
  color: #fff;
}
.step-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 800;
}
.step-done .step-badge {
  background: #d1fae5;
}
.step-current .step-badge {
  background: rgb(255 255 255 / 0.2);
}
.step-arrow {
  color: #cbd5e1;
  display: none;
}
@media (min-width: 480px) {
  .step-arrow {
    display: inline;
  }
}

.page-head {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
@media (min-width: 640px) {
  .page-head {
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
  }
}
.eyebrow {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--if-muted, #64748b);
}
.page-head h1 {
  margin: 0.35rem 0 0;
  font-family: var(--ds-font-display, Sora, sans-serif);
  font-size: clamp(1.45rem, 4vw, 1.85rem);
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--if-ink, #0f172a);
}
.lede {
  margin: 0.5rem 0 0;
  max-width: 34rem;
  font-size: 0.875rem;
  line-height: 1.55;
  color: var(--if-muted, #64748b);
}
.lede a {
  color: var(--if-primary, #1e3a5f);
  font-weight: 600;
  text-decoration: none;
}
.lede a:hover {
  text-decoration: underline;
}

.invoice-layout {
  display: grid;
  gap: 1rem;
  align-items: start;
}
@media (min-width: 960px) {
  .invoice-layout {
    grid-template-columns: minmax(17rem, 22rem) minmax(0, 1fr);
    gap: 1.25rem;
  }
  .pay-panel {
    order: 1;
  }
  .doc {
    order: 2;
  }
}

.doc {
  background: transparent;
}
.sheet {
  background: #fff;
  color: #0f172a;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: 1.35rem 1.25rem 1.25rem;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
}
@media (min-width: 640px) {
  .sheet {
    padding: 1.75rem 1.85rem 1.5rem;
  }
}

.sheet-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 1.25rem;
  padding-bottom: 1.15rem;
  border-bottom: 2px solid #0f172a;
}
.brand-block {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 2.6rem;
  height: 2.6rem;
  border-radius: 0.55rem;
  background: #0f172a;
  color: #fff;
  font-family: var(--ds-font-display, Sora, sans-serif);
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.brand-name {
  margin: 0;
  font-family: var(--ds-font-display, Sora, sans-serif);
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.03em;
}
.brand-tag,
.brand-web {
  margin: 0.1rem 0 0;
  font-size: 0.75rem;
  color: #64748b;
}
.sheet-title-block {
  text-align: right;
}
.sheet-kind {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #64748b;
}
.sheet-no {
  margin: 0.15rem 0 0.45rem;
  font-family: ui-monospace, monospace;
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #334155;
}
.sheet-invoice-title {
  margin: 0.1rem 0 0;
  font-family: var(--ds-font-display, Sora, sans-serif);
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #0f172a;
  line-height: 1;
}
.meta-card-right {
  text-align: right;
}
.meta-card-right .meta-dl div {
  justify-content: flex-end;
}
.totals-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.5rem;
}
.totals-box {
  min-width: 14rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  overflow: hidden;
}
.totals-line {
  display: flex;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 0.55rem 0.85rem;
  font-size: 0.85rem;
  color: #475569;
  border-bottom: 1px solid #f1f5f9;
}
.totals-grand {
  background: #f8fafc;
  border-bottom: 0;
  font-size: 0.95rem;
  color: #0f172a;
}
.totals-grand strong {
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
}
.items-table .col-unit,
.items-table .col-amt,
.items-table td.amt {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.items-table th.col-unit,
.items-table th.col-amt {
  text-align: right;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.22rem 0.55rem;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.status-pill.pending {
  background: #fffbeb;
  color: #b45309;
}
.status-pill.submitted {
  background: #fef3c7;
  color: #92400e;
}
.status-pill.ok {
  background: #ecfdf5;
  color: #047857;
}

.meta-grid {
  display: grid;
  gap: 0.85rem;
  margin-top: 1.15rem;
}
@media (min-width: 560px) {
  .meta-grid {
    grid-template-columns: 1fr 1fr;
  }
}
.meta-card {
  padding: 0.85rem 0.95rem;
  border-radius: 0.75rem;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}
.meta-label {
  margin: 0 0 0.4rem;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #94a3b8;
}
.meta-strong {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
}
.meta-line {
  margin: 0.2rem 0 0;
  font-size: 0.8125rem;
  color: #475569;
  word-break: break-word;
}
.meta-dl {
  margin: 0;
  display: grid;
  gap: 0.35rem;
}
.meta-dl > div {
  display: grid;
  grid-template-columns: 4.5rem 1fr;
  gap: 0.5rem;
  font-size: 0.8125rem;
}
.meta-dl dt {
  margin: 0;
  color: #94a3b8;
}
.meta-dl dd {
  margin: 0;
  font-weight: 600;
  color: #0f172a;
  word-break: break-word;
}

.items-table {
  width: 100%;
  margin-top: 1.25rem;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.items-table th {
  padding: 0.55rem 0.35rem;
  border-bottom: 1px solid #cbd5e1;
  text-align: left;
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #64748b;
}
.items-table td {
  padding: 0.85rem 0.35rem;
  border-bottom: 1px solid #eef2f7;
  vertical-align: top;
}
.items-table td strong {
  display: block;
  font-weight: 650;
}
.item-hint {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.78rem;
  color: #64748b;
  word-break: break-all;
}
.col-qty {
  width: 3.5rem;
  text-align: center !important;
}
.col-amt {
  width: 7.5rem;
  text-align: right !important;
}
.items-table td:nth-child(2) {
  text-align: center;
  color: #64748b;
}
.items-table td:nth-child(3) {
  text-align: right;
  font-weight: 650;
  white-space: nowrap;
}
.items-table tfoot td {
  border-bottom: none;
  padding-top: 0.95rem;
  font-weight: 800;
  font-size: 0.95rem;
}
.items-table tfoot td:last-child {
  font-size: 1.1rem;
}

.pay-box {
  margin-top: 1.25rem;
  padding: 1rem 1.05rem;
  border-radius: 0.85rem;
  border: 1px solid #dbe3ee;
  background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
}
.pay-box-title {
  margin: 0 0 0.75rem;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
}
.pay-box-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: 1fr 1fr;
}
@media (min-width: 640px) {
  .pay-box-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.pay-k {
  margin: 0;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #94a3b8;
}
.pay-v {
  margin: 0.2rem 0 0;
  font-size: 0.875rem;
  font-weight: 700;
  color: #0f172a;
  word-break: break-word;
}
.mono {
  font-family: var(--ds-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  letter-spacing: 0.02em;
}
.pay-box-note {
  margin: 0.85rem 0 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: #475569;
}

.sheet-note {
  margin: 0.9rem 0 0;
  font-size: 0.8125rem;
  color: #64748b;
}
.sheet-live {
  margin: 0.85rem 0 0;
  padding: 0.65rem 0.85rem;
  border-radius: 0.65rem;
  background: #ecfdf5;
  font-size: 0.875rem;
  font-weight: 600;
  color: #047857;
}
.sheet-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 1.5rem;
  padding-top: 0.95rem;
  border-top: 1px solid #e2e8f0;
  font-size: 0.72rem;
  line-height: 1.45;
  color: #94a3b8;
}
.sheet-foot p {
  margin: 0;
}
.sheet-thanks {
  font-weight: 600;
  color: #64748b;
}
.back-btn {
  margin-top: 1rem;
}

.pay-panel {
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #e2e8f0);
  border-radius: 1rem;
  padding: 1.15rem;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
}
@media (min-width: 960px) {
  .pay-panel {
    position: sticky;
    top: 5.25rem;
  }
}
.pay-title {
  margin: 0 0 0.85rem;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--if-ink, #0f172a);
}
.pay-flow {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.merchant-card {
  padding: 0.95rem 1rem;
  border-radius: 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.merchant-kicker {
  margin: 0;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
}
.merchant-network {
  margin: 0.35rem 0 0;
  font-size: 0.8125rem;
  color: #475569;
}
.merchant-number {
  margin: 0.5rem 0 0;
  font-family: var(--ds-font-mono, ui-monospace, monospace);
  font-size: clamp(1.35rem, 5vw, 1.75rem);
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.2;
  color: var(--if-ink, #0f172a);
  word-break: break-all;
}
.merchant-note {
  margin: 0.65rem 0 0;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: #475569;
}
.merchant-note strong {
  color: var(--if-ink, #0f172a);
}
.pay-steps {
  margin: 0;
  padding-left: 1.15rem;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: #64748b;
}
.pay-steps li + li {
  margin-top: 0.35rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.field-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #64748b;
}
.field-input {
  width: 100%;
  border: 1px solid #dbe3ee;
  border-radius: 0.65rem;
  background: #fff;
  padding: 0.65rem 0.75rem;
  font-size: 0.875rem;
  color: var(--if-ink, #0f172a);
  outline: none;
}
.field-input:focus {
  border-color: var(--if-primary, #1e3a5f);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--if-primary, #1e3a5f) 14%, transparent);
}
.pay-msg {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.45;
  color: #b45309;
  text-align: center;
}
.pay-msg.ok {
  color: #047857;
}

.btn-primary,
.btn-ghost,
.btn-copy,
.btn-pdf {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.65rem;
  padding: 0.7rem 0.95rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.btn-primary,
.btn-copy {
  width: 100%;
}
.btn-primary {
  border: none;
  background: var(--if-primary, #1e3a5f);
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--if-primary-hover, #16304d);
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.btn-ghost {
  border: 1px solid #dbe3ee;
  background: #fff;
  color: var(--if-ink, #0f172a);
}
.btn-ghost:hover {
  background: #f8fafc;
}
.btn-copy {
  margin-top: 0.75rem;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: var(--if-ink, #0f172a);
}
.btn-copy:hover {
  background: #f1f5f9;
}
.btn-pdf {
  border: none;
  background: #0f172a;
  color: #fff;
  white-space: nowrap;
}
.btn-pdf:hover {
  background: #1e293b;
}

.state-card {
  margin: 0;
  padding: 2rem 1rem;
  border-radius: 1rem;
  border: 1px solid var(--if-border, #e2e8f0);
  background: var(--if-surface, #fff);
  text-align: center;
  font-size: 0.875rem;
  color: var(--if-muted, #64748b);
}
.state-error {
  padding: 0.85rem 1rem;
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
  text-align: left;
}

@media print {
  @page {
    size: A4;
    margin: 14mm 14mm 16mm;
  }

  html,
  body {
    background: #fff !important;
    color: #0f172a !important;
  }

  .no-print,
  .pay-panel,
  .page-head,
  .steps,
  .back-btn,
  :deep(header),
  :deep(aside),
  :deep(nav),
  :deep(.portal-nav),
  :deep(.portal-sidebar),
  :deep(.portal-top) {
    display: none !important;
  }

  .invoice-page,
  .invoice-layout,
  .doc {
    max-width: none !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    display: block !important;
  }

  .sheet {
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
  }

  .sheet-head {
    border-bottom-color: #0f172a !important;
  }

  .meta-card,
  .pay-box {
    break-inside: avoid;
    background: #f8fafc !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  .status-pill,
  .brand-mark,
  .sheet-live {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  .items-table {
    page-break-inside: avoid;
  }

  .sheet-foot {
    page-break-inside: avoid;
  }
}
</style>
