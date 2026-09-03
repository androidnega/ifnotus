<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalSitePanel from '@/components/portal/PortalSitePanel.vue'
import PortalFilesView from '@/views/portal/PortalFilesView.vue'
import PortalAiPanel from '@/components/ai/PortalAiPanel.vue'
import PortalDomainTools from '@/components/portal/PortalDomainTools.vue'
import PortalTerminalPanel from '@/components/portal/PortalTerminalPanel.vue'
import { usePortalSiteTools, type PortalSiteTab } from '@/composables/usePortalSiteTools'
import { getApiErrorMessage } from '@/lib/apiError'
import { formatCpu, formatRamGb } from '@/lib/planResources'

function formatRamFromMb(mb: number): string {
  if (!Number.isFinite(mb) || mb <= 0) return '—'
  if (mb >= 1024) {
    const gb = mb / 1024
    const nice = Number.isInteger(gb) ? String(gb) : String(Number(gb.toFixed(2)))
    return `${nice} GB`
  }
  return `${Math.round(mb)} MB`
}
import {
  processPct,
  resourceStatusClass,
  resourceStatusLabel,
} from '@/lib/resourceUsage'
import { envCan } from '@/lib/planMatrix'
import { HOSTING_PANEL_TABS } from '@/lib/uiRegistry'
import { isCustomerCpanelHost, isStaffPanelHost, isTenantPanelHost, isTenantSubdomainHost, tenantCpanelUrl, tenantMailUrl, staffPanelHref } from '@/lib/platformHosts'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'

type HostingTab =
  | 'overview'
  | 'files'
  | 'databases'
  | 'domains'
  | 'email'
  | 'transfer'
  | 'terminal'
  | 'stack'
  | 'apps'
  | 'cron'
  | 'backups'
  | 'logs'
  | 'ai'
  | 'git'

const ALL_TABS = HOSTING_PANEL_TABS.map((t) => ({ id: t.id as HostingTab, label: t.label }))

const TABS = computed(() => {
  return ALL_TABS.filter((t) => {
    if (!env.value) return true
    if (t.id === 'files') return envCan(env.value, 'file_manager')
    if (t.id === 'databases') return envCan(env.value, 'db_manage')
    if (t.id === 'email') return envCan(env.value, 'mail')
    if (t.id === 'transfer') return envCan(env.value, 'sftp')
    if (t.id === 'cron') return envCan(env.value, 'cron')
    if (t.id === 'terminal') {
      const mode = String(env.value?.capabilities?.ssh_mode || '')
      return ['limited', 'jail', 'root'].includes(mode)
    }
    return true
  })
})

const HOSTING_TO_SITE: Partial<Record<HostingTab, PortalSiteTab>> = {
  files: 'files',
  databases: 'database',
  domains: 'protect',
  email: 'mail',
  transfer: 'ftp',
  stack: 'stack',
  apps: 'applications',
  cron: 'cron',
  logs: 'logs',
  git: 'git',
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
const cacheBusy = ref(false)
const cacheMsg = ref('')

const resolvedEnvId = ref('')
const environmentId = computed(() => {
  if (route.params.environmentId) return String(route.params.environmentId)
  if (resolvedEnvId.value) return resolvedEnvId.value
  const stored = typeof window !== 'undefined' ? localStorage.getItem('tenant_env_id') : ''
  return stored || ''
})

const previewThemeId = ref<string | null>(null)
const themePendingPurchase = ref<string | null>(null)

const effectiveTheme = computed(() => {
  if (previewThemeId.value && panelTheme.value) {
    const found = panelTheme.value.catalog.find((p) => p.id === previewThemeId.value)
    if (found) return found
  }
  return panelTheme.value?.theme || null
})

const effectiveThemeId = computed(() => {
  return previewThemeId.value || panelTheme.value?.active || 'compact-navy'
})

const isPreviewActive = computed(() => {
  return Boolean(
    previewThemeId.value &&
      panelTheme.value &&
      !panelTheme.value.owned.includes(previewThemeId.value) &&
      previewThemeId.value !== panelTheme.value.active,
  )
})

const hostingThemeStyle = computed(() => {
  const colors = effectiveTheme.value?.colors as Record<string, string> | undefined
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
    '--hp-accent': colors.accent,
    '--hp-paper': colors.paper,
    '--hp-surface': colors.surface,
    '--hp-ink': colors.ink,
    '--hp-muted': colors.muted,
    '--hp-border': colors.border,
    '--hp-side-start': colors.sidebar_start || '#18263f',
    '--hp-side-end': colors.sidebar_end || '#152238',
    '--hp-side-text': colors.sidebar_text || '#d7dee8',
    '--hp-side-muted': colors.sidebar_muted || '#8b97a8',
  } as Record<string, string>
})

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
    previewThemeId.value = null
    themePendingPurchase.value = null
    void activatePanelTheme(themeId)
    return
  }
  // Immediately apply live preview to the whole cPanel system for the user to test-drive!
  previewThemeId.value = themeId
  themePendingPurchase.value = themeId
  themeMsg.value = ''
}

function cancelThemePurchase() {
  previewThemeId.value = null
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
    previewThemeId.value = null
    themePendingPurchase.value = null
    themeMsg.value = 'Theme applied and saved to this hosting workspace.'
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
    previewThemeId.value = null
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

async function clearSiteCache() {
  if (!environmentId.value || cacheBusy.value) return
  cacheBusy.value = true
  cacheMsg.value = ''
  try {
    const { data } = await customersApi.clearEnvCache(environmentId.value)
    cacheMsg.value = data.message || 'Site cache cleared.'
  } catch (e) {
    cacheMsg.value = getApiErrorMessage(e, 'Could not clear site cache.')
  } finally {
    cacheBusy.value = false
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
  newDbUser,
  newDbPassword,
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
  newAppRuntimeVersion,
  newAppGitUrl,
  newAppPythonModule,
  newAppPythonObject,
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
  importDatabaseSql,
  backupDatabase,
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
  gitStatus,
  gitBusy,
  gitMsg,
  gitCloneUrl,
  gitCloneBranch,
  loadGitStatus,
  cloneGitRepo,
  pullGitRepo,
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
  // Prefer live enforced MemoryHigh/Max from usage snapshot when available.
  const liveMb = usageSnapshot.value?.memory_limit_mb
  const ram =
    liveMb && liveMb > 0
      ? formatRamFromMb(liveMb)
      : formatRamGb(e?.ram_limit_gb ?? p?.ram_gb ?? 0)
  return {
    cpu: formatCpu(e?.cpu_limit ?? p?.cpu_cores ?? 0),
    ram,
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
const terminalEnabled = computed(() => {
  const mode = String(env.value?.capabilities?.ssh_mode || '')
  return ['limited', 'jail', 'root'].includes(mode)
})

const allNavManage = [
  { id: 'files' as HostingTab, label: 'File Manager', icon: 'fa-folder-open' },
  { id: 'databases' as HostingTab, label: 'Databases', icon: 'fa-database' },
  { id: 'domains' as HostingTab, label: 'Domains & DNS', icon: 'fa-globe' },
  { id: 'email' as HostingTab, label: 'Email Accounts', icon: 'fa-envelope-open-text' },
  { id: 'transfer' as HostingTab, label: 'FTP / SFTP', icon: 'fa-network-wired' },
  { id: 'terminal' as HostingTab, label: 'Terminal', icon: 'fa-terminal' },
  { id: 'stack' as HostingTab, label: 'One-Click Stacks', icon: 'fa-layer-group' },
  { id: 'apps' as HostingTab, label: 'Applications', icon: 'fa-cubes' },
  { id: 'ai' as HostingTab, label: 'AI Engineer', icon: 'fa-wand-magic-sparkles' },
  { id: 'cron' as HostingTab, label: 'Scheduled Tasks', icon: 'fa-clock' },
  { id: 'backups' as HostingTab, label: 'Backups & Snapshots', icon: 'fa-cloud-arrow-up' },
  { id: 'logs' as HostingTab, label: 'Server Logs', icon: 'fa-scroll' },
]

const navManage = computed(() => {
  return allNavManage.filter((t) => {
    if (!env.value) return true
    if (t.id === 'files') return envCan(env.value, 'file_manager')
    if (t.id === 'databases') return envCan(env.value, 'db_manage')
    if (t.id === 'email') return envCan(env.value, 'mail')
    if (t.id === 'transfer') return envCan(env.value, 'sftp')
    if (t.id === 'cron') return envCan(env.value, 'cron')
    if (t.id === 'terminal') return terminalEnabled.value
    return true
  })
})

const allQuickTools = [
  { id: 'files' as HostingTab, label: 'File Manager', tone: 'blue', icon: 'fa-folder-open' },
  { id: 'databases' as HostingTab, label: 'Databases', tone: 'purple', icon: 'fa-database' },
  { id: 'domains' as HostingTab, label: 'Domains', tone: 'green', icon: 'fa-globe' },
  { id: 'email' as HostingTab, label: 'Email', tone: 'orange', icon: 'fa-envelope' },
  { id: 'terminal' as HostingTab, label: 'Terminal', tone: 'slate', icon: 'fa-terminal' },
  { id: 'ai' as HostingTab, label: 'AI Engineer', tone: 'purple', icon: 'fa-wand-magic-sparkles' },
  { id: 'stack' as HostingTab, label: 'Install stack', tone: 'teal', icon: 'fa-layer-group' },
  { id: 'apps' as HostingTab, label: 'Applications', tone: 'indigo', icon: 'fa-cubes' },
  { id: 'cron' as HostingTab, label: 'Cron Jobs', tone: 'red', icon: 'fa-clock' },
  { id: 'git' as HostingTab, label: 'Git Deploy', tone: 'orange', icon: 'fa-code-branch' },
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
    if (t.id === 'git') return envCan(env.value, 'git')
    if (t.id === 'terminal') return terminalEnabled.value
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
  if (tab.value === 'overview' || tab.value === 'backups' || tab.value === 'files' || tab.value === 'domains' || tab.value === 'ai') return ''
  return HOSTING_TO_SITE[tab.value] || 'stack'
})

const showSitePanel = computed(
  () => tab.value !== 'overview' && tab.value !== 'backups' && tab.value !== 'files' && tab.value !== 'domains' && tab.value !== 'ai',
)

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
  if (next === 'files') {
    if (isTenantPanelHost()) {
      window.open('/files', '_blank')
    } else if (environmentId.value) {
      window.open(`/hosting/${encodeURIComponent(environmentId.value)}/files`, '_blank')
    } else {
      window.open('/files', '_blank')
    }
    return
  }
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

    let owned = data.environments.find((e) => e.id === targetEnvId)
    if (!owned && targetEnvId) {
      try {
        const { data: envData } = await customersApi.getEnvironment(targetEnvId)
        if (envData && envData.id) {
          owned = envData
          if (dash.value) {
            dash.value.environments = [...(dash.value.environments || []), envData]
          }
        }
      } catch {
        // Fallback
      }
    }
    if (!owned) {
      error.value = 'This hosting service is not on your account.'
      return
    }
    resolvedEnvId.value = owned.id
    setActiveEnvId(owned.id)
    await hydrateActiveEnv()
    await loadPanelTheme()
    if (tab.value === 'stack') void loadStacks()
    if (tab.value === 'apps') {
      void loadAppCatalog()
      void loadApplications()
    }
    if (tab.value === 'backups') void loadBackups()
    if (tab.value === 'databases') void loadDbList()
    if (tab.value === 'domains') void loadDns()
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

const isCollapsed = ref(typeof window !== 'undefined' && localStorage.getItem('hp_sidebar_collapsed') === 'true')

const errorBackHref = computed(() =>
  isStaffPanelHost() ? staffPanelHref('/panel') : 'https://ifnotus.space/account',
)
const errorBackLabel = computed(() => (isStaffPanelHost() ? 'staff panel' : 'account'))

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
  try {
    localStorage.setItem('hp_sidebar_collapsed', String(isCollapsed.value))
  } catch {
    // ignore
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div
    class="hp hosting-themed"
    :class="{
      compact: Boolean((effectiveTheme as any)?.compact !== false),
      'sidebar-collapsed': isCollapsed,
      'is-standalone-files': tab === 'files',
    }"
    :data-hosting-theme="effectiveThemeId"
    :style="hostingThemeStyle"
  >
    <aside v-if="tab !== 'files'" class="hp-side" :class="{ collapsed: isCollapsed }" aria-label="Hosting navigation">
      <div class="hp-brand">
        <div class="hp-brand-main">
          <span class="hp-mark">IF</span>
          <div v-if="!isCollapsed" class="hp-brand-info">
            <span class="hp-word">fPanel</span>
          </div>
        </div>
        <button
          type="button"
          class="hp-collapse-btn"
          :title="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          :aria-label="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="toggleCollapse"
        >
          <i class="fas" :class="isCollapsed ? 'fa-angles-right' : 'fa-angles-left'" />
        </button>
      </div>

      <nav class="hp-nav">
        <p v-if="!isCollapsed" class="hp-nav-label">Core</p>
        <button
          type="button"
          class="hp-nav-item"
          :class="{ on: tab === 'overview' }"
          :title="isCollapsed ? 'Overview' : undefined"
          @click="goTab('overview')"
        >
          <span class="hp-nav-icon-wrap"><i class="fas fa-gauge-high" aria-hidden="true" /></span>
          <span v-if="!isCollapsed" class="hp-nav-text">Overview</span>
        </button>

        <p v-if="!isCollapsed" class="hp-nav-label">Hosting Tools</p>
        <button
          v-for="item in navManage"
          :key="item.id"
          type="button"
          class="hp-nav-item"
          :class="{ on: tab === item.id }"
          :title="isCollapsed ? item.label : undefined"
          @click="goTab(item.id)"
        >
          <span class="hp-nav-icon-wrap"><i class="fas" :class="item.icon" aria-hidden="true" /></span>
          <span v-if="!isCollapsed" class="hp-nav-text">{{ item.label }}</span>
        </button>
      </nav>

      <a
        class="hp-side-foot"
        href="https://ifnotus.space/account"
        :title="isCollapsed ? 'Account Portal' : undefined"
      >
        <span class="hp-nav-icon-wrap"><i class="fas fa-arrow-up-right-from-square" aria-hidden="true" /></span>
        <span v-if="!isCollapsed" class="hp-foot-text">Account portal</span>
      </a>
    </aside>

    <div class="hp-main">
      <p v-if="loading" class="muted pad">Loading hosting…</p>
      <div v-else-if="error" class="hp-card pad">
        <h2>Unavailable</h2>
        <p class="muted">{{ error }}</p>
        <a class="hp-btn primary" :href="errorBackHref">Back to {{ errorBackLabel }}</a>
      </div>

      <template v-else-if="env">
        <section v-if="tab === 'overview'" class="hp-overview">
          <div class="hp-metrics">
            <article class="hp-metric tone-blue">
              <div class="hp-metric-icon"><i class="fas fa-microchip" /></div>
              <div>
                <p class="lbl"><span>CPU Usage</span> <em class="rs-badge" :class="resourceStatusClass(rs?.cpu)">{{ resourceStatusLabel(rs?.cpu) }}</em></p>
                <p class="val">{{ cpuPct != null ? Math.round(cpuPct) + '%' : '—' }}</p>
                <p class="hint">{{ usageSnapshot?.cpu_usage_vcpu != null ? Number(usageSnapshot.cpu_usage_vcpu).toFixed(2) : '—' }} / {{ spec.cpu }}</p>
              </div>
            </article>
            <article class="hp-metric tone-green">
              <div class="hp-metric-icon"><i class="fas fa-memory" /></div>
              <div>
                <p class="lbl"><span>RAM Usage</span> <em class="rs-badge" :class="resourceStatusClass(rs?.memory)">{{ resourceStatusLabel(rs?.memory) }}</em></p>
                <p class="val">{{ memPct != null ? Math.round(memPct) + '%' : '—' }}</p>
                <p class="hint">
                  {{ Math.round(usageSnapshot?.memory_usage_mb || 0) }}
                  /
                  {{
                    usageSnapshot?.memory_limit_mb
                      ? formatRamFromMb(usageSnapshot.memory_limit_mb)
                      : spec.ram
                  }}
                </p>
              </div>
            </article>
            <article class="hp-metric tone-purple">
              <div class="hp-metric-icon"><i class="fas fa-hdd" /></div>
              <div>
                <p class="lbl"><span>Disk Usage</span> <em class="rs-badge" :class="resourceStatusClass(rs?.disk)">{{ resourceStatusLabel(rs?.disk) }}</em></p>
                <p class="val">{{ Math.round(diskPct) }}%</p>
                <p class="hint">{{ usageSnapshot?.storage_used_gb ?? '—' }} / {{ usageSnapshot?.storage_limit_gb ?? spec.disk }} GB</p>
              </div>
            </article>
            <article class="hp-metric tone-orange">
              <div class="hp-metric-icon"><i class="fas fa-network-wired" /></div>
              <div>
                <p class="lbl"><span>Processes</span> <em class="rs-badge" :class="resourceStatusClass(rs?.processes)">{{ resourceStatusLabel(rs?.processes) }}</em></p>
                <p class="val">{{ procsPct != null ? Math.round(procsPct) + '%' : '—' }}</p>
                <p class="hint">{{ usageSnapshot?.process_count ?? '—' }} / {{ usageSnapshot?.process_limit ?? '—' }}</p>
              </div>
            </article>
          </div>

          <div class="hp-grid-3">
            <!-- Card 1: Hosting Overview -->
            <article class="hp-card overview-detail-card">
              <div class="overview-card-head">
                <div class="overview-card-icon tone-blue">
                  <i class="fas fa-server" />
                </div>
                <div>
                  <p class="kicker">HOSTING</p>
                  <h3 class="overview-card-title">Hosting Overview</h3>
                </div>
              </div>

              <dl class="hp-dl-clean">
                <div class="dl-row">
                  <dt>Primary domain</dt>
                  <dd>
                    <a v-if="env.domain" :href="`https://${env.domain}`" target="_blank" rel="noopener" class="link-domain">
                      {{ env.domain }}
                      <i class="fas fa-external-link-alt mini-icon" />
                    </a>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div class="dl-row">
                  <dt>Hosting ID</dt>
                  <dd>
                    <span class="chip-id">{{ env.hosting_name || shortEnvId }}</span>
                  </dd>
                </div>
                <div v-if="customPanel" class="dl-row">
                  <dt>Control panel</dt>
                  <dd class="text-truncate" :title="customPanel">{{ customPanel }}</dd>
                </div>
                <div v-if="customMail" class="dl-row">
                  <dt>Mail host</dt>
                  <dd class="text-truncate" :title="customMail">{{ customMail }}</dd>
                </div>
                <div class="dl-row">
                  <dt>Status</dt>
                  <dd>
                    <span class="status-chip" :class="statusLabel === 'Active' ? 'active' : 'warn'">
                      <span class="pulse-dot" />
                      {{ statusLabel }}
                    </span>
                  </dd>
                </div>
                <div class="dl-row">
                  <dt>Created</dt>
                  <dd class="text-muted">{{ env.created_at ? new Date(env.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—' }}</dd>
                </div>
                <div class="dl-row">
                  <dt>Renewal</dt>
                  <dd class="text-muted">{{ subForEnv?.expires_at ? new Date(subForEnv.expires_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—' }}</dd>
                </div>
              </dl>
            </article>

            <!-- Card 2: Stack / Application -->
            <article class="hp-card overview-detail-card">
              <div class="overview-card-head">
                <div class="overview-card-icon tone-green">
                  <i class="fas fa-layer-group" />
                </div>
                <div>
                  <p class="kicker">RUNTIME</p>
                  <h3 class="overview-card-title">Stack / Application</h3>
                </div>
              </div>

              <div class="hp-stack-body">
                <div class="stack-hero-box">
                  <div class="stack-status-badge">
                    <span class="badge-dot" />
                    <strong>{{ currentStack?.name || currentStack?.id || 'Ready' }}</strong>
                  </div>
                  <p class="stack-desc">
                    {{ stackMsg || (currentStack ? 'Active runtime detected on isolated disk.' : 'Standard isolated stack ready for web apps.') }}
                  </p>
                </div>

                <div class="stack-specs-grid">
                  <div class="spec-tile">
                    <span class="spec-tile-label">CPU</span>
                    <strong class="spec-tile-val">{{ spec.cpu }}</strong>
                  </div>
                  <div class="spec-tile">
                    <span class="spec-tile-label">RAM</span>
                    <strong class="spec-tile-val">{{ spec.ram }}</strong>
                  </div>
                  <div class="spec-tile">
                    <span class="spec-tile-label">Disk</span>
                    <strong class="spec-tile-val">{{ spec.disk }} GB</strong>
                  </div>
                </div>

                <button type="button" class="btn-card-action" @click="goTab(currentStack ? 'apps' : 'stack')">
                  <i class="fas" :class="currentStack ? 'fa-sliders-h' : 'fa-plus-circle'" />
                  <span>{{ currentStack ? 'Manage Application' : 'Install stack' }}</span>
                </button>

                <button
                  type="button"
                  class="btn-card-action secondary"
                  :disabled="cacheBusy"
                  @click="clearSiteCache"
                >
                  <i class="fas" :class="cacheBusy ? 'fa-spinner fa-spin' : 'fa-broom'" />
                  <span>{{ cacheBusy ? 'Clearing cache…' : 'Clear cache' }}</span>
                </button>
                <p v-if="cacheMsg" class="cache-msg">{{ cacheMsg }}</p>
              </div>
            </article>

            <!-- Card 3: Account / Billing -->
            <article class="hp-card overview-detail-card">
              <div class="overview-card-head">
                <div class="overview-card-icon tone-purple">
                  <i class="fas fa-file-invoice-dollar" />
                </div>
                <div>
                  <p class="kicker">BILLING</p>
                  <h3 class="overview-card-title">Account / Billing</h3>
                </div>
              </div>

              <dl class="hp-dl-clean">
                <div class="dl-row">
                  <dt>Plan</dt>
                  <dd><strong class="plan-name-highlight">{{ plan?.name || 'Personal Hosting' }}</strong></dd>
                </div>
                <div class="dl-row">
                  <dt>Term</dt>
                  <dd>{{ subForEnv?.billing_term_months ? `${subForEnv.billing_term_months} months` : '1 month' }}</dd>
                </div>
                <div class="dl-row">
                  <dt>Next renewal</dt>
                  <dd class="text-muted">{{ subForEnv?.expires_at ? new Date(subForEnv.expires_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—' }}</dd>
                </div>
                <div class="dl-row">
                  <dt>Status</dt>
                  <dd>
                    <span class="status-chip active">
                      <span class="pulse-dot" />
                      {{ subForEnv?.status || 'active' }}
                    </span>
                  </dd>
                </div>
              </dl>

              <div class="card-footer-action">
                <a class="btn-card-action" href="https://ifnotus.space/account?tab=billing" target="_blank" rel="noopener">
                  <i class="fas fa-credit-card" />
                  <span>Manage Billing</span>
                </a>
              </div>
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
            <div class="hp-card-header-flex">
              <div>
                <p class="kicker">Hosting Workspace Appearance</p>
                <h2>Panel Theme Studio</h2>
                <p class="muted">
                  Choose a signature look for this hosting workspace. Click any theme to immediately test-drive and live-preview it across your fPanel. Unowned themes revert upon page refresh unless purchased.
                </p>
              </div>
            </div>

            <!-- Live Preview Banner -->
            <div v-if="isPreviewActive && pendingThemePack" class="theme-live-preview-box">
              <div class="preview-box-main">
                <span class="preview-live-pill"><i class="fas fa-eye" /> Live Preview Active</span>
                <p class="preview-desc">
                  You are test-driving <strong>{{ pendingThemePack.name }}</strong> live across all fPanel views. Refreshing the browser will revert to your active theme.
                </p>
              </div>
              <div class="preview-box-actions">
                <button type="button" class="btn-ghost btn-sm" @click="cancelThemePurchase">
                  Revert to {{ panelTheme.theme?.name || 'Saved' }}
                </button>
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="themeBusy"
                  @click="buyPanelTheme(pendingThemePack.id)"
                >
                  <i class="fas fa-shopping-bag" /> Buy &amp; Unlock (₵{{ pendingThemePack.price_ghs }})
                </button>
              </div>
            </div>

            <div class="theme-grid">
              <button
                v-for="pack in panelTheme.catalog"
                :key="pack.id"
                type="button"
                class="theme-pack"
                :class="{
                  on: panelTheme.active === pack.id && !isPreviewActive,
                  previewing: previewThemeId === pack.id && isPreviewActive,
                }"
                :disabled="themeBusy"
                @click="onThemePackClick(pack.id)"
              >
                <div class="swatch-container">
                  <span class="swatch-accent" :style="{ background: pack.colors.accent }" />
                  <span class="swatch-sidebar" :style="{ background: pack.colors.sidebar_start || pack.colors.accent }" />
                </div>
                <span class="theme-name">{{ pack.name }}</span>
                <span class="theme-meta">
                  <template v-if="panelTheme.owned.includes(pack.id)">
                    <span v-if="panelTheme.active === pack.id && !isPreviewActive" class="badge-active">Active</span>
                    <span v-else class="badge-owned">Owned — tap to use</span>
                  </template>
                  <template v-else-if="previewThemeId === pack.id">
                    <span class="badge-preview">Previewing (tap to buy)</span>
                  </template>
                  <template v-else>
                    <span class="badge-price">₵{{ pack.price_ghs }} · Preview</span>
                  </template>
                </span>
              </button>
            </div>

            <div v-if="pendingThemePack && !isPreviewActive" class="theme-confirm">
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

        <section v-else-if="tab === 'domains'" class="hp-domains-embed">
          <div v-if="loading && !env && !environmentId && !resolvedEnvId" class="hp-ai-loading">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <p>Loading domain management…</p>
          </div>
          <PortalDomainTools
            v-else-if="env?.id || environmentId || resolvedEnvId"
            :environment-id="env?.id || environmentId || resolvedEnvId"
            :can-redirects="env ? envCan(env, 'redirects') : true"
            :can-git="env ? envCan(env, 'git') : true"
            :repos-limit="Number(env?.capabilities?.repos ?? 1)"
            :mailboxes-limit="env?.capabilities?.mailboxes == null ? null : Number(env.capabilities.mailboxes)"
          />
          <div v-else class="hp-ai-loading">
            <p>No hosting environment active on this domain.</p>
          </div>
        </section>

        <section v-else-if="tab === 'ai'" class="hp-ai-embed">
          <div v-if="loading && !env && !environmentId && !resolvedEnvId" class="hp-ai-loading">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <p>Connecting to AI Engineer environment…</p>
          </div>
          <PortalAiPanel
            v-else-if="env?.id || environmentId || resolvedEnvId"
            :environment-id="env?.id || environmentId || resolvedEnvId"
            :domain="env?.domain || undefined"
            mode="files"
          />
          <div v-else class="hp-ai-loading">
            <p>No hosting environment active on this domain.</p>
          </div>
        </section>

        <section v-else-if="tab === 'terminal'" class="hp-terminal-embed">
          <div v-if="loading && !env" class="hp-ai-loading">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <p>Loading terminal…</p>
          </div>
          <PortalTerminalPanel
            v-else-if="env"
            :environment-id="env.id"
            :can-execute="terminalEnabled"
          />
          <div v-else class="hp-ai-loading">
            <p>No hosting environment active on this domain.</p>
          </div>
        </section>

        <div v-else-if="showSitePanel" class="hp-embed">
          <PortalSitePanel
          hide-subnav
          :environments="dash?.environments?.length ? dash.environments : [env]"
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
          :new-db-user="newDbUser"
          :new-db-password="newDbPassword"
          :git-status="gitStatus"
          :git-busy="gitBusy"
          :git-msg="gitMsg"
          :git-clone-url="gitCloneUrl"
          :git-clone-branch="gitCloneBranch"
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
          :new-app-runtime-version="newAppRuntimeVersion"
          :new-app-git-url="newAppGitUrl"
          :new-app-python-module="newAppPythonModule"
          :new-app-python-object="newAppPythonObject"
          @select-env="selectEnv"
          @load-files="loadFiles"
          @load-logs="loadLogs"
          @load-applications="() => { loadAppCatalog(); loadApplications() }"
          @create-application="createApplication"
          @deploy-application="deployApplication"
          @delete-application="deleteApplication"
          @update:new-app-name="(v) => (newAppName = v)"
          @update:new-app-framework="(v) => (newAppFramework = v)"
          @update:new-app-runtime-version="(v) => (newAppRuntimeVersion = v)"
          @update:new-app-git-url="(v) => (newAppGitUrl = v)"
          @update:new-app-python-module="(v) => (newAppPythonModule = v)"
          @update:new-app-python-object="(v) => (newAppPythonObject = v)"
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
          @import-database-sql="importDatabaseSql"
          @backup-database="backupDatabase"
          @update:new-db-engine="(v) => (newDbEngine = v)"
          @update:new-db-name="(v) => (newDbName = v)"
          @update:new-db-user="(v) => (newDbUser = v)"
          @update:new-db-password="(v) => (newDbPassword = v)"
          @load-git-status="loadGitStatus"
          @clone-git-repo="cloneGitRepo"
          @pull-git-repo="pullGitRepo"
          @update:git-clone-url="(v) => (gitCloneUrl = v)"
          @update:git-clone-branch="(v) => (gitCloneBranch = v)"
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
  --hp-side: #111a28;
  --hp-side-text: #cbd5e1;
  --hp-side-muted: #64748b;
  --hp-paper: var(--p-paper, #f1f4f8);
  --hp-surface: var(--p-surface, #ffffff);
  --hp-ink: var(--p-ink, #1e293b);
  --hp-muted: var(--p-muted, #64748b);
  --hp-border: var(--p-border, #cbd5e1);
  --hp-accent: var(--p-accent, #2b4c7e);
  display: grid;
  grid-template-columns: 15.5rem minmax(0, 1fr);
  min-height: 100vh;
  background: var(--hp-paper);
  color: var(--hp-ink);
  font-family: Figtree, ui-sans-serif, system-ui, sans-serif;
  transition: grid-template-columns 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}

.hp.sidebar-collapsed {
  grid-template-columns: 4.8rem minmax(0, 1fr);
}

.hp-side {
  background: linear-gradient(180deg, var(--hp-side-start, #18263f) 0%, var(--hp-side-end, var(--hp-side, #152238)) 100%);
  color: var(--hp-side-text, #d7dee8);
  padding: 1.1rem 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}

.hp-side.collapsed {
  padding: 1.1rem 0.45rem 1rem;
  align-items: center;
}

.hp-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.55rem;
  padding: 0.25rem 0.35rem 0.75rem;
  border-bottom: 1px solid rgb(255 255 255 / 0.08);
}

.hp-side.collapsed .hp-brand {
  justify-content: center;
  padding: 0.25rem 0 0.75rem;
  width: 100%;
}

.hp-brand-main {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}

.hp-brand-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.15;
}

.hp-mark {
  width: 2.15rem;
  height: 2.15rem;
  border-radius: 0.55rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--hp-accent);
  color: #fff;
  font-family: Sora, sans-serif;
  font-size: 0.75rem;
  font-weight: 800;
  flex-shrink: 0;
  box-shadow: 0 2px 8px color-mix(in srgb, var(--hp-accent) 40%, transparent);
}

.hp-word {
  font-family: Sora, sans-serif;
  font-weight: 800;
  letter-spacing: -0.03em;
  font-size: 0.98rem;
  color: #fff;
}

.hp-subword {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--hp-side-muted);
}

.hp-collapse-btn {
  background: rgb(255 255 255 / 0.06);
  border: 1px solid rgb(255 255 255 / 0.1);
  color: var(--hp-side-muted);
  width: 1.85rem;
  height: 1.85rem;
  border-radius: 0.45rem;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.hp-collapse-btn:hover {
  background: rgb(255 255 255 / 0.15);
  color: #fff;
  border-color: rgb(255 255 255 / 0.2);
}

.hp-side.collapsed .hp-collapse-btn {
  margin-top: 0.35rem;
  width: 2rem;
  height: 2rem;
}

.hp-nav {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
}
.hp-nav::-webkit-scrollbar {
  display: none;
}

.hp-side.collapsed .hp-nav {
  align-items: center;
  width: 100%;
}

.hp-nav-label {
  margin: 0.85rem 0.5rem 0.35rem;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--hp-side-muted);
}

.hp-nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: none;
  background: transparent;
  color: var(--hp-side-text, #d7dee8);
  text-decoration: none;
  font: inherit;
  font-size: 0.86rem;
  font-weight: 600;
  padding: 0.58rem 0.75rem;
  border-radius: 0.65rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  width: 100%;
}

.hp-side.collapsed .hp-nav-item {
  justify-content: center;
  padding: 0.6rem;
  width: 2.65rem;
  height: 2.65rem;
  border-radius: 0.65rem;
}

.hp-nav-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.35rem;
  flex-shrink: 0;
  font-size: 0.92rem;
  opacity: 0.85;
  transition: all 0.15s ease;
}

.hp-nav-item:hover {
  background: rgb(255 255 255 / 0.08);
  color: #fff;
}

.hp-nav-item:hover .hp-nav-icon-wrap {
  opacity: 1;
  transform: scale(1.08);
}

.hp-nav-item.on {
  background: var(--hp-accent);
  color: #fff;
  font-weight: 700;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--hp-accent) 40%, transparent);
}

.hp-nav-item.on .hp-nav-icon-wrap {
  opacity: 1;
}

.hp-side-foot {
  margin-top: auto;
  color: var(--hp-side-muted);
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.6rem 0.75rem;
  border-radius: 0.65rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border-top: 1px solid rgb(255 255 255 / 0.08);
  transition: all 0.15s ease;
}

.hp-side.collapsed .hp-side-foot {
  justify-content: center;
  padding: 0.6rem;
  width: 2.65rem;
  height: 2.65rem;
}

.hp-side-foot:hover {
  background: rgb(255 255 255 / 0.08);
  color: #fff;
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
.hp-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.75rem; width: 100%; }
@media (max-width: 1200px) { .hp-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) { .hp-metrics { grid-template-columns: 1fr; } }
.hp-metric {
  display: flex; gap: 0.75rem; align-items: center; min-width: 0;
  background: var(--hp-surface); border: 1px solid var(--hp-border);
  border-radius: 0.9rem; padding: 0.85rem 0.95rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.hp-metric > div { min-width: 0; flex: 1; }
.hp-metric-icon {
  width: 2.2rem; height: 2.2rem; border-radius: 0.65rem;
  display: grid; place-items: center; color: #fff; flex-shrink: 0;
}
.tone-blue .hp-metric-icon { background: #3b82f6; }
.tone-green .hp-metric-icon { background: #10b981; }
.tone-purple .hp-metric-icon { background: #8b5cf6; }
.tone-orange .hp-metric-icon { background: #f59e0b; }
.hp-metric .lbl {
  margin: 0; font-size: 0.68rem; font-weight: 700; color: var(--hp-muted);
  text-transform: uppercase; letter-spacing: 0.03em;
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.2rem 0.35rem;
  min-width: 0;
}
.hp-metric .lbl span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.hp-metric .lbl em.rs-badge {
  font-style: normal;
  font-size: 0.58rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 0.08rem 0.32rem;
  border-radius: 0.25rem;
  flex-shrink: 0;
  line-height: 1.2;
}
.hp-metric .val { margin: 0.15rem 0 0; font-size: 1.25rem; font-weight: 800; font-family: Sora, sans-serif; line-height: 1.2; }
.hp-metric .hint {
  margin: 0.15rem 0 0; font-size: 0.73rem; color: var(--hp-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.hp-grid-3 { display: grid; grid-template-columns: 1fr; gap: 1rem; }
@media (min-width: 960px) { .hp-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }

.overview-detail-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 1.25rem 1.3rem;
  border-radius: 1.1rem;
  background: var(--hp-surface);
  border: 1px solid var(--hp-border);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03), 0 8px 24px rgba(15, 23, 42, 0.03);
}

.overview-card-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid color-mix(in srgb, var(--hp-border) 60%, transparent);
}

.overview-card-head .kicker {
  margin: 0;
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.1em;
}

.overview-card-title {
  margin: 0.15rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--hp-ink);
  letter-spacing: -0.02em;
}

.overview-card-icon {
  width: 2.35rem;
  height: 2.35rem;
  border-radius: 0.65rem;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 0.95rem;
  flex-shrink: 0;
}

.overview-card-icon.tone-blue { background: linear-gradient(135deg, #2563eb, #3b82f6); }
.overview-card-icon.tone-green { background: linear-gradient(135deg, #059669, #10b981); }
.overview-card-icon.tone-purple { background: linear-gradient(135deg, #7c3aed, #8b5cf6); }

.hp-dl-clean {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  flex: 1;
}

.dl-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.65rem;
  font-size: 0.86rem;
}

.dl-row dt {
  margin: 0;
  color: var(--hp-muted);
  font-weight: 500;
  flex-shrink: 0;
}

.dl-row dd {
  margin: 0;
  font-weight: 650;
  color: var(--hp-ink);
  text-align: right;
  word-break: break-all;
}

.link-domain {
  color: var(--hp-accent);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-weight: 700;
}

.link-domain:hover {
  text-decoration: underline;
}

.mini-icon {
  font-size: 0.72rem;
  opacity: 0.8;
}

.chip-id {
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  font-weight: 700;
  background: color-mix(in srgb, var(--hp-accent) 10%, #fff);
  color: var(--hp-accent);
  padding: 0.15rem 0.5rem;
  border-radius: 0.4rem;
  border: 1px solid color-mix(in srgb, var(--hp-accent) 25%, transparent);
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.18rem 0.6rem;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: capitalize;
}

.status-chip.active {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.status-chip.warn {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}

.pulse-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: currentColor;
}

.text-truncate {
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.text-muted {
  color: var(--hp-muted);
  font-weight: 500;
}

.plan-name-highlight {
  color: var(--hp-accent);
  font-weight: 700;
}

.hp-stack-body {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  flex: 1;
  justify-content: space-between;
}

.stack-hero-box {
  background: color-mix(in srgb, var(--hp-surface) 40%, #f8fafc);
  border: 1px solid var(--hp-border);
  border-radius: 0.75rem;
  padding: 0.75rem 0.85rem;
}

.stack-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.2rem 0.55rem;
  background: color-mix(in srgb, var(--hp-accent) 12%, #fff);
  color: var(--hp-accent);
  border-radius: 0.45rem;
  font-size: 0.82rem;
  font-weight: 800;
  margin-bottom: 0.35rem;
}

.badge-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: currentColor;
}

.stack-desc {
  margin: 0;
  font-size: 0.82rem;
  color: var(--hp-muted);
  line-height: 1.4;
}

.stack-specs-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.45rem;
}

.spec-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0.55rem 0.35rem;
  background: color-mix(in srgb, var(--hp-surface) 60%, #f1f5f9);
  border: 1px solid var(--hp-border);
  border-radius: 0.6rem;
  text-align: center;
}

.spec-tile-label {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--hp-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.spec-tile-val {
  margin-top: 0.15rem;
  font-size: 0.86rem;
  font-weight: 800;
  color: var(--hp-ink);
}

.btn-card-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.6rem 1rem;
  border-radius: 0.65rem;
  background: color-mix(in srgb, var(--hp-surface) 50%, #f8fafc);
  border: 1px solid var(--hp-border);
  color: var(--hp-ink);
  font-weight: 700;
  font-size: 0.84rem;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.15s ease;
  margin-top: auto;
}

.btn-card-action:hover {
  border-color: var(--hp-accent);
  color: var(--hp-accent);
  background: color-mix(in srgb, var(--hp-accent) 6%, #fff);
  transform: translateY(-1px);
}

.btn-card-action.secondary {
  margin-top: 0.65rem;
}

.btn-card-action:disabled {
  opacity: 0.65;
  cursor: wait;
  transform: none;
}

.cache-msg {
  margin: 0.5rem 0 0;
  font-size: 0.78rem;
  color: var(--hp-muted);
  line-height: 1.4;
}

.card-footer-action {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid color-mix(in srgb, var(--hp-border) 60%, transparent);
}

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
.theme-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: 0.75rem; margin-top: 1rem; }
.theme-pack {
  display: flex; flex-direction: column; gap: 0.45rem; text-align: left;
  border: 1px solid var(--hp-border); background: var(--hp-surface); border-radius: 0.85rem;
  padding: 0.85rem 0.95rem; cursor: pointer; color: inherit; font: inherit;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}
.theme-pack:hover {
  transform: translateY(-2px);
  border-color: var(--hp-accent);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}
.theme-pack.on {
  border-color: var(--hp-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--hp-accent) 20%, transparent);
}
.theme-pack.previewing {
  border-color: var(--hp-accent);
  background: color-mix(in srgb, var(--hp-accent) 8%, var(--hp-surface));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--hp-accent) 30%, transparent);
}
.swatch-container {
  display: flex;
  height: 0.75rem;
  width: 100%;
  border-radius: 999px;
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.1);
}
.swatch-accent {
  flex: 2;
  height: 100%;
}
.swatch-sidebar {
  flex: 1;
  height: 100%;
}
.theme-name { font-size: 0.9rem; font-weight: 700; color: var(--hp-ink); }
.theme-meta { font-size: 0.75rem; color: var(--hp-muted); display: flex; align-items: center; gap: 0.35rem; }
.badge-active {
  color: var(--hp-accent);
  font-weight: 700;
  background: color-mix(in srgb, var(--hp-accent) 12%, transparent);
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  font-size: 0.7rem;
}
.badge-owned {
  color: #059669;
  font-weight: 600;
  background: rgba(5, 150, 105, 0.1);
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  font-size: 0.7rem;
}
.badge-preview {
  color: #7c3aed;
  font-weight: 700;
  background: rgba(124, 58, 237, 0.12);
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  font-size: 0.7rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.badge-price {
  color: var(--hp-muted);
  font-weight: 600;
}

/* Live Preview notification banner */
.theme-live-preview-box {
  margin-top: 1rem;
  padding: 1rem 1.15rem;
  border-radius: 0.85rem;
  background: linear-gradient(135deg, color-mix(in srgb, var(--hp-accent) 12%, #fff), color-mix(in srgb, var(--hp-accent) 4%, #fff));
  border: 1px solid var(--hp-accent);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.85rem;
  box-shadow: 0 4px 16px color-mix(in srgb, var(--hp-accent) 12%, transparent);
}
.preview-box-main {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
  min-width: 14rem;
}
.preview-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--hp-accent);
  color: #fff;
  font-size: 0.7rem;
  font-weight: 800;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  width: fit-content;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.preview-desc {
  margin: 0;
  font-size: 0.85rem;
  color: var(--hp-ink);
  line-height: 1.4;
}
.preview-box-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

/* ==========================================================================
   Hosting Panel Theme Engine — Unique Visual Identifiers per Theme
   ========================================================================== */

/* Compact Mode Core */
.hp.compact .hp-card {
  padding: 0.85rem 0.95rem;
  border-radius: 0.75rem;
}
.hp.compact .hp-metrics {
  gap: 0.6rem;
}
.hp.compact .hp-metric {
  padding: 0.75rem 0.85rem;
  border-radius: 0.75rem;
}
.hp.compact .hp-metric-icon {
  width: 2rem;
  height: 2rem;
  font-size: 0.85rem;
}
.hp.compact .hp-metric .val {
  font-size: 1.15rem;
}
.hp.compact .hp-tools {
  gap: 0.45rem;
}
.hp.compact .hp-tool {
  min-height: 4.4rem;
  padding: 0.5rem 0.4rem;
  border-radius: 0.65rem;
  font-size: 0.76rem;
}
.hp.compact .hp-tool i {
  width: 1.85rem;
  height: 1.85rem;
  font-size: 0.8rem;
}

/* --------------------------------------------------------------------------
   1. Compact Navy (Default Enterprise) — Crisp, Pale Slate & Soft Contrast
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="compact-navy"] .hp-card,
.hp[data-hosting-theme="default"] .hp-card {
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03), 0 4px 12px rgba(15, 23, 42, 0.02);
  border-color: #cbd5e1;
  background: #ffffff;
}
.hp[data-hosting-theme="compact-navy"] .hp-metric,
.hp[data-hosting-theme="default"] .hp-metric {
  background: #ffffff;
  border: 1px solid #cbd5e1;
}
.hp[data-hosting-theme="compact-navy"] .hp-tool,
.hp[data-hosting-theme="default"] .hp-tool {
  background: #f8fafc;
  border-color: #cbd5e1;
  transition: all 0.15s ease;
}
.hp[data-hosting-theme="compact-navy"] .hp-tool:hover,
.hp[data-hosting-theme="default"] .hp-tool:hover {
  border-color: var(--hp-accent);
  background: #ffffff;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(43, 76, 126, 0.08);
}

/* --------------------------------------------------------------------------
   2. Arctic Cyan (Ocean Panel) — Glacier Ice & Crisp Crystalline Aesthetic
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="ocean-panel"] {
  --hp-accent: #0284c7;
}
.hp[data-hosting-theme="ocean-panel"] .hp-card {
  background: #ffffff;
  border: 1px solid #c8e1f0;
  border-radius: 0.65rem;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.04), 0 1px 2px rgba(2, 132, 199, 0.06);
}
.hp[data-hosting-theme="ocean-panel"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #f0f9ff 100%);
  border: 1px solid #bae6fd;
  border-radius: 0.65rem;
}
.hp[data-hosting-theme="ocean-panel"] .hp-metric-icon {
  background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%) !important;
  border-radius: 50%;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.25);
}
.hp[data-hosting-theme="ocean-panel"] .hp-tool {
  background: #f8fcff;
  border: 1px solid #d0e8f7;
  border-radius: 0.65rem;
  transition: all 0.18s ease;
}
.hp[data-hosting-theme="ocean-panel"] .hp-tool i {
  border-radius: 50%;
  background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%) !important;
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.2);
}
.hp[data-hosting-theme="ocean-panel"] .hp-tool:hover {
  background: #ffffff;
  border-color: #0284c7;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(2, 132, 199, 0.14);
}
.hp[data-hosting-theme="ocean-panel"] .hp-stack-badge {
  background: #e0f2fe;
  color: #0369a1;
  border: 1px solid #bae6fd;
  border-radius: 999px;
}

/* --------------------------------------------------------------------------
   3. Cyber Indigo (Developer Neon Violet / High-Tech IDE)
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="indigo-panel"] {
  --hp-accent: #6366f1;
}
.hp[data-hosting-theme="indigo-panel"] .hp-card {
  background: #ffffff;
  border: 1px solid #dedbf1;
  border-radius: 0.85rem;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.06), 0 1px 3px rgba(99, 102, 241, 0.04);
}
.hp[data-hosting-theme="indigo-panel"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #f5f3ff 100%);
  border: 1px solid #e0e7ff;
  border-radius: 0.85rem;
}
.hp[data-hosting-theme="indigo-panel"] .hp-metric-icon {
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%) !important;
  border-radius: 0.55rem;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
.hp[data-hosting-theme="indigo-panel"] .hp-tool {
  background: #faf8ff;
  border: 1px solid #e5e0fb;
  border-radius: 0.85rem;
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.hp[data-hosting-theme="indigo-panel"] .hp-tool i {
  border-radius: 0.55rem;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
  box-shadow: 0 3px 10px rgba(99, 102, 241, 0.25);
}
.hp[data-hosting-theme="indigo-panel"] .hp-tool:hover {
  background: #ffffff;
  border-color: #6366f1;
  transform: translateY(-3px) scale(1.02);
  box-shadow: 0 8px 22px rgba(99, 102, 241, 0.18);
}
.hp[data-hosting-theme="indigo-panel"] .hp-nav-item.on {
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}

/* --------------------------------------------------------------------------
   4. Emerald Grove (Palm Panel) — Organic Tropical Eco-Minimalist
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="palm-panel"] {
  --hp-accent: #059669;
}
.hp[data-hosting-theme="palm-panel"] .hp-card {
  background: #ffffff;
  border: 1px solid #d1fae5;
  border-radius: 1.25rem;
  box-shadow: 0 4px 16px rgba(5, 150, 105, 0.05);
}
.hp[data-hosting-theme="palm-panel"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #f0fdf4 100%);
  border: 1px solid #bbf7d0;
  border-radius: 1.15rem;
}
.hp[data-hosting-theme="palm-panel"] .hp-metric-icon {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
  border-radius: 1rem 0.35rem 1rem 0.35rem;
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.25);
}
.hp[data-hosting-theme="palm-panel"] .hp-tool {
  background: #f7fdf9;
  border: 1px solid #dcfce7;
  border-radius: 1.15rem;
  transition: all 0.2s ease;
}
.hp[data-hosting-theme="palm-panel"] .hp-tool i {
  border-radius: 0.95rem 0.3rem 0.95rem 0.3rem;
  background: linear-gradient(135deg, #059669 0%, #34d399 100%) !important;
  box-shadow: 0 3px 8px rgba(5, 150, 105, 0.2);
}
.hp[data-hosting-theme="palm-panel"] .hp-tool:hover {
  background: #ffffff;
  border-color: #059669;
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(5, 150, 105, 0.15);
}

/* --------------------------------------------------------------------------
   5. Royal Crimson (Crimson Panel) — Regal Luxury & Gem-Cut Ruby
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="crimson-panel"] {
  --hp-accent: #e11d48;
}
.hp[data-hosting-theme="crimson-panel"] .hp-card {
  background: #ffffff;
  border: 1px solid #fce7ec;
  border-radius: 0.75rem;
  box-shadow: 0 3px 14px rgba(225, 29, 72, 0.05);
}
.hp[data-hosting-theme="crimson-panel"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f2 100%);
  border: 1px solid #fecdd3;
  border-radius: 0.75rem;
}
.hp[data-hosting-theme="crimson-panel"] .hp-metric-icon {
  background: linear-gradient(135deg, #e11d48 0%, #be123c 100%) !important;
  border-radius: 0.65rem;
  box-shadow: 0 4px 14px rgba(225, 29, 72, 0.3);
}
.hp[data-hosting-theme="crimson-panel"] .hp-tool {
  background: #fff8f9;
  border: 1px solid #fee2e6;
  border-radius: 0.75rem;
  transition: all 0.18s ease;
}
.hp[data-hosting-theme="crimson-panel"] .hp-tool i {
  border-radius: 0.65rem;
  background: linear-gradient(135deg, #e11d48 0%, #f43f5e 100%) !important;
  box-shadow: 0 3px 10px rgba(225, 29, 72, 0.22);
}
.hp[data-hosting-theme="crimson-panel"] .hp-tool:hover {
  background: #ffffff;
  border-color: #e11d48;
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(225, 29, 72, 0.16);
}

/* --------------------------------------------------------------------------
   6. Obsidian Gold (Solar Gold) — Prestige Amber-Gold & Contrast Slate
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="solar-gold"] {
  --hp-accent: #d97706;
}
.hp[data-hosting-theme="solar-gold"] .hp-card {
  background: #ffffff;
  border: 1px solid #fef3c7;
  border-radius: 0.85rem;
  box-shadow: 0 4px 18px rgba(217, 119, 6, 0.06);
}
.hp[data-hosting-theme="solar-gold"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #fffbeb 100%);
  border: 1px solid #fde68a;
  border-radius: 0.85rem;
}
.hp[data-hosting-theme="solar-gold"] .hp-metric-icon {
  background: linear-gradient(135deg, #d97706 0%, #fbbf24 100%) !important;
  border-radius: 0.55rem;
  box-shadow: 0 4px 12px rgba(217, 119, 6, 0.35);
  color: #1a160d !important;
}
.hp[data-hosting-theme="solar-gold"] .hp-tool {
  background: #fffdf5;
  border: 1px solid #fef08a;
  border-radius: 0.85rem;
  transition: all 0.18s ease;
}
.hp[data-hosting-theme="solar-gold"] .hp-tool i {
  border-radius: 0.55rem;
  background: linear-gradient(135deg, #d97706 0%, #fbbf24 100%) !important;
  box-shadow: 0 3px 8px rgba(217, 119, 6, 0.25);
  color: #1a160d !important;
}
.hp[data-hosting-theme="solar-gold"] .hp-tool:hover {
  background: #ffffff;
  border-color: #d97706;
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(217, 119, 6, 0.2);
}

/* --------------------------------------------------------------------------
   7. Neon Horizon (Synthwave Neon) — Cyberpunk Magenta & Electric Cyan
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="synthwave-neon"] {
  --hp-accent: #c026d3;
}
.hp[data-hosting-theme="synthwave-neon"] .hp-card {
  background: #ffffff;
  border: 1px solid #fae8ff;
  border-radius: 0.95rem;
  box-shadow: 0 4px 20px rgba(192, 38, 211, 0.07);
}
.hp[data-hosting-theme="synthwave-neon"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #fdf4ff 100%);
  border: 1px solid #f5d0fe;
  border-radius: 0.95rem;
}
.hp[data-hosting-theme="synthwave-neon"] .hp-metric-icon {
  background: linear-gradient(135deg, #c026d3 0%, #06b6d4 100%) !important;
  border-radius: 0.65rem;
  box-shadow: 0 4px 16px rgba(192, 38, 211, 0.35);
}
.hp[data-hosting-theme="synthwave-neon"] .hp-tool {
  background: #fdfaff;
  border: 1px solid #f5d0fe;
  border-radius: 0.95rem;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.hp[data-hosting-theme="synthwave-neon"] .hp-tool i {
  border-radius: 0.65rem;
  background: linear-gradient(135deg, #c026d3 0%, #06b6d4 100%) !important;
  box-shadow: 0 4px 12px rgba(192, 38, 211, 0.28);
}
.hp[data-hosting-theme="synthwave-neon"] .hp-tool:hover {
  background: #ffffff;
  border-color: #c026d3;
  transform: translateY(-3px) scale(1.02);
  box-shadow: 0 8px 24px rgba(192, 38, 211, 0.22);
}

/* --------------------------------------------------------------------------
   8. Ember Studio (Ember Panel) — Volcanic Amber & Studio Terracotta
   -------------------------------------------------------------------------- */
.hp[data-hosting-theme="ember-panel"] {
  --hp-accent: #ff6c2c;
}
.hp[data-hosting-theme="ember-panel"] .hp-card {
  background: #ffffff;
  border: 1px solid #fed7aa;
  border-radius: 0.85rem;
  box-shadow: 0 4px 16px rgba(255, 108, 44, 0.06);
}
.hp[data-hosting-theme="ember-panel"] .hp-metric {
  background: linear-gradient(180deg, #ffffff 0%, #fff7ed 100%);
  border: 1px solid #ffedd5;
  border-radius: 0.85rem;
}
.hp[data-hosting-theme="ember-panel"] .hp-metric-icon {
  background: linear-gradient(135deg, #ff6c2c 0%, #f97316 100%) !important;
  border-radius: 0.55rem;
  box-shadow: 0 4px 12px rgba(255, 108, 44, 0.3);
}
.hp[data-hosting-theme="ember-panel"] .hp-tool {
  background: #fffcf8;
  border: 1px solid #ffedd5;
  border-radius: 0.85rem;
  transition: all 0.18s ease;
}
.hp[data-hosting-theme="ember-panel"] .hp-tool i {
  border-radius: 0.55rem;
  background: linear-gradient(135deg, #ff6c2c 0%, #ea580c 100%) !important;
  box-shadow: 0 3px 8px rgba(255, 108, 44, 0.25);
}
.hp[data-hosting-theme="ember-panel"] .hp-tool:hover {
  background: #ffffff;
  border-color: #ff6c2c;
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(255, 108, 44, 0.18);
}

.theme-confirm {
  margin-top: 0.85rem; padding: 0.85rem 0.9rem; border-radius: 0.75rem;
  border: 1px solid var(--hp-border); background: color-mix(in srgb, var(--hp-accent) 5%, #fff);
}
.theme-confirm p { margin: 0; font-size: 0.88rem; line-height: 1.45; }
.theme-confirm-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.7rem; }
.theme-msg { margin-top: 0.65rem; }
.hp.is-standalone-files {
  display: block;
  grid-template-columns: 1fr !important;
  padding: 0;
  max-width: 100vw;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
}
.hp.is-standalone-files .hp-side {
  display: none !important;
}
.hp.is-standalone-files .hp-main {
  padding: 0 !important;
  height: 100vh;
  max-height: 100vh;
  overflow: hidden;
}
.hp.is-standalone-files .hp-files-embed {
  height: 100vh;
  min-height: 100vh;
  max-height: 100vh;
  border-radius: 0;
}
.hp.is-standalone-files .hp-files-embed :deep(.cpanel-fm) {
  height: 100vh;
  min-height: 100vh;
  max-height: 100vh;
  border-radius: 0;
  border: none;
  box-shadow: none;
}
.hp-embed { min-width: 0; }
.hp-files-embed {
  min-width: 0;
  width: 100%;
  height: calc(100vh - 5rem);
  min-height: 650px;
  display: flex;
  flex-direction: column;
}
.hp-files-embed :deep(.cpanel-fm) {
  height: 100%;
  border-radius: 0.75rem;
  overflow: hidden;
  border: 1px solid var(--hp-border, #cbd5e1);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
}
.hp-ai-embed {
  min-width: 0;
  width: 100%;
  height: calc(100vh - 11rem);
  min-height: 600px;
  max-height: 880px;
  display: flex;
  flex-direction: column;
}
.hp-domains-embed {
  min-width: 0;
  width: 100%;
  background: var(--hp-surface, #ffffff);
  border: 1px solid var(--hp-border, #cbd5e1);
  border-radius: 0.85rem;
  padding: 1.5rem;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
}
.hp-ai-embed :deep(.agent) {
  height: 100%;
  border-radius: 0.85rem;
  border: 1px solid var(--hp-border, #cbd5e1);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
  background: var(--hp-surface, #ffffff);
}
.hp-ai-embed :deep(.thread) {
  flex: 1;
  min-height: 250px;
}
.hp-ai-loading {
  padding: 3.5rem 1.5rem;
  text-align: center;
  color: var(--hp-muted, #64748b);
  background: var(--hp-surface, #ffffff);
  border: 1px solid var(--hp-border, #cbd5e1);
  border-radius: 0.85rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.hp-ai-loading i {
  font-size: 1.75rem;
  color: var(--hp-accent, #2563eb);
}
.hp-ai-loading p {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}
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
