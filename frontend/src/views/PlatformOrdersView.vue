<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { platformAdminApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { StaffOrderItem } from '@/types/staffPlatform'

const router = useRouter()
const { can } = usePermissions()
const canConfirm = computed(() => can(Permission.CUSTOMERS_MANAGE))
const orders = ref<StaffOrderItem[]>([])
const paymentFilter = ref('submitted')
const confirmAmount = ref('')
const confirmNotes = ref('')
const loading = ref(true)
const error = ref('')
const busyId = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listOrders({
      payment_status: paymentFilter.value || undefined,
    })
    orders.value = data
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

onMounted(load)

async function confirmPay(id: string, expected: number) {
  const typed = confirmAmount.value.trim()
  const amount = typed ? Number(typed) : expected
  if (!confirm(`Confirm MoMo of GHS ${amount} (invoice GHS ${expected}) and activate hosting?`)) return
  busyId.value = id
  try {
    await platformAdminApi.confirmOrderPayment(id, {
      amount_received: amount,
      notes: confirmNotes.value || undefined,
    })
    await load()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not confirm payment.'
  } finally {
    busyId.value = ''
  }
}

async function retryProvision(id: string) {
  busyId.value = id
  try {
    await platformAdminApi.retryOrderProvision(id)
    await load()
  } catch (e: unknown) {
    const errObj = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = errObj.response?.data?.error?.message ?? 'Could not retry setup.'
  } finally {
    busyId.value = ''
  }
}

async function rejectPay(id: string) {
  if (!confirm('Reject this payment submission? Order will be marked failed.')) return
  busyId.value = id
  try {
    await platformAdminApi.rejectOrderPayment(id, {
      notes: confirmNotes.value || undefined,
    })
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
  <DashboardLayout>
    <div class="space-y-4 p-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold text-slate-900 dark:text-white">Orders</h1>
          <p class="text-sm text-slate-500">Confirm MoMo IDs against the invoice amount, then activate.</p>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label class="text-xs text-slate-500">Amount received
            <input v-model="confirmAmount" class="mt-0.5 block rounded border border-slate-300 px-2 py-1.5 text-sm" placeholder="matches invoice" />
          </label>
          <label class="text-xs text-slate-500">Staff note
            <input v-model="confirmNotes" class="mt-0.5 block rounded border border-slate-300 px-2 py-1.5 text-sm" placeholder="checked in MoMo app" />
          </label>
          <select
            v-model="paymentFilter"
            class="rounded border border-slate-300 px-2 py-1.5 text-sm"
            @change="load"
          >
            <option value="">All payments</option>
            <option value="pending">Pending</option>
            <option value="submitted">Awaiting confirmation</option>
            <option value="paid">Paid</option>
            <option value="failed">Failed</option>
          </select>
          <button type="button" class="rounded border border-slate-300 px-3 py-1.5 text-sm" @click="load">
            Refresh
          </button>
        </div>
      </div>

      <p v-if="loading" class="text-sm text-slate-500">Loading…</p>
      <p v-else-if="error" class="text-sm text-red-600">{{ error }}</p>

      <div
        v-else
        class="overflow-hidden rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
      >
        <table class="min-w-full text-left text-sm">
          <thead class="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500 dark:border-slate-800 dark:bg-slate-800/50">
            <tr>
              <th class="px-4 py-2">Customer</th>
              <th class="px-4 py-2">Plan / domain</th>
              <th class="px-4 py-2">Amount</th>
              <th class="px-4 py-2">Payment</th>
              <th class="px-4 py-2">Provision</th>
              <th class="px-4 py-2">When</th>
              <th class="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
            <tr v-for="o in orders" :key="o.id">
              <td class="px-4 py-3">
                <button type="button" class="text-left hover:text-[#ff6c2c]" @click="openCustomer(o.customer_id)">
                  <p class="font-medium">{{ o.customer_name || 'Customer' }}</p>
                  <p class="text-xs text-slate-500">{{ o.customer_email }}</p>
                  <p v-if="o.customer_phone" class="text-xs text-slate-500">{{ o.customer_phone }}</p>
                </button>
              </td>
              <td class="px-4 py-3">
                <p>{{ o.plan_name || o.plan_id }}</p>
                <p class="text-xs text-slate-500">
                  {{ o.order_kind || 'hosting' }}
                  <span v-if="o.domain_name"> · {{ o.domain_name }}</span>
                </p>
              </td>
              <td class="px-4 py-3">{{ o.currency }} {{ o.total_price }}</td>
              <td class="px-4 py-3">
                <span class="rounded bg-slate-50 px-2 py-0.5 text-xs dark:bg-slate-800">{{ o.payment_status }}</span>
                <p v-if="o.invoice_number" class="mt-0.5 font-mono text-[10px] text-slate-400">{{ o.invoice_number }}</p>
                <p v-if="o.momo_transaction_id" class="mt-0.5 font-mono text-[10px] text-emerald-700">
                  MoMo {{ o.momo_transaction_id }}
                </p>
              </td>
              <td class="px-4 py-3 text-xs">{{ o.provisioning_status }}</td>
              <td class="px-4 py-3 text-xs text-slate-500">
                {{ new Date(o.created_at).toLocaleString() }}
              </td>
              <td class="px-4 py-3">
                <div class="flex flex-wrap gap-1">
                  <button
                    v-if="canConfirm && o.payment_status !== 'paid' && o.payment_status !== 'failed'"
                    type="button"
                    class="rounded bg-blue-600 px-2 py-1 text-xs font-semibold text-white disabled:opacity-50"
                    :disabled="busyId === o.id"
                    @click="confirmPay(o.id, Number(o.total_price))"
                  >
                    Confirm &amp; activate
                  </button>
                  <button
                    v-if="canConfirm && o.payment_status !== 'paid' && o.payment_status !== 'failed'"
                    type="button"
                    class="rounded border border-red-300 px-2 py-1 text-xs text-red-700 disabled:opacity-50"
                    :disabled="busyId === o.id"
                    @click="rejectPay(o.id)"
                  >
                    Reject
                  </button>
                  <button
                    v-if="canConfirm && o.payment_status === 'paid' && o.provisioning_status !== 'active'"
                    type="button"
                    class="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50"
                    :disabled="busyId === o.id"
                    @click="retryProvision(o.id)"
                  >
                    Retry setup
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!orders.length">
              <td colspan="7" class="px-4 py-6 text-slate-500">No orders.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </DashboardLayout>
</template>
