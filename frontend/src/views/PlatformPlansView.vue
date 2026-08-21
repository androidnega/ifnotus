<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { platformAdminApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { HostingPlan } from '@/types/platform'
import type { StaffPlanInput } from '@/types/staffPlatform'
import { formatCpu, formatRamGb, resourcesFromPrice } from '@/lib/planResources'

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.PLATFORM_WRITE))

const plans = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')
const msg = ref('')
const busy = ref(false)
const showForm = ref(false)
const editingId = ref<string | null>(null)
const sizeFromPrice = ref(true)
const formRamMb = ref(256)
const formAccent = ref('')
const formCustomDomains = ref(1)

const form = ref<StaffPlanInput>({
  name: '',
  slug: '',
  cpu_cores: 0.25,
  ram_gb: 0.25,
  storage_gb: 5,
  bandwidth_tb: 1,
  ai_credits: 10,
  price_monthly: 30,
  price_yearly: null,
  currency: 'GHS',
  sort_order: 0,
  is_active: true,
  features: {},
})

function applyPriceSizing() {
  const sized = resourcesFromPrice(form.value.price_monthly)
  form.value.cpu_cores = sized.cpu_cores
  form.value.ram_gb = sized.ram_gb
  formRamMb.value = sized.ram_mb
  form.value.storage_gb = sized.storage_gb
  form.value.bandwidth_tb = sized.bandwidth_tb
  form.value.ai_credits = sized.ai_credits
}

watch(
  () => [form.value.price_monthly, sizeFromPrice.value] as const,
  () => {
    if (sizeFromPrice.value) applyPriceSizing()
  },
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listPlans(true)
    plans.value = data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load plans.'
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  sizeFromPrice.value = true
  form.value = {
    name: '',
    slug: '',
    cpu_cores: 0.25,
    ram_gb: 0.25,
    storage_gb: 5,
    bandwidth_tb: 1,
    ai_credits: 10,
    price_monthly: 30,
    price_yearly: null,
    currency: 'GHS',
    sort_order: (plans.value.at(-1)?.sort_order ?? 0) + 10,
    is_active: true,
    features: {},
  }
  formAccent.value = ''
  formCustomDomains.value = 1
  applyPriceSizing()
  showForm.value = true
}

function edit(plan: HostingPlan) {
  editingId.value = plan.id
  sizeFromPrice.value = true
  form.value = {
    name: plan.name,
    slug: plan.slug,
    cpu_cores: Number(plan.cpu_cores),
    ram_gb: Number(plan.ram_gb),
    storage_gb: plan.storage_gb,
    bandwidth_tb: plan.bandwidth_tb,
    ai_credits: plan.ai_credits,
    price_monthly: plan.price_monthly,
    price_yearly: plan.price_yearly,
    currency: plan.currency,
    sort_order: plan.sort_order,
    is_active: plan.is_active,
    features: plan.features || {},
  }
  formAccent.value = typeof plan.features?.accent === 'string' ? plan.features.accent : ''
  const existingCustom = Number(plan.features?.custom_domains)
  formCustomDomains.value = Number.isFinite(existingCustom) ? existingCustom : Number(plan.price_monthly) > 0 ? 1 : 0
  applyPriceSizing()
  showForm.value = true
}

async function save() {
  if (!canWrite.value) return
  busy.value = true
  msg.value = ''
  try {
    if (sizeFromPrice.value) applyPriceSizing()
    const features = { ...(form.value.features || {}) }
    if (formAccent.value.trim()) features.accent = formAccent.value.trim()
    else delete features.accent
    features.custom_domains = Math.max(0, Number(formCustomDomains.value) || 0)
    const body = {
      ...form.value,
      features,
      slug: form.value.slug || undefined,
      price_yearly: form.value.price_yearly === '' ? null : form.value.price_yearly,
      size_from_price: sizeFromPrice.value,
    }
    if (editingId.value) {
      await platformAdminApi.updatePlan(editingId.value, body)
      msg.value = 'Plan updated.'
    } else {
      await platformAdminApi.createPlan(body)
      msg.value = 'Plan created.'
    }
    showForm.value = false
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = err.response?.data?.error?.message ?? 'Save failed.'
  } finally {
    busy.value = false
  }
}

async function toggleActive(plan: HostingPlan) {
  if (!canWrite.value) return
  busy.value = true
  try {
    await platformAdminApi.updatePlan(plan.id, { is_active: !plan.is_active })
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = err.response?.data?.error?.message ?? 'Update failed.'
  } finally {
    busy.value = false
  }
}

async function rebalanceAll() {
  if (!canWrite.value) return
  if (!confirm('Recalculate CPU, RAM, storage, bandwidth, and AI for every plan from its price?')) {
    return
  }
  busy.value = true
  msg.value = ''
  try {
    await platformAdminApi.rebalancePlansFromPrice()
    msg.value = 'All plans rebalanced from price.'
    await load()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = err.response?.data?.error?.message ?? 'Rebalance failed.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <DashboardLayout>
    <div class="space-y-4 p-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold text-slate-900 dark:text-white">Hosting plans</h1>
          <p class="text-sm text-slate-500">
            Resources follow price (₵30 → 0.25 vCPU / 256 MB · ₵70 → 0.5 vCPU / 512 MB)
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="rounded border border-slate-300 px-3 py-1.5 text-sm" @click="load">
            Refresh
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="busy"
            @click="rebalanceAll"
          >
            Rebalance from price
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="rounded bg-[#ff6c2c] px-3 py-1.5 text-sm font-medium text-white"
            @click="resetForm"
          >
            New plan
          </button>
        </div>
      </div>

      <p v-if="msg" class="text-sm text-slate-600">{{ msg }}</p>
      <p v-if="loading" class="text-sm text-slate-500">Loading…</p>
      <p v-else-if="error" class="text-sm text-red-600">{{ error }}</p>

      <div
        v-if="showForm && canWrite"
        class="rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
      >
        <h2 class="font-semibold">{{ editingId ? 'Edit plan' : 'Create plan' }}</h2>
        <form class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" @submit.prevent="save">
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Name</span>
            <input v-model="form.name" required class="w-full rounded border border-slate-300 px-2 py-1.5" />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Slug (optional)</span>
            <input v-model="form.slug" class="w-full rounded border border-slate-300 px-2 py-1.5" />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Monthly price (GHS)</span>
            <input
              v-model="form.price_monthly"
              type="number"
              min="0"
              step="0.01"
              required
              class="w-full rounded border border-slate-300 px-2 py-1.5"
            />
          </label>
          <label class="flex items-center gap-2 text-sm sm:col-span-2 lg:col-span-3">
            <input v-model="sizeFromPrice" type="checkbox" />
            Auto-size CPU / RAM / storage from price
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">vCPU</span>
            <input
              v-model.number="form.cpu_cores"
              type="number"
              min="0.1"
              step="0.05"
              required
              :disabled="sizeFromPrice"
              class="w-full rounded border border-slate-300 px-2 py-1.5 disabled:bg-slate-50"
            />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">RAM (MB)</span>
            <input
              v-model.number="formRamMb"
              type="number"
              min="64"
              step="64"
              required
              :disabled="sizeFromPrice"
              class="w-full rounded border border-slate-300 px-2 py-1.5 disabled:bg-slate-50"
            />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Storage (GB)</span>
            <input
              v-model.number="form.storage_gb"
              type="number"
              min="1"
              required
              :disabled="sizeFromPrice"
              class="w-full rounded border border-slate-300 px-2 py-1.5 disabled:bg-slate-50"
            />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Bandwidth (TB)</span>
            <input
              v-model="form.bandwidth_tb"
              type="number"
              min="0"
              step="0.1"
              required
              :disabled="sizeFromPrice"
              class="w-full rounded border border-slate-300 px-2 py-1.5 disabled:bg-slate-50"
            />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">AI credits / mo</span>
            <input
              v-model.number="form.ai_credits"
              type="number"
              min="0"
              :disabled="sizeFromPrice"
              class="w-full rounded border border-slate-300 px-2 py-1.5 disabled:bg-slate-50"
            />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Sort order</span>
            <input v-model.number="form.sort_order" type="number" class="w-full rounded border border-slate-300 px-2 py-1.5" />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Portal accent (optional)</span>
            <div class="flex items-center gap-2">
              <input v-model="formAccent" type="color" class="h-9 w-10 rounded border border-slate-300 bg-transparent p-0.5" />
              <input
                v-model="formAccent"
                type="text"
                placeholder="#0f766e or leave blank"
                class="w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-xs"
              />
            </div>
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-slate-600">Professional domains (custom_domains)</span>
            <input v-model.number="formCustomDomains" type="number" min="0" max="20" class="w-full rounded border border-slate-300 px-2 py-1.5" />
            <span class="mt-1 block text-xs text-slate-500">How many own domains a customer can attach besides the included hostname. Paid plans default to 1.</span>
          </label>
          <label class="flex items-center gap-2 text-sm sm:col-span-2">
            <input v-model="form.is_active" type="checkbox" />
            Active (visible on portal)
          </label>
          <div class="flex gap-2 sm:col-span-2 lg:col-span-3">
            <button
              type="submit"
              class="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50"
              :disabled="busy"
            >
              {{ busy ? 'Saving…' : 'Save plan' }}
            </button>
            <button type="button" class="rounded border border-slate-300 px-3 py-2 text-sm" @click="showForm = false">
              Cancel
            </button>
          </div>
        </form>
      </div>

      <div
        v-if="!loading && !error"
        class="overflow-hidden rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
      >
        <table class="min-w-full text-left text-sm">
          <thead class="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500 dark:border-slate-800 dark:bg-slate-800/50">
            <tr>
              <th class="px-4 py-2">Plan</th>
              <th class="px-4 py-2">Resources</th>
              <th class="px-4 py-2">Price</th>
              <th class="px-4 py-2">Status</th>
              <th class="px-4 py-2" />
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
            <tr v-for="plan in plans" :key="plan.id">
              <td class="px-4 py-3">
                <p class="font-medium">{{ plan.name }}</p>
                <p class="text-xs text-slate-500">{{ plan.slug }}</p>
              </td>
              <td class="px-4 py-3 text-slate-600">
                {{ formatCpu(plan.cpu_cores) }} vCPU · {{ formatRamGb(plan.ram_gb) }} · {{ plan.storage_gb }} GB ·
                {{ plan.ai_credits }} AI
              </td>
              <td class="px-4 py-3">GHS {{ plan.price_monthly }}/mo</td>
              <td class="px-4 py-3">
                <span
                  class="rounded px-2 py-0.5 text-xs"
                  :class="plan.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                >
                  {{ plan.is_active ? 'active' : 'hidden' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <div v-if="canWrite" class="flex justify-end gap-2">
                  <button type="button" class="text-xs text-[#ff6c2c] hover:underline" @click="edit(plan)">
                    Edit
                  </button>
                  <button type="button" class="text-xs text-slate-600 hover:underline" @click="toggleActive(plan)">
                    {{ plan.is_active ? 'Hide' : 'Activate' }}
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!plans.length">
              <td colspan="5" class="px-4 py-6 text-slate-500">No plans yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </DashboardLayout>
</template>
