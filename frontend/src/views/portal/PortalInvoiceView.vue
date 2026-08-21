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

const unpaid = computed(() => {
  const s = order.value?.payment_status
  return s === 'pending' || s === 'submitted'
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
    const { data } = await customersApi.getInvoice(String(route.params.id))
    order.value = data.order
    planName.value = data.plan_name || ''
    momo.value = data.momo
    supportHours.value = data.support_hours || supportHours.value
    supportWhatsapp.value = data.support_whatsapp || supportWhatsapp.value
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

    <div class="invoice-page mx-auto w-full max-w-5xl">
      <nav class="mb-6 flex flex-wrap items-center gap-2 text-xs font-semibold print:hidden" aria-label="Checkout steps">
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-emerald-800">
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-[10px]">✓</span>
          Pack
        </span>
        <span class="hidden text-slate-300 sm:inline">→</span>
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-emerald-800">
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-[10px]">✓</span>
          Domain
        </span>
        <span class="hidden text-slate-300 sm:inline">→</span>
        <span class="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1.5 text-white">
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-[10px]">3</span>
          Invoice
        </span>
      </nav>

      <p v-if="loading" class="rounded-2xl border border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-500">
        Loading invoice…
      </p>
      <p v-else-if="error" class="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {{ error }}
      </p>

      <template v-else-if="order">
        <header class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Proforma invoice</p>
            <h1 class="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              Pay & activate
            </h1>
            <p class="mt-2 max-w-xl text-sm leading-relaxed text-slate-600">
              Choose Mobile Money, pay the merchant number, then share the transaction ID.
              Support {{ supportHours }}. WhatsApp {{ supportWhatsapp }}.
            </p>
          </div>
          <button
            type="button"
            class="print-btn inline-flex items-center justify-center rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 print:hidden"
            @click="printInvoice"
          >
            Print / save PDF
          </button>
        </header>

        <div class="grid gap-4 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:items-start">
          <aside v-if="unpaid" class="pay-panel space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-5 text-white shadow-sm">
            <div>
              <h2 class="text-sm font-bold">Payment method</h2>
              <select
                v-model="method"
                class="mt-3 w-full rounded-xl border-0 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none ring-0"
              >
                <option value="">— Select payment method —</option>
                <option value="momo">Mobile Money (Direct Transfer)</option>
              </select>
            </div>

            <div v-if="method === 'momo' && momo" class="space-y-4 rounded-2xl bg-white/10 p-4 ring-1 ring-white/10">
              <div>
                <p class="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-300">Merchant Mobile Money</p>
                <p class="mt-1 text-sm text-slate-200">{{ momo.network }} merchant</p>
                <p class="mt-1 font-mono text-2xl font-extrabold tracking-wide text-white sm:text-3xl">
                  {{ momo.number }}
                </p>
                <p class="mt-1 text-sm text-slate-300">Account name: {{ momo.account_name }}</p>
              </div>

              <p class="text-sm leading-relaxed text-slate-200">
                Send
                <strong class="text-white">{{ order.currency }} {{ money(order.total_price) }}</strong>
                and use
                <strong class="text-white">{{ order.invoice_number }}</strong>
                as the reference.
              </p>

              <ol class="list-decimal space-y-1.5 pl-4 text-sm leading-relaxed text-slate-300">
                <li>Pay the merchant number from your MoMo wallet.</li>
                <li>Copy the transaction ID from the confirmation SMS.</li>
                <li>Paste it below so we can match and activate hosting.</li>
              </ol>

              <button
                type="button"
                class="w-full rounded-xl border border-white/25 bg-white/10 px-3 py-2 text-sm font-semibold text-white hover:bg-white/15"
                @click="copyNumber"
              >
                Copy merchant number
              </button>

              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-300">
                Transaction ID
                <input
                  v-model="txn"
                  class="mt-2 w-full rounded-xl border-0 bg-white px-3.5 py-2.5 text-sm font-medium text-slate-900 outline-none placeholder:text-slate-400"
                  placeholder="e.g. 1234567890"
                />
              </label>

              <button
                type="button"
                class="w-full rounded-xl bg-white px-4 py-3 text-sm font-bold text-slate-900 transition hover:bg-slate-100 disabled:opacity-60"
                :disabled="busy"
                @click="submit"
              >
                {{ busy ? 'Sending…' : 'I’ve paid — share ID' }}
              </button>
              <p v-if="msg" class="text-center text-sm font-medium text-emerald-300">{{ msg }}</p>
            </div>
          </aside>

          <article class="doc rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <header class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p class="text-xs font-extrabold uppercase tracking-[0.18em] text-slate-800">IFNOTUS</p>
                <p class="mt-1 text-xl font-bold text-slate-900 sm:text-2xl">
                  {{ order.invoice_number || order.id.slice(0, 8) }}
                </p>
              </div>
              <span
                class="rounded-full px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-wide"
                :class="
                  order.payment_status === 'paid' || order.payment_status === 'submitted'
                    ? 'bg-emerald-50 text-emerald-800'
                    : 'bg-amber-50 text-amber-800'
                "
              >
                {{ order.payment_status }}
              </span>
            </header>

            <p class="mt-3 text-sm text-slate-500">
              Created {{ new Date(order.created_at).toLocaleString() }}
              <span v-if="order.paid_at"> · Paid {{ new Date(order.paid_at).toLocaleString() }}</span>
            </p>

            <div class="mt-5 overflow-hidden rounded-xl border border-slate-100">
              <table class="w-full text-sm">
                <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th class="px-3 py-2.5 font-semibold">Item</th>
                    <th class="px-3 py-2.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100">
                  <tr>
                    <td class="px-3 py-3 text-slate-800">
                      {{ planName || 'Hosting' }}
                      <span v-if="order.domain_name" class="text-slate-500"> · {{ order.domain_name }}</span>
                    </td>
                    <td class="px-3 py-3 text-right font-semibold text-slate-900">
                      {{ order.currency }} {{ money(order.plan_price ?? order.total_price) }}
                    </td>
                  </tr>
                  <tr v-if="Number(order.domain_price || 0) > 0">
                    <td class="px-3 py-3 text-slate-800">Domain</td>
                    <td class="px-3 py-3 text-right font-semibold text-slate-900">
                      {{ order.currency }} {{ money(order.domain_price) }}
                    </td>
                  </tr>
                </tbody>
                <tfoot>
                  <tr class="bg-slate-50">
                    <th class="px-3 py-3 text-left font-bold text-slate-900">Total</th>
                    <th class="px-3 py-3 text-right text-lg font-extrabold text-slate-900">
                      {{ order.currency }} {{ money(order.total_price) }}
                    </th>
                  </tr>
                </tfoot>
              </table>
            </div>

            <p v-if="order.momo_transaction_id" class="mt-4 text-sm text-slate-500">
              Transaction {{ order.momo_transaction_id }}
            </p>
            <p
              v-if="order.provisioning_status === 'active'"
              class="mt-4 rounded-xl bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800"
            >
              Hosting is live in your account.
            </p>

            <button
              type="button"
              class="mt-5 inline-flex items-center justify-center rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 print:hidden"
              @click="router.push({ name: 'portal-dashboard' })"
            >
              Back to account
            </button>
          </article>
        </div>
      </template>
    </div>
  </PortalShell>
</template>

<style scoped>
@media print {
  .pay-panel,
  .print-btn,
  :deep(header),
  :deep(aside.portal-sidebar),
  nav[aria-label='Checkout steps'] {
    display: none !important;
  }
  .doc {
    border: none !important;
    box-shadow: none !important;
  }
}
</style>
