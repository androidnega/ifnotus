<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalDomainOptions, { type DomainKind } from '@/components/portal/PortalDomainOptions.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import { useAuthStore } from '@/stores/auth'
import { useSiteTheme } from '@/composables/useSiteTheme'
import type { ComingSoonProduct, CustomerDashboard, HostingPlan } from '@/types/platform'
import { planAccentFromPrice } from '@/lib/theme'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { sshHeadline, visibleStacks } from '@/lib/planMatrix'

const DOMAIN_FEES = ref<Record<string, number>>({
  '.online': 65,
  '.com': 225,
  '.org': 240,
  '.net': 260,
  '.xyz': 70,
  '.store': 95,
  '.tech': 120,
  '.site': 65,
})

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { planColors, load: loadTheme } = useSiteTheme()
const plans = ref<HostingPlan[]>([])
const comingSoon = ref<ComingSoonProduct[]>([])
const dash = ref<CustomerDashboard | null>(null)
const loading = ref(true)
const error = ref('')
const orderMsg = ref('')
const selected = ref<HostingPlan | null>(null)
const domainMode = ref<DomainKind>('register')
const studentSurname = ref('')
const domainLocal = ref('')
const domainExt = ref('.online')
const domainStatus = ref('')
const busy = ref(false)
const billingTerms = ref<
  Array<{
    months: number
    label: string
    recommended?: boolean
    discount_pct?: number
    subtotal?: number | null
    discount_amount?: number | null
    plan_total?: number | null
  }>
>([])
const selectedTermMonths = ref(1)
const couponCode = ref('')
const couponMsg = ref('')
const couponDiscount = ref(0)
const couponBusy = ref(false)

const featuredId = computed(() => {
  if (!plans.value.length) return ''
  const mid = plans.value.find((p) => /pro|business|growth/i.test(p.name))
  return (mid || plans.value[Math.min(1, plans.value.length - 1)]).id
})

const sortedPlans = computed(() =>
  [...plans.value].sort((a, b) => Number(a.price_monthly) - Number(b.price_monthly)),
)

const packageAccent = computed(() => {
  const sub = dash.value?.subscriptions[0]
  const plan = plans.value.find((p) => p.id === sub?.plan_id) || selected.value
  if (!plan) return undefined
  return planAccentFromPrice(Number(plan.price_monthly), planColors.value, plan.features)
})

const domainFee = computed(() =>
  domainMode.value === 'register' ? DOMAIN_FEES.value[domainExt.value] || 0 : 0,
)

const selectedTerm = computed(
  () => billingTerms.value.find((t) => t.months === selectedTermMonths.value) || billingTerms.value[0] || null,
)

const planTermTotal = computed(() => {
  if (selectedTerm.value?.plan_total != null) return Number(selectedTerm.value.plan_total)
  return Number(selected.value?.price_monthly || 0) * (selectedTermMonths.value || 1)
})

const termSubtotal = computed(() => {
  if (selectedTerm.value?.subtotal != null) return Number(selectedTerm.value.subtotal)
  return Number(selected.value?.price_monthly || 0) * (selectedTermMonths.value || 1)
})

const termDiscount = computed(() => Number(selectedTerm.value?.discount_amount || 0))

const invoiceTotal = computed(() =>
  Math.max(0, planTermTotal.value - couponDiscount.value) + domainFee.value,
)

async function applyCoupon() {
  if (!selected.value || !couponCode.value.trim()) {
    couponMsg.value = 'Enter a coupon code.'
    return
  }
  couponBusy.value = true
  couponMsg.value = ''
  try {
    const { data } = await customersApi.previewCoupon({
      code: couponCode.value.trim(),
      plan_id: selected.value.id,
      billing_term_months: selectedTermMonths.value || 1,
    })
    couponDiscount.value = Number(data.discount_amount || 0)
    couponCode.value = data.code
    couponMsg.value = `Saved GHS ${couponDiscount.value.toFixed(0)} with ${data.code}.`
  } catch (e: unknown) {
    couponDiscount.value = 0
    couponMsg.value = getApiErrorMessage(e, 'Coupon could not be applied.')
  } finally {
    couponBusy.value = false
  }
}

const renewsOnLabel = computed(() => {
  const months = selectedTermMonths.value || 1
  const d = new Date()
  d.setMonth(d.getMonth() + months)
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
})

const step = computed(() => (selected.value ? 2 : 1))

function priceLabel(plan: HostingPlan) {
  const n = Number(plan.price_monthly)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function stacksPreview(plan: HostingPlan) {
  const names = visibleStacks(plan)
    .filter((s) => s.level === 'yes')
    .map((s) => s.label)
    .slice(0, 8)
  return names.length ? names.join(' · ') : 'Core hosting stacks'
}

onMounted(async () => {
  await loadTheme()
  try {
    const me = await customersApi.me()
    // Incomplete profiles stay on /account with staged prompts — not guest signup.
    if (!me.data.can_order && !me.data.profile_complete) {
      await router.replace({
        name: 'portal-dashboard',
        query: { plan: route.query.plan || undefined, complete: '1' },
      })
      return
    }
    const [planRes, dashRes, metaRes] = await Promise.all([
      catalogApi.plans(),
      customersApi.dashboard(),
      catalogApi.meta().catch(() => null),
    ])
    plans.value = planRes.data.items
    comingSoon.value = planRes.data.coming_soon || []
    dash.value = dashRes.data
    if (metaRes?.data?.domain_prices?.length) {
      const map: Record<string, number> = {}
      for (const d of metaRes.data.domain_prices) {
        map[d.extension] = Number(d.price_yearly)
      }
      DOMAIN_FEES.value = { ...DOMAIN_FEES.value, ...map }
    }
    // Prefill student surname from profile during checkout only (not after activation).
    const parts = (dash.value.customer.full_name || '').trim().split(/\s+/).filter(Boolean)
    if (parts.length && !studentSurname.value) {
      studentSurname.value = parts[parts.length - 1]
    }
    const pref = typeof route.query.plan === 'string' ? route.query.plan : ''
    if (pref) {
      const match = plans.value.find((p) => p.slug === pref)
      if (match) {
        selected.value = match
        await loadBillingTerms(match)
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load plans.'
  } finally {
    loading.value = false
  }
})

function choose(plan: HostingPlan) {
  selected.value = plan
  orderMsg.value = ''
  domainStatus.value = ''
  void loadBillingTerms(plan)
}

async function loadBillingTerms(plan: HostingPlan | null) {
  if (!plan) {
    billingTerms.value = []
    selectedTermMonths.value = 1
    return
  }
  try {
    const { data } = await catalogApi.billingTerms(Number(plan.price_monthly))
    billingTerms.value = data.terms || []
    const preferred =
      billingTerms.value.find((t) => t.recommended) ||
      billingTerms.value.find((t) => t.months === selectedTermMonths.value) ||
      billingTerms.value[0]
    selectedTermMonths.value = preferred?.months || 1
  } catch {
    billingTerms.value = [
      { months: 1, label: '1 month', plan_total: Number(plan.price_monthly), subtotal: Number(plan.price_monthly) },
    ]
    selectedTermMonths.value = 1
  }
}

async function checkDomain() {
  if (!domainLocal.value.trim()) {
    domainStatus.value = 'Enter a domain name first.'
    return
  }
  domainStatus.value = 'Checking…'
  try {
    const { data } = await customersApi.checkDomain(domainLocal.value, domainExt.value)
    domainStatus.value = data.available
      ? `${data.domain} is available — GHS ${data.price_yearly}/yr`
      : data.message
  } catch {
    domainStatus.value = 'Domain check failed.'
  }
}

async function checkout() {
  if (!selected.value) return
  if (domainMode.value === 'student' && studentSurname.value.trim().length < 2) {
    orderMsg.value = 'Enter your surname for the student address.'
    return
  }
  const fullDomain = domainLocal.value
    ? `${domainLocal.value.replace(/\s+/g, '').toLowerCase()}${domainExt.value}`
    : undefined
  busy.value = true
  orderMsg.value = ''
  try {
    const { data } = await customersApi.createOrder({
      plan_id: selected.value.id,
      domain_name: domainMode.value === 'student' ? undefined : fullDomain,
      domain_extension: domainMode.value === 'student' ? undefined : fullDomain ? domainExt.value : undefined,
      include_domain: domainMode.value === 'register' && !!fullDomain,
      domain_kind: domainMode.value,
      student_surname: domainMode.value === 'student' ? studentSurname.value.trim() : undefined,
      billing_term_months: selectedTermMonths.value || 1,
      coupon_code: couponCode.value.trim() || undefined,
    })
    const orderId = data?.order?.id
    if (!orderId) {
      orderMsg.value = 'Invoice was created but could not be opened. Open it from Billing.'
      return
    }
    await router.push(`/account/invoice/${orderId}`)
  } catch (e: unknown) {
    orderMsg.value = getApiErrorMessage(e, 'Could not start checkout.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <PortalShell
    mode="app"
    :email="dash?.customer.email || auth.user?.email || undefined"
    :display-name="dash?.customer.full_name || auth.user?.full_name || undefined"
    :plan-accent="packageAccent"
  >
    <template #sidebar>
      <PortalAccountNav :has-env="!!dash?.environments?.length" :environment-id="dash?.environments?.[0]?.id" active="plans" />
    </template>

    <div class="mx-auto w-full max-w-5xl">
      <!-- Steps -->
      <nav class="mb-6 flex flex-wrap items-center gap-2 text-xs font-semibold sm:gap-3" aria-label="Checkout steps">
        <span
          class="inline-flex items-center gap-2 rounded-full px-3 py-1.5"
          :class="step === 1 ? 'bg-slate-900 text-white' : 'bg-emerald-50 text-emerald-800'"
        >
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-[10px]">1</span>
          Pack
        </span>
        <span class="hidden text-slate-300 sm:inline">→</span>
        <span
          class="inline-flex items-center gap-2 rounded-full px-3 py-1.5"
          :class="step === 2 ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-500'"
        >
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-white/15 text-[10px]">2</span>
          Domain
        </span>
        <span class="hidden text-slate-300 sm:inline">→</span>
        <span class="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-slate-500">
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-white/40 text-[10px]">3</span>
          Invoice
        </span>
      </nav>

      <header class="mb-6 sm:mb-8">
        <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">New order</p>
        <h1 class="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          {{ selected ? 'Name your site' : 'Choose hosting' }}
        </h1>
        <p class="mt-2 max-w-xl text-sm leading-relaxed text-slate-600 sm:text-base">
          {{
            selected
              ? 'Pick how the site is addressed, confirm the total, then open the invoice.'
              : 'Select a pack. Next you choose a domain, then pay the invoice.'
          }}
        </p>
      </header>

      <p v-if="loading" class="rounded-2xl border border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
        Loading plans…
      </p>
      <p v-else-if="error" class="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {{ error }}
      </p>

      <!-- Step 1: plans -->
      <div v-else-if="!selected">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <button
            v-for="plan in sortedPlans"
            :key="plan.id"
            type="button"
            class="group flex flex-col rounded-2xl border bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus:ring-4 focus:ring-slate-900/10 sm:p-5"
            :class="
              plan.id === featuredId
                ? 'border-slate-900 ring-1 ring-slate-900'
                : 'border-slate-200 hover:border-slate-300'
            "
            @click="choose(plan)"
          >
            <div class="flex items-start justify-between gap-2">
              <h2 class="text-base font-bold text-slate-900 sm:text-lg">{{ plan.name }}</h2>
              <span
                v-if="plan.id === featuredId"
                class="shrink-0 rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white"
              >
                Popular
              </span>
            </div>
            <p class="mt-3 flex items-baseline gap-1 text-slate-900">
              <span class="text-sm font-semibold text-slate-500">GHS</span>
              <span class="text-3xl font-extrabold tracking-tight">{{ priceLabel(plan) }}</span>
              <span class="text-sm text-slate-500">/mo</span>
            </p>
            <p class="mt-1 text-xs font-medium text-slate-500">{{ sshHeadline(plan) }}</p>
            <dl class="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-600">
              <div class="rounded-xl bg-slate-50 px-2.5 py-2">
                <dt class="text-slate-400">CPU</dt>
                <dd class="mt-0.5 font-semibold text-slate-800">{{ formatCpu(plan.cpu_cores) }} vCPU</dd>
              </div>
              <div class="rounded-xl bg-slate-50 px-2.5 py-2">
                <dt class="text-slate-400">RAM</dt>
                <dd class="mt-0.5 font-semibold text-slate-800">{{ formatRamGb(plan.ram_gb) }}</dd>
              </div>
              <div class="rounded-xl bg-slate-50 px-2.5 py-2">
                <dt class="text-slate-400">Disk</dt>
                <dd class="mt-0.5 font-semibold text-slate-800">{{ plan.storage_gb }} GB</dd>
              </div>
              <div class="rounded-xl bg-slate-50 px-2.5 py-2">
                <dt class="text-slate-400">AI</dt>
                <dd class="mt-0.5 font-semibold text-slate-800">{{ plan.ai_credits }} credits</dd>
              </div>
            </dl>
            <p class="mt-3 line-clamp-2 text-[11px] leading-snug text-slate-500">
              {{ stacksPreview(plan) }}
            </p>
            <span
              class="mt-4 inline-flex w-full items-center justify-center rounded-xl bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white transition group-hover:bg-slate-800"
            >
              Select {{ plan.name }}
            </span>
          </button>
        </div>

        <section
          v-if="comingSoon.length"
          class="mt-8 border-t border-slate-200 pt-6"
          aria-label="Coming soon"
        >
          <h2 class="text-base font-bold text-slate-900">Coming soon</h2>
          <p class="mt-1 max-w-xl text-sm text-slate-600">
            Dedicated VMs need their own provisioning path — not sold on this shared node.
          </p>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <article
              v-for="item in comingSoon"
              :key="item.slug"
              class="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-4 py-4"
            >
              <p class="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Coming soon</p>
              <h3 class="mt-2 text-lg font-bold text-slate-900">{{ item.name }}</h3>
              <p class="mt-1 text-sm leading-relaxed text-slate-600">{{ item.blurb }}</p>
            </article>
          </div>
        </section>
      </div>

      <!-- Step 2: domain -->
      <section v-else class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-4">
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected pack</p>
              <p class="mt-1 text-lg font-bold text-slate-900">
                {{ selected.name }}
                <span class="font-semibold text-slate-500">· GHS {{ selected.price_monthly }}/mo</span>
              </p>
            </div>
            <button
              type="button"
              class="text-sm font-semibold text-slate-700 underline-offset-2 hover:underline"
              @click="selected = null"
            >
              Change pack
            </button>
          </div>

          <div class="mt-5">
            <PortalDomainOptions
              v-model:domain-mode="domainMode"
              v-model:domain-local="domainLocal"
              v-model:domain-ext="domainExt"
              v-model:student-surname="studentSurname"
              :domain-status="domainStatus"
              @check-domain="checkDomain"
            />
          </div>

          <div v-if="billingTerms.length" class="mt-6 border-t border-slate-100 pt-5">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Billing term</p>
            <p class="mt-1 text-sm text-slate-600">Pay for more months up front when a discount is offered.</p>
            <div class="mt-3 grid gap-2 sm:grid-cols-2">
              <button
                v-for="term in billingTerms"
                :key="term.months"
                type="button"
                class="rounded-xl border px-3 py-3 text-left transition"
                :class="
                  selectedTermMonths === term.months
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 bg-white text-slate-800 hover:border-slate-400'
                "
                @click="selectedTermMonths = term.months"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="text-sm font-bold">{{ term.label }}</span>
                  <span
                    v-if="term.recommended"
                    class="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                    :class="selectedTermMonths === term.months ? 'bg-white/15 text-white' : 'bg-amber-50 text-amber-800'"
                  >Best</span>
                </div>
                <p class="mt-1 text-xs" :class="selectedTermMonths === term.months ? 'text-white/80' : 'text-slate-500'">
                  GHS {{ Number(term.plan_total ?? 0).toFixed(0) }}
                  <span v-if="Number(term.discount_amount || 0) > 0">
                    · save {{ Number(term.discount_pct || 0).toFixed(0) }}%
                  </span>
                </p>
              </button>
            </div>
          </div>
        </div>

        <aside class="h-fit rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:sticky lg:top-4">
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Summary</p>
          <div class="mt-4 space-y-3 text-sm">
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Plan</span>
              <span class="font-semibold text-slate-900">{{ selected.name }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Monthly</span>
              <span class="font-semibold text-slate-900">GHS {{ Number(selected.price_monthly).toFixed(0) }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Term</span>
              <span class="font-semibold text-slate-900">{{ selectedTerm?.label || `${selectedTermMonths} mo` }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Subtotal</span>
              <span class="font-semibold text-slate-900">GHS {{ termSubtotal.toFixed(0) }}</span>
            </div>
            <div v-if="termDiscount > 0" class="flex justify-between gap-3">
              <span class="text-slate-500">Term discount</span>
              <span class="font-semibold text-emerald-700">− GHS {{ termDiscount.toFixed(0) }}</span>
            </div>
            <div class="space-y-2 border-t border-slate-100 pt-3">
              <label class="block text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Coupon</label>
              <div class="flex gap-2">
                <input
                  v-model="couponCode"
                  type="text"
                  class="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm uppercase"
                  placeholder="TTU2026"
                  @keydown.enter.prevent="applyCoupon"
                />
                <button
                  type="button"
                  class="rounded-lg bg-slate-900 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"
                  :disabled="couponBusy"
                  @click="applyCoupon"
                >
                  Apply
                </button>
              </div>
              <p v-if="couponMsg" class="text-xs" :class="couponDiscount > 0 ? 'text-emerald-700' : 'text-red-600'">
                {{ couponMsg }}
              </p>
            </div>
            <div v-if="couponDiscount > 0" class="flex justify-between gap-3">
              <span class="text-slate-500">Coupon</span>
              <span class="font-semibold text-emerald-700">− GHS {{ couponDiscount.toFixed(0) }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Hosting</span>
              <span class="font-semibold text-slate-900">
                GHS {{ Math.max(0, planTermTotal - couponDiscount).toFixed(0) }}
              </span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Domain</span>
              <span class="font-semibold text-slate-900">
                {{ domainFee ? `GHS ${domainFee}` : 'GHS 0' }}
              </span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Renews / expires</span>
              <span class="font-semibold text-slate-900">{{ renewsOnLabel }}</span>
            </div>
            <div class="border-t border-slate-100 pt-3">
              <div class="flex items-baseline justify-between gap-3">
                <span class="font-semibold text-slate-800">Invoice total</span>
                <span class="text-2xl font-extrabold tracking-tight text-slate-900">GHS {{ invoiceTotal.toFixed(0) }}</span>
              </div>
            </div>
          </div>
          <button
            type="button"
            class="mt-5 flex w-full items-center justify-center rounded-xl bg-slate-900 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="busy"
            @click="checkout"
          >
            {{ busy ? 'Creating invoice…' : 'Continue to invoice' }}
          </button>
          <p v-if="orderMsg" class="mt-3 text-center text-sm font-medium text-red-600">{{ orderMsg }}</p>
          <p class="mt-3 text-center text-xs leading-relaxed text-slate-500">
            Next: pay Mobile Money on the invoice page.
          </p>
        </aside>
      </section>
    </div>
  </PortalShell>
</template>
