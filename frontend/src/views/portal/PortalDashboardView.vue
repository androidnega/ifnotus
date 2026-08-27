<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalBillingPanel from '@/components/portal/PortalBillingPanel.vue'
import PortalOverviewPanel from '@/components/portal/PortalOverviewPanel.vue'
import PortalProfileStageGate from '@/components/portal/PortalProfileStageGate.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import PortalSupportView from '@/views/portal/PortalSupportView.vue'
import type { CustomerDashboard, CustomerProfile, HostingPlan } from '@/types/platform'
import { planAccentFromPrice } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { usePortalSiteTools } from '@/composables/usePortalSiteTools'
import { nextProfileStage } from '@/lib/portalProfileStages'
import { openHostingFromAccount } from '@/lib/hostingDeepLink'

const PLANS_CACHE_KEY = 'ifnotus.catalog.plans'

function readCachedPlans(): HostingPlan[] {
  try {
    const raw = sessionStorage.getItem(PLANS_CACHE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as HostingPlan[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const router = useRouter()
const route = useRoute()
const { planColors } = useSiteTheme()
const dash = ref<CustomerDashboard | null>(null)
const profile = ref<CustomerProfile | null>(null)
const showStageGate = ref(false)
const plans = ref<HostingPlan[]>(readCachedPlans())
const loading = ref(true)
const error = ref('')
const selectedPlanId = ref(localStorage.getItem('ifnotus_selected_plan') || '')
const billingMsg = ref('')
const changePlanId = ref('')
const topUpCredits = ref(20)
const panel = ref<'home' | 'billing' | 'support'>('home')

const {
  activeEnv,
  usageInfo,
  usageStatus,
  usagePct,
  usageSnapshot,
  healthInfo,
  setActiveEnvId,
  selectEnv,
  hydrateActiveEnv,
} = usePortalSiteTools(dash)

const selectedPlan = computed(() => plans.value.find((p) => p.id === selectedPlanId.value) || plans.value[0])

const activeSubscription = computed(() => {
  const env = activeEnv.value
  if (!env || !dash.value) return dash.value?.subscriptions[0] || null
  return dash.value.subscriptions.find((s) => s.id === env.subscription_id) || dash.value.subscriptions[0] || null
})

const activePlan = computed(() => {
  const sub = activeSubscription.value
  if (!sub) return null
  return plans.value.find((p) => p.id === sub.plan_id) || null
})

const packageAccent = computed(() => {
  const plan = activePlan.value || selectedPlan.value
  if (!plan) return '#1e3a5f'
  return planAccentFromPrice(Number(plan.price_monthly), planColors.value, plan.features)
})

const firstName = computed(
  () =>
    profile.value?.first_name ||
    dash.value?.customer.full_name?.split(' ')[0] ||
    'there',
)

const stageMode = computed(() => {
  if (!profile.value) return 'gate' as const
  return profile.value.can_order || profile.value.profile_complete ? ('card' as const) : ('gate' as const)
})

onMounted(() => {
  void loadAccount()
})

async function loadAccount() {
  loading.value = true
  error.value = ''
  try {
    const me = await customersApi.me()
    profile.value = me.data
    const needsStage = Boolean(nextProfileStage(me.data, { includeOptional: true }))
    showStageGate.value = needsStage
    const requiredDone = Boolean(me.data.can_order || me.data.profile_complete)
    if (!requiredDone) {
      // Overlay only — account loads after required stages finish.
      loading.value = false
      return
    }
    await loadDashboard()
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { error?: { message?: string } } } }
    if (err.response?.status === 401 || err.response?.status === 403) {
      localStorage.removeItem('ifnotus_portal')
      await router.push({ name: 'login' })
      return
    }
    error.value = err.response?.data?.error?.message ?? 'Failed to load dashboard.'
  } finally {
    loading.value = false
  }
}

async function loadDashboard() {
  const { data } = await customersApi.dashboard()
  dash.value = data
  const envFromQuery = typeof route.query.env === 'string' ? route.query.env : ''
  if (envFromQuery && data.environments.some((e) => e.id === envFromQuery)) {
    setActiveEnvId(envFromQuery)
  } else if (data.environments[0]) {
    setActiveEnvId(data.environments[0].id)
  }
  if (data.plans?.length) {
    plans.value = data.plans
    if (!selectedPlanId.value) selectedPlanId.value = data.plans[0].id
  }
  void hydrateActiveEnv()
  void catalogApi
    .plans()
    .then(({ data: catalog }) => {
      if (!catalog.items?.length) return
      const byId = new Map<string, (typeof catalog.items)[0]>()
      for (const p of catalog.items) byId.set(p.id, p)
      for (const p of plans.value) byId.set(p.id, p)
      plans.value = [...byId.values()]
      if (!selectedPlanId.value && catalog.items[0]) selectedPlanId.value = catalog.items[0].id
      try {
        sessionStorage.setItem(PLANS_CACHE_KEY, JSON.stringify(catalog.items))
      } catch {
        /* ignore quota */
      }
    })
    .catch(() => {
      /* overview still works from the cached matrix */
    })
}

function onProfileUpdated(next: CustomerProfile) {
  profile.value = next
  showStageGate.value = Boolean(nextProfileStage(next, { includeOptional: true }))
  // Once required fields are done, hydrate the workspace under the remaining optional prompts.
  if ((next.can_order || next.profile_complete) && !dash.value) {
    void loadDashboard().catch(() => {
      /* gate still works */
    })
  }
}

async function onProfileComplete(next: CustomerProfile) {
  profile.value = next
  showStageGate.value = false
  if (dash.value) return
  loading.value = true
  try {
    await loadDashboard()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Failed to load dashboard.'
  } finally {
    loading.value = false
  }
}

function onStageDismiss() {
  showStageGate.value = false
  if (!dash.value && profile.value) void onProfileComplete(profile.value)
}

async function refreshDash() {
  const refreshed = await customersApi.dashboard()
  dash.value = refreshed.data
}

async function renew(id: string) {
  billingMsg.value = 'Starting renewal payment…'
  try {
    const { data } = await customersApi.renewSubscription(id)
    if (data.applied) {
      await refreshDash()
      billingMsg.value = data.message || 'Subscription updated.'
      return
    }
    if (data.order_id) {
      await router.push({ name: 'portal-invoice', params: { id: data.order_id } })
      return
    }
    await refreshDash()
    billingMsg.value = `Invoice ${data.invoice_number || ''} created. Pay the merchant number on the invoice.`
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    billingMsg.value = err.response?.data?.error?.message ?? 'Renew failed.'
  }
}

async function toggleRenew(id: string, enabled: boolean) {
  billingMsg.value = 'Saving…'
  try {
    await customersApi.setAutoRenew(id, enabled)
    await refreshDash()
    billingMsg.value = enabled ? 'Auto-renew on.' : 'Auto-renew off.'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    billingMsg.value = err.response?.data?.error?.message ?? 'Could not update auto-renew.'
  }
}

async function changePlan(id: string) {
  if (!changePlanId.value) return
  billingMsg.value = 'Updating plan…'
  try {
    const { data } = await customersApi.changePlan(id, changePlanId.value)
    if (data.applied) {
      await refreshDash()
      billingMsg.value = data.message || 'Plan updated.'
      return
    }
    if (data.order_id) {
      await router.push({ name: 'portal-invoice', params: { id: data.order_id } })
      return
    }
    await refreshDash()
    billingMsg.value = `Invoice ${data.invoice_number || ''} created. Pay the merchant number on the invoice.`
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    billingMsg.value = err.response?.data?.error?.message ?? 'Plan change failed.'
  }
}

async function buyCredits() {
  billingMsg.value = 'Starting credit top-up…'
  try {
    const { data } = await customersApi.topUpCredits(topUpCredits.value)
    if (data.order_id) {
      await router.push({ name: 'portal-invoice', params: { id: data.order_id } })
      return
    }
    await refreshDash()
    billingMsg.value = `Invoice ${data.invoice_number || ''} created for ${data.credits} credits.`
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    billingMsg.value = err.response?.data?.error?.message ?? 'Top-up failed.'
  }
}

function openInvoice(id: string) {
  if (!id) {
    billingMsg.value = 'Invoice not found.'
    return
  }
  void router.push(`/account/invoice/${id}`)
}

function onOpenPanel(next: 'site' | 'billing' | 'ai' | 'support') {
  if (next === 'ai' || next === 'site') {
    goToHosting(next === 'ai' ? 'apps' : 'overview')
      return
    }
  goNav(next)
}

function onOpenSiteTab(tab: string) {
  goToHosting(tab)
}

function goToHosting(tab?: string) {
  const domain = activeEnv.value?.domain
  if (!domain) {
    panel.value = 'billing'
    void router.replace({ name: 'portal-dashboard', query: { panel: 'billing' } })
    return
  }
  openHostingFromAccount(domain, tab)
}

function goNav(next: 'home' | 'billing' | 'ai' | 'support' | 'site', tab?: string) {
  if (next === 'ai' || next === 'site') {
    goToHosting(tab || (next === 'ai' ? 'apps' : 'overview'))
    return
  }
  panel.value = next
  if (next === 'home') {
    void router.replace({ name: 'portal-dashboard' })
    return
  }
  void router.replace({ name: 'portal-dashboard', query: { panel: next } })
}

watch(
  () => [route.name, route.query.panel, route.query.tab, route.query.env, activeEnv.value?.id] as const,
  ([name, qPanel, qTab, qEnv]) => {
    if (name !== 'portal-dashboard') return
    if (typeof qEnv === 'string' && dash.value?.environments.some((e) => e.id === qEnv)) {
      setActiveEnvId(qEnv)
    }
    let p = typeof qPanel === 'string' ? qPanel : 'home'
    // Phase H: technical tools live only in Hosting Panel.
    if (p === 'site' || p === 'ai') {
      const tab = typeof qTab === 'string' ? qTab : p === 'ai' ? 'apps' : 'overview'
      goToHosting(tab)
      return
    }
    if (p === 'billing' || p === 'support' || p === 'home') {
      panel.value = p
    }
  },
  { immediate: true },
)
</script>

<template>
  <PortalShell
    mode="app"
    :email="profile?.email?.includes('@phone.pending.ifnotus') ? undefined : (profile?.email || dash?.customer.email)"
    :display-name="profile?.full_name || dash?.customer.full_name"
    :plan-accent="packageAccent"
    :support-count="dash?.unread_notifications"
  >
    <template #sidebar>
      <PortalAccountNav
        :has-env="!!activeEnv"
        :environment-id="activeEnv?.id"
        :domain="activeEnv?.domain"
        :active="panel"
      />
    </template>

    <PortalProfileStageGate
      v-if="showStageGate && profile"
      :profile="profile"
      :mode="stageMode"
      :include-optional="true"
      @updated="onProfileUpdated"
      @complete="onProfileComplete"
      @dismiss="onStageDismiss"
    />

    <p v-if="loading" class="muted">Loading your account…</p>
    <div v-else-if="error" class="p-card account-error">
      <p class="eyebrow">Account</p>
      <h2>Couldn’t open your workspace</h2>
      <p class="lede">{{ error }}</p>
      <button type="button" class="nav-cta" @click="loadAccount">Try again</button>
    </div>

    <div
      v-else-if="!dash && showStageGate"
      class="p-card account-error"
    >
      <p class="eyebrow">Welcome back</p>
      <h2>Finish a few details</h2>
      <p class="lede">
        We’ll ask for one thing at a time — email and the rest of your account info — then open your workspace.
      </p>
    </div>

    <template v-else-if="dash">
      <PortalOverviewPanel
        v-if="panel === 'home'"
        :dash="dash"
        :active-env="activeEnv"
        :active-plan="activePlan"
        :usage-pct="usagePct"
        :usage-status="usageStatus"
        :usage-info="usageInfo"
        :usage-snapshot="usageSnapshot"
        :health-info="healthInfo"
        :first-name="firstName"
        @open-panel="onOpenPanel"
        @select-env="selectEnv"
        @open-site-tab="onOpenSiteTab"
      />

      <PortalBillingPanel
        v-else-if="panel === 'billing'"
        :dash="dash"
        :plans="plans"
        :plan-colors="planColors"
        :billing-msg="billingMsg"
        :has-live-hosting="!!activeEnv"
        v-model:change-plan-id="changePlanId"
        v-model:top-up-credits="topUpCredits"
        @renew="renew"
        @toggle-renew="(id, enabled) => toggleRenew(id, enabled)"
        @change-plan="changePlan"
        @buy-credits="buyCredits"
        @open-invoice="openInvoice"
      />

      <PortalSupportView v-else-if="panel === 'support'" embed />
    </template>
  </PortalShell>
</template>

<style scoped>
.nav-text,
.nav-cta {
  border: none;
  background: transparent;
  font-size: 0.875rem;
  cursor: pointer;
  padding: 0.4rem 0.75rem;
  border-radius: 999px;
}
.nav-text { color: var(--if-muted); }
.nav-text:hover { color: var(--if-primary); }
.nav-cta {
  background: var(--if-primary);
  color: #fff;
  font-weight: 600;
}
.side-k {
  margin: 0.65rem 0.45rem 0.3rem;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--if-muted);
}
.side-k:first-child { margin-top: 0.15rem; }
@media (max-width: 860px) {
  .side-k { display: none; }
}
.hero {
  margin: 0 0 0.85rem;
}
.hero h1 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.035em;
  color: var(--if-ink);
}
.lede {
  margin: 0.35rem 0 0;
  max-width: 28rem;
  color: var(--if-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}
.last-login {
  margin: 0.45rem 0 0;
  font-size: 0.78rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--if-muted);
}
.tabs {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 1.2rem;
  padding: 0.3rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--if-border) 45%, var(--if-surface));
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
}
.tabs button {
  border: none;
  background: transparent;
  padding: 0.5rem 0.95rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--if-muted);
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.tabs button.on {
  color: var(--p-accent, var(--if-plan));
}
.tabs button:disabled { opacity: 0.35; cursor: not-allowed; }
.stack { display: flex; flex-direction: column; gap: 1rem; }
.stack-sm { display: flex; flex-direction: column; gap: 0.6rem; }
.panel-card {
  background: var(--if-surface);
  border: 1px solid var(--if-border);
  border-radius: 1rem;
  padding: 1.15rem 1.2rem;
  box-shadow: var(--shadow-card);
}
.panel-card h2 { margin: 0; font-size: 1.02rem; font-weight: 650; color: var(--if-ink); }
.panel-card h3 { margin: 0 0 0.35rem; font-size: 0.85rem; font-weight: 650; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
.plan-chip {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  color: var(--p-accent, var(--if-plan));
  background: var(--if-plan-soft);
}
.callout {
  background: color-mix(in srgb, var(--if-primary) 8%, var(--if-surface));
  border: 1px solid color-mix(in srgb, var(--if-primary) 28%, var(--if-border));
  border-radius: 1rem;
  padding: 1.25rem;
}
.callout h2 { margin: 0 0 0.4rem; font-size: 1.1rem; }
.callout p { margin: 0 0 1rem; color: var(--if-muted); font-size: 0.9rem; }
.site-cards { list-style: none; margin: 0.85rem 0 0; padding: 0; display: grid; gap: 0.75rem; }
.site-card {
  border: 1px solid var(--if-border);
  border-radius: 0.9rem;
  padding: 0.95rem 1rem;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.site-card:hover { border-color: color-mix(in srgb, var(--if-plan) 45%, var(--if-border)); }
.site-card.active {
  border-color: var(--p-accent, var(--if-plan));
  box-shadow: 0 0 0 3px var(--if-plan-soft);
}
.site-top { display: flex; justify-content: space-between; gap: 0.75rem; align-items: flex-start; }
.env-list { list-style: none; margin: 0.75rem 0 0; padding: 0; }
.env-list li { display: flex; justify-content: space-between; gap: 1rem; align-items: center; padding: 0.75rem 0; border-top: 1px solid var(--if-border); }
.env-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; }
.health-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  background: color-mix(in srgb, var(--if-border) 70%, white);
  color: var(--if-muted);
}
.health-pill.ok { background: #e7f8ee; color: #0f7a45; }
.health-pill.warn { background: #fff4e5; color: #b54708; }
.health-pill.bad { background: #feeceb; color: #b42318; }
.meter { margin-top: 0.85rem; }
.meter-bar {
  height: 0.45rem;
  border-radius: 999px;
  background: var(--if-border);
  overflow: hidden;
  margin-bottom: 0.35rem;
}
.meter-bar i {
  display: block;
  height: 100%;
  background: var(--if-plan);
  border-radius: inherit;
}
.meter.warning .meter-bar i { background: #d97706; }
.meter.over .meter-bar i { background: #b42318; }
.env-name { margin: 0; font-weight: 650; font-size: 0.95rem; display: flex; align-items: center; gap: 0.45rem; }
.plan-dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; display: inline-block; }
.sub-item { align-items: flex-start !important; flex-direction: column; }
.site-grid { margin-top: 1rem; display: grid; gap: 1rem; }
@media (min-width: 900px) { .site-grid { grid-template-columns: 1fr 1fr; } }
.file-list { list-style: none; margin: 0; padding: 0; max-height: 16rem; overflow: auto; border: 1px solid var(--if-border); border-radius: 0.65rem; }
.file-list li { padding: 0.55rem 0.75rem; font-size: 0.85rem; cursor: pointer; border-bottom: 1px solid color-mix(in srgb, var(--if-border) 70%, var(--if-surface)); }
.file-list li:hover { background: color-mix(in srgb, var(--if-plan) 10%, var(--if-surface)); }
.editor { width: 100%; border: 1px solid var(--if-border); border-radius: 0.55rem; padding: 0.6rem; font-family: ui-monospace, monospace; font-size: 0.75rem; background: var(--if-surface); color: var(--if-ink); }
.tools { margin-top: 1rem; display: grid; gap: 0.85rem; }
.tools > div { border-top: 1px solid var(--if-border); padding-top: 0.75rem; }
.backup-list { list-style: none; margin: 0.5rem 0 0; padding: 0; font-size: 0.75rem; }
.backup-list li { display: flex; justify-content: space-between; gap: 0.5rem; padding: 0.35rem 0; }
.order-grid { display: grid; gap: 0.85rem; }
@media (min-width: 640px) { .order-grid { grid-template-columns: 1fr 1fr; } }
.order-grid label { display: block; font-size: 0.8rem; color: var(--if-muted); }
.domain-row { display: grid; grid-template-columns: 1fr auto; gap: 0.4rem; margin-top: 0.35rem; }
.block { display: block; width: 100%; margin-top: 0.35rem; }
.toolbar { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.row-between { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.75rem; align-items: center; }
.mt { margin-top: 0.75rem; }
.pad { padding: 1rem; }
.box { border: 1px dashed var(--if-border); border-radius: 0.55rem; }
.muted { color: var(--if-muted); font-size: 0.85rem; margin: 0; }
.account-error {
  max-width: 28rem;
}
.account-error h2 {
  margin: 0.2rem 0 0.45rem;
  font-family: Sora, sans-serif;
  font-size: 1.25rem;
}
.account-error .nav-cta { margin-top: 0.85rem; }
.err { color: #b91c1c; font-size: 0.9rem; }
.btn-primary {
  border: none;
  border-radius: 0.55rem;
  background: var(--if-primary);
  color: #fff;
  font-weight: 650;
  font-size: 0.85rem;
  padding: 0.55rem 0.95rem;
  cursor: pointer;
}
.btn-primary:hover { background: var(--if-primary-hover); }
.btn-ghost {
  border: 1px solid var(--if-border);
  border-radius: 0.5rem;
  background: var(--if-surface);
  color: var(--if-ink);
  font-size: 0.75rem;
  padding: 0.35rem 0.65rem;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.select, .input {
  border: 1px solid var(--if-border);
  border-radius: 0.5rem;
  padding: 0.45rem 0.6rem;
  font-size: 0.85rem;
  background: var(--if-surface);
  color: var(--if-ink);
}
.input { width: 100%; }
</style>
