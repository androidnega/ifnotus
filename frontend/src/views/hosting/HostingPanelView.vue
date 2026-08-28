<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalSitePanel from '@/components/portal/PortalSitePanel.vue'
import PortalFilesView from '@/views/portal/PortalFilesView.vue'
import { usePortalSiteTools, type PortalSiteTab } from '@/composables/usePortalSiteTools'
import { getApiErrorMessage } from '@/lib/apiError'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import {
  processPct,
  resourceStatusClass,
  resourceStatusLabel,
} from '@/lib/resourceUsage'
import { envCan } from '@/lib/planMatrix'
import { HOSTING_PANEL_TABS } from '@/lib/uiRegistry'
import { hostnameNow, isCustomerCpanelHost, tenantCpanelUrl, tenantMailUrl } from '@/lib/platformHosts'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'

type HostingTab =
  | 'overview'
  | 'files'
  | 'databases'
  | 'domains'
  | 'email'
  | 'transfer'
  | 'stack'
  | 'apps'
  | 'cron'
  | 'backups'
  | 'logs'

const ALL_TABS = HOSTING_PANEL_TABS.map((t) => ({ id: t.id as HostingTab, label: t.label }))

const TABS = computed(() => {
  return ALL_TABS.filter((t) => {
    if (!env.value) return true
    if (t.id === 'files') return envCan(env.value, 'file_manager')
    if (t.id === 'databases') return envCan(env.value, 'db_manage')
    if (t.id === 'email') return envCan(env.value, 'mail')
    if (t.id === 'transfer') return envCan(env.value, 'sftp')
    if (t.id === 'cron') return envCan(env.value, 'cron')
    return true
  })
})

const HOSTING_TO_SITE: Record<Exclude<HostingTab, 'overview' | 'backups'>, PortalSiteTab> = {
  files: 'files',
  databases: 'database',
  domains: 'protect',
  email: 'mail',
  transfer: 'ftp',
  stack: 'stack',
  apps: 'applications',
  cron: 'cron',
  logs: 'logs',
}

const route = useRoute()
const router = useRouter()

const dash = ref<CustomerDashboard | null>(null)
const plans = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')
const tab = ref<HostingTab>('overview')
const panelTheme = ref<{
  active: string
  owned: string[]
  price_ghs: string
  theme: { id: string; name: string; colors: Record<string, string>; compact?: boolean }
  catalog: Array<{
    id: string
    name: string
    description: string
    price_ghs: string
    free?: boolean
    colors: Record<string, string>
  }>
} | null>(null)
const themeBusy = ref(false)
const themeMsg = ref('')

const resolvedEnvId = ref('')
const environmentId = computed(() => {
  if (route.params.environmentId) return String(route.params.environmentId)
  if (resolvedEnvId.value) return resolvedEnvId.value
  const stored = typeof window !== 'undefined' ? localStorage.getItem('tenant_env_id') : ''
  return stored || ''
})

const hostingThemeStyle = computed(() => {
  const colors = panelTheme.value?.theme?.colors
  if (!colors) return undefined
  return {
    '--p-accent': colors.accent,
    '--p-accent-hover': colors.accent_hover || colors.accent,
    '--p-ink': colors.ink,
    '--p-paper': colors.paper,
    '--p-surface': colors.surface,
    '--p-muted': colors.muted,
    '--p-border': colors.border,
    '--ds-accent': colors.accent,
    '--ds-ink': colors.ink,
    '--ds-paper': colors.paper,
    '--ds-surface': colors.surface,
    '--ds-muted': colors.muted,
    '--ds-border': colors.border,
  } as Record<string, string>
})

const themePendingPurchase = ref<string | null>(null)

async function loadPanelTheme() {
  if (!environmentId.value) return
  try {
    const { data } = await customersApi.getPanelTheme(environmentId.value)
    panelTheme.value = data
  } catch {
    panelTheme.value = null
  }
}

function onThemePackClick(themeId: string) {
  if (!panelTheme.value) return
  if (panelTheme.value.owned.includes(themeId)) {
    themePendingPurchase.value = null
    void activatePanelTheme(themeId)
    return
  }
  // Preview / select only — never auto-create an invoice on click.
  themePendingPurchase.value = themeId
  themeMsg.value = ''
}

function cancelThemePurchase() {
  themePendingPurchase.value = null
  themeMsg.value = ''
}

const pendingThemePack = computed(() => {
  if (!panelTheme.value || !themePendingPurchase.value) return null
  return panelTheme.value.catalog.find((p) => p.id === themePendingPurchase.value) || null
})

async function activatePanelTheme(themeId: string) {
  if (!environmentId.value) return
  themeBusy.value = true
  themeMsg.value = ''
  try {
    const { data } = await customersApi.setPanelTheme(environmentId.value, themeId)
    panelTheme.value = data
    themeMsg.value = 'Theme applied to this hosting workspace.'
  } catch (e) {
    themeMsg.value = getApiErrorMessage(e, 'Could not apply theme.')
  } finally {
    themeBusy.value = false
  }
}

async function buyPanelTheme(themeId: string) {
  if (!environmentId.value) return
  themeBusy.value = true
  themeMsg.value = ''
  try {
    const { data } = await customersApi.purchasePanelTheme(environmentId.value, themeId)
    themePendingPurchase.value = null
    themeMsg.value =
      data.message ||
      `Invoice ${data.invoice_number || ''} created for ₵${data.amount}. Pay MoMo then open Billing to finish unlock.`
    if (data.order_id) {
      await router.push({ name: 'portal-invoice', params: { id: data.order_id } })
    }
  } catch (e) {
    themeMsg.value = getApiErrorMessage(e, 'Could not start theme purchase.')
  } finally {
    themeBusy.value = false
  }
}

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
  dbList,
  selectedDbId,
  dbBusy,
  dbActionMsg,
  newDbEngine,
  newDbName,
  ftpInfo,
  ftpCreds,
  sftpCreds,
  sftpInfo,
  sftpKeyInput,
  sftpKeyName,
  sshCreds,
  logEntries,
  logMsg,
  logBusy,
  usagePct,
  usageSnapshot,
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
  cronLimits,
  appCatalog,
  applications,
  appMsg,
  appBusy,
  newAppName,
  newAppFramework,
  newAppGitUrl,
  setActiveEnvId,
  selectEnv,
  hydrateActiveEnv,
  loadFiles,
  openEntry,
  goUp,
  saveFile,
  loadDb,
  loadDbList,
  loadDbSchema,
  loadDbRows,
  runDbQuery,
  createDatabase,
  deleteDatabase,
  resetDbPassword,
  selectDatabase,
  loadFtp,
  loadSsh,
  loadSftp,
  ensureSftp,
  addSftpKey,
  removeSftpKey,
  setSftpKeyInput,
  setSftpKeyName,
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
  loadAppCatalog,
  loadApplications,
  createApplication,
  deployApplication,
  deleteApplication,
  installStack,
  clearStack,
  loadStacks,
  loadLogs,
  loadCron,
  addCron,
  toggleCron,
  runCron,
  deleteCron,
} = usePortalSiteTools(dash, { lockEnvId: environmentId })

const env = computed<CustomerEnvironment | null>(() => activeEnv.value)

const plan = computed(() => {
  const e = env.value
  if (!e || !dash.value) return null
  const sub = dash.value.subscriptions.find((s) => s.id === e.subscription_id)
  if (!sub) return null
  return plans.value.find((p) => p.id === sub.plan_id) || dash.value.plans?.find((p) => p.id === sub.plan_id) || null
})

const spec = computed(() => {
  const e = env.value
  const p = plan.value
  return {
    cpu: formatCpu(e?.cpu_limit ?? p?.cpu_cores ?? 0),
    ram: formatRamGb(e?.ram_limit_gb ?? p?.ram_gb ?? 0),
    disk: e?.storage_limit_gb ?? p?.storage_gb ?? 0,
  }
})

const customPanel = computed(() => {
  const url = env.value?.domain ? tenantCpanelUrl(env.value.domain) : null
  return url ? url.replace(/^https:\/\//, '') : null
})
const customMail = computed(() => {
  const url = env.value?.domain ? tenantMailUrl(env.value.domain) : null
  return url ? url.replace(/^https:\/\//, '').replace(/\/$/, '') : null
})

const subForEnv = computed(() => {
  const e = env.value
  if (!e || !dash.value) return null
  return dash.value.subscriptions.find((s) => s.id === e.subscription_id) || null
})

const statusLabel = computed(() => {
  const s = (env.value?.status || '').toLowerCase()
  if (s === 'active') return 'Active'
  if (!s) return '—'
  return s.charAt(0).toUpperCase() + s.slice(1)
})

const shortEnvId = computed(() => (environmentId.value || '').replace(/-/g, '').slice(0, 8))

const allNavManage = [
  { id: 'files' as HostingTab, label: 'File Manager', icon: 'fa-folder-open' },
  { id: 'databases' as HostingTab, label: 'Databases', icon: 'fa-database' },
  { id: 'domains' as HostingTab, label: 'Domains', icon: 'fa-globe' },
  { id: 'email' as HostingTab, label: 'Email', icon: 'fa-envelope' },
  { id: 'transfer' as HostingTab, label: 'FTP / SFTP', icon: 'fa-exchange-alt' },
  { id: 'stack' as HostingTab, label: 'Stack / Install', icon: 'fa-layer-group' },
  { id: 'apps' as HostingTab, label: 'Applications', icon: 'fa-cubes' },
  { id: 'cron' as HostingTab, label: 'Cron Jobs', icon: 'fa-clock' },
  { id: 'backups' as HostingTab, label: 'Backups', icon: 'fa-cloud-upload-alt' },
  { id: 'logs' as HostingTab, label: 'Logs', icon: 'fa-scroll' },
]

const navManage = computed(() => {
  return allNavManage.filter((t) => {
    if (!env.value) return true
    if (t.id === 'files') return envCan(env.value, 'file_manager')
    if (t.id === 'databases') return envCan(env.value, 'db_manage')
    if (t.id === 'email') return envCan(env.value, 'mail')
    if (t.id === 'transfer') return envCan(env.value, 'sftp')
    if (t.id === 'cron') return envCan(env.value, 'cron')
    return true
  })
})

const allQuickTools = [
  { id: 'files' as HostingTab, label: 'File Manager', tone: 'blue', icon: 'fa-folder-open' },
  { id: 'databases' as HostingTab, label: 'Databases', tone: 'purple', icon: 'fa-database' },
  { id: 'domains' as HostingTab, label: 'Domains', tone: 'green', icon: 'fa-globe' },
  { id: 'email' as HostingTab, label: 'Email', tone: 'orange', icon: 'fa-envelope' },
  { id: 'stack' as HostingTab, label: 'Install stack', tone: 'teal', icon: 'fa-layer-group' },
  { id: 'apps' as HostingTab, label: 'Applications', tone: 'indigo', icon: 'fa-cubes' },
  { id: 'cron' as HostingTab, label: 'Cron Jobs', tone: 'red', icon: 'fa-clock' },
  { id: 'backups' as HostingTab, label: 'Backups', tone: 'sky', icon: 'fa-cloud-upload-alt' },
  { id: 'transfer' as HostingTab, label: 'FTP / SFTP', tone: 'blue', icon: 'fa-exchange-alt' },
  { id: 'logs' as HostingTab, label: 'Logs', tone: 'red', icon: 'fa-scroll' },
]

const quickTools = computed(() => {
  return allQuickTools.filter((t) => {
    if (!env.value) return true
    if (t.id === 'files') return envCan(env.value, 'file_manager')
    if (t.id === 'databases') return envCan(env.value, 'db_manage')
    if (t.id === 'email') return envCan(env.value, 'mail')
    if (t.id === 'transfer') return envCan(env.value, 'sftp')
    if (t.id === 'cron') return envCan(env.value, 'cron')
    return true
  })
})


const cpuPct = computed(() => {
  const p = usageSnapshot.value?.cpu_usage_percent
  return p != null && !Number.isNaN(Number(p)) ? Math.min(100, Number(p)) : null
})
const memPct = computed(() => {
  const p = usageSnapshot.value?.memory_pct
  return p != null && !Number.isNaN(Number(p)) ? Math.min(100, Number(p)) : null
})
const diskPct = computed(() => Math.min(100, Number(usagePct.value) || 0))
const procsPct = computed(() => processPct(usageSnapshot.value))
const rs = computed(() => usageSnapshot.value?.resource_statuses || null)

const siteInitialTab = computed<PortalSiteTab>(() => {
  if (tab.value === 'overview' || tab.value === 'backups' || tab.value === 'files') return ''
  return HOSTING_TO_SITE[tab.value] || 'stack'
})

const showSitePanel = computed(() => tab.value !== 'overview' && tab.value !== 'backups' && tab.value !== 'files')

function resolveTabFromRoute(): HostingTab {
  if (route.name === 'hosting-files' || route.name === 'cpanel-files' || route.meta.hostingTab === 'files' || route.path === '/files') return 'files'
  const pathPart = route.path.replace(/^\//, '').split('/')[0] as HostingTab
  if (TABS.value.some((t) => t.id === pathPart)) return pathPart
  const metaTab = route.meta.hostingTab as HostingTab | undefined
  if (metaTab && TABS.value.some((t) => t.id === metaTab)) return metaTab
  const raw = typeof route.query.tab === 'string' ? route.query.tab : ''
  if (TABS.value.some((t) => t.id === raw)) return raw as HostingTab
  return 'overview'
}

function goTab(next: HostingTab) {
  tab.value = next
  if (isCustomerCpanelHost()) {
    if (next === 'overview') {
      void router.replace('/')
    } else {
      void router.replace(`/${next}`)
    }
    return
  }
  const query = next === 'overview' ? {} : { tab: next }
  void router.replace({ name: 'hosting-panel', params: { environmentId: environmentId.value }, query })
}

function formatBytes(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.dashboard()
    dash.value = data
    plans.value = data.plans?.length ? data.plans : []

    let targetEnvId = environmentId.value
    if (!targetEnvId && isCustomerCpanelHost()) {
      const host = hostnameNow()
      try {
        const { data: aliasData } = await customersApi.resolvePanelAlias(host)
        if (aliasData.environment_id) {
          targetEnvId = aliasData.environment_id
          resolvedEnvId.value = aliasData.environment_id
          localStorage.setItem('tenant_env_id', aliasData.environment_id)
        }
      } catch {
        // Fallback below
      }
    }
    if (!targetEnvId && data.environments.length >= 1) {
      targetEnvId = data.environments[0].id
      resolvedEnvId.value = targetEnvId
      localStorage.setItem('tenant_env_id', targetEnvId)
    }

    const owned = data.environments.find((e) => e.id === targetEnvId)
    if (!owned) {
      error.value = 'This hosting service is not on your account.'
      return
    }
    resolvedEnvId.value = owned.id
    setActiveEnvId(owned.id)
    await hydrateActiveEnv()
    await loadPanelTheme()
  } catch (e: unknown) {
    error.value = getApiErrorMessage(e, 'Could not load hosting panel.')
  } finally {
    loading.value = false
  }
}

watch(
  () => [route.name, route.path, route.query.tab, route.meta.hostingTab] as const,
  () => {
    tab.value = resolveTabFromRoute()
  },
  { immediate: true },
)

watch(environmentId, () => {
  void load()
})

watch(tab, (next) => {
  if (!env.value) return
  if (next === 'backups') void loadBackups()
  if (next === 'apps') {
    void loadAppCatalog()
    void loadApplications()
  }
  if (next === 'stack') void loadStacks()
  if (next === 'cron') void loadCron()
  if (next === 'logs') void loadLogs()
  if (next === 'databases') void loadDbList()
  if (next === 'domains') void loadDns()
  if (next === 'transfer') {
    void loadFtp(true)
    void loadSftp(true)
    void loadSsh()
  }
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div
    class="hp hosting-themed"
    :class="{ compact: panelTheme?.theme?.compact !== false }"
    :data-hosting-theme="panelTheme?.active || 'compact-navy'"
    :style="hostingThemeStyle"
  >
    <aside class="hp-side" aria-label="Hosting navigation">
      <div class="hp-brand">
        <span class="hp-mark">IF</span>
        <span class="hp-word">IFNOTUS</span>
      </div>
      <nav class="hp-nav">
        <p class="hp-nav-label">Main</p>
        <button type="button" class="hp-nav-item" :class="{ on: tab === 'overview' }" @click="goTab('overview')">
          <i class="fas fa-th-large" aria-hidden="true" />
          Overview
        </button>
        <p class="hp-nav-label">Manage</p>
        <button
          v-for="item in navManage"
          :key="item.id"
          type="button"
          class="hp-nav-item"
          :class="{ on: tab === item.id }"
          @click="goTab(item.id)"
        >
          <i class="fas" :class="item.icon" aria-hidden="true" />
          {{ item.label }}
        </button>
        <p class="hp-nav-label">Account</p>
        <a class="hp-nav-item" href="https://ifnotus.space/account?tab=billing" target="_blank" rel="noopener">
          <i class="fas fa-file-invoice-dollar" aria-hidden="true" />
          Billing &amp; Invoices
        </a>
        <a class="hp-nav-item" href="https://ifnotus.space/account/settings" target="_blank" rel="noopener">
          <i class="fas fa-user" aria-hidden="true" />
          Profile
        </a>
        <a class="hp-nav-item" href="https://ifnotus.space/account/support" target="_blank" rel="noopener">
          <i class="fas fa-life-ring" aria-hidden="true" />
          Support
        </a>
      </nav>
      <a class="hp-side-foot" href="https://ifnotus.space/account">← Account portal</a>
    </aside>

    <div class="hp-main">
      <p v-if="loading" class="muted pad">Loading hosting…</p>
      <div v-else-if="error" class="hp-card pad">
        <h2>Unavailable</h2>
        <p class="muted">{{ error }}</p>
        <a class="hp-btn primary" href="https://ifnotus.space/account">Back to account</a>
      </div>

      <template v-else-if="env">
        <section v-if="tab === 'overview'" class="hp-overview">
          <div class="hp-metrics">
            <article class="hp-metric tone-blue">
              <div class="hp-metric-icon"><i class="fas fa-microchip" /></div>
              <div>
                <p class="lbl">CPU Usage <em class="rs-badge" :class="resourceStatusClass(rs?.cpu)">{{ resourceStatusLabel(rs?.cpu) }}</em></p>
                <p class="val">{{ cpuPct != null ? Math.round(cpuPct) + '%' : '—' }}</p>
                <p class="hint">{{ usageSnapshot?.cpu_usage_vcpu != null ? Number(usageSnapshot.cpu_usage_vcpu).toFixed(2) : '—' }} / {{ spec.cpu }}</p>
              </div>
            </article>
            <article class="hp-metric tone-green">
              <div class="hp-metric-icon"><i class="fas fa-memory" /></div>
              <div>
                <p class="lbl">RAM Usage <em class="rs-badge" :class="resourceStatusClass(rs?.memory)">{{ resourceStatusLabel(rs?.memory) }}</em></p>
                <p class="val">{{ memPct != null ? Math.round(memPct) + '%' : '—' }}</p>
                <p class="hint">{{ Math.round(usageSnapshot?.memory_usage_mb || 0) }} / {{ Math.round(usageSnapshot?.memory_limit_mb || 0) || spec.ram }} MB</p>
              </div>
            </article>
            <article class="hp-metric tone-purple">
              <div class="hp-metric-icon"><i class="fas fa-hdd" /></div>
              <div>
                <p class="lbl">Disk Usage <em class="rs-badge" :class="resourceStatusClass(rs?.disk)">{{ resourceStatusLabel(rs?.disk) }}</em></p>
                <p class="val">{{ Math.round(diskPct) }}%</p>
                <p class="hint">{{ usageSnapshot?.storage_used_gb ?? '—' }} / {{ usageSnapshot?.storage_limit_gb ?? spec.disk }} GB</p>
              </div>
            </article>
            <article class="hp-metric tone-orange">
              <div class="hp-metric-icon"><i class="fas fa-network-wired" /></div>
              <div>
                <p class="lbl">Processes <em class="rs-badge" :class="resourceStatusClass(rs?.processes)">{{ resourceStatusLabel(rs?.processes) }}</em></p>
                <p class="val">{{ procsPct != null ? Math.round(procsPct) + '%' : '—' }}</p>
                <p class="hint">{{ usageSnapshot?.process_count ?? '—' }} / {{ usageSnapshot?.process_limit ?? '—' }}</p>
              </div>
            </article>
          </div>

          <div class="hp-grid-3">
            <article class="hp-card">
              <p class="kicker">Hosting Overview</p>
              <dl class="hp-dl">
                <div><dt>Primary domain</dt><dd>
                  <a v-if="env.domain" :href="`https://${env.domain}`" target="_blank" rel="noopener">{{ env.domain }}</a>
                  <span v-else>—</span>
                </dd></div>
                <div><dt>Hosting ID</dt><dd>{{ env.hosting_name || shortEnvId }}</dd></div>
                <div v-if="customPanel"><dt>Control panel</dt><dd>{{ customPanel }}</dd></div>
                <div v-if="customMail"><dt>Mail host</dt><dd>{{ customMail }}</dd></div>
                <div><dt>Status</dt><dd><span v-if="statusLabel === 'Active'" class="hp-status mini ok">{{ statusLabel }}</span><span v-else>{{ statusLabel }}</span></dd></div>
                <div><dt>Created</dt><dd>{{ env.created_at ? new Date(env.created_at).toLocaleDateString() : '—' }}</dd></div>
                <div><dt>Renewal</dt><dd>{{ subForEnv?.expires_at ? new Date(subForEnv.expires_at).toLocaleDateString() : '—' }}</dd></div>
              </dl>
            </article>

            <article class="hp-card">
              <p class="kicker">Stack / Application</p>
              <div class="hp-stack">
                <div class="hp-stack-badge">{{ currentStack?.name || currentStack?.id || 'Ready' }}</div>
                <p class="muted">{{ stackMsg || (currentStack ? 'Installed on this hosting.' : 'No application installed yet — use Apps to deploy.') }}</p>
                <ul class="hp-stack-meta">
                  <li>CPU {{ spec.cpu }}</li>
                  <li>RAM {{ spec.ram }}</li>
                  <li>Disk {{ spec.disk }} GB</li>
                </ul>
                <button type="button" class="hp-btn ghost" @click="goTab(currentStack ? 'apps' : 'stack')">
                  {{ currentStack ? 'Manage Application' : 'Install stack' }}
                </button>
              </div>
            </article>

            <article class="hp-card">
              <p class="kicker">Account / Billing</p>
              <dl class="hp-dl">
                <div><dt>Plan</dt><dd>{{ plan?.name || '—' }}</dd></div>
                <div><dt>Term</dt><dd>{{ subForEnv?.billing_term_months ? `${subForEnv.billing_term_months} months` : 'Monthly' }}</dd></div>
                <div><dt>Next renewal</dt><dd>{{ subForEnv?.expires_at ? new Date(subForEnv.expires_at).toLocaleDateString() : '—' }}</dd></div>
                <div><dt>Status</dt><dd>{{ subForEnv?.status || '—' }}</dd></div>
              </dl>
              <RouterLink class="hp-btn ghost" :to="{ name: 'portal-dashboard', query: { tab: 'billing' } }">Manage Billing</RouterLink>
            </article>
          </div>

          <article class="hp-card">
            <p class="kicker">Quick Tools</p>
            <div class="hp-tools">
              <button
                v-for="tool in quickTools"
                :key="tool.label"
                type="button"
                class="hp-tool"
                :class="`tone-${tool.tone}`"
                @click="goTab(tool.id)"
              >
                <i class="fas" :class="tool.icon" aria-hidden="true" />
                <span>{{ tool.label }}</span>
              </button>
            </div>
          </article>

          <article v-if="panelTheme" class="hp-card">
            <p class="kicker">Hosting look</p>
            <h2>Panel theme</h2>
            <p class="muted">Colors for this hosting workspace only. Compact Navy is free; extras cost ₵{{ panelTheme.price_ghs }}. Selecting a paid theme does not create an invoice until you confirm.</p>
            <div class="theme-grid">
              <button
                v-for="pack in panelTheme.catalog"
                :key="pack.id"
                type="button"
                class="theme-pack"
                :class="{
                  on: panelTheme.active === pack.id,
                  pending: themePendingPurchase === pack.id,
                }"
                :disabled="themeBusy"
                @click="onThemePackClick(pack.id)"
              >
                <span class="swatch" :style="{ background: pack.colors.accent }" />
                <span class="theme-name">{{ pack.name }}</span>
                <span class="theme-meta">
                  <template v-if="panelTheme.owned.includes(pack.id)">
                    {{ panelTheme.active === pack.id ? 'Active' : 'Owned — tap to use' }}
                  </template>
                  <template v-else-if="themePendingPurchase === pack.id">Selected</template>
                  <template v-else>₵{{ pack.price_ghs }} — tap to select</template>
                </span>
              </button>
            </div>
            <div v-if="pendingThemePack" class="theme-confirm">
              <p>
                Buy <strong>{{ pendingThemePack.name }}</strong> for ₵{{ pendingThemePack.price_ghs }}?
                This creates a Mobile Money invoice.
              </p>
              <div class="theme-confirm-actions">
                <button type="button" class="btn-ghost" :disabled="themeBusy" @click="cancelThemePurchase">
                  Cancel
                </button>
                <button
                  type="button"
                  class="btn-primary"
                  :disabled="themeBusy"
                  @click="buyPanelTheme(pendingThemePack.id)"
                >
                  Confirm &amp; create invoice
                </button>
              </div>
            </div>
            <p v-if="themeMsg" class="muted theme-msg">{{ themeMsg }}</p>
          </article>
        </section>

        <section v-else-if="tab === 'backups'" class="hp-card pad">
          <p class="kicker">Backups</p>
          <h2>Restore points</h2>
          <p class="muted">{{ backupMsg || 'Save a restore point of your site files.' }}</p>
          <div class="actions">
            <button type="button" class="hp-btn ghost" @click="loadBackups">Refresh</button>
            <button type="button" class="hp-btn primary" @click="createBackup">Back up now</button>
          </div>
          <ul v-if="backups.length" class="backup-list">
            <li v-for="b in backups" :key="b.id">
              <span>{{ b.status }} · {{ formatBytes(b.file_size) }} · {{ b.filename }}</span>
              <button
                v-if="b.status === 'success'"
                type="button"
                class="hp-btn ghost"
                @click="restoreBackup(b.id)"
              >
                Restore
              </button>
            </li>
          </ul>
        </section>

        <section v-else-if="tab === 'files'" class="hp-files-embed">
          <PortalFilesView
            v-if="env"
            :environment-id="env.id"
            :embedded="true"
            @back="goTab('overview')"
          />
        </section>

        <div v-else-if="showSitePanel" class="hp-embed">
<PortalSitePanel
          hide-subnav
          :environments="[env]"
          :active-env="env"
          :active-plan="plan"
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
          :cron-limits="cronLimits"
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
          :db-list="dbList"
          :selected-db-id="selectedDbId"
          :db-busy="dbBusy"
          :db-action-msg="dbActionMsg"
          :new-db-engine="newDbEngine"
          :new-db-name="newDbName"
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
          :applications="applications"
          :app-catalog="appCatalog"
          :app-msg="appMsg"
          :app-busy="appBusy"
          :new-app-name="newAppName"
          :new-app-framework="newAppFramework"
          :new-app-git-url="newAppGitUrl"
          @select-env="selectEnv"
          @load-files="loadFiles"
          @load-logs="loadLogs"
          @load-applications="() => { loadAppCatalog(); loadApplications() }"
          @create-application="createApplication"
          @deploy-application="deployApplication"
          @delete-application="deleteApplication"
          @update:new-app-name="(v) => (newAppName = v)"
          @update:new-app-framework="(v) => (newAppFramework = v)"
          @update:new-app-git-url="(v) => (newAppGitUrl = v)"
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
          @load-db-list="loadDbList"
          @load-db-schema="loadDbSchema"
          @load-db-rows="loadDbRows"
          @create-database="createDatabase"
          @delete-database="deleteDatabase"
          @reset-db-password="resetDbPassword"
          @select-database="selectDatabase"
          @update:new-db-engine="(v) => (newDbEngine = v)"
          @update:new-db-name="(v) => (newDbName = v)"
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

        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.hp {
  --hp-side: #152238;
  --hp-side-text: #d7dee8;
  --hp-side-muted: #8b97a8;
  --hp-paper: var(--p-paper, #f3f5f8);
  --hp-surface: var(--p-surface, #fff);
  --hp-ink: var(--p-ink, #161a1d);
  --hp-muted: var(--p-muted, #5c6670);
  --hp-border: var(--p-border, #e3e7ec);
  --hp-accent: var(--p-accent, #ff6c2c);
  display: grid;
  grid-template-columns: 15.5rem minmax(0, 1fr);
  min-height: 100vh;
  background: var(--hp-paper);
  color: var(--hp-ink);
  font-family: Figtree, ui-sans-serif, system-ui, sans-serif;
}
.hp-side {
  background: linear-gradient(180deg, #18263f 0%, var(--hp-side) 100%);
  color: var(--hp-side-text);
  padding: 1.1rem 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  position: sticky;
  top: 0;
  height: 100vh;
}
.hp-brand { display: flex; align-items: center; gap: 0.55rem; padding: 0.25rem 0.4rem 0.75rem; }
.hp-mark {
  width: 2rem; height: 2rem; border-radius: 0.45rem;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--hp-accent); color: #fff;
  font-family: Sora, sans-serif; font-size: 0.72rem; font-weight: 800;
}
.hp-word { font-family: Sora, sans-serif; font-weight: 700; letter-spacing: -0.03em; }
.hp-nav { display: flex; flex-direction: column; gap: 0.15rem; flex: 1; overflow: auto; }
.hp-nav-label {
  margin: 0.7rem 0.5rem 0.25rem; font-size: 0.62rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--hp-side-muted);
}
.hp-nav-item {
  display: flex; align-items: center; gap: 0.65rem;
  border: none; background: transparent; color: inherit;
  text-decoration: none; font: inherit; font-size: 0.86rem; font-weight: 600;
  padding: 0.55rem 0.65rem; border-radius: 0.55rem; cursor: pointer; text-align: left;
}
.hp-nav-item i { width: 1rem; opacity: 0.85; }
.hp-nav-item:hover { background: rgb(255 255 255 / 0.06); }
.hp-nav-item.on { background: color-mix(in srgb, var(--hp-accent) 88%, #fff); color: #fff; }
.hp-side-foot {
  margin-top: auto; color: var(--hp-side-muted); text-decoration: none;
  font-size: 0.78rem; font-weight: 600; padding: 0.5rem 0.65rem;
}
.hp-main { min-width: 0; padding: 1rem 1.15rem 2rem; }
.hp-top {
  display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between;
  gap: 0.85rem; margin-bottom: 1rem;
}
.hp-title-row { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; }
.hp-title-row h1 {
  margin: 0; font-family: Sora, sans-serif; font-size: clamp(1.2rem, 2vw, 1.55rem);
  letter-spacing: -0.03em;
}
.hp-status {
  display: inline-flex; align-items: center; padding: 0.18rem 0.55rem;
  border-radius: 999px; font-size: 0.72rem; font-weight: 700;
  background: #e8edf3; color: #445064;
}
.hp-status.ok { background: #dcfce7; color: #166534; }
.hp-status.mini { padding: 0.1rem 0.45rem; }
.hp-meta { margin: 0.35rem 0 0; color: var(--hp-muted); font-size: 0.86rem; display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
.hp-id {
  border: none; background: transparent; color: inherit; font: inherit; cursor: pointer;
  display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 650;
}
.hp-top-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.hp-btn {
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 0.55rem; padding: 0.55rem 0.95rem; font-size: 0.86rem; font-weight: 700;
  text-decoration: none; cursor: pointer; border: 1px solid transparent;
}
.hp-btn.primary { background: var(--hp-accent); color: #fff; border-color: var(--hp-accent); }
.hp-btn.ghost { background: var(--hp-surface); color: var(--hp-ink); border-color: var(--hp-border); }
.hp-overview { display: flex; flex-direction: column; gap: 1rem; }
.hp-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.75rem; }
@media (min-width: 960px) { .hp-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.hp-metric {
  display: flex; gap: 0.75rem; align-items: flex-start;
  background: var(--hp-surface); border: 1px solid var(--hp-border);
  border-radius: 0.9rem; padding: 0.9rem 0.95rem;
}
.hp-metric-icon {
  width: 2.2rem; height: 2.2rem; border-radius: 0.65rem;
  display: grid; place-items: center; color: #fff; flex-shrink: 0;
}
.tone-blue .hp-metric-icon { background: #3b82f6; }
.tone-green .hp-metric-icon { background: #10b981; }
.tone-purple .hp-metric-icon { background: #8b5cf6; }
.tone-orange .hp-metric-icon { background: #f59e0b; }
.hp-metric .lbl { margin: 0; font-size: 0.72rem; font-weight: 700; color: var(--hp-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.hp-metric .val { margin: 0.15rem 0 0; font-size: 1.25rem; font-weight: 800; font-family: Sora, sans-serif; }
.hp-metric .hint { margin: 0.15rem 0 0; font-size: 0.75rem; color: var(--hp-muted); }
.hp-grid-3 { display: grid; grid-template-columns: 1fr; gap: 0.85rem; }
@media (min-width: 960px) { .hp-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.hp-card {
  background: var(--hp-surface); border: 1px solid var(--hp-border);
  border-radius: 0.95rem; padding: 1rem 1.05rem;
}
.pad { padding: 1rem; }
.kicker {
  margin: 0 0 0.65rem; font-size: 0.68rem; font-weight: 800;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--hp-accent);
}
.hp-dl { margin: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.hp-dl > div { display: grid; grid-template-columns: 7.5rem minmax(0, 1fr); gap: 0.5rem; font-size: 0.86rem; }
.hp-dl dt { margin: 0; color: var(--hp-muted); font-weight: 600; }
.hp-dl dd { margin: 0; font-weight: 650; word-break: break-word; }
.hp-dl a { color: inherit; }
.hp-stack-badge {
  display: inline-flex; padding: 0.35rem 0.7rem; border-radius: 0.55rem;
  background: color-mix(in srgb, var(--hp-accent) 12%, #fff);
  color: var(--hp-accent); font-weight: 800; font-size: 0.9rem; margin-bottom: 0.55rem;
}
.hp-stack-meta { margin: 0.65rem 0 0.85rem; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 0.45rem; }
.hp-stack-meta li {
  padding: 0.25rem 0.55rem; border-radius: 999px; background: #f1f4f8;
  font-size: 0.75rem; font-weight: 650; color: var(--hp-muted);
}
.hp-tools { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.55rem; }
@media (min-width: 720px) { .hp-tools { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.hp-tool {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.45rem; min-height: 5.2rem; border: 1px solid var(--hp-border);
  border-radius: 0.85rem; background: #fafbfc; cursor: pointer; font: inherit; font-weight: 700; font-size: 0.8rem;
}
.hp-tool i {
  width: 2.2rem; height: 2.2rem; border-radius: 0.65rem; display: grid; place-items: center; color: #fff;
}
.hp-tool.tone-blue i { background: #3b82f6; }
.hp-tool.tone-purple i { background: #8b5cf6; }
.hp-tool.tone-green i { background: #10b981; }
.hp-tool.tone-orange i { background: #f59e0b; }
.hp-tool.tone-teal i { background: #14b8a6; }
.hp-tool.tone-sky i { background: #0ea5e9; }
.hp-tool.tone-red i { background: #ef4444; }
.hp-tool.tone-indigo i { background: #6366f1; }
.muted { color: var(--hp-muted); font-size: 0.88rem; line-height: 1.45; }
h2 { margin: 0.2rem 0 0.45rem; font-family: Sora, sans-serif; font-size: 1.1rem; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.85rem; }
.backup-list { list-style: none; margin: 1rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.backup-list li {
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem;
  padding: 0.75rem 0.85rem; border: 1px solid var(--hp-border); border-radius: 0.75rem; font-size: 0.86rem;
}
.theme-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr)); gap: 0.55rem; margin-top: 0.85rem; }
.theme-pack {
  display: flex; flex-direction: column; gap: 0.35rem; text-align: left;
  border: 1px solid var(--hp-border); background: var(--hp-surface); border-radius: 0.7rem;
  padding: 0.7rem 0.75rem; cursor: pointer; color: inherit; font: inherit;
}
.theme-pack.on { border-color: var(--hp-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--hp-accent) 16%, transparent); }
.theme-pack.pending { border-color: var(--hp-accent); background: color-mix(in srgb, var(--hp-accent) 6%, var(--hp-surface)); }
.swatch { width: 100%; height: 0.55rem; border-radius: 999px; }
.theme-name { font-size: 0.86rem; font-weight: 700; }
.theme-meta { font-size: 0.75rem; color: var(--hp-muted); }
.theme-confirm {
  margin-top: 0.85rem; padding: 0.85rem 0.9rem; border-radius: 0.75rem;
  border: 1px solid var(--hp-border); background: color-mix(in srgb, var(--hp-accent) 5%, #fff);
}
.theme-confirm p { margin: 0; font-size: 0.88rem; line-height: 1.45; }
.theme-confirm-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.7rem; }
.theme-msg { margin-top: 0.65rem; }
.hp-embed { min-width: 0; }
@media (max-width: 860px) {
  .hp { grid-template-columns: 1fr; }
  .hp-side { position: relative; height: auto; }
}
.rs-badge {
  font-style: normal;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-left: 0.25rem;
  padding: 0.08rem 0.32rem;
  border-radius: 999px;
  vertical-align: middle;
}
.rs-enforced { background: #dcfce7; color: #166534; }
.rs-reported { background: #dbeafe; color: #1e40af; }
.rs-monitored { background: #fef3c7; color: #92400e; }
.rs-allocated { background: #f3f4f6; color: #4b5563; }
</style>
