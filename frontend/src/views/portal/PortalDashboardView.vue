<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalBillingPanel from '@/components/portal/PortalBillingPanel.vue'
import PortalOverviewPanel from '@/components/portal/PortalOverviewPanel.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import PortalSitePanel from '@/components/portal/PortalSitePanel.vue'
import PortalSupportView from '@/views/portal/PortalSupportView.vue'
import type { CustomerDashboard, HostingPlan } from '@/types/platform'
import type { DbQueryResult, DbSchema } from '@/types/databases'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planAccentFromPrice } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'

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
const activeEnvId = ref('')
const filePath = ref('.')
const fileEntries = ref<Array<{ name: string; path: string; is_dir: boolean; size_bytes?: number | null }>>([])
const fileContent = ref('')
const editingFile = ref('')
const fileMsg = ref('')
const dbInfo = ref('')
const dbCreds = ref<{
  engine?: string | null
  name?: string | null
  username?: string | null
  host?: string | null
  port?: number | null
  password_set?: boolean
  password?: string | null
  empty?: boolean
  error?: string
} | null>(null)
const dbSchema = ref<DbSchema | null>(null)
const dbRows = ref<DbQueryResult | null>(null)
const dbStudioBusy = ref(false)
const dbStudioMsg = ref('')
const dbSelectedTable = ref('')
const dbRowOffset = ref(0)
const dbSql = ref('SELECT * FROM ')
const ftpInfo = ref('')
const ftpCreds = ref<{
  enabled?: boolean
  username?: string | null
  host?: string
  wordpress_host?: string
  port?: number
  password_set?: boolean
  password?: string | null
  home?: string | null
  connection_type?: string
  hint?: string
  message?: string | null
  error?: string
} | null>(null)
const sshCreds = ref<{
  ssh_allowed?: boolean
  enabled?: boolean
  username?: string | null
  host?: string
  shared_ip?: string | null
  port?: number
  command?: string | null
  min_price_ghs?: number
  hint?: string
  message?: string | null
  error?: string
} | null>(null)
const usageInfo = ref('')
const logEntries = ref<Array<{ source: string; message: string }>>([])
const logMsg = ref('')
const logBusy = ref(false)
const usageStatus = ref<'ok' | 'warning' | 'over' | ''>('')
const usagePct = ref(0)
const healthInfo = ref('')
const dnsInfo = ref('')
const dnsData = ref<{
  domain?: string | null
  addon?: string | null
  custom?: string | null
  nameservers?: string[]
  customDomains?: string[]
  availableDomains?: string[]
  used?: number
  limit?: number
  canAssign?: boolean
  ip: string
  message?: string
  namecheap?: boolean
  includedHostname?: boolean
  nsLive?: boolean | null
  resolves?: boolean | null
  sslReady?: boolean
  statusSummary?: string
  checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
  panelHostname?: string | null
  panelUrl?: string | null
  error?: string
} | null>(null)
const sslMsg = ref('')
const topUpCredits = ref(20)
const backups = ref<
  Array<{
    id: string
    status: string
    file_size?: number | null
    created_at?: string | null
    filename: string
  }>
>([])
const backupMsg = ref('')
const stackMsg = ref('')
const stackBusy = ref(false)
const stackProgress = ref<import('@/api').StackInstallProgress | null>(null)
const stackJobId = ref('')
const stackOutcome = ref<'idle' | 'running' | 'success' | 'error'>('idle')
let stackPollTimer: ReturnType<typeof setInterval> | null = null

function stopStackPoll() {
  if (stackPollTimer) {
    clearInterval(stackPollTimer)
    stackPollTimer = null
  }
}

function applyStackProgress(progress?: import('@/api').StackInstallProgress | null, fallbackMsg?: string) {
  if (progress) stackProgress.value = progress
  if (progress?.label) stackMsg.value = progress.label
  else if (progress?.message) stackMsg.value = progress.message
  else if (fallbackMsg) stackMsg.value = fallbackMsg
}

async function pollStackJob(envId: string, jobId: string) {
  try {
    const { data } = await customersApi.getEnvStackJob(envId, jobId)
    applyStackProgress(data.progress, data.message || undefined)
    const status = (data.progress?.status || data.status || '').toLowerCase()
    if (status === 'success') {
      stopStackPoll()
      stackBusy.value = false
      stackOutcome.value = 'success'
      stackMsg.value = data.message || data.progress?.message || 'Stack installed successfully.'
      currentStack.value = data.current || data.result || currentStack.value
      await loadFiles()
      await loadStacks()
      return
    }
    if (status === 'failed') {
      stopStackPoll()
      stackBusy.value = false
      stackOutcome.value = 'error'
      stackMsg.value = data.error || data.message || data.progress?.error || 'Install failed.'
      return
    }
    stackOutcome.value = 'running'
    stackBusy.value = true
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    // Keep polling on transient errors; surface message.
    stackMsg.value = err.response?.data?.error?.message ?? (stackMsg.value || 'Checking install status…')
  }
}

function startStackPoll(envId: string, jobId: string) {
  stopStackPoll()
  stackJobId.value = jobId
  void pollStackJob(envId, jobId)
  stackPollTimer = setInterval(() => {
    void pollStackJob(envId, jobId)
  }, 1500)
}

const selectedStack = ref('static')
const stacks = ref<
  Array<{
    id: string
    name: string
    description: string
    icon?: string
    level?: string
    one_click?: boolean
  }>
>([])
const currentStack = ref<Record<string, unknown> | null>(null)
const cronJobs = ref<
  Array<{
    id: string
    schedule: string
    command: string
    enabled: boolean
    last_run_at?: string | null
    last_status?: string | null
    last_output?: string | null
  }>
>([])
const cronSchedule = ref('*/15 * * * *')
const cronCommand = ref('php artisan schedule:run')
const cronMsg = ref('')
const cronBusy = ref(false)
const panel = ref<'home' | 'site' | 'billing' | 'support'>('home')
const siteInitialTab = ref<'files' | 'stack' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | ''>('')

const selectedPlan = computed(() => plans.value.find((p) => p.id === selectedPlanId.value) || plans.value[0])
const activeEnv = computed(() => dash.value?.environments.find((e) => e.id === activeEnvId.value) || dash.value?.environments[0] || null)
const dbCanWrite = computed(() => {
  const level = activeEnv.value?.capabilities?.levels?.db_manage
  if (!level) return true
  return level === 'yes'
})

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

function healthLabel(status?: string | null) {
  switch ((status || 'unknown').toLowerCase()) {
    case 'healthy':
      return 'Online'
    case 'degraded':
      return 'Degraded'
    case 'unhealthy':
      return 'Offline'
    case 'offline':
      return 'Offline'
    case 'checking':
      return 'Checking'
    default:
      return 'Unknown'
  }
}

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
    if (data.environments[0]) activeEnvId.value = data.environments[0].id
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

onUnmounted(() => {
  stopStackPoll()
})

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

async function loadFiles() {
  if (!activeEnv.value) return
  fileMsg.value = ''
  try {
    const { data } = await customersApi.listEnvFiles(activeEnv.value.id, filePath.value)
    filePath.value = data.path || '.'
    fileEntries.value = data.entries
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    fileMsg.value = err.response?.data?.error?.message ?? 'Could not list files.'
  }
}

async function openEntry(entry: { name: string; path: string; is_dir: boolean }) {
  if (!activeEnv.value) return
  if (entry.is_dir) {
    filePath.value = entry.path
    editingFile.value = ''
    fileContent.value = ''
    await loadFiles()
    return
  }
  try {
    const { data } = await customersApi.readEnvFile(activeEnv.value.id, entry.path)
    editingFile.value = entry.path
    fileContent.value = data.content ?? ''
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    fileMsg.value = err.response?.data?.error?.message ?? 'Could not open file.'
  }
}

async function goUp() {
  if (filePath.value === '.' || !filePath.value) return
  const parts = filePath.value.split('/').filter(Boolean)
  parts.pop()
  filePath.value = parts.length ? parts.join('/') : '.'
  editingFile.value = ''
  await loadFiles()
}

async function saveFile() {
  if (!activeEnv.value || !editingFile.value) return
  fileMsg.value = 'Saving…'
  try {
    await customersApi.writeEnvFile(activeEnv.value.id, editingFile.value, fileContent.value)
    fileMsg.value = 'Saved.'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    fileMsg.value = err.response?.data?.error?.message ?? 'Save failed.'
  }
}

async function loadDb(reveal = true) {
  if (!activeEnv.value) return
  dbInfo.value = 'Loading…'
  try {
    const { data } = await customersApi.getEnvDatabase(activeEnv.value.id, reveal)
    if (!data.name && !data.engine) {
      dbCreds.value = { empty: true }
      dbInfo.value = 'No database on this site yet. Install WordPress or Laravel from Stack when you need one.'
      dbSchema.value = null
      dbRows.value = null
      return
    }
    dbCreds.value = {
      engine: data.engine,
      name: data.name,
      username: data.username,
      host: data.host || 'localhost',
      port: data.port || 3306,
      password_set: data.password_set,
      password: data.password || null,
    }
    dbInfo.value = ''
    await loadDbSchema()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not load database.'
    dbInfo.value = msg
    dbCreds.value = { error: msg }
  }
}

async function loadDbSchema() {
  if (!activeEnv.value) return
  dbStudioBusy.value = true
  dbStudioMsg.value = ''
  try {
    const { data } = await customersApi.getEnvDatabaseSchema(activeEnv.value.id)
    dbSchema.value = data
    if (!data.tables?.length) {
      dbStudioMsg.value = 'This database has no tables yet.'
      dbRows.value = null
      return
    }
    if (dbSelectedTable.value && data.tables.some((t) => t.name === dbSelectedTable.value)) {
      await loadDbRows(dbSelectedTable.value, dbRowOffset.value)
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    dbSchema.value = null
    dbStudioMsg.value = err.response?.data?.error?.message ?? 'Could not open tables.'
  } finally {
    dbStudioBusy.value = false
  }
}

async function loadDbRows(table: string, offset = 0) {
  if (!activeEnv.value) return
  dbSelectedTable.value = table
  dbRowOffset.value = Math.max(0, offset)
  dbStudioBusy.value = true
  try {
    const { data } = await customersApi.getEnvDatabaseRows(activeEnv.value.id, {
      table,
      limit: 50,
      offset: dbRowOffset.value,
    })
    dbRows.value = data
    if (!data.rows?.length && dbRowOffset.value > 0) {
      dbStudioMsg.value = 'No more rows.'
    } else {
      dbStudioMsg.value = ''
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    dbStudioMsg.value = err.response?.data?.error?.message ?? 'Could not load rows.'
  } finally {
    dbStudioBusy.value = false
  }
}

async function runDbQuery() {
  if (!activeEnv.value || !dbSql.value.trim()) return
  dbStudioBusy.value = true
  dbStudioMsg.value = ''
  try {
    const { data } = await customersApi.queryEnvDatabase(activeEnv.value.id, dbSql.value.trim(), 100)
    dbRows.value = data
    dbSelectedTable.value = ''
    if (data.message) dbStudioMsg.value = data.message
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    dbStudioMsg.value = err.response?.data?.error?.message ?? 'Query failed.'
  } finally {
    dbStudioBusy.value = false
  }
}

async function loadFtp(reveal = true) {
  if (!activeEnv.value) return
  ftpInfo.value = 'Loading…'
  try {
    const { data } = await customersApi.getEnvFtp(activeEnv.value.id, reveal)
    ftpCreds.value = {
      enabled: data.enabled,
      username: data.username,
      host: data.host,
      wordpress_host: data.wordpress_host || 'localhost',
      port: data.port,
      password_set: data.password_set,
      password: data.password || null,
      home: data.home,
      connection_type: data.connection_type,
      hint: data.hint,
      message: data.message,
    }
    ftpInfo.value = ''
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not load FTP.'
    ftpInfo.value = msg
    ftpCreds.value = { host: '', error: msg }
  }
  await loadSsh()
}

async function loadSsh() {
  if (!activeEnv.value) return
  try {
    const { data } = await customersApi.getEnvSsh(activeEnv.value.id, false)
    sshCreds.value = data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    sshCreds.value = { host: 'ssh.ifnotus.space', error: err.response?.data?.error?.message ?? 'Could not load SSH.' }
  }
}

async function ensureSsh() {
  if (!activeEnv.value) return
  try {
    const { data } = await customersApi.ensureEnvSsh(activeEnv.value.id)
    sshCreds.value = data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    sshCreds.value = {
      ...(sshCreds.value || { host: 'ssh.ifnotus.space' }),
      error: err.response?.data?.error?.message ?? 'Could not enable SSH.',
    }
  }
}

async function ensureFtp(resetPassword = false) {
  if (!activeEnv.value) return
  ftpInfo.value = 'Loading…'
  try {
    const { data } = await customersApi.ensureEnvFtp(activeEnv.value.id, resetPassword)
    ftpCreds.value = {
      enabled: data.enabled,
      username: data.username,
      host: data.host,
      wordpress_host: data.wordpress_host || 'localhost',
      port: data.port,
      password_set: data.password_set,
      password: data.password || null,
      home: data.home,
      connection_type: data.connection_type,
      hint: data.hint,
      message: data.message || 'Your FTP login is ready.',
    }
    ftpInfo.value = ''
    await loadSsh()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not create FTP account.'
    ftpInfo.value = msg
    ftpCreds.value = { ...(ftpCreds.value || { host: '' }), error: msg }
  }
}

async function repairFs() {
  if (!activeEnv.value) return
  try {
    const { data } = await customersApi.repairEnvFilesystem(activeEnv.value.id)
    fileMsg.value = data.message
    await loadFtp(true)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    fileMsg.value = err.response?.data?.error?.message ?? 'Could not repair file access.'
  }
}

async function loadDns() {
  if (!activeEnv.value) return
  dnsInfo.value = 'Loading…'
  try {
    const { data } = await customersApi.getEnvDns(activeEnv.value.id)
    dnsData.value = mapDns(data, activeEnv.value.domain)
    dnsInfo.value = ''
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not load DNS.'
    dnsInfo.value = msg
    dnsData.value = { ip: '', error: msg }
  }
}

async function ensureDns() {
  if (!activeEnv.value) return
  dnsInfo.value = 'Updating…'
  try {
    const { data } = await customersApi.ensureEnvDnsA(activeEnv.value.id)
    dnsData.value = mapDns(data, activeEnv.value.domain)
    dnsInfo.value = ''
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not update nameservers.'
    dnsInfo.value = msg
    if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
  }
}

async function attachCustomDomain(domainName: string) {
  if (!activeEnv.value) return
  const name = domainName.trim().toLowerCase()
  if (!name) {
    dnsInfo.value = 'Enter a domain such as studio.online.'
    return
  }
  dnsInfo.value = 'Adding…'
  try {
    const { data } = await customersApi.attachEnvCustomDomain(activeEnv.value.id, name)
    dnsData.value = mapDns(data, name)
    dnsInfo.value = ''
    const refreshed = await customersApi.dashboard()
    dash.value = refreshed.data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not add that domain.'
    dnsInfo.value = msg
    if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
  }
}

async function unassignCustomDomain(domainName: string) {
  if (!activeEnv.value) return
  const name = domainName.trim().toLowerCase()
  if (!name) return
  dnsInfo.value = 'Unassigning…'
  try {
    const { data } = await customersApi.unassignEnvCustomDomain(activeEnv.value.id, name)
    dnsData.value = mapDns(data, data.domain || activeEnv.value.domain)
    dnsInfo.value = ''
    const refreshed = await customersApi.dashboard()
    dash.value = refreshed.data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    const msg = err.response?.data?.error?.message ?? 'Could not unassign that domain.'
    dnsInfo.value = msg
    if (dnsData.value) dnsData.value = { ...dnsData.value, error: msg }
  }
}

function mapDns(
  data: {
    domain?: string | null
    addon_domain?: string | null
    custom_domain?: string | null
    nameservers?: string[]
    custom_domains?: string[]
    available_domains?: string[]
    custom_domains_used?: number
    custom_domains_limit?: number
    can_assign?: boolean
    recommended_ip?: string
    message?: string
    namecheap_pushed?: boolean
    included_hostname?: boolean
    ns_live?: boolean | null
    resolves?: boolean | null
    ssl_ready?: boolean
    status_summary?: string
    checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
    panel_hostname?: string | null
    panel_url?: string | null
  },
  fallbackDomain?: string | null,
) {
  return {
    domain: data.domain || fallbackDomain,
    addon: data.addon_domain || null,
    custom: data.custom_domain || null,
    nameservers: data.nameservers?.length ? data.nameservers : ['ns1.ifnotus.space', 'ns2.ifnotus.space'],
    customDomains: data.custom_domains || [],
    availableDomains: data.available_domains || [],
    used: data.custom_domains_used ?? 0,
    limit: data.custom_domains_limit ?? 1,
    canAssign: Boolean(data.can_assign),
    ip: '',
    message: data.message,
    namecheap: Boolean(data.namecheap_pushed),
    includedHostname: Boolean(data.included_hostname),
    nsLive: data.ns_live ?? null,
    resolves: data.resolves ?? null,
    sslReady: Boolean(data.ssl_ready),
    statusSummary: data.status_summary || data.message || '',
    checklist: data.checklist || [],
    panelHostname: data.panel_hostname || null,
    panelUrl: data.panel_url || null,
  }
}

async function loadUsage() {
  if (!activeEnv.value) return
  usageInfo.value = 'Loading…'
  usageStatus.value = ''
  usagePct.value = 0
  try {
    const { data } = await customersApi.getEnvUsage(activeEnv.value.id)
    usagePct.value = Number(data.storage_pct) || 0
    usageInfo.value = `${formatCpu(data.cpu_limit)} vCPU · ${formatRamGb(data.ram_limit_gb)} RAM · disk ${data.storage_used_gb} / ${data.storage_limit_gb} GB · ${data.file_count} files`
    if (data.message) usageInfo.value += ` — ${data.message}`
    usageStatus.value =
      data.storage_status === 'over' || data.hard_exceeded
        ? 'over'
        : data.storage_status === 'warning' || data.soft_warning
          ? 'warning'
          : 'ok'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    usageInfo.value = err.response?.data?.error?.message ?? 'Could not load usage.'
    usageStatus.value = ''
  }
}

async function checkHealth(envId?: string) {
  const id = envId || activeEnv.value?.id
  if (!id) return
  healthInfo.value = 'Checking…'
  try {
    const { data } = await customersApi.checkEnvHealth(id)
    healthInfo.value = data.summary || healthLabel(data.health_status)
    if (dash.value) {
      const env = dash.value.environments.find((e) => e.id === id)
      if (env) env.health_status = data.health_status
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    healthInfo.value = err.response?.data?.error?.message ?? 'Health check failed.'
  }
}

async function issueSsl() {
  if (!activeEnv.value) return
  sslMsg.value = 'Turning on secure HTTPS…'
  try {
    const { data } = await customersApi.issueEnvSsl(activeEnv.value.id)
    sslMsg.value =
      data.message ||
      (data.queued
        ? 'Working on it — HTTPS will be ready shortly after your domain points here.'
        : data.success
          ? 'HTTPS is on. Your site is secured.'
          : 'Could not turn on HTTPS yet. Check that your domain points here first.')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    sslMsg.value = err.response?.data?.error?.message ?? 'Could not turn on HTTPS.'
  }
}

async function loadBackups() {
  if (!activeEnv.value) return
  backupMsg.value = 'Loading…'
  try {
    const { data } = await customersApi.listEnvBackups(activeEnv.value.id)
    backups.value = data
    backupMsg.value = data.length ? '' : 'No backups yet.'
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    backupMsg.value = err.response?.data?.error?.message ?? 'Could not load backups.'
  }
}

async function createBackup() {
  if (!activeEnv.value) return
  backupMsg.value = 'Queueing backup…'
  try {
    const { data } = await customersApi.createEnvBackup(activeEnv.value.id)
    backupMsg.value = `Backup ${data.status}. Refresh in a moment.`
    await loadBackups()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    backupMsg.value = err.response?.data?.error?.message ?? 'Backup failed.'
  }
}

async function restoreBackup(id: string) {
  if (!activeEnv.value) return
  if (!confirm('Restore this backup? Current site files will be replaced.')) return
  backupMsg.value = 'Queueing restore…'
  try {
    const { data } = await customersApi.restoreEnvBackup(activeEnv.value.id, id)
    backupMsg.value = data.message
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    backupMsg.value = err.response?.data?.error?.message ?? 'Restore failed.'
  }
}

async function hydrateActiveEnv() {
  if (!activeEnv.value) return
  await Promise.allSettled([loadFiles(), loadUsage(), loadStacks(), loadCron(), loadSsh(), checkHealth()])
}

async function selectEnv(id: string) {
  activeEnvId.value = id
  filePath.value = '.'
  editingFile.value = ''
  fileContent.value = ''
  dbInfo.value = ''
  dbCreds.value = null
  ftpInfo.value = ''
  ftpCreds.value = null
  usageInfo.value = ''
  dnsInfo.value = ''
  dnsData.value = null
  sslMsg.value = ''
  backupMsg.value = ''
  stackMsg.value = ''
  backups.value = []
  await hydrateActiveEnv()
}

async function loadStacks() {
  if (!activeEnv.value) return
  try {
    const { data } = await customersApi.listEnvStacks(activeEnv.value.id)
    stacks.value = data.stacks
    currentStack.value = data.current || null
    if (data.current?.stack && !selectedStack.value) {
      selectedStack.value = String(data.current.stack)
    } else if (!selectedStack.value && stacks.value[0]) {
      selectedStack.value = stacks.value[0].id
    }

    const progress = data.progress
    const status = String(progress?.status || '').toLowerCase()

    if (progress && ['queued', 'running'].includes(status)) {
      stackProgress.value = progress
      stackOutcome.value = 'running'
      stackBusy.value = true
      applyStackProgress(progress)
      const jobId = data.active_job_id || progress.job_id
      if (jobId && !stackPollTimer) startStackPoll(activeEnv.value.id, String(jobId))
      return
    }

    if (progress && status === 'failed') {
      stackProgress.value = progress
      stackOutcome.value = 'error'
      stackBusy.value = false
      stackMsg.value = String(progress.error || progress.message || 'Install failed.')
      return
    }

    if (data.current) {
      stackProgress.value = progress?.status === 'success' ? progress : null
      stackOutcome.value = 'success'
      stackBusy.value = false
      stackMsg.value = String(
        data.current.message ||
          progress?.message ||
          `${data.current.stack_name || data.current.stack || 'Stack'} is installed on this site.`,
      )
      return
    }

    // No current stack and no active/failed job
    if (!stackBusy.value) {
      stackOutcome.value = 'idle'
      stackProgress.value = null
      stackMsg.value = ''
    }
  } catch {
    stacks.value = [
      { id: 'static', name: 'Static site', description: 'HTML starter' },
      { id: 'wordpress', name: 'WordPress', description: 'WordPress + MySQL' },
      { id: 'laravel', name: 'Laravel', description: 'Laravel via Composer' },
      { id: 'nodejs', name: 'Node.js', description: 'Express app' },
    ]
  }
}

async function installStack() {
  if (!activeEnv.value || !selectedStack.value) return
  const pick = stacks.value.find((s) => s.id === selectedStack.value)
  if (pick && pick.one_click === false) {
    stackMsg.value =
      `${pick.name} is included on your pack — deploy it with Files or Git. One-click install is only for Static/PHP, WordPress, Laravel, and Node.js for now.`
    return
  }
  const needsReplace = Boolean(currentStack.value) || fileEntries.value.length > 1
  if (needsReplace && !confirm('Replace existing site files with this stack?')) return
  stopStackPoll()
  stackBusy.value = true
  stackOutcome.value = 'running'
  stackMsg.value = 'Starting install…'
  stackProgress.value = {
    status: 'queued',
    stack: selectedStack.value,
    step: 'prepare',
    label: 'Starting install…',
    percent: 2,
    steps: [],
  }
  try {
    const { data } = await customersApi.installEnvStack(activeEnv.value.id, {
      stack: selectedStack.value,
      replace: true,
    })
    applyStackProgress(data.progress, data.message)
    if (!data.queued) {
      stackBusy.value = false
      stackOutcome.value = 'success'
      stackMsg.value = data.message || 'Stack installed successfully.'
      currentStack.value = data.current || data.result || null
      await loadFiles()
      await loadStacks()
      return
    }
    if (data.job_id) {
      startStackPoll(activeEnv.value.id, data.job_id)
    } else {
      stackBusy.value = false
      stackOutcome.value = 'error'
      stackMsg.value = 'Install was queued but no job id was returned.'
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    stackBusy.value = false
    stackOutcome.value = 'error'
    stackMsg.value = err.response?.data?.error?.message ?? 'Install failed.'
    if (stackProgress.value) {
      stackProgress.value = {
        ...stackProgress.value,
        status: 'failed',
        error: stackMsg.value,
        label: 'Install failed',
      }
    }
  }
}

async function clearStack(dropDatabase = false) {
  if (!activeEnv.value) return
  stopStackPoll()
  stackBusy.value = true
  stackMsg.value = 'Clearing installation…'
  try {
    const { data } = await customersApi.clearEnvStack(activeEnv.value.id, {
      drop_database: Boolean(dropDatabase),
    })
    currentStack.value = null
    stackProgress.value = null
    stackOutcome.value = 'idle'
    stackMsg.value = data.message || 'Installation cleared.'
    await loadFiles()
    await loadStacks()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    stackOutcome.value = 'error'
    stackMsg.value = err.response?.data?.error?.message ?? 'Could not clear installation.'
  } finally {
    stackBusy.value = false
  }
}

async function loadLogs() {
  if (!activeEnv.value) return
  logBusy.value = true
  logMsg.value = ''
  try {
    const { data } = await customersApi.listEnvLogs(activeEnv.value.id)
    logEntries.value = data.entries || []
    logMsg.value = data.message || ''
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    logMsg.value = err.response?.data?.error?.message ?? 'Could not load logs.'
  } finally {
    logBusy.value = false
  }
}

async function loadCron() {
  if (!activeEnv.value) return
  try {
    const { data } = await customersApi.listEnvCron(activeEnv.value.id)
    cronJobs.value = data.jobs
  } catch {
    cronJobs.value = []
  }
}

async function addCron() {
  if (!activeEnv.value) return
  cronBusy.value = true
  cronMsg.value = ''
  try {
    await customersApi.createEnvCron(activeEnv.value.id, {
      schedule: cronSchedule.value,
      command: cronCommand.value,
      enabled: true,
    })
    cronMsg.value = 'Cron job added.'
    await loadCron()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    cronMsg.value = err.response?.data?.error?.message ?? 'Could not add cron job.'
  } finally {
    cronBusy.value = false
  }
}

async function toggleCron(job: { id: string; enabled: boolean }) {
  if (!activeEnv.value) return
  try {
    await customersApi.updateEnvCron(activeEnv.value.id, job.id, { enabled: !job.enabled })
    await loadCron()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    cronMsg.value = err.response?.data?.error?.message ?? 'Update failed.'
  }
}

async function runCron(jobId: string) {
  if (!activeEnv.value) return
  cronMsg.value = 'Running…'
  try {
    const { data } = await customersApi.runEnvCron(activeEnv.value.id, jobId)
    cronMsg.value = `Last run: ${data.last_status || 'done'}${data.last_output ? ` — ${data.last_output.slice(0, 120)}` : ''}`
    await loadCron()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    cronMsg.value = err.response?.data?.error?.message ?? 'Run failed.'
  }
}

async function deleteCron(jobId: string) {
  if (!activeEnv.value) return
  if (!confirm('Delete this cron job?')) return
  try {
    await customersApi.deleteEnvCron(activeEnv.value.id, jobId)
    await loadCron()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    cronMsg.value = err.response?.data?.error?.message ?? 'Delete failed.'
  }
}

function onOpenPanel(next: 'site' | 'billing' | 'ai' | 'support') {
  if (next === 'ai') {
    // Agent is infused in the file editor — send users to Files.
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
  () => [route.name, route.query.panel, route.query.tab] as const,
  ([name, qPanel, qTab]) => {
    if (name !== 'portal-dashboard') return
    let p = typeof qPanel === 'string' ? qPanel : 'home'
    // AI lives inside the file editor now — no standalone account tab.
    if (p === 'ai') {
      p = 'site'
      void router.replace({ name: 'portal-dashboard', query: { panel: 'site', tab: 'files' } })
    }
    // No live hosting yet — keep the account on Overview / Billing only.
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
