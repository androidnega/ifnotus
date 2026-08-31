<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { platformAdminApi } from '@/api'
import type { CustomerOrder } from '@/types/platform'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { isPlatformOwner, isBillingAgent } from '@/lib/roles'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { can } = usePermissions()

const canManageBilling = computed(
  () => isPlatformOwner(auth.user) || isBillingAgent(auth.user) || can(Permission.BILLING_MANAGE),
)

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

const busyAction = ref(false)
const actionMsg = ref('')
const showPaymentModal = ref(false)
const editForm = ref({
  payment_status: 'paid',
  payment_method: 'complimentary',
  amount_received: 0,
  notes: '',
})

const isComplimentary = computed(() => {
  const m = (order.value?.payment_method || '').toLowerCase()
  return ['staff', 'complimentary', 'free', 'comp'].includes(m)
})

const isPaid = computed(() => (order.value?.payment_status || '').toLowerCase() === 'paid')
const isReceipt = computed(() => documentKind.value === 'receipt' || isPaid.value)

const statusLabel = computed(() => {
  const s = (order.value?.payment_status || 'pending').toLowerCase()
  if (isComplimentary.value && s === 'paid') return 'Complimentary (Free Grant)'
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

function openPaymentModal() {
  if (!order.value) return
  editForm.value = {
    payment_status: order.value.payment_status || 'paid',
    payment_method: order.value.payment_method || (isComplimentary.value ? 'complimentary' : 'momo'),
    amount_received: Number(
      order.value.payment_amount_received ??
        (isComplimentary.value ? 0 : order.value.total_price),
    ),
    notes: order.value.payment_notes || '',
  }
  showPaymentModal.value = true
}

async function savePaymentSettings() {
  if (!order.value) return
  busyAction.value = true
  try {
    await platformAdminApi.updateOrderPaymentStatus(order.value.id, {
      payment_status: editForm.value.payment_status,
      payment_method: editForm.value.payment_method,
      amount_received:
        editForm.value.payment_method === 'complimentary'
          ? 0
          : editForm.value.amount_received,
      notes: editForm.value.notes,
    })
    showPaymentModal.value = false
    actionMsg.value = 'Payment details & receipt status updated.'
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    alert(err.response?.data?.error?.message ?? 'Failed to update payment status.')
  } finally {
    busyAction.value = false
  }
}

async function toggleComplimentary() {
  if (!order.value || !canManageBilling.value) return
  const isComp = isComplimentary.value
  const newMethod = isComp ? 'momo' : 'complimentary'
  const newStatus = isComp ? 'pending' : 'paid'

  const defaultNote = isComp
    ? 'Reverted from complimentary grant to standard payment'
    : 'Complimentary Free Grant (0.00 GHS) approved by billing'

  const enteredNote = prompt(
    isComp
      ? `Revert receipt #${invoiceNo.value} from Complimentary back to regular payment? Enter note:`
      : `Grant receipt #${invoiceNo.value} as COMPLIMENTARY (0.00 GHS collected)? Enter approval note:`,
    defaultNote,
  )
  if (enteredNote === null) return

  busyAction.value = true
  actionMsg.value = ''
  try {
    await platformAdminApi.updateOrderPaymentStatus(order.value.id, {
      payment_method: newMethod,
      payment_status: newStatus,
      amount_received: isComp ? Number(order.value.total_price) : 0,
      notes: enteredNote.trim() || defaultNote,
    })
    actionMsg.value = isComp
      ? 'Reverted to regular invoice/receipt.'
      : 'Updated to Complimentary Grant (0.00 GHS).'
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    actionMsg.value =
      err.response?.data?.error?.message ?? 'Failed to update complimentary status.'
  } finally {
    busyAction.value = false
  }
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

      <!-- Billing Agent Actions Bar (Billing Agent only) -->
      <div v-if="order && canManageBilling" class="billing-mgmt-bar no-print">
        <div class="billing-mgmt-info">
          <div class="billing-mgmt-title">
            <i class="fa-solid fa-file-invoice-dollar text-indigo-500" />
            <span>Billing &amp; Receipt Controls</span>
            <span v-if="isComplimentary" class="pill-comp-badge">
              <i class="fa-solid fa-gift" /> Complimentary Grant
            </span>
            <span v-else class="pill-paid-badge">
              <i class="fa-solid fa-credit-card" /> {{ order.payment_method?.toUpperCase() || 'MOMO' }}
            </span>
          </div>
          <p class="billing-mgmt-desc">
            {{ isComplimentary
              ? 'This receipt is recorded as a 100% complimentary grant (0.00 GHS collected cash).'
              : `Current collection status: ${statusLabel}. You can update payment status or grant as complimentary.`
            }}
          </p>
        </div>

        <div class="billing-mgmt-actions">
          <button
            type="button"
            class="btn-comp-toggle"
            :class="{ 'is-comp': isComplimentary }"
            :disabled="busyAction"
            @click="toggleComplimentary"
          >
            <i class="fa-solid" :class="isComplimentary ? 'fa-rotate-left' : 'fa-gift'" />
            <span>{{ isComplimentary ? 'Revert from Comp' : 'Grant as Complimentary' }}</span>
          </button>

          <button
            type="button"
            class="btn-edit-pay"
            :disabled="busyAction"
            @click="openPaymentModal"
          >
            <i class="fa-solid fa-pen-to-square" />
            <span>Edit Payment &amp; Status</span>
          </button>
        </div>
      </div>

      <UiAlert v-if="actionMsg" variant="success" class="no-print mt-2" @close="actionMsg = ''">
        {{ actionMsg }}
      </UiAlert>

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
              <div><dt>Payment method</dt><dd class="font-semibold">{{ isComplimentary ? 'Complimentary Free Grant' : (order.payment_method?.toUpperCase() || 'MoMo') }}</dd></div>
              <div><dt>Currency</dt><dd>{{ order.currency }}</dd></div>
              <div v-if="order.payment_confirmed_by"><dt>Staff ID</dt><dd class="font-mono text-xs">{{ order.payment_confirmed_by }}</dd></div>
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
            <div v-if="isComplimentary" class="totals-line comp-discount-line">
              <span>Complimentary grant (100%)</span>
              <span>- {{ order.currency }} {{ money(order.total_price) }}</span>
            </div>
            <div class="totals-line totals-grand">
              <span>{{ isReceipt ? 'Amount paid' : 'Total due' }}</span>
              <strong>{{ order.currency }} {{ isComplimentary ? '0.00 (Comp)' : money(order.payment_amount_received ?? order.total_price) }}</strong>
            </div>
          </div>
        </div>

        <p v-if="isComplimentary" class="sheet-comp-notice">
          <i class="fa-solid fa-gift mr-1 text-purple-600" />
          <strong>COMPLIMENTARY GRANT:</strong> This invoice was fulfilled as a complimentary courtesy by IFNOTUS Billing. Cash due is 0.00 GHS.
        </p>

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

      <!-- Edit Payment Modal for Billing Agents -->
      <div v-if="showPaymentModal" class="modal-backdrop no-print" @click.self="showPaymentModal = false">
        <div class="modal-card">
          <div class="modal-head">
            <h3><i class="fa-solid fa-pen-to-square text-indigo-500 mr-1.5" /> Update Receipt &amp; Payment Status</h3>
            <button type="button" class="btn-close-modal" @click="showPaymentModal = false">✕</button>
          </div>
          <form class="modal-form" @submit.prevent="savePaymentSettings">
            <label class="form-label">
              Payment Status
              <select v-model="editForm.payment_status" class="form-select">
                <option value="paid">Paid (Accepted / Valid Receipt)</option>
                <option value="submitted">Submitted (Awaiting Staff Confirmation)</option>
                <option value="pending">Pending (Unpaid Invoice)</option>
                <option value="failed">Rejected / Failed</option>
              </select>
            </label>

            <label class="form-label">
              Payment Method
              <select v-model="editForm.payment_method" class="form-select">
                <option value="complimentary">Complimentary Free Grant (0.00 GHS)</option>
                <option value="momo">MTN Mobile Money / MoMo</option>
                <option value="telecel">Telecel Cash</option>
                <option value="bank">Bank Transfer</option>
                <option value="cash">Direct Cash</option>
                <option value="card">Card / Online Payment</option>
                <option value="staff">Staff Manual Credit</option>
              </select>
            </label>

            <label v-if="editForm.payment_method !== 'complimentary'" class="form-label">
              Amount Received (GHS)
              <input v-model.number="editForm.amount_received" type="number" step="0.01" class="form-input" />
            </label>

            <label class="form-label">
              Internal Billing Notes
              <textarea v-model="editForm.notes" rows="2" class="form-input" placeholder="e.g. Student grant approved by billing manager"></textarea>
            </label>

            <div class="modal-actions">
              <button type="button" class="btn-ghost" @click="showPaymentModal = false">Cancel</button>
              <button type="submit" class="btn-primary" :disabled="busyAction">
                {{ busyAction ? 'Saving…' : 'Save Payment Changes' }}
              </button>
            </div>
          </form>
        </div>
      </div>
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
.sheet-comp-notice {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: #fdf4ff;
  border: 1px solid #f0abfc;
  border-radius: 0.6rem;
  font-size: 0.8rem;
  color: #701a75;
}
.comp-discount-line {
  color: #9333ea !important;
  font-weight: 600;
}
.billing-mgmt-bar {
  margin-top: 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.85rem 1.1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.billing-mgmt-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 700;
  font-size: 0.88rem;
  color: #0f172a;
}
.pill-comp-badge {
  background: #f3e8ff;
  color: #6b21a8;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.pill-paid-badge {
  background: #e0e7ff;
  color: #3730a3;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
}
.billing-mgmt-desc {
  margin: 0.2rem 0 0;
  font-size: 0.78rem;
  color: #64748b;
}
.billing-mgmt-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.btn-comp-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: #7c3aed;
  color: #fff;
  border: none;
  border-radius: 0.6rem;
  padding: 0.45rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-comp-toggle:hover {
  background: #6d28d9;
}
.btn-comp-toggle.is-comp {
  background: #64748b;
}
.btn-comp-toggle.is-comp:hover {
  background: #475569;
}
.btn-edit-pay {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: #fff;
  border: 1px solid #cbd5e1;
  color: #334155;
  border-radius: 0.6rem;
  padding: 0.45rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-edit-pay:hover {
  background: #f1f5f9;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(2px);
  z-index: 999;
  display: grid;
  place-items: center;
  padding: 1rem;
}
.modal-card {
  background: #fff;
  border-radius: 1rem;
  width: 100%;
  max-width: 28rem;
  box-shadow: 0 20px 25px -5px rgba(0,0,0,0.2);
  padding: 1.25rem;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}
.modal-head h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
}
.btn-close-modal {
  background: none;
  border: none;
  font-size: 1.1rem;
  cursor: pointer;
  color: #64748b;
}
.modal-form {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.form-label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
}
.form-select,
.form-input {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  background: #fff;
  color: #0f172a;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

@media print {
  .no-print { display: none !important; }
  .receipt-page { padding: 0; max-width: none; }
  .sheet { border: none; border-radius: 0; padding: 0; }
}
</style>
