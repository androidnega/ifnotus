<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalBillingPanel from '@/components/portal/PortalBillingPanel.vue'
import PortalOverviewPanel from '@/components/portal/PortalOverviewPanel.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import PortalSitePanel from '@/components/portal/PortalSitePanel.vue'
import PortalSupportView from '@/views/portal/PortalSupportView.vue'
import type { CustomerDashboard, HostingPlan } from '@/types/platform'
import { planAccentFromPrice } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { usePortalSiteTools } from '@/composables/usePortalSiteTools'

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
const plans = ref<HostingPlan[]>(readCachedPlans())
const loading = ref(true)
const error = ref('')
const selectedPlanId = ref(localStorage.getItem('ifnotus_selected_plan') || '')
const billingMsg = ref('')
const changePlanId = ref('')
const topUpCredits = ref(20)
const panel = ref<'home' | 'site' | 'billing' | 'support'>('home')
const siteInitialTab = ref<'files' | 'stack' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | ''>('')

const {
  activeEnv,
  dbCanWrite,
  filePath,
  fileEntries,
  fileContent,
  editingFile,
  fileMsg,
  dbInfo,
  dbCreds,
  dbSchema,
  dbRows,
  dbStudioBusy,
  dbStudioMsg,
  dbSelectedTable,
  dbRowOffset,
  dbSql,
  ftpInfo,
  ftpCreds,
  sftpCreds,
  sftpInfo,
  sftpKeyInput,
  sftpKeyName,
  sshCreds,
  usageInfo,
  logEntries,
  logMsg,
  logBusy,
  usageStatus,
  usagePct,
  healthInfo,
  dnsInfo,
  dnsData,
  sslMsg,
  backups,
  backupMsg,
  stackMsg,
  stackBusy,
  stackProgress,
  stackOutcome,
  selectedStack,
  stacks,
  currentStack,
  cronJobs,
  cronSchedule,
  cronCommand,
  cronMsg,
  cronBusy,
  setActiveEnvId,
  selectEnv,
  hydrateActiveEnv,
  loadFiles,
  openEntry,
  goUp,
  saveFile,
  loadDb,
  loadDbSchema,
  loadDbRows,
  runDbQuery,
  loadFtp,
  loadSftp,
  ensureSftp,
  addSftpKey,
  removeSftpKey,
  setSftpKeyInput,
  setSftpKeyName,
  loadSsh,
  ensureSsh,
  ensureFtp,
  repairFs,
  loadDns,
  ensureDns,
  attachCustomDomain,
  unassignCustomDomain,
  issueSsl,
  loadBackups,
  createBackup,
  restoreBackup,
  installStack,
  clearStack,
  loadLogs,
  addCron,
  toggleCron,
  runCron,
  deleteCron,
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

const firstName = computed(() => dash.value?.customer.full_name?.split(' ')[0] || 'there')

onMounted(() => {
  void loadAccount()
})

async function loadAccount() {
  loading.value = true
  error.value = ''
  try {
    const me = await customersApi.me()
    if (!me.data.profile_complete) {
      await router.replace({ name: 'portal-signup', query: { complete: '1' } })
      return
    }
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
  void hydrateActiveEnv()
  void catalogApi
    .plans()
    .then(({ data }) => {
      if (!data.items?.length) return
      const byId = new Map<string, (typeof data.items)[0]>()
      for (const p of data.items) byId.set(p.id, p)
      for (const p of plans.value) byId.set(p.id, p)
      plans.value = [...byId.values()]
      if (!selectedPlanId.value && data.items[0]) selectedPlanId.value = data.items[0].id
      try {
        sessionStorage.setItem(PLANS_CACHE_KEY, JSON.stringify(data.items))
      } catch {
        /* ignore quota */
      }
    })
    .catch(() => {
      /* overview still works from the cached matrix */
    })
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
  router.push({ name: 'portal-invoice', params: { id } })
}

function onOpenPanel(next: 'site' | 'billing' | 'ai' | 'support') {
  if (next === 'ai') {
    if (activeEnv.value) {
      window.open(`/account/files?env=${encodeURIComponent(activeEnv.value.id)}`, '_blank')
    } else {
      goNav('site', 'files')
    }
    return
  }
  goNav(next)
}

function onOpenSiteTab(tab: string) {
  goNav('site', tab)
}

function goNav(next: 'home' | 'billing' | 'ai' | 'support' | 'site', tab?: string) {
  if (next === 'ai') {
    onOpenPanel('ai')
    return
  }
  if (next === 'site') {
    const t = tab || 'stack'
    if (
      t === 'files' ||
      t === 'stack' ||
      t === 'cron' ||
      t === 'database' ||
      t === 'protect' ||
      t === 'ftp' ||
      t === 'logs'
    ) {
      siteInitialTab.value = t
    }
    panel.value = 'site'
    void router.replace({ name: 'portal-dashboard', query: { panel: 'site', tab: t } })
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
  () => [route.name, route.query.panel, route.query.tab, route.query.env] as const,
  ([name, qPanel, qTab, qEnv]) => {
    if (name !== 'portal-dashboard') return
    if (typeof qEnv === 'string' && dash.value?.environments.some((e) => e.id === qEnv)) {
      setActiveEnvId(qEnv)
    }
    let p = typeof qPanel === 'string' ? qPanel : 'home'
    if (p === 'ai') {
      p = 'site'
      void router.replace({ name: 'portal-dashboard', query: { panel: 'site', tab: 'files' } })
    }
    if (p === 'site' && !activeEnv.value) {
      p = 'home'
      void router.replace({ name: 'portal-dashboard' })
    }
    if (p === 'billing' || p === 'support' || p === 'site' || p === 'home') {
      panel.value = p
    }
    if (typeof qTab === 'string' && qTab) {
      siteInitialTab.value = qTab as typeof siteInitialTab.value
    }
  },
  { immediate: true },
)
</script>

<template>
  <PortalShell mode="app" :email="dash?.customer.email" :display-name="dash?.customer.full_name" :plan-accent="packageAccent">
    <template #sidebar>
      <PortalAccountNav
        :has-env="!!activeEnv"
        :environment-id="activeEnv?.id"
        :active="panel"
      />
    </template>

    <p v-if="loading" class="muted">Loading your account…</p>
    <div v-else-if="error" class="p-card account-error">
      <p class="eyebrow">Account</p>
      <h2>Couldn’t open your workspace</h2>
      <p class="lede">{{ error }}</p>
      <button type="button" class="nav-cta" @click="loadAccount">Try again</button>
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
        :health-info="healthInfo"
        :first-name="firstName"
        @open-panel="onOpenPanel"
        @select-env="selectEnv"
        @open-site-tab="onOpenSiteTab"
      />

      <PortalSitePanel
        v-else-if="panel === 'site' && activeEnv"
        :environments="dash.environments"
        :active-env="activeEnv"
        :active-plan="activePlan"
        :initial-tab="siteInitialTab"
        :file-path="filePath"
        :file-entries="fileEntries"
        :file-content="fileContent"
        :editing-file="editingFile"
        :file-msg="fileMsg"
        :stacks="stacks"
        v-model:selected-stack="selectedStack"
        :current-stack="currentStack"
        :stack-busy="stackBusy"
        :stack-msg="stackMsg"
        :stack-progress="stackProgress"
        :stack-outcome="stackOutcome"
        :cron-jobs="cronJobs"
        v-model:cron-schedule="cronSchedule"
        v-model:cron-command="cronCommand"
        :cron-busy="cronBusy"
        :cron-msg="cronMsg"
        :db-info="dbInfo"
        :db-creds="dbCreds"
        :db-schema="dbSchema"
        :db-rows="dbRows"
        :db-studio-busy="dbStudioBusy"
        :db-studio-msg="dbStudioMsg"
        :db-selected-table="dbSelectedTable"
        :db-row-offset="dbRowOffset"
        :db-sql="dbSql"
        :db-can-write="dbCanWrite"
        :ftp-info="ftpInfo"
        :ftp-creds="ftpCreds"
        :sftp-creds="sftpCreds"
        :sftp-info="sftpInfo"
        :sftp-key-input="sftpKeyInput"
        :sftp-key-name="sftpKeyName"
        :ssh-creds="sshCreds"
        :dns-info="dnsInfo"
        :dns-data="dnsData"
        :ssl-msg="sslMsg"
        :backups="backups"
        :backup-msg="backupMsg"
        :log-entries="logEntries"
        :log-msg="logMsg"
        :log-busy="logBusy"
        @select-env="selectEnv"
        @load-files="loadFiles"
        @load-logs="loadLogs"
        @go-up="goUp"
        @open-entry="openEntry"
        @save-file="saveFile"
        @install-stack="installStack"
        @clear-stack="clearStack"
        @add-cron="addCron"
        @run-cron="runCron"
        @toggle-cron="toggleCron"
        @delete-cron="deleteCron"
        @load-db="loadDb"
        @load-db-schema="loadDbSchema"
        @load-db-rows="loadDbRows"
        @run-db-query="runDbQuery"
        @update-db-sql="(v) => (dbSql = v)"
        @load-ftp="loadFtp"
        @ensure-ftp="ensureFtp"
        @load-sftp="loadSftp"
        @ensure-sftp="ensureSftp"
        @add-sftp-key="addSftpKey"
        @remove-sftp-key="removeSftpKey"
        @update:sftp-key-input="setSftpKeyInput"
        @update:sftp-key-name="setSftpKeyName"
        @load-ssh="loadSsh"
        @ensure-ssh="ensureSsh"
        @repair-fs="repairFs"
        @load-dns="loadDns"
        @ensure-dns="ensureDns"
        @attach-custom="attachCustomDomain"
        @unassign-custom="unassignCustomDomain"
        @issue-ssl="issueSsl"
        @load-backups="loadBackups"
        @create-backup="createBackup"
        @restore-backup="restoreBackup"
        @open-support="router.push({ name: 'portal-support' })"
        @update:file-content="(v) => (fileContent = v)"
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
