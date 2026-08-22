<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalDomainOptions, { type DomainKind } from '@/components/portal/PortalDomainOptions.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import { useAuthStore } from '@/stores/auth'
import { useSiteTheme } from '@/composables/useSiteTheme'
import type { ComingSoonProduct, CustomerDashboard, HostingPlan } from '@/types/platform'
import { planAccentFromPrice } from '@/lib/theme'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { sshHeadline, visibleStacks } from '@/lib/planMatrix'

const DOMAIN_FEES: Record<string, number> = {
  '.online': 50,
  '.com': 250,
  '.org': 180,
  '.net': 200,
}

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
  domainMode.value === 'register' ? DOMAIN_FEES[domainExt.value] || 0 : 0,
)

const invoiceTotal = computed(() => {
  const plan = Number(selected.value?.price_monthly || 0)
  return plan + domainFee.value
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
    if (!me.data.profile_complete) {
      await router.replace({
        name: 'portal-signup',
        query: { plan: route.query.plan || undefined, complete: '1' },
      })
      return
    }
    const [planRes, dashRes] = await Promise.all([catalogApi.plans(), customersApi.dashboard()])
    plans.value = planRes.data.items
    comingSoon.value = planRes.data.coming_soon || []
    dash.value = dashRes.data
    // Prefill student surname from profile during checkout only (not after activation).
    const parts = (dash.value.customer.full_name || '').trim().split(/\s+/).filter(Boolean)
    if (parts.length && !studentSurname.value) {
      studentSurname.value = parts[parts.length - 1]
    }
    const pref = typeof route.query.plan === 'string' ? route.query.plan : ''
    if (pref) {
      const match = plans.value.find((p) => p.slug === pref)
      if (match) selected.value = match
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
    })
    await router.push({ name: 'portal-invoice', params: { id: data.order.id } })
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    orderMsg.value = err.response?.data?.error?.message ?? 'Could not start checkout.'
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
        </div>

        <aside class="h-fit rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:sticky lg:top-4">
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Summary</p>
          <div class="mt-4 space-y-3 text-sm">
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Hosting</span>
              <span class="font-semibold text-slate-900">GHS {{ Number(selected.price_monthly).toFixed(0) }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-slate-500">Domain</span>
              <span class="font-semibold text-slate-900">
                {{ domainFee ? `GHS ${domainFee}` : 'GHS 0' }}
              </span>
            </div>
            <div class="border-t border-slate-100 pt-3">
              <div class="flex items-baseline justify-between gap-3">
                <span class="font-semibold text-slate-800">Invoice total</span>
                <span class="text-2xl font-extrabold tracking-tight text-slate-900">GHS {{ invoiceTotal }}</span>
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
