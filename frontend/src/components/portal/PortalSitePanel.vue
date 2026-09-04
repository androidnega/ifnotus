<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { customersApi } from '@/api'
import type { CustomerEnvironment, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import ServiceBrandMark from '@/components/dashboard/ServiceBrandMark.vue'
import PortalMailPanel from '@/components/portal/PortalMailPanel.vue'
import PortalDomainTools from '@/components/portal/PortalDomainTools.vue'
import UiTabBar from '@/components/ui/UiTabBar.vue'
import { envCan, packStacksForDisplay, planMatrix, type FeatureLevel } from '@/lib/planMatrix'
import { SITE_WORKSPACE_TABS } from '@/lib/uiRegistry'
import { isCustomerCpanelHost, tenantCpanelUrl } from '@/lib/platformHosts'
import { getApiErrorMessage } from '@/lib/apiError'

const props = defineProps<{
  environments: CustomerEnvironment[]
  activeEnv: CustomerEnvironment
  /** Domains on this hosting only (primary + addons + subdomains). */
  hostingDomains?: Array<{
    domain_name: string
    domain_type?: string
    is_primary?: boolean
  }>
  /** Enforced resource labels for the Site header (prefer live/policy over stale env rows). */
  displayCpu?: string | null
  displayRam?: string | null
  displayStorageGb?: number | string | null
  activePlan?: HostingPlan | null
  initialTab?: 'files' | 'stack' | 'applications' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | 'git' | ''
  hideSubnav?: boolean
  filePath: string
  fileEntries: Array<{ name: string; path: string; is_dir: boolean; size_bytes?: number | null }>
  fileContent: string
  editingFile: string
  fileMsg: string
  stacks: Array<{
    id: string
    name: string
    description: string
    icon?: string
    level?: string
    one_click?: boolean
    allowed?: boolean
  }>
  selectedStack: string
  currentStack: Record<string, unknown> | null
  stackBusy: boolean
  stackMsg: string
  stackProgress?: {
    status?: string
    stack?: string
    step?: string
    label?: string
    percent?: number
    message?: string | null
    error?: string | null
    steps?: Array<{ id: string; label: string; state: string }>
  } | null
  stackOutcome?: 'idle' | 'running' | 'success' | 'error'
  applications?: Array<{
    id: string
    name: string
    runtime: string
    framework?: string | null
    framework_label?: string | null
    runtime_version?: string | null
    status: string
    port?: number | null
    slug?: string | null
    app_root?: string | null
    app_root_display?: string | null
    uses_site_root?: boolean
    serve_url?: string | null
    log_path?: string | null
    message?: string | null
  }>
  appCatalog?: Array<{
    id: string
    runtime: string
    label: string
    allowed: boolean
    runtime_version?: string
    runtime_versions?: string[]
  }>
  appMsg?: string
  appBusy?: boolean
  newAppName?: string
  newAppFramework?: string
  newAppRuntimeVersion?: string | null
  newAppGitUrl?: string
  newAppPythonModule?: string
  newAppPythonObject?: string
  newAppRootPlacement?: 'apps' | 'home' | 'public_html'
  newAppServeAtDomain?: boolean
  newAppLogPath?: string
  showAppCreateForm?: boolean
  editingAppId?: string | null
  editAppName?: string
  editAppLogPath?: string
  editAppPythonModule?: string
  editAppPythonObject?: string
  editAppServeAtDomain?: boolean
  editAppRuntimeVersion?: string | null
  editAppEnvVars?: Array<{ key: string; value: string }>
  newAppEnvVars?: Array<{ key: string; value: string }>
  cronJobs: Array<{
    id: string
    schedule: string
    command: string
    enabled: boolean
    last_status?: string | null
  }>
  cronSchedule: string
  cronCommand: string
  cronBusy: boolean
  cronMsg: string
  cronLimits?: {
    max_jobs: number
    min_interval_minutes: number
    jobs_used: number
    runs_as?: string | null
    note?: string
  } | null
  dbInfo: string
  dbCreds?: {
    engine?: string | null
    name?: string | null
    username?: string | null
    host?: string | null
    port?: number | null
    password_set?: boolean
    password?: string | null
    remote_access_mode?: string | null
    message?: string | null
    empty?: boolean
    error?: string
  } | null
  dbSchema?: {
    database?: string
    tables?: Array<{ name: string; approx_rows?: number | null }>
  } | null
  dbRows?: {
    columns?: string[]
    rows?: Record<string, unknown>[]
    row_count?: number
    message?: string | null
    truncated?: boolean
  } | null
  dbStudioBusy?: boolean
  dbStudioMsg?: string
  dbSelectedTable?: string
  dbRowOffset?: number
  dbSql?: string
  dbCanWrite?: boolean
  dbList?: Array<{
    id: string
    engine?: string | null
    logical_name?: string | null
    name?: string | null
    username?: string | null
    host?: string | null
    port?: number | null
    password_set?: boolean
    legacy?: boolean
    status?: string | null
    size_mb?: number | null
    message?: string | null
  }>
  selectedDbId?: string
  dbBusy?: boolean
  dbActionMsg?: string
  newDbEngine?: string
  newDbName?: string
  newDbUser?: string
  newDbPassword?: string
  ftpInfo?: string
  ftpCreds?: {
    enabled?: boolean
    username?: string | null
    host?: string
    wordpress_host?: string
    port?: number
    password_set?: boolean
    password?: string | null
    home?: string | null
    connection_type?: string
    sftp_coming_note?: string | null
    hint?: string
    message?: string | null
    error?: string
  } | null
  sftpCreds?: {
    sftp_allowed?: boolean
    enabled?: boolean
    username?: string | null
    host?: string
    shared_ip?: string | null
    port?: number
    password_set?: boolean
    password?: string | null
    connection_type?: string
    shell_access?: boolean
    keys?: Array<{ id: string; name?: string | null; fingerprint?: string | null; created_at?: string | null }>
    command?: string | null
    hint?: string
    message?: string | null
    beta_note?: string | null
    error?: string
  } | null
  sftpInfo?: string
  sftpKeyInput?: string
  sftpKeyName?: string
  sshCreds?: {
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
  } | null
  dnsInfo: string
  dnsData?: {
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
    records?: Array<{ record_type: string; host: string; value: string; ttl?: number }>
    message?: string
    namecheap?: boolean
    includedHostname?: boolean
    nsLive?: boolean | null
    resolves?: boolean | null
    dnsLive?: boolean
    dnsMode?: string | null
    aRecordsLive?: boolean
    cpanelLive?: boolean
    sslReady?: boolean
    statusSummary?: string
    checklist?: Array<{ id: string; label: string; done: boolean; detail?: string }>
    panelHostname?: string | null
    panelUrl?: string | null
    mailHostname?: string | null
    error?: string
  } | null
  sslMsg: string
  backups: Array<{
    id: string
    status: string
    file_size?: number | null
    filename: string
  }>
  backupMsg: string
  logEntries?: Array<{ source: string; message: string }>
  logMsg?: string
  logBusy?: boolean
  gitStatus?: {
    environment_id?: string
    configured?: boolean
    path?: string
    home_display?: string
    repos_limit?: number | null
    branch?: string | null
    commit?: string | null
    remote?: string | null
    dirty?: boolean
    message?: string
    repositories?: Array<{
      id: string
      name: string
      path: string
      path_display: string
      configured: boolean
      branch?: string | null
      commit?: string | null
      commit_full?: string | null
      author?: string | null
      author_email?: string | null
      committed_at?: string | null
      message?: string | null
      remote?: string | null
      dirty?: boolean
      clone_url?: string | null
    }>
  } | null
  gitBusy?: boolean
  gitMsg?: string
  gitCloneUrl?: string
  gitCloneBranch?: string
  gitView?: 'list' | 'create' | 'history'
  gitCloneRemote?: boolean
  gitRepoName?: string
  gitRepoPath?: string
  gitCreateAnother?: boolean
  gitServeAsWebsite?: boolean
  gitExpandedId?: string | null
  gitSearch?: string
  gitHistory?: Array<{ commit: string; committed_at: string; author: string; message: string }>
  gitHistoryPath?: string
}>()

const emit = defineEmits<{
  'update:selectedStack': [string]
  'update:cronSchedule': [string]
  'update:cronCommand': [string]
  'update:fileContent': [string]
  selectEnv: [string]
  loadFiles: []
  goUp: []
  openEntry: [{ name: string; path: string; is_dir: boolean }]
  saveFile: []
  installStack: []
  clearStack: [boolean?]
  addCron: []
  runCron: [string]
  toggleCron: [
    {
      id: string
      schedule: string
      command: string
      enabled: boolean
      last_status?: string | null
    },
  ]
  deleteCron: [string]
  loadDb: [boolean]
  loadDbList: []
  loadDbSchema: []
  loadDbRows: [string, number?]
  runDbQuery: []
  createDatabase: []
  deleteDatabase: [string]
  resetDbPassword: [string]
  selectDatabase: [string]
  importDatabaseSql: [string | null, string]
  backupDatabase: [string]
  'update:newDbEngine': [string]
  'update:newDbName': [string]
  'update:newDbUser': [string]
  'update:newDbPassword': [string]
  updateDbSql: [string]
  loadGitStatus: []
  cloneGitRepo: []
  activateGitWebsite: [string]
  pullGitRepo: [string?]
  loadGitHistory: [string]
  removeGitRepo: [string]
  openHostingTab: [string]
  'update:gitCloneUrl': [string]
  'update:gitCloneBranch': [string]
  'update:gitView': ['list' | 'create' | 'history']
  'update:gitCloneRemote': [boolean]
  'update:gitRepoName': [string]
  'update:gitRepoPath': [string]
  'update:gitCreateAnother': [boolean]
  'update:gitServeAsWebsite': [boolean]
  'update:gitExpandedId': [string | null]
  'update:gitSearch': [string]
  loadFtp: [boolean?]
  ensureFtp: [boolean?]
  loadSftp: [boolean?]
  ensureSftp: [boolean?]
  addSftpKey: []
  removeSftpKey: [string]
  'update:sftpKeyInput': [string]
  'update:sftpKeyName': [string]
  loadSsh: []
  ensureSsh: []
  repairFs: []
  loadDns: []
  ensureDns: []
  attachCustom: [string]
  unassignCustom: [string]
  issueSsl: []
  loadBackups: []
  createBackup: []
  restoreBackup: [string]
  openSupport: []
  loadLogs: []
  loadApplications: []
  createApplication: []
  deployApplication: [string]
  restartApplication: [string]
  stopApplication: [string]
  startApplication: [string]
  refreshApplication: [string]
  editApplication: [string]
  saveEditApplication: []
  cancelEditApplication: []
  deleteApplication: [string]
  'update:newAppName': [string]
  'update:newAppFramework': [string]
  'update:newAppRuntimeVersion': [string]
  'update:newAppGitUrl': [string]
  'update:newAppPythonModule': [string]
  'update:newAppPythonObject': [string]
  'update:newAppRootPlacement': ['apps' | 'home' | 'public_html']
  'update:newAppServeAtDomain': [boolean]
  'update:newAppLogPath': [string]
  'update:showAppCreateForm': [boolean]
  'update:editAppName': [string]
  'update:editAppLogPath': [string]
  'update:editAppPythonModule': [string]
  'update:editAppPythonObject': [string]
  'update:editAppServeAtDomain': [boolean]
  'update:editAppRuntimeVersion': [string]
  addEnvVarRow: ['new' | 'edit']
  removeEnvVarRow: ['new' | 'edit', number]
  updateEnvVarRow: ['new' | 'edit', number, 'key' | 'value', string]
}>()

const siteTab = ref<'files' | 'stack' | 'applications' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | 'git'>('stack')
const appFamily = ref<'python' | 'nodejs' | 'php' | ''>('')
const appHelpPage = ref<'hub' | null>('hub')
const copiedKey = ref('')
const customDomainInput = ref('')
const assignPick = ref('')
const dnsConnectMode = ref<'nameserver' | 'a_record'>('nameserver')

/** Domains attached to this hosting (primary + addon + subdomain) — never other account hostings. */
const siteDomainOptions = computed(() => {
  const fromHosting = (props.hostingDomains || [])
    .map((d) => ({
      name: String(d.domain_name || '').trim().toLowerCase(),
      type: String(d.domain_type || (d.is_primary ? 'primary' : 'addon')).toLowerCase(),
      isPrimary: Boolean(d.is_primary) || String(d.domain_type || '').toLowerCase() === 'primary',
    }))
    .filter((d) => d.name)
  if (fromHosting.length) {
    const seen = new Set<string>()
    return fromHosting.filter((d) => {
      if (seen.has(d.name)) return false
      seen.add(d.name)
      return true
    })
  }
  // Fallback before domain-items load: only the active hosting's primary domain.
  const primary = String(props.activeEnv?.domain || '').trim().toLowerCase()
  return primary ? [{ name: primary, type: 'primary', isPrimary: true }] : []
})

const selectedSiteDomain = ref('')

watch(
  siteDomainOptions,
  (opts) => {
    if (!opts.length) {
      selectedSiteDomain.value = ''
      return
    }
    const primary = opts.find((d) => d.isPrimary)?.name || opts[0]?.name || ''
    // Prefer primary whenever selection is empty or no longer on this hosting.
    if (!selectedSiteDomain.value || !opts.some((d) => d.name === selectedSiteDomain.value)) {
      selectedSiteDomain.value = primary
    }
  },
  { immediate: true },
)

watch(
  () => props.activeEnv?.id,
  () => {
    const primary =
      siteDomainOptions.value.find((d) => d.isPrimary)?.name ||
      String(props.activeEnv?.domain || '').trim().toLowerCase()
    if (primary) selectedSiteDomain.value = primary
  },
)

const displaySiteDomain = computed(
  () => selectedSiteDomain.value || String(props.activeEnv?.domain || '').trim().toLowerCase(),
)

const displayCpuLabel = computed(
  () => props.displayCpu || formatCpu(props.activeEnv?.cpu_limit ?? props.activePlan?.cpu_cores ?? 0),
)
const displayRamLabel = computed(
  () =>
    props.displayRam ||
    formatRamGb(Number(props.activePlan?.ram_gb ?? props.activeEnv?.ram_limit_gb ?? 0)),
)
const displayStorageLabel = computed(
  () => props.displayStorageGb ?? props.activeEnv?.storage_limit_gb ?? props.activePlan?.storage_gb ?? '—',
)

function onSiteDomainChange(domain: string) {
  const name = domain.trim().toLowerCase()
  if (!name) return
  selectedSiteDomain.value = name
}

function confirmClear(dropDatabase = false) {
  const msg = dropDatabase
    ? 'Clear this site’s installation and drop its database? This only affects this environment.'
    : 'Clear this site’s installation files? You can install a fresh stack afterward. This only affects this environment.'
  if (!confirm(msg)) return
  emit('clearStack', dropDatabase)
}

function gitFileManagerPath(pathDisplay: string) {
  const home = String(props.gitStatus?.home_display || '').replace(/\/$/, '')
  if (home && pathDisplay.startsWith(home)) {
    const rel = pathDisplay.slice(home.length).replace(/^\//, '')
    return rel || '.'
  }
  return '.'
}

function openFileManager(path = '.') {
  const id = props.activeEnv?.id
  if (!id) return
  const q = path && path !== '.' ? `?path=${encodeURIComponent(path)}` : ''
  if (isCustomerCpanelHost()) {
    window.open(`/files${q}`, '_blank')
    return
  }
  const customUrl = props.activeEnv?.domain ? tenantCpanelUrl(props.activeEnv.domain, 'files') : null
  if (customUrl) {
    window.open(`${customUrl}${q}`, '_blank')
    return
  }
  window.open(`/hosting/${encodeURIComponent(id)}/files${q}`, '_blank')
}
const showPassword = ref(false)
const showFtpPassword = ref(false)
const showSftpPassword = ref(false)

async function toggleSftpPassword() {
  showSftpPassword.value = !showSftpPassword.value
  if (showSftpPassword.value && !props.sftpCreds?.password) {
    emit('loadSftp', true)
  }
}

watch(
  () => [props.activeEnv.id, props.initialTab] as const,
  ([, tab]) => {
    if (
      tab === 'files' ||
      tab === 'stack' ||
      tab === 'applications' ||
      tab === 'cron' ||
      tab === 'database' ||
      tab === 'protect' ||
      tab === 'ftp' ||
      tab === 'logs' ||
      tab === 'mail' ||
      tab === 'git'
    ) {
      siteTab.value = tab
    } else {
      siteTab.value = 'stack'
    }
  },
  { immediate: true },
)

watch(siteTab, (tab) => {
  if (tab === 'applications') emit('loadApplications')
  if (tab === 'database') {
    showPassword.value = false
    emit('loadDbList')
  }
  if (tab === 'ftp') {
    showFtpPassword.value = false
    showSftpPassword.value = false
    emit('loadFtp', true)
    emit('loadSsh')
  }
  if (tab === 'protect') emit('loadDns')
  if (tab === 'logs') emit('loadLogs')
  if (tab === 'git') emit('loadGitStatus')
})

const RUNTIME_CHIP_HIDE = new Set(['mysql', 'postgres', 'mongodb', 'redis', 'docker'])
const packStacks = computed(() =>
  packStacksForDisplay(props.activePlan).filter((s) => !RUNTIME_CHIP_HIDE.has(s.id)),
)
const ONE_CLICK_STACK_IDS = new Set(['static', 'wordpress', 'laravel', 'nodejs'])

function matrixKeyForInstall(id: string) {
  if (id === 'static') return 'php'
  if (id === 'express') return 'nodejs'
  return id
}

const installStacks = computed(() => {
  const matrix = planMatrix(props.activePlan)
  const envStacks = (props.activeEnv?.capabilities?.stacks || {}) as Record<string, string>
  const on = props.activeEnv?.capabilities?.on || {}
  return (props.stacks || [])
    .map((s) => {
      const key = matrixKeyForInstall(s.id)
      const fromEnv = envStacks[key] || envStacks[s.id]
      const fromMatrix = matrix.stacks[key as keyof typeof matrix.stacks]
      let level = String(fromEnv || s.level || fromMatrix || 'no') as FeatureLevel
      if (on[key] === false || on[s.id] === false) level = 'no'
      if (s.id === 'static' && (matrix.stacks.php === 'yes' || matrix.stacks.php === 'limited' || on.php !== false)) {
        if (level === 'no') level = (matrix.stacks.php as FeatureLevel) || 'yes'
      }
      const allowed = s.allowed !== false && level === 'yes'
      const oneClick = s.one_click === true || (s.one_click !== false && ONE_CLICK_STACK_IDS.has(s.id))
      return { ...s, level, allowed, oneClick }
    })
    .filter((s) => s.level !== 'no')
})

const selectedInstall = computed(() => installStacks.value.find((s) => s.id === props.selectedStack) || installStacks.value[0] || null)
const canFiles = computed(() => envCan(props.activeEnv, 'file_manager'))
const canGit = computed(() => envCan(props.activeEnv, 'git'))
const gitRepos = computed(() => {
  const q = String(props.gitSearch || '').trim().toLowerCase()
  const rows = props.gitStatus?.repositories || []
  if (!q) return rows
  return rows.filter(
    (r) =>
      r.name.toLowerCase().includes(q) ||
      (r.path_display || '').toLowerCase().includes(q) ||
      (r.branch || '').toLowerCase().includes(q),
  )
})
const canCron = computed(() => envCan(props.activeEnv, 'cron'))
const canDb = computed(() => envCan(props.activeEnv, 'db_manage'))
const canMail = computed(() => envCan(props.activeEnv, 'mail'))
const canFtp = computed(() => envCan(props.activeEnv, 'sftp'))
const PYTHON_FRAMEWORKS = [
  { id: 'fastapi', label: 'FastAPI' },
  { id: 'flask', label: 'Flask' },
  { id: 'django', label: 'Django' },
  { id: 'python', label: 'Python (ASGI)' },
] as const
const PYTHON_RUNTIME_VERSIONS = ['3.9', '3.10', '3.11', '3.12', '3.13']
const NODE_FRAMEWORKS = [
  { id: 'express', label: 'Express' },
  { id: 'nodejs', label: 'Node.js' },
] as const
const NODE_RUNTIME_VERSIONS = ['18', '20', '22']
const PHP_FRAMEWORKS = [
  { id: 'laravel', label: 'Laravel' },
  { id: 'php', label: 'PHP' },
] as const
const PHP_RUNTIME_VERSIONS = ['8.1', '8.2', '8.3']

const activeFrameworkList = computed(() => {
  if (appFamily.value === 'nodejs') return NODE_FRAMEWORKS
  if (appFamily.value === 'php') return PHP_FRAMEWORKS
  return PYTHON_FRAMEWORKS
})
const familyFrameworkOptions = computed(() =>
  activeFrameworkList.value.map((fw) => {
    const catalog = (props.appCatalog || []).find((item) => String(item.id).toLowerCase() === fw.id)
    return {
      id: fw.id,
      label: fw.label,
      allowed: catalog ? Boolean(catalog.allowed) : true,
      runtime_versions:
        catalog?.runtime_versions?.length
          ? catalog.runtime_versions
          : appFamily.value === 'nodejs'
            ? NODE_RUNTIME_VERSIONS
            : appFamily.value === 'php'
              ? PHP_RUNTIME_VERSIONS
              : PYTHON_RUNTIME_VERSIONS,
    }
  }),
)
const selectedFamilyFramework = computed(
  () => familyFrameworkOptions.value.find((item) => item.id === props.newAppFramework) || familyFrameworkOptions.value[0] || null,
)

const familyRuntimeOptions = computed(() => {
  const fw = selectedFamilyFramework.value
  const fallback =
    appFamily.value === 'nodejs'
      ? NODE_RUNTIME_VERSIONS
      : appFamily.value === 'php'
        ? PHP_RUNTIME_VERSIONS
        : PYTHON_RUNTIME_VERSIONS
  const versions = fw?.runtime_versions?.length ? fw.runtime_versions : fallback
  const recommended = appFamily.value === 'nodejs' ? '20' : appFamily.value === 'php' ? '8.3' : '3.12'
  return versions.map((version) => ({
    runtime_version: String(version),
    allowed: fw?.allowed ?? true,
    recommended: String(version) === recommended,
  }))
})

watch(
  () => [props.newAppFramework, props.newAppRuntimeVersion, familyRuntimeOptions.value],
  () => {
    if (!familyRuntimeOptions.value.length) return
    const current = String(props.newAppRuntimeVersion || '').trim()
    const hasCurrent = current && familyRuntimeOptions.value.some((o) => String(o.runtime_version) === current)
    if (hasCurrent) return
    const first = familyRuntimeOptions.value.find((o) => o.allowed)?.runtime_version || familyRuntimeOptions.value[0]?.runtime_version
    if (first && first !== current) emit('update:newAppRuntimeVersion', String(first))
  },
  { immediate: true },
)

const pythonApplications = computed(() =>
  (props.applications || []).filter((app) => {
    const runtime = String(app.runtime || '').toLowerCase()
    const framework = String(app.framework || '').toLowerCase()
    return runtime === 'python' || ['python', 'fastapi', 'flask', 'django'].includes(framework)
  }),
)
const nodeApplications = computed(() =>
  (props.applications || []).filter((app) => {
    const runtime = String(app.runtime || '').toLowerCase()
    const framework = String(app.framework || '').toLowerCase()
    return runtime === 'nodejs' || ['nodejs', 'express', 'react', 'vue'].includes(framework)
  }),
)
const phpApplications = computed(() =>
  (props.applications || []).filter((app) => {
    const runtime = String(app.runtime || '').toLowerCase()
    const framework = String(app.framework || '').toLowerCase()
    if (['wordpress', 'static'].includes(framework)) return false
    return runtime === 'php' || ['php', 'laravel'].includes(framework)
  }),
)
const familyApplications = computed(() => {
  if (appFamily.value === 'nodejs') return nodeApplications.value
  if (appFamily.value === 'php') return phpApplications.value
  if (appFamily.value === 'python') return pythonApplications.value
  return []
})

function isPhpManagedApp(app: { runtime?: string | null; framework?: string | null }) {
  const runtime = String(app.runtime || '').toLowerCase()
  const framework = String(app.framework || '').toLowerCase()
  return runtime === 'php' || ['php', 'laravel'].includes(framework)
}

function isPythonManagedApp(app: { runtime?: string | null; framework?: string | null }) {
  const runtime = String(app.runtime || '').toLowerCase()
  const framework = String(app.framework || '').toLowerCase()
  return runtime === 'python' || ['python', 'fastapi', 'flask', 'django'].includes(framework)
}

function openFamilyForApp(app: { runtime?: string | null; framework?: string | null }) {
  const runtime = String(app.runtime || '').toLowerCase()
  const framework = String(app.framework || '').toLowerCase()
  if (runtime === 'nodejs' || ['nodejs', 'express', 'react', 'vue'].includes(framework)) {
    appFamily.value = 'nodejs'
  } else if (runtime === 'php' || ['php', 'laravel'].includes(framework)) {
    appFamily.value = 'php'
  } else if (runtime === 'python' || ['python', 'fastapi', 'flask', 'django'].includes(framework)) {
    appFamily.value = 'python'
  }
  appHelpPage.value = null
}

watch(
  () => props.newAppFramework,
  (fw) => {
    // Blank module/object = auto-detect on create/deploy; do not force framework defaults.
    const allowed = [...PYTHON_FRAMEWORKS, ...NODE_FRAMEWORKS, ...PHP_FRAMEWORKS].some((item) => item.id === fw)
    if (!allowed) {
      emit(
        'update:newAppFramework',
        appFamily.value === 'nodejs' ? 'express' : appFamily.value === 'php' ? 'laravel' : 'fastapi',
      )
    }
  },
  { immediate: true },
)

function openAppFamily(family: 'python' | 'nodejs' | 'php') {
  startAppFamily(family)
}

function startAppFamily(family: 'python' | 'nodejs' | 'php') {
  appHelpPage.value = null
  appFamily.value = family
  emit(
    'update:newAppFramework',
    family === 'nodejs' ? 'express' : family === 'php' ? 'laravel' : 'fastapi',
  )
  emit('update:newAppRuntimeVersion', family === 'nodejs' ? '20' : family === 'php' ? '8.3' : '3.12')
  emit('update:showAppCreateForm', false)
}

function closeAppFamily() {
  appFamily.value = ''
  appHelpPage.value = 'hub'
  emit('update:showAppCreateForm', false)
}

const familyTitle = computed(() => {
  if (appFamily.value === 'nodejs') return 'Node.js Applications'
  if (appFamily.value === 'php') return 'PHP & Laravel Applications'
  return 'Python Applications'
})

const familyBlurb = computed(() => {
  if (appFamily.value === 'nodejs') {
    return 'Active Node apps on this hosting. Create another when you need a new project folder.'
  }
  if (appFamily.value === 'php') {
    return 'Laravel and PHP apps are served by Nginx + PHP-FPM (document root), not the Python/Node process tunnel.'
  }
  return 'Active Python apps on this hosting. Create another when you need a new project folder.'
})

const familyRuntimeLabel = computed(() => {
  if (appFamily.value === 'nodejs') return 'Node version'
  if (appFamily.value === 'php') return 'PHP version'
  return 'Python version'
})

/** Kept for edit panels that still reference python* names for Python apps only. */
const pythonRuntimeOptions = familyRuntimeOptions
const pythonFrameworkOptions = familyFrameworkOptions

const appRootTreePreview = computed(() => {
  const home = props.activeEnv?.hosting_name || 'user'
  const slug = (props.newAppName || '').trim() || 'student-api'
  const placement = props.newAppRootPlacement || 'apps'
  if (placement === 'public_html') {
    return `(/home3/${home})\n  ├── public_html/   ← this app (domain root)\n  ├── apps/\n  └── …`
  }
  if (placement === 'home') {
    return `(/home3/${home})\n  ├── public_html/\n  ├── ${slug}/   ← this app\n  └── …`
  }
  return `(/home3/${home})\n  ├── public_html/\n  ├── apps/\n  │     └── ${slug}/   ← this app\n  └── …`
})

const passengerLogPlaceholder = computed(
  () => `/home3/${props.activeEnv?.hosting_name || 'user'}/logs/passenger.log`,
)

const siteTabItems = computed(() =>
  SITE_WORKSPACE_TABS.filter((t) => {
    if (t.id === 'files') return canFiles.value
    if (t.id === 'git') return canGit.value
    if (t.id === 'cron') return canCron.value
    if (t.id === 'database') return canDb.value
    if (t.id === 'ftp') return canFtp.value
    if (t.id === 'mail') return canMail.value
    return true
  }).map((t) => ({ id: t.id, label: t.label, disabled: false })),
)

type SiteTabId = (typeof SITE_WORKSPACE_TABS)[number]['id']

function onSiteTab(id: string) {
  const hit = siteTabItems.value.find((t) => t.id === id)
  if (hit?.disabled) return
  siteTab.value = id as SiteTabId
}

const dbEngineLabel = computed(() => {
  const e = String(props.dbCreds?.engine || '').toLowerCase()
  if (e === 'mysql' || e === 'mariadb') return 'MySQL'
  if (e === 'postgresql' || e === 'postgres') return 'PostgreSQL'
  if (e === 'mongodb' || e === 'mongo') return 'MongoDB'
  if (e === 'sqlite') return 'SQLite'
  if (e) return e
  return ''
})

const isWordpressInstalled = computed(() => String(props.currentStack?.stack || '') === 'wordpress')

function packLocked(label: string) {
  return `${label} is not on ${props.activePlan?.name || 'this package'}. Open Billing to upgrade.`
}
const route = useRoute()

const activeStackToken = computed(() => {
  const param = route.params?.stackToken
  if (param && typeof param === 'string' && param.trim()) {
    return param.trim()
  }
  if (Array.isArray(param) && param.length) {
    return param.filter(Boolean).join('-')
  }
  const raw = String(props.activeEnv?.id || '48330444-347').replace(/[^a-zA-Z0-9]/g, '')
  return `${raw.slice(0, 8) || '48330444'}-347`
})

const currentStackIcon = computed(() => {
  const id = String(props.currentStack?.stack || '')
  const hit = props.stacks.find((s) => s.id === id)
  return hit?.icon || id || 'php'
})

const showImportModal = ref(false)
const targetImportDbId = ref('')
const importFile = ref<File | null>(null)
const importSqlText = ref('')
const importBusy = ref(false)
const importSuccessMsg = ref('')
const importErrorMsg = ref('')
const connectionSnippetType = ref<'pdo' | 'mysqli' | 'pgsql' | 'laravel' | 'wordpress' | 'nodejs' | 'python'>('pdo')
const showDbPassword = ref(false)
const showCreateDbForm = ref(false)

function openImportModal(dbId?: string) {
  targetImportDbId.value = dbId || props.selectedDbId || ''
  importFile.value = null
  importSqlText.value = ''
  importSuccessMsg.value = ''
  importErrorMsg.value = ''
  showImportModal.value = true
}

function closeImportModal() {
  showImportModal.value = false
  importFile.value = null
  importSqlText.value = ''
  importSuccessMsg.value = ''
  importErrorMsg.value = ''
}

async function onImportFileSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  importFile.value = file
  try {
    const text = await file.text()
    importSqlText.value = text
  } catch {
    /* ignore */
  }
}

async function runDirectSqlImport() {
  const envId = props.activeEnv?.id
  const sql = importSqlText.value.trim()
  if (!envId || !sql) return
  importBusy.value = true
  importSuccessMsg.value = ''
  importErrorMsg.value = ''
  try {
    const { data } = await customersApi.importEnvDatabaseSql(envId, targetImportDbId.value || undefined, sql)
    importSuccessMsg.value = data.message || 'SQL dump imported successfully!'
    emit('loadDbList')
    if (props.selectedDbId) emit('loadDb', true)
  } catch (e: unknown) {
    importErrorMsg.value = getApiErrorMessage(e, 'SQL import failed.')
  } finally {
    importBusy.value = false
  }
}

function generateStrongPassword() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+'
  let pass = ''
  for (let i = 0; i < 20; i++) {
    pass += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  emit('update:newDbPassword', pass)
}

async function openPhpMyAdminDirect(dbId?: string) {
  const id = props.activeEnv?.id
  if (!id) return
  try {
    const target = dbId || props.selectedDbId || undefined
    const { data } = await customersApi.openEnvPhpMyAdmin(id, target)
    window.open(data.url, `ifnotus-pma-${id}`)
  } catch (e) {
    alert(getApiErrorMessage(e, 'Could not launch phpMyAdmin.'))
  }
}

function openBuiltinSqlStudio() {
  const id = props.activeEnv?.id
  if (!id) return
  const href = `https://ifnotus.space/account/database/studio?env=${encodeURIComponent(id)}`
  window.open(href, `ifnotus-sql-${id}`)
}

const connectionSnippet = computed(() => {
  const name = props.dbCreds?.name || 'app_db'
  const user = props.dbCreds?.username || 'app_user'
  const pass = props.dbCreds?.password || 'YourPasswordHere'
  const host = props.dbCreds?.host || 'localhost'
  const isPg = String(props.dbCreds?.engine || '').toLowerCase().includes('postgre')
  const port = props.dbCreds?.port || (isPg ? 5432 : 3306)

  if (connectionSnippetType.value === 'pdo') {
    if (isPg) {
      return `// PHP PDO Connection (PostgreSQL - pdo_pgsql)
$dbHost = '${host}';
$dbName = '${name}';
$dbUser = '${user}';
$dbPass = '${pass}';
$dbPort = ${port};

try {
    $pdo = new PDO("pgsql:host=$dbHost;port=$dbPort;dbname=$dbName", $dbUser, $dbPass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
} catch (PDOException $e) {
    die("PostgreSQL connection failed: " . $e->getMessage());
}`
    }
    return `// PHP PDO Connection (MySQL - pdo_mysql)
$dbHost = '${host}';
$dbName = '${name}';
$dbUser = '${user}';
$dbPass = '${pass}';
$dbPort = ${port};

try {
    $pdo = new PDO("mysql:host=$dbHost;port=$dbPort;dbname=$dbName;charset=utf8mb4", $dbUser, $dbPass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
} catch (PDOException $e) {
    die("MySQL connection failed: " . $e->getMessage());
}`
  }

  if (connectionSnippetType.value === 'mysqli') {
    return `// PHP MySQLi Connection
$dbHost = '${host}';
$dbName = '${name}';
$dbUser = '${user}';
$dbPass = '${pass}';
$dbPort = ${port};

$conn = new mysqli($dbHost, $dbUser, $dbPass, $dbName, $dbPort);
if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
}
$conn->set_charset("utf8mb4");`
  }

  if (connectionSnippetType.value === 'pgsql') {
    return `// PHP pg_connect Connection (PostgreSQL)
$connStr = "host=${host} port=${port} dbname=${name} user=${user} password=${pass}";
$dbconn = pg_connect($connStr);
if (!$dbconn) {
    die("PostgreSQL connection failed: " . pg_last_error());
}`
  }

  if (connectionSnippetType.value === 'laravel') {
    return `# Laravel .env Configuration
DB_CONNECTION=${isPg ? 'pgsql' : 'mysql'}
DB_HOST=${host}
DB_PORT=${port}
DB_DATABASE=${name}
DB_USERNAME=${user}
DB_PASSWORD=${pass}`
  }

  if (connectionSnippetType.value === 'wordpress') {
    return `// WordPress wp-config.php Database Settings
define( 'DB_NAME', '${name}' );
define( 'DB_USER', '${user}' );
define( 'DB_PASSWORD', '${pass}' );
define( 'DB_HOST', '${host}:${port}' );
define( 'DB_CHARSET', 'utf8mb4' );
define( 'DB_COLLATE', '' );`
  }

  if (connectionSnippetType.value === 'nodejs') {
    if (isPg) {
      return `// Node.js (PostgreSQL - pg)
const { Pool } = require('pg');
const pool = new Pool({
  host: '${host}',
  port: ${port},
  database: '${name}',
  user: '${user}',
  password: '${pass}',
});`
    }
    return `// Node.js (MySQL - mysql2)
const mysql = require('mysql2/promise');
const pool = mysql.createPool({
  host: '${host}',
  port: ${port},
  database: '${name}',
  user: '${user}',
  password: '${pass}',
});`
  }

  if (connectionSnippetType.value === 'python') {
    if (isPg) {
      return `# Python (PostgreSQL - psycopg2)
import psycopg2

conn = psycopg2.connect(
    host="${host}",
    port=${port},
    dbname="${name}",
    user="${user}",
    password="${pass}"
)`
    }
    return `# Python (MySQL - pymysql)
import pymysql

conn = pymysql.connect(
    host="${host}",
    port=${port},
    database="${name}",
    user="${user}",
    password="${pass}"
)`
  }

  return ''
})

async function copyValue(key: string, value?: string | null) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    copiedKey.value = key
    setTimeout(() => {
      if (copiedKey.value === key) copiedKey.value = ''
    }, 1600)
  } catch {
    /* ignore */
  }
}

function togglePassword() {
  showPassword.value = !showPassword.value
  if (showPassword.value && !props.dbCreds?.password) {
    emit('loadDb', true)
  }
}

function toggleFtpPassword() {
  showFtpPassword.value = !showFtpPassword.value
  if (showFtpPassword.value && !props.ftpCreds?.password) {
    emit('loadFtp', true)
  }
}

const stackModel = computed({
  get: () => props.selectedStack,
  set: (v: string) => emit('update:selectedStack', v),
})
const cronScheduleModel = computed({
  get: () => props.cronSchedule,
  set: (v: string) => emit('update:cronSchedule', v),
})
const cronCommandModel = computed({
  get: () => props.cronCommand,
  set: (v: string) => emit('update:cronCommand', v),
})

const nameservers = computed(() =>
  props.dnsData?.nameservers?.length
    ? props.dnsData.nameservers
    : ['ns1.ifnotus.space', 'ns2.ifnotus.space'],
)
const dnsRecords = computed(() => {
  if (props.dnsData?.records?.length) return props.dnsData.records
  const ip = props.dnsData?.ip
  if (!ip) return []
  return [
    { record_type: 'A', host: '@', value: ip },
    { record_type: 'A', host: 'www', value: ip },
    { record_type: 'A', host: 'fpanel', value: ip },
    { record_type: 'A', host: 'cpanel', value: ip },
    { record_type: 'A', host: 'mail', value: ip },
  ]
})

watch(
  () => props.dnsData?.dnsMode,
  (mode) => {
    if (mode === 'a_record') dnsConnectMode.value = 'a_record'
    else if (mode === 'nameserver') dnsConnectMode.value = 'nameserver'
  },
  { immediate: true },
)
const customLimit = computed(() => props.dnsData?.limit ?? 1)
const customUsed = computed(() => props.dnsData?.used ?? 0)
const canAttachCustom = computed(() => Boolean(props.dnsData?.canAssign) || customLimit.value > customUsed.value)
const assignedDomains = computed(() => props.dnsData?.customDomains || [])
const availableDomains = computed(() => props.dnsData?.availableDomains || [])

function submitCustomDomain() {
  emit('attachCustom', customDomainInput.value.trim())
}

function submitAssign() {
  const name = assignPick.value.trim()
  if (!name) return
  emit('attachCustom', name)
}

function publicSiteUrl(domain: string) {
  const host = domain.toLowerCase()
  const secure =
    host === 'ifnotus.space' ||
    host.endsWith('.ifnotus.space') ||
    host === 'serverlabsttu.space' ||
    host.endsWith('.serverlabsttu.space')
  return `${secure ? 'https' : 'http'}://${domain}`
}

function formatBytes(n?: number | null) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <section class="site-panel">
    <header class="site-head">
      <div>
        <p class="eyebrow">Site</p>
        <h2>{{ displaySiteDomain || 'Your site' }}</h2>
        <p class="muted">
          {{ displayCpuLabel }} vCPU · {{ displayRamLabel }} ·
          {{ displayStorageLabel }} GB · {{ activePlan?.name || 'Plan' }}
        </p>
      </div>
      <div class="head-actions">
        <select
          class="select"
          :value="displaySiteDomain"
          @change="onSiteDomainChange(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="d in siteDomainOptions" :key="d.name" :value="d.name">
            {{ d.name }}{{ d.isPrimary ? '' : d.type === 'subdomain' ? ' (subdomain)' : ' (addon)' }}
          </option>
        </select>
        <a
          v-if="displaySiteDomain"
          class="btn-ghost"
          :href="publicSiteUrl(displaySiteDomain)"
          target="_blank"
          rel="noopener"
        >Open site</a>
      </div>
    </header>

    <UiTabBar
      v-if="!hideSubnav"
      :items="siteTabItems"
      :model-value="siteTab"
      variant="flat"
      aria-label="Site sections"
      class="site-subtabs"
      @update:model-value="onSiteTab"
    />

    <div v-if="siteTab === 'files' && !canFiles" class="block">
      <p>{{ packLocked('File manager') }}</p>
    </div>
    <div v-else-if="siteTab === 'files'" class="block files-launch">
      <h3>File manager</h3>
      <p class="muted">
        Browse, upload, and edit your site files in a full file manager and code editor.
        Opens in a new browser tab. Uploads stay within your package storage.
      </p>
      <div class="install-actions">
        <button type="button" class="btn-primary" @click="openFileManager()">Open file manager</button>
        <button type="button" class="btn-ghost" @click="openFileManager('.')">Open at site root</button>
      </div>
      <p v-if="fileMsg" class="muted mt">{{ fileMsg }}</p>
    </div>

    <div v-else-if="siteTab === 'git' && !canGit" class="block">
      <p>{{ packLocked('Git Version Control') }}</p>
    </div>
    <div v-else-if="siteTab === 'git'" class="block git-vc">
      <div class="git-vc-head">
        <div>
          <h3>Git™ Version Control</h3>
          <p class="muted">
            Create and manage Git repositories, clone remotes, and pull updates into this hosting account.
            <template v-if="gitStatus?.repos_limit === 1"> This package includes 1 repository.</template>
            <template v-else-if="gitStatus?.repos_limit"> This package includes up to {{ gitStatus.repos_limit }} repositories.</template>
          </p>
        </div>
        <button
          v-if="gitView !== 'create'"
          type="button"
          class="btn-primary"
          @click="emit('update:gitView', 'create')"
        >
          Create
        </button>
      </div>

      <p class="git-crumbs">
        <button type="button" class="text-btn" @click="emit('update:gitView', 'list')">List Repositories</button>
        <span v-if="gitView === 'create'"> / Create Repository</span>
        <span v-else-if="gitView === 'history'"> / History</span>
      </p>

      <div v-if="gitMsg" class="git-alert-bar mt" :class="{ 'is-err': gitMsg.toLowerCase().includes('failed') || gitMsg.toLowerCase().includes('error') }">
        <span>{{ gitMsg }}</span>
      </div>

      <div v-if="gitView === 'create'" class="git-create-card mt">
        <div class="git-create-layout">
        <div class="git-create-main">
        <h4>Create Repository</h4>
        <label class="git-toggle">
          <input
            type="checkbox"
            :checked="gitCloneRemote !== false"
            @change="emit('update:gitCloneRemote', ($event.target as HTMLInputElement).checked)"
          />
          <span>Clone a Repository</span>
        </label>
        <p class="hint">Enable this toggle if you want to clone a remote repository, or disable this toggle to create a new repository.</p>

        <form class="git-create-form" @submit.prevent="emit('cloneGitRepo')">
          <label v-if="gitCloneRemote !== false" class="field">
            <span>Clone URL</span>
            <p class="hint">Enter the clone URL. URLs must begin with http://, https://, ssh://, git://, or git@.</p>
            <input
              :value="gitCloneUrl"
              type="text"
              placeholder="https://github.com/username/project.git"
              spellcheck="false"
              :disabled="gitBusy"
              @input="emit('update:gitCloneUrl', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <label class="field">
            <span>Repository Path</span>
            <p class="hint">
              Any folder under your hosting home (for example {{ gitStatus?.home_display || '/home3/user' }}/try).
              Not limited to public_html — Git and apps can live in a custom folder.
            </p>
            <input
              :value="gitRepoPath"
              type="text"
              spellcheck="false"
              :disabled="gitBusy"
              @input="emit('update:gitRepoPath', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <label class="field">
            <span>Repository Name</span>
            <p class="hint">Display name only. Do not include &lt; or &gt;.</p>
            <input
              :value="gitRepoName"
              type="text"
              :disabled="gitBusy"
              @input="emit('update:gitRepoName', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <label v-if="gitCloneRemote !== false" class="field">
            <span>Branch (optional)</span>
            <input
              :value="gitCloneBranch"
              type="text"
              placeholder="main"
              :disabled="gitBusy"
              @input="emit('update:gitCloneBranch', ($event.target as HTMLInputElement).value)"
            />
          </label>
          <label class="git-another">
            <input
              type="checkbox"
              :checked="gitServeAsWebsite !== false"
              @change="emit('update:gitServeAsWebsite', ($event.target as HTMLInputElement).checked)"
            />
            Serve this folder as the website (PHP / static)
          </label>
          <label class="git-another">
            <input
              type="checkbox"
              :checked="Boolean(gitCreateAnother)"
              @change="emit('update:gitCreateAnother', ($event.target as HTMLInputElement).checked)"
            />
            Create Another
          </label>
          <div class="git-create-actions">
            <button type="submit" class="btn-primary" :disabled="gitBusy">
              {{ gitBusy ? 'Working…' : 'Create' }}
            </button>
            <button type="button" class="text-btn" @click="emit('update:gitView', 'list')">Return to Repository List</button>
          </div>
        </form>
        </div>
        <aside class="git-related">
          <h5>Related Links</h5>
          <button type="button" class="text-btn" @click="emit('openHostingTab', 'transfer')">SSH Access</button>
        </aside>
        </div>
      </div>

      <div v-else-if="gitView === 'history'" class="git-history-card mt">
        <h4>History — {{ gitHistoryPath }}</h4>
        <ul v-if="gitHistory?.length" class="git-history-list">
          <li v-for="item in gitHistory" :key="item.commit">
            <code>{{ item.commit }}</code>
            <span>{{ item.message }}</span>
            <em>{{ item.author }} · {{ item.committed_at }}</em>
          </li>
        </ul>
        <p v-else class="muted">No commits yet.</p>
        <button type="button" class="text-btn mt" @click="emit('update:gitView', 'list')">Return to Repository List</button>
      </div>

      <div v-else class="git-list-card mt">
        <div class="git-list-toolbar">
          <input
            :value="gitSearch"
            type="search"
            placeholder="Search"
            @input="emit('update:gitSearch', ($event.target as HTMLInputElement).value)"
          />
          <span class="muted">Displaying {{ gitRepos.length }} item{{ gitRepos.length === 1 ? '' : 's' }}</span>
        </div>
        <div v-if="!gitRepos.length" class="git-empty">No repositories yet. Click Create to clone or initialize one.</div>
        <div v-for="repo in gitRepos" :key="repo.id" class="git-row">
          <button type="button" class="git-row-main" @click="emit('update:gitExpandedId', gitExpandedId === repo.id ? null : repo.id)">
            <strong>{{ repo.name }}</strong>
            <code>{{ repo.path_display }}</code>
          </button>
          <div class="git-row-actions">
            <button type="button" class="btn-ghost btn-sm" title="Manage" @click="emit('update:gitExpandedId', repo.id)">Manage</button>
            <button type="button" class="btn-ghost btn-sm" title="History" :disabled="gitBusy" @click="emit('loadGitHistory', repo.path_display)">History</button>
            <button type="button" class="btn-ghost btn-sm" title="Remove" :disabled="gitBusy" @click="emit('removeGitRepo', repo.path_display)">Remove</button>
          </div>
          <div v-if="gitExpandedId === repo.id" class="git-row-detail">
            <dl>
              <div><dt>Repository Name</dt><dd>{{ repo.name }}</dd></div>
              <div><dt>Repository Path</dt><dd><code>{{ repo.path_display }}</code></dd></div>
              <div><dt>Checked-out Branch</dt><dd>{{ repo.branch || '—' }}</dd></div>
              <div><dt>Commit</dt><dd><code>{{ repo.commit_full || repo.commit || '—' }}</code></dd></div>
              <div><dt>Author</dt><dd>{{ repo.author }}<template v-if="repo.author_email"> &lt;{{ repo.author_email }}&gt;</template></dd></div>
              <div><dt>Date</dt><dd>{{ repo.committed_at || '—' }}</dd></div>
              <div><dt>Commit Message</dt><dd>{{ repo.message || '—' }}</dd></div>
            </dl>
            <div class="git-detail-actions">
              <button type="button" class="btn-ghost" @click="openFileManager(gitFileManagerPath(repo.path_display))">File Manager</button>
              <button
                type="button"
                class="btn-ghost"
                :disabled="gitBusy"
                title="Point this domain at this folder for PHP/static files"
                @click="emit('activateGitWebsite', repo.path_display)"
              >
                Make website
              </button>
              <button type="button" class="btn-primary" :disabled="gitBusy || !repo.remote" @click="emit('pullGitRepo', repo.path_display)">
                {{ gitBusy ? 'Pulling…' : 'Pull' }}
              </button>
            </div>
            <label class="field mt">
              <span>Clone URL</span>
              <div class="git-clone-url">
                <input :value="repo.clone_url || repo.remote || ''" readonly />
                <button type="button" class="btn-ghost" @click="copyValue('clone', repo.clone_url || repo.remote || '')">
                  {{ copiedKey === 'clone' ? 'Copied' : 'Copy' }}
                </button>
              </div>
            </label>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="siteTab === 'applications'" class="block">
      <div v-if="appHelpPage === 'hub' && !appFamily" class="apps-help-page mt">
        <div class="apps-help-hero">
          <p class="apps-help-kicker">Applications</p>
          <h3>Choose a runtime</h3>
          <p class="muted">
            Python and Node run as managed processes on a private port. PHP and Laravel use Nginx + PHP-FPM
            from the project document root — a separate pipeline, not the same tunnel.
          </p>
          <div class="apps-help-actions">
            <router-link class="btn-ghost" :to="{ name: 'cpanel-apps-guide' }">Open install guide</router-link>
            <button type="button" class="btn-ghost" @click="emit('openHostingTab', 'ai')">Ask AI Engineer</button>
          </div>
        </div>

        <div class="app-family-grid">
          <button type="button" class="app-family-card" @click="openAppFamily('python')">
            <i class="fab fa-python" />
            <strong>Python</strong>
            <span>FastAPI, Flask, Django</span>
            <em>{{ pythonApplications.length ? `${pythonApplications.length} active →` : 'Create app →' }}</em>
          </button>
          <button type="button" class="app-family-card" @click="openAppFamily('nodejs')">
            <i class="fab fa-node-js" />
            <strong>Node.js</strong>
            <span>Express, Node apps</span>
            <em>{{ nodeApplications.length ? `${nodeApplications.length} active →` : 'Create app →' }}</em>
          </button>
          <button type="button" class="app-family-card" @click="openAppFamily('php')">
            <i class="fab fa-php" />
            <strong>PHP &amp; Laravel</strong>
            <span>PHP-FPM document root</span>
            <em>{{ phpApplications.length ? `${phpApplications.length} active →` : 'Create app →' }}</em>
          </button>
        </div>
        <p class="muted mt" style="font-size: 0.85rem">
          WordPress and plain site stacks still install from the
          <button type="button" class="linkish" @click="siteTab = 'stack'">Stack</button> tab.
        </p>
      </div>

      <div v-else-if="!appFamily" class="apps-container mt">
        <div class="apps-head-box">
          <h3>Applications</h3>
          <p class="muted">Choose a runtime to manage active apps or create a new one.</p>
        </div>
        <div class="app-family-grid">
          <button type="button" class="app-family-card" @click="openAppFamily('python')">
            <i class="fab fa-python" />
            <strong>Python</strong>
            <span>FastAPI, Flask, Django</span>
            <em>{{ pythonApplications.length }} deployed</em>
          </button>
          <button type="button" class="app-family-card" @click="openAppFamily('nodejs')">
            <i class="fab fa-node-js" />
            <strong>Node.js</strong>
            <span>Express, Node.js</span>
            <em>{{ nodeApplications.length }} deployed</em>
          </button>
          <button type="button" class="app-family-card" @click="openAppFamily('php')">
            <i class="fab fa-php" />
            <strong>PHP &amp; Laravel</strong>
            <span>PHP-FPM</span>
            <em>{{ phpApplications.length }} deployed</em>
          </button>
        </div>
      </div>

      <div v-else class="apps-container mt">
        <div class="apps-head-box">
          <button type="button" class="btn-ghost btn-sm" @click="closeAppFamily">← All runtimes</button>
          <h3>{{ familyTitle }}</h3>
          <p class="muted">{{ familyBlurb }}</p>
        </div>

        <div v-if="familyApplications.length" class="apps-list-card">
          <div class="apps-card-header">
            <h4>Active Applications</h4>
            <span class="apps-count-badge">{{ familyApplications.length }} deployed</span>
          </div>
          <div class="app-items-grid">
            <div v-for="app in familyApplications" :key="app.id" class="app-card-item">
              <div class="app-card-main">
                <div class="app-title-row">
                  <span class="app-icon-tag"><i class="fas fa-cube" /></span>
                  <strong class="app-title">{{ app.name }}</strong>
                  <span class="pill" :class="app.status">{{ app.status }}</span>
                </div>
                <div class="app-meta-row">
                  <span><i class="fas fa-layer-group" /> {{ app.framework_label || app.framework }}</span>
                  <span><i class="fas fa-code-branch" /> {{ app.runtime_version || app.runtime }}</span>
                </div>
                <div v-if="app.app_root_display || app.serve_url || (app.log_path && isPythonManagedApp(app))" class="app-meta-row app-path-row">
                  <span v-if="app.app_root_display"><i class="fas fa-folder" /> {{ app.app_root_display }}</span>
                  <a v-if="app.serve_url" :href="app.serve_url" target="_blank" rel="noopener" class="app-serve-link">
                    {{ app.serve_url.replace(/^https?:\/\//, '') }}
                  </a>
                  <span v-if="app.log_path && isPythonManagedApp(app)"><i class="fas fa-file-alt" /> {{ app.log_path }}</span>
                </div>
                <pre v-if="app.message && (app.status === 'failed' || app.status === 'pending')" class="app-error-msg">{{ app.message }}</pre>
              </div>
              <div class="app-card-actions">
                <button
                  type="button"
                  class="app-act app-act-edit"
                  title="Edit"
                  :disabled="appBusy"
                  @click="emit('editApplication', app.id)"
                >
                  <i class="fas fa-pen" /> Edit
                </button>
                <button
                  type="button"
                  class="app-act app-act-refresh"
                  title="Refresh status"
                  :disabled="appBusy"
                  @click="emit('refreshApplication', app.id)"
                >
                  <i class="fas fa-sync-alt" /> Refresh
                </button>
                <button
                  v-if="!isPhpManagedApp(app) && (app.status === 'running' || app.status === 'restarting')"
                  type="button"
                  class="app-act app-act-restart"
                  title="Restart"
                  :disabled="appBusy"
                  @click="emit('restartApplication', app.id)"
                >
                  <i class="fas fa-redo-alt" /> Restart
                </button>
                <button
                  v-if="!isPhpManagedApp(app) && (app.status === 'running' || app.status === 'restarting')"
                  type="button"
                  class="app-act app-act-stop"
                  title="Stop"
                  :disabled="appBusy"
                  @click="emit('stopApplication', app.id)"
                >
                  <i class="fas fa-stop" /> Stop
                </button>
                <button
                  v-if="!isPhpManagedApp(app) && app.status === 'stopped'"
                  type="button"
                  class="app-act app-act-start"
                  title="Start"
                  :disabled="appBusy"
                  @click="emit('startApplication', app.id)"
                >
                  <i class="fas fa-play" /> Start
                </button>
                <button
                  v-if="app.status === 'pending' || app.status === 'failed' || isPhpManagedApp(app)"
                  type="button"
                  class="app-act app-act-deploy"
                  title="Deploy"
                  :disabled="appBusy"
                  @click="emit('deployApplication', app.id)"
                >
                  <i class="fas fa-rocket" /> {{ isPhpManagedApp(app) ? 'Deploy / Composer' : 'Deploy' }}
                </button>
                <a
                  v-if="app.serve_url"
                  class="app-act app-act-restart"
                  :href="app.serve_url"
                  target="_blank"
                  rel="noopener"
                >
                  <i class="fas fa-external-link-alt" /> Open
                </a>
                <button
                  type="button"
                  class="app-act app-act-delete"
                  title="Delete"
                  :disabled="appBusy"
                  @click="emit('deleteApplication', app.id)"
                >
                  <i class="fas fa-trash-alt" /> Delete
                </button>
              </div>

              <div v-if="editingAppId === app.id" class="app-edit-panel">
                <div class="app-section-label mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Edit application
                </div>
                <div class="app-edit-grid">
                  <label class="field">
                    <span>Name</span>
                    <input :value="editAppName" type="text" @input="emit('update:editAppName', ($event.target as HTMLInputElement).value)" />
                  </label>
                  <label v-if="isPythonManagedApp(app)" class="field">
                    <span>Python version</span>
                    <select
                      :value="editAppRuntimeVersion || ''"
                      @change="emit('update:editAppRuntimeVersion', ($event.target as HTMLSelectElement).value)"
                    >
                      <option v-for="opt in pythonRuntimeOptions" :key="String(opt.runtime_version)" :value="opt.runtime_version" :disabled="!opt.allowed">
                        {{ opt.runtime_version }}{{ opt.allowed ? '' : ' (upgrade)' }}
                      </option>
                    </select>
                  </label>
                  <label v-if="isPhpManagedApp(app)" class="field">
                    <span>PHP version</span>
                    <select
                      :value="editAppRuntimeVersion || ''"
                      @change="emit('update:editAppRuntimeVersion', ($event.target as HTMLSelectElement).value)"
                    >
                      <option v-for="ver in PHP_RUNTIME_VERSIONS" :key="ver" :value="ver">{{ ver }}</option>
                    </select>
                  </label>
                  <label v-if="isPythonManagedApp(app)" class="field">
                    <span>Passenger log file</span>
                    <input
                      :value="editAppLogPath"
                      type="text"
                      :placeholder="passengerLogPlaceholder"
                      spellcheck="false"
                      @input="emit('update:editAppLogPath', ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                  <label v-if="isPythonManagedApp(app)" class="field">
                    <span>Startup module</span>
                    <input
                      :value="editAppPythonModule"
                      type="text"
                      spellcheck="false"
                      @input="emit('update:editAppPythonModule', ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                  <label v-if="isPythonManagedApp(app)" class="field">
                    <span>Entry point</span>
                    <input
                      :value="editAppPythonObject"
                      type="text"
                      spellcheck="false"
                      @input="emit('update:editAppPythonObject', ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                  <label class="app-serve-check">
                    <input
                      type="checkbox"
                      :checked="Boolean(editAppServeAtDomain)"
                      @change="emit('update:editAppServeAtDomain', ($event.target as HTMLInputElement).checked)"
                    />
                    {{
                      isPhpManagedApp(app)
                        ? 'Point this domain at this app (Laravel public/ or PHP root)'
                        : 'Point this domain at this app (apex /)'
                    }}
                  </label>
                </div>

                <div class="app-env-block">
                  <div class="app-env-head">
                    <div>
                      <div class="app-section-label text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                        Environment variables
                      </div>
                      <p class="app-env-help">
                        Existing keys are listed without values. Re-enter a value to change it, or add a new variable.
                      </p>
                    </div>
                    <button type="button" class="app-act app-act-add" @click="emit('addEnvVarRow', 'edit')">
                      <i class="fas fa-plus" /> Add variable
                    </button>
                  </div>
                  <div v-if="!(editAppEnvVars || []).length" class="app-env-empty">No variables yet.</div>
                  <div
                    v-for="(row, idx) in editAppEnvVars || []"
                    :key="`edit-env-${idx}`"
                    class="app-env-row"
                  >
                    <input
                      :value="row.key"
                      type="text"
                      placeholder="KEY"
                      spellcheck="false"
                      @input="emit('updateEnvVarRow', 'edit', idx, 'key', ($event.target as HTMLInputElement).value)"
                    />
                    <input
                      :value="row.value"
                      type="text"
                      placeholder="value"
                      spellcheck="false"
                      @input="emit('updateEnvVarRow', 'edit', idx, 'value', ($event.target as HTMLInputElement).value)"
                    />
                    <button type="button" class="app-act app-act-remove" title="Remove" @click="emit('removeEnvVarRow', 'edit', idx)">
                      <i class="fas fa-times" />
                    </button>
                  </div>
                </div>

                <div class="app-edit-actions">
                  <button type="button" class="app-act app-act-save" :disabled="appBusy" @click="emit('saveEditApplication')">
                    <i class="fas fa-save" /> {{ appBusy ? 'Saving…' : 'Save changes' }}
                  </button>
                  <button type="button" class="app-act app-act-cancel" :disabled="appBusy" @click="emit('cancelEditApplication')">
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!showAppCreateForm && familyApplications.length" class="mt-3">
          <button type="button" class="btn-primary rounded-xl px-4 py-3 text-sm font-semibold" @click="emit('update:showAppCreateForm', true)">
            Create new application
          </button>
        </div>

        <div
          v-if="showAppCreateForm || !familyApplications.length"
          class="app-create-card mt-3 rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950"
        >
          <div class="apps-card-header" style="padding: 0 0 12px">
            <h4>{{ familyApplications.length ? 'Create new application' : 'Application setup' }}</h4>
            <button
              v-if="familyApplications.length"
              type="button"
              class="btn-ghost btn-sm"
              @click="emit('update:showAppCreateForm', false)"
            >
              Cancel
            </button>
          </div>
          <div class="app-create-form">
            <div class="app-form-section rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/60">
              <div class="app-section-label mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">Application setup</div>
              <div class="app-control-list">
                <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                  <div class="app-control-meta">
                    <span class="app-control-title">Framework</span>
                    <p class="app-control-help">Only frameworks for this runtime.</p>
                  </div>
                  <label class="field app-control-input">
                    <span class="sr-only">Framework</span>
                    <select :value="newAppFramework" @change="emit('update:newAppFramework', ($event.target as HTMLSelectElement).value)">
                      <option v-for="f in familyFrameworkOptions" :key="f.id" :value="f.id" :disabled="!f.allowed">
                        {{ f.label }}{{ f.allowed ? '' : ' (Requires Plan Upgrade)' }}
                      </option>
                    </select>
                  </label>
                </div>

                <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                  <div class="app-control-meta">
                    <span class="app-control-title">{{ familyRuntimeLabel }}</span>
                    <p class="app-control-help">Runtime version used for this application.</p>
                  </div>
                  <label class="field app-control-input">
                    <span class="sr-only">Runtime version</span>
                    <select :value="newAppRuntimeVersion || ''" @change="emit('update:newAppRuntimeVersion', ($event.target as HTMLSelectElement).value)">
                      <option v-for="opt in familyRuntimeOptions" :key="String(opt.runtime_version)" :value="opt.runtime_version" :disabled="!opt.allowed">
                        {{ opt.runtime_version }}{{ opt.recommended ? ' (recommended)' : '' }}
                      </option>
                    </select>
                  </label>
                </div>

                <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                  <div class="app-control-meta">
                    <span class="app-control-title">Application root</span>
                    <p class="app-control-help">
                      Folder under your home
                      <code>(/home3/{{ activeEnv.hosting_name || 'user' }})</code>.
                      <template v-if="appFamily === 'php'"> Laravel is served from <code>public/</code> inside this folder.</template>
                    </p>
                    <pre class="app-root-tree">{{ appRootTreePreview }}</pre>
                  </div>
                  <div class="app-control-input app-root-fields">
                    <label class="field">
                      <span class="sr-only">Placement</span>
                      <select
                        :value="newAppRootPlacement || 'apps'"
                        @change="emit('update:newAppRootPlacement', ($event.target as HTMLSelectElement).value as 'apps' | 'home' | 'public_html')"
                      >
                        <option value="apps">apps / &lt;folder&gt; (recommended)</option>
                        <option value="home">Home folder (outside public_html)</option>
                        <option value="public_html">public_html (domain root)</option>
                      </select>
                    </label>
                    <label class="field">
                      <span class="sr-only">Application root</span>
                      <input
                        :value="newAppName"
                        type="text"
                        :placeholder="(newAppRootPlacement || 'apps') === 'public_html' ? 'public_html' : 'e.g. student-api'"
                        :disabled="(newAppRootPlacement || 'apps') === 'public_html'"
                        @input="emit('update:newAppName', ($event.target as HTMLInputElement).value)"
                      />
                    </label>
                    <label
                      v-if="(newAppRootPlacement || 'apps') !== 'public_html'"
                      class="app-serve-check"
                    >
                      <input
                        type="checkbox"
                        :checked="Boolean(newAppServeAtDomain)"
                        @change="emit('update:newAppServeAtDomain', ($event.target as HTMLInputElement).checked)"
                      />
                      Point this domain at this app (apex /)
                    </label>
                  </div>
                </div>

                <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                  <div class="app-control-meta">
                    <span class="app-control-title">Application URL</span>
                    <p class="app-control-help">Domain or subdomain on this hosting that should serve this app.</p>
                  </div>
                  <label class="field app-control-input">
                    <span class="sr-only">Application URL</span>
                    <select
                      :value="displaySiteDomain"
                      @change="onSiteDomainChange(($event.target as HTMLSelectElement).value)"
                    >
                      <option v-for="d in siteDomainOptions" :key="d.name" :value="d.name">
                        {{ d.name }}{{ d.isPrimary ? '' : d.type === 'subdomain' ? ' (subdomain)' : ' (addon)' }}
                      </option>
                    </select>
                  </label>
                </div>

                <div
                  v-if="appFamily === 'python'"
                  class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80"
                >
                  <div class="app-control-meta">
                    <span class="app-control-title">Passenger log file</span>
                    <p class="app-control-help">
                      Path plus filename for application stdout/stderr
                      (e.g. <code>/home3/{{ activeEnv.hosting_name || 'user' }}/logs/passenger.log</code>).
                    </p>
                  </div>
                  <label class="field app-control-input">
                    <span class="sr-only">Passenger log file</span>
                    <input
                      :value="newAppLogPath || ''"
                      type="text"
                      :placeholder="passengerLogPlaceholder"
                      spellcheck="false"
                      @input="emit('update:newAppLogPath', ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                </div>

                <div
                  v-if="appFamily === 'php'"
                  class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80"
                >
                  <div class="app-control-meta">
                    <span class="app-control-title">How PHP is hosted</span>
                    <p class="app-control-help">
                      Composer install runs on Deploy. Nginx serves PHP-FPM from the document root
                      (Laravel: <code>public/</code>). There is no Gunicorn, Passenger, or private-port process.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div
              v-if="appFamily === 'python' && ['python', 'fastapi', 'django', 'flask'].includes(String(newAppFramework || ''))"
              class="mt-1"
            >
              <div class="app-form-section rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/60">
                <div class="app-section-label mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                  {{ newAppFramework === 'django' || newAppFramework === 'flask' ? 'WSGI startup' : 'ASGI startup' }}
                </div>
                <div class="app-control-list">
                  <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                    <div class="app-control-meta">
                      <span class="app-control-title">Application startup file</span>
                      <p class="app-control-help">
                        Module path, for example
                        <code>{{ newAppFramework === 'django' ? 'config.wsgi' : 'app.main' }}</code>.
                        Leave blank to auto-detect from your project files.
                      </p>
                    </div>
                    <label class="field app-control-input">
                      <span class="sr-only">Startup module</span>
                      <input
                        :value="newAppPythonModule"
                        type="text"
                        :placeholder="newAppFramework === 'django' ? 'config.wsgi' : 'app.main'"
                        spellcheck="false"
                        @input="emit('update:newAppPythonModule', ($event.target as HTMLInputElement).value)"
                      />
                    </label>
                  </div>
                  <div class="app-control-row rounded-xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950/80">
                    <div class="app-control-meta">
                      <span class="app-control-title">Application entry point</span>
                      <p class="app-control-help">
                        Callable object, for example
                        <code>{{ newAppFramework === 'django' ? 'application' : 'app' }}</code>.
                        Leave blank to auto-detect.
                      </p>
                    </div>
                    <label class="field app-control-input">
                      <span class="sr-only">App variable</span>
                      <input
                        :value="newAppPythonObject"
                        type="text"
                        :placeholder="newAppFramework === 'django' ? 'application' : 'app'"
                        spellcheck="false"
                        @input="emit('update:newAppPythonObject', ($event.target as HTMLInputElement).value)"
                      />
                    </label>
                  </div>
                </div>
              </div>
            </div>

            <div class="app-form-section mt-1 rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/60">
              <div class="app-env-head">
                <div>
                  <div class="app-section-label text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                    Environment variables
                  </div>
                  <p class="app-env-help">Optional KEY=value pairs{{ appFamily === 'php' ? ' (e.g. for .env-style keys)' : ' injected when the app starts' }}.</p>
                </div>
                <button type="button" class="app-act app-act-add" @click="emit('addEnvVarRow', 'new')">
                  <i class="fas fa-plus" /> Add variable
                </button>
              </div>
              <div v-if="!(newAppEnvVars || []).length" class="app-env-empty">No variables yet.</div>
              <div
                v-for="(row, idx) in newAppEnvVars || []"
                :key="`new-env-${idx}`"
                class="app-env-row"
              >
                <input
                  :value="row.key"
                  type="text"
                  placeholder="KEY"
                  spellcheck="false"
                  @input="emit('updateEnvVarRow', 'new', idx, 'key', ($event.target as HTMLInputElement).value)"
                />
                <input
                  :value="row.value"
                  type="text"
                  placeholder="value"
                  spellcheck="false"
                  @input="emit('updateEnvVarRow', 'new', idx, 'value', ($event.target as HTMLInputElement).value)"
                />
                <button type="button" class="app-act app-act-remove" title="Remove" @click="emit('removeEnvVarRow', 'new', idx)">
                  <i class="fas fa-times" />
                </button>
              </div>
            </div>

            <button
              type="button"
              class="btn-primary btn-create-app mt-1 rounded-xl px-4 py-3 text-sm font-semibold"
              :disabled="appBusy || ((newAppRootPlacement || 'apps') !== 'public_html' && !(newAppName || '').trim())"
              @click="emit('createApplication')"
            >
              {{ appBusy ? 'Creating…' : 'Create Application' }}
            </button>
          </div>
        </div>
      </div>
      <p v-if="appMsg" class="muted mt">{{ appMsg }}</p>
    </div>

    <div v-else-if="siteTab === 'stack'" class="block">
      <!-- Runtime Telemetry & Execution Environment Token -->
      <div class="stack-telemetry-card">
        <div class="stk-top">
          <div class="stk-id-block">
            <span class="stk-pill">STACK RUNTIME</span>
            <div class="stk-token-wrap">
              <span class="stk-token-label">Deployment Token:</span>
              <code class="stk-token-val">STK-{{ activeStackToken }}-PROD</code>
              <button
                type="button"
                class="stk-copy-btn"
                @click="copyValue('stk_token', `STK-${activeStackToken}-PROD`)"
              >
                {{ copiedKey === 'stk_token' ? 'Copied' : 'Copy' }}
              </button>
            </div>
          </div>
          <div class="stk-actions-top">
            <button
              type="button"
              class="stk-guide-btn"
              @click="openStackGuide(selectedStack === 'wordpress' ? 'wordpress' : selectedStack === 'laravel' ? 'laravel' : 'mysql')"
            >
              <i class="fas fa-circle-info" /> (i) Stack Guide
            </button>
            <div class="stk-status-badge">
              <span class="stk-dot" />
              <span>FastCGI Pool Active</span>
            </div>
          </div>
        </div>

        <div class="stk-grid">
          <div class="stk-metric">
            <span class="stk-lbl">PHP FastCGI Engine</span>
            <strong class="stk-num">v8.3.6 (FPM)</strong>
            <small class="stk-sub">unix:/run/php/php8.3-fpm.sock</small>
          </div>
          <div class="stk-metric">
            <span class="stk-lbl">Memory Allocation</span>
            <strong class="stk-num">512 MB</strong>
            <small class="stk-sub">Max execution limit 120s</small>
          </div>
          <div class="stk-metric">
            <span class="stk-lbl">OPcache Shared Mem</span>
            <strong class="stk-num">128 MB</strong>
            <small class="stk-sub">100% Accelerator Hit Ratio</small>
          </div>
          <div class="stk-metric">
            <span class="stk-lbl">FastCGI Process Pool</span>
            <strong class="stk-num">5 – 50 Workers</strong>
            <small class="stk-sub">Dynamic process multiplexing</small>
          </div>
          <div class="stk-metric">
            <span class="stk-lbl">Node Infrastructure</span>
            <strong class="stk-num">IFN-NODE-80.241</strong>
            <small class="stk-sub">HTTP/2 + TLSv1.3 AES-256</small>
          </div>
          <div class="stk-metric">
            <span class="stk-lbl">Docroot Isolation</span>
            <strong class="stk-num">Jailed OpenBaseDir</strong>
            <small class="stk-sub">Tenant Sandboxed Boundary</small>
          </div>
        </div>
      </div>

      <div class="pack-soft mt">
        <h3>On {{ activePlan?.name || 'this package' }}</h3>
        <p class="muted">Runtimes included with this package. Limited items are faded.</p>
        <ul class="stack-pick pack">
          <li v-for="s in packStacks" :key="s.id" :class="{ faded: s.level !== 'yes' }">
            <ServiceBrandMark :name="s.id" :size="36" />
            <strong>{{ s.label }}</strong>
            <em>{{ s.level === 'limited' ? 'Limited' : 'Included' }}</em>
          </li>
        </ul>
      </div>

      <template v-if="currentStack && stackOutcome !== 'running' && stackOutcome !== 'error'">
        <div class="install-panel success mt">
          <div class="install-head">
            <ServiceBrandMark :name="currentStackIcon" :size="32" />
            <strong>{{ currentStack.stack_name || currentStack.stack || 'Stack' }} installed</strong>
            <span class="badge-ok">Active</span>
          </div>
          <p class="install-label">
            {{
              currentStack.message ||
                stackMsg ||
                'This stack is installed on your site. Open it to finish any first-time setup.'
            }}
          </p>
          <div
            v-if="currentStack.stack === 'wordpress' && currentStack.admin_user"
            class="wp-login mt"
          >
            <p><strong>WordPress login</strong></p>
            <p class="muted">User {{ currentStack.admin_user }} · {{ currentStack.admin_email }}</p>
            <p v-if="currentStack.admin_password" class="mono">Password: {{ currentStack.admin_password }}</p>
            <p class="muted">Change this password after you first log in.</p>
            <a
              v-if="currentStack.admin_url"
              class="btn-ghost"
              :href="String(currentStack.admin_url)"
              target="_blank"
              rel="noopener"
            >Open wp-admin</a>
          </div>
          <div class="install-actions">
            <a
              v-if="displaySiteDomain"
              class="btn-primary"
              :href="publicSiteUrl(displaySiteDomain)"
              target="_blank"
              rel="noopener"
            >Open site</a>
            <button type="button" class="btn-ghost" @click="openFileManager()">
              View files
            </button>
            <button
              type="button"
              class="btn-ghost danger"
              :disabled="stackBusy"
              @click="confirmClear(false)"
            >
              Clear install
            </button>
          </div>
          <p class="support-hint">
            Clear removes this site’s installed apps and files.
            Prefer
            <button type="button" class="linkish" @click="emit('openSupport')">support</button>
            if you are unsure.
          </p>
        </div>

        <details class="reinstall mt" open>
          <summary>Stacks on this pack</summary>
          <p class="muted mt">
            Only stacks on this pack are listed. One-click installers are Static/PHP, WordPress, Laravel, and Node.js when your plan includes them. Other included runtimes deploy from Applications, Files, or Git.
          </p>
          <div class="stack-pick mt">
            <button
              v-for="s in installStacks"
              :key="s.id"
              type="button"
              class="stack-opt"
              :class="{ on: selectedStack === s.id, 'is-matrix': !s.oneClick, faded: !s.allowed }"
              :disabled="stackBusy || !s.allowed"
              @click="stackModel = s.id"
            >
              <ServiceBrandMark :name="s.icon || s.id" :size="36" />
              <strong>{{ s.name }}</strong>
              <em v-if="!s.allowed">Not on this plan</em>
              <em v-else-if="!s.oneClick">Files / Git</em>
              <em v-else-if="s.level === 'limited'">Limited</em>
              <em v-else>One-click</em>
            </button>
          </div>
          <p class="muted mt">{{ selectedInstall?.description }}</p>
          <button
            type="button"
            class="btn-primary mt"
            :disabled="stackBusy || !selectedInstall?.oneClick || !selectedInstall?.allowed"
            @click="emit('installStack')"
          >
            {{
              !selectedInstall?.allowed
                ? 'Not on this plan'
                : !selectedInstall?.oneClick
                  ? 'Use Applications or Git'
                  : 'Replace stack'
            }}
          </button>
        </details>
      </template>

      <!-- Fresh install / in-progress / failed -->
      <template v-else>
        <h3>{{ stackOutcome === 'running' ? 'Installing stack' : 'Install stack' }}</h3>
        <p class="muted">
          Your pack only lists stacks it includes. Faded tiles are limited or not installable here.
          One-click: Static/PHP, WordPress, Laravel, Node.js — when the plan allows them.
        </p>
        <div class="stack-pick mt">
          <button
            v-for="s in installStacks"
            :key="s.id"
            type="button"
            class="stack-opt"
            :class="{ on: selectedStack === s.id, 'is-matrix': !s.oneClick, faded: !s.allowed }"
            :disabled="stackBusy || !s.allowed"
            @click="stackModel = s.id"
          >
            <ServiceBrandMark :name="s.icon || s.id" :size="36" />
            <strong>{{ s.name }}</strong>
            <em v-if="!s.allowed">Not on this plan</em>
            <em v-else-if="!s.oneClick">Files / Git</em>
            <em v-else-if="s.level === 'limited'">Limited</em>
            <em v-else>One-click</em>
          </button>
        </div>
        <p class="muted mt">{{ selectedInstall?.description }}</p>
        <button
          type="button"
          class="btn-primary mt"
          :disabled="stackBusy || !selectedInstall?.oneClick || !selectedInstall?.allowed"
          @click="emit('installStack')"
        >
          {{
            stackBusy
              ? 'Installing…'
              : !selectedInstall?.allowed
                ? 'Not on this plan'
                : !selectedInstall?.oneClick
                  ? 'Use Applications or Git'
                  : 'Install stack'
          }}
        </button>

        <div
          v-if="stackOutcome === 'running' || stackOutcome === 'error' || stackProgress"
          class="install-panel mt"
          :class="stackOutcome"
        >
          <div class="install-head">
            <strong>
              <template v-if="stackOutcome === 'error'">Install failed</template>
              <template v-else>Installing {{ stackProgress?.stack || selectedStack }}…</template>
            </strong>
            <span v-if="stackOutcome === 'running'" class="pct">{{ Math.round(stackProgress?.percent || 0) }}%</span>
          </div>

          <div v-if="stackOutcome === 'running'" class="meter">
            <i :style="{ width: Math.min(100, stackProgress?.percent || 5) + '%' }" />
          </div>

          <p class="install-label">
            {{
              stackOutcome === 'error'
                ? (stackProgress?.error || stackMsg || 'Something went wrong.')
                : (stackProgress?.label || stackMsg)
            }}
          </p>

          <ol v-if="stackProgress?.steps?.length" class="step-list">
            <li
              v-for="step in stackProgress.steps"
              :key="step.id"
              :class="step.state"
            >
              <span class="dot" aria-hidden="true" />
              {{ step.label }}
            </li>
          </ol>

          <p v-if="stackOutcome === 'error'" class="support-hint err">
            <button
              type="button"
              class="btn-ghost danger"
              :disabled="stackBusy"
              @click="confirmClear(false)"
            >
              Clear broken install
            </button>
            or
            <button type="button" class="linkish" @click="emit('openSupport')">contact support</button>.
          </p>
        </div>
      </template>
    </div>

    <div v-else-if="siteTab === 'logs'" class="block">
      <div class="toolbar">
        <h3>Application logs</h3>
        <button type="button" class="btn-ghost" :disabled="logBusy" @click="emit('loadLogs')">
          {{ logBusy ? 'Loading…' : 'Refresh' }}
        </button>
      </div>
      <p class="muted">Recent logs for this site.</p>
      <p v-if="logMsg" class="muted mt">{{ logMsg }}</p>
      <pre v-else class="log-view">{{ (logEntries || []).map((e) => `[${e.source}] ${e.message}`).join('\n') || 'No log lines yet.' }}</pre>
    </div>

    <div v-else-if="siteTab === 'cron' && !canCron" class="block">
      <p>{{ packLocked('Cron jobs') }}</p>
    </div>
    <div v-else-if="siteTab === 'cron'" class="block">
      <h3>Cron jobs</h3>
      <p class="muted">
        Commands run as {{ cronLimits?.runs_as || 'your hosting user' }} in your site folder.
        <template v-if="cronLimits">
          Limit {{ cronLimits.jobs_used }}/{{ cronLimits.max_jobs }} · min interval
          {{ cronLimits.min_interval_minutes }} min.
        </template>
      </p>
      <div class="form-row mt">
        <input v-model="cronScheduleModel" class="input" :placeholder="cronLimits?.min_interval_minutes ? `*/${cronLimits.min_interval_minutes} * * * *` : '*/15 * * * *'" />
        <input v-model="cronCommandModel" class="input grow" placeholder="php artisan schedule:run" />
        <button
          type="button"
          class="btn-primary"
          :disabled="cronBusy || (cronLimits != null && cronLimits.jobs_used >= cronLimits.max_jobs)"
          @click="emit('addCron')"
        >
          {{ cronBusy ? 'Adding…' : 'Add' }}
        </button>
      </div>
      <ul v-if="cronJobs.length" class="job-list mt">
        <li v-for="job in cronJobs" :key="job.id">
          <div>
            <p class="env-name">{{ job.schedule }}</p>
            <p class="muted mono">{{ job.command }}</p>
            <p class="muted">{{ job.enabled ? 'Enabled' : 'Disabled' }}<template v-if="job.last_status"> · last {{ job.last_status }}</template></p>
          </div>
          <div class="row-actions">
            <button type="button" class="btn-ghost" @click="emit('runCron', job.id)">Run</button>
            <button type="button" class="btn-ghost" @click="emit('toggleCron', job)">
              {{ job.enabled ? 'Disable' : 'Enable' }}
            </button>
            <button type="button" class="btn-ghost" @click="emit('deleteCron', job.id)">Delete</button>
          </div>
        </li>
      </ul>
      <p v-else class="muted mt">No cron jobs yet.</p>
      <p v-if="cronMsg" class="muted mt">{{ cronMsg }}</p>
    </div>

    <div v-else-if="siteTab === 'database' && !canDb" class="block">
      <p>{{ packLocked('Database management') }}</p>
    </div>
    <div v-else-if="siteTab === 'database'" class="block db-management-section">
      <!-- Database Header & Quick Actions -->
      <div class="db-head-compact">
        <div>
          <div class="db-title-row">
            <span class="db-badge-mysql"><i class="fas fa-database" /> MySQL & PostgreSQL</span>
            <h3>Databases</h3>
          </div>
          <p class="muted tiny">
            Manage your MySQL / PostgreSQL databases, users, and phpMyAdmin access.
          </p>
        </div>
        <div class="db-head-actions">
          <button
            type="button"
            class="btn-primary"
            @click="showCreateDbForm = !showCreateDbForm"
          >
            <i class="fas" :class="showCreateDbForm ? 'fa-minus' : 'fa-plus'" />
            {{ showCreateDbForm ? 'Close Form' : 'Create Database' }}
          </button>
          <button
            type="button"
            class="btn-ghost pma-btn"
            @click="openPhpMyAdminDirect()"
          >
            <i class="fas fa-arrow-up-right-from-square" /> phpMyAdmin
          </button>
          <button
            type="button"
            class="btn-ghost btn-import-sql"
            @click="openImportModal()"
          >
            <i class="fas fa-file-import" /> Import .sql
          </button>
          <button
            type="button"
            class="btn-ghost"
            :disabled="dbBusy"
            @click="emit('loadDb', true); emit('loadDbList')"
          >
            <i class="fas fa-rotate" :class="{ 'fa-spin': dbBusy }" /> Refresh
          </button>
        </div>
      </div>

      <!-- Action Message / Alert -->
      <div v-if="dbActionMsg" class="db-alert-bar mt-sm" :class="{ 'is-err': dbActionMsg.toLowerCase().includes('failed') || dbActionMsg.toLowerCase().includes('error') }">
        <i class="fas" :class="dbActionMsg.toLowerCase().includes('failed') || dbActionMsg.toLowerCase().includes('error') ? 'fa-triangle-exclamation' : 'fa-circle-check'" />
        <span>{{ dbActionMsg }}</span>
      </div>

      <!-- Database Creation Card (Clean & Compact) -->
      <div v-if="showCreateDbForm || !dbList?.length" class="db-create-compact mt-sm">
        <div class="db-compact-head">
          <span class="db-compact-title"><i class="fas fa-plus-circle text-primary" /> New Database & User</span>
          <span class="muted tiny">Auto-grants full user privileges</span>
        </div>

        <div class="db-compact-grid mt-xs">
          <label class="field-compact">
            <span class="label-tiny">Database Name</span>
            <input
              :value="newDbName"
              type="text"
              placeholder="e.g. app_db"
              class="input-compact"
              spellcheck="false"
              @input="emit('update:newDbName', ($event.target as HTMLInputElement).value)"
            />
          </label>

          <label class="field-compact">
            <span class="label-tiny">Engine</span>
            <select
              :value="newDbEngine"
              class="input-compact select-compact"
              @change="emit('update:newDbEngine', ($event.target as HTMLSelectElement).value)"
            >
              <option value="mysql">MySQL (Default)</option>
              <option value="postgresql">PostgreSQL</option>
            </select>
          </label>

          <label class="field-compact">
            <span class="label-tiny">User (Optional)</span>
            <input
              :value="newDbUser"
              type="text"
              placeholder="Auto-created if empty"
              class="input-compact"
              spellcheck="false"
              @input="emit('update:newDbUser', ($event.target as HTMLInputElement).value)"
            />
          </label>

          <label class="field-compact">
            <span class="label-tiny">Password</span>
            <div class="input-with-mini-actions">
              <input
                :value="newDbPassword"
                :type="showDbPassword ? 'text' : 'password'"
                placeholder="Auto-generated if blank"
                class="input-compact"
                spellcheck="false"
                @input="emit('update:newDbPassword', ($event.target as HTMLInputElement).value)"
              />
              <button
                type="button"
                class="btn-mini-ico"
                title="Toggle password visibility"
                @click="showDbPassword = !showDbPassword"
              >
                <i class="fas" :class="showDbPassword ? 'fa-eye-slash' : 'fa-eye'" />
              </button>
              <button
                type="button"
                class="btn-mini-ico"
                title="Generate strong password"
                @click="generateStrongPassword"
              >
                <i class="fas fa-dice" />
              </button>
            </div>
          </label>
        </div>

        <div class="db-compact-actions mt-xs">
          <button
            type="button"
            class="btn-primary btn-sm"
            :disabled="dbBusy || !newDbName"
            @click="emit('createDatabase')"
          >
            <i class="fas fa-plus" />
            {{ dbBusy ? 'Creating…' : 'Create Database' }}
          </button>
          <button
            v-if="dbList?.length"
            type="button"
            class="btn-ghost btn-sm"
            @click="showCreateDbForm = false"
          >
            Cancel
          </button>
        </div>
      </div>

      <!-- Databases Table List (Clean & Compact) -->
      <div v-if="dbList?.length" class="db-table-section mt-sm">
        <div class="table-responsive">
          <table class="db-compact-table">
            <thead>
              <tr>
                <th>Database</th>
                <th>Engine</th>
                <th>Username</th>
                <th>Host & Port</th>
                <th>Size</th>
                <th class="th-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="db in dbList"
                :key="db.id"
                :class="{ 'row-active': selectedDbId === db.id }"
                @click="emit('selectDatabase', db.id)"
              >
                <td class="td-name">
                  <div class="db-name-cell">
                    <i class="fas fa-database db-row-ico" />
                    <strong>{{ db.name }}</strong>
                    <span v-if="db.logical_name && db.logical_name !== db.name" class="db-sub-name">({{ db.logical_name }})</span>
                    <span v-if="db.legacy" class="badge-primary-site">Primary</span>
                  </div>
                </td>
                <td>
                  <span class="db-engine-chip" :class="db.engine || 'mysql'">
                    {{ (db.engine || 'mysql').toUpperCase() }}
                  </span>
                </td>
                <td>
                  <span class="mono-text">{{ db.username || '—' }}</span>
                </td>
                <td>
                  <span class="mono-text">{{ db.host || '127.0.0.1' }}:{{ db.port || (db.engine === 'postgresql' ? 5432 : 3306) }}</span>
                </td>
                <td>
                  <span class="size-text">{{ db.size_mb != null ? db.size_mb + ' MB' : '—' }}</span>
                </td>
                <td class="td-actions" @click.stop>
                  <div class="action-btn-group">
                    <button
                      type="button"
                      class="btn-tbl-action pma"
                      title="Open in phpMyAdmin"
                      @click="openPhpMyAdminDirect(db.id)"
                    >
                      <i class="fas fa-arrow-up-right-from-square" /> phpMyAdmin
                    </button>
                    <button
                      type="button"
                      class="btn-tbl-action import"
                      title="Import .sql file"
                      @click="openImportModal(db.id)"
                    >
                      <i class="fas fa-file-import" /> Import
                    </button>
                    <button
                      type="button"
                      class="btn-tbl-action"
                      :class="{ 'active-cred-btn': selectedDbId === db.id }"
                      title="View connection parameters"
                      @click="emit('selectDatabase', db.id)"
                    >
                      <i class="fas fa-key" /> Creds
                    </button>
                    <button
                      type="button"
                      class="btn-tbl-action"
                      title="Reset database password"
                      :disabled="dbBusy || db.legacy"
                      @click="emit('resetDbPassword', db.id)"
                    >
                      <i class="fas fa-arrows-rotate" />
                    </button>
                    <button
                      type="button"
                      class="btn-tbl-action danger"
                      title="Delete database"
                      :disabled="dbBusy || db.legacy"
                      @click="emit('deleteDatabase', db.id)"
                    >
                      <i class="fas fa-trash-can" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Active Database Connection & Credentials Card -->
      <div v-if="dbCreds && !dbCreds.empty && !dbCreds.error" class="db-creds-box mt">
        <div class="creds-box-head">
          <div>
            <h4>Connection Credentials</h4>
            <p class="muted tiny">Use these exact parameters in your PHP connection file, <code>.env</code>, or <code>wp-config.php</code>.</p>
          </div>
          <div class="creds-head-badges">
            <span class="badge-privilege"><i class="fas fa-check-double" /> Full Privileges (ALL)</span>
          </div>
        </div>

        <div class="creds-grid mt-sm">
          <div class="cred-item">
            <div class="cred-data">
              <span class="cred-key">Database Host</span>
              <strong class="cred-val">{{ dbCreds.host || 'localhost' }}</strong>
              <span class="cred-sub">Port {{ dbCreds.port || 3306 }}</span>
            </div>
            <button
              type="button"
              class="btn-copy-chip"
              @click="copyValue('host', dbCreds.host || 'localhost')"
            >
              <i class="fas" :class="copiedKey === 'host' ? 'fa-check text-green' : 'fa-copy'" />
              {{ copiedKey === 'host' ? 'Copied' : 'Copy' }}
            </button>
          </div>

          <div class="cred-item">
            <div class="cred-data">
              <span class="cred-key">Database Name</span>
              <strong class="cred-val mono">{{ dbCreds.name || '—' }}</strong>
              <span class="cred-sub">Engine: {{ dbEngineLabel || 'MySQL' }}</span>
            </div>
            <button
              type="button"
              class="btn-copy-chip"
              @click="copyValue('name', dbCreds.name)"
            >
              <i class="fas" :class="copiedKey === 'name' ? 'fa-check text-green' : 'fa-copy'" />
              {{ copiedKey === 'name' ? 'Copied' : 'Copy' }}
            </button>
          </div>

          <div class="cred-item">
            <div class="cred-data">
              <span class="cred-key">Username</span>
              <strong class="cred-val mono">{{ dbCreds.username || '—' }}</strong>
              <span class="cred-sub">Full access user</span>
            </div>
            <button
              type="button"
              class="btn-copy-chip"
              @click="copyValue('user', dbCreds.username)"
            >
              <i class="fas" :class="copiedKey === 'user' ? 'fa-check text-green' : 'fa-copy'" />
              {{ copiedKey === 'user' ? 'Copied' : 'Copy' }}
            </button>
          </div>

          <div class="cred-item">
            <div class="cred-data">
              <span class="cred-key">Password</span>
              <strong class="cred-val mono">
                <template v-if="showPassword && dbCreds.password">{{ dbCreds.password }}</template>
                <template v-else-if="dbCreds.password_set || dbCreds.password">••••••••••••••••</template>
                <template v-else>Not set</template>
              </strong>
              <span class="cred-sub">Encrypted credential</span>
            </div>
            <div class="cred-btn-group">
              <button
                type="button"
                class="btn-copy-chip ghost"
                :disabled="!dbCreds.password && !dbCreds.password_set"
                @click="togglePassword"
              >
                <i class="fas" :class="showPassword ? 'fa-eye-slash' : 'fa-eye'" />
                {{ showPassword ? 'Hide' : 'Show' }}
              </button>
              <button
                type="button"
                class="btn-copy-chip primary"
                :disabled="!dbCreds.password"
                @click="copyValue('pass', dbCreds.password)"
              >
                <i class="fas" :class="copiedKey === 'pass' ? 'fa-check text-green' : 'fa-copy'" />
                {{ copiedKey === 'pass' ? 'Copied' : 'Copy' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Connection Snippets Accordion / Helper -->
        <div class="snippet-helper-box mt">
          <div class="snippet-header">
            <span class="snippet-title"><i class="fas fa-code" /> Code Snippet Generator</span>
            <div class="snippet-tabs">
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'pdo' }"
                @click="connectionSnippetType = 'pdo'"
              >
                PHP (PDO)
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'mysqli' }"
                @click="connectionSnippetType = 'mysqli'"
              >
                PHP (MySQLi)
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'pgsql' }"
                @click="connectionSnippetType = 'pgsql'"
              >
                PHP (pg_connect)
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'laravel' }"
                @click="connectionSnippetType = 'laravel'"
              >
                Laravel .env
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'wordpress' }"
                @click="connectionSnippetType = 'wordpress'"
              >
                WordPress
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'nodejs' }"
                @click="connectionSnippetType = 'nodejs'"
              >
                Node.js
              </button>
              <button
                type="button"
                class="snippet-tab"
                :class="{ active: connectionSnippetType === 'python' }"
                @click="connectionSnippetType = 'python'"
              >
                Python
              </button>
            </div>
          </div>

          <div class="snippet-code-wrap">
            <pre class="snippet-code">{{ connectionSnippet }}</pre>
            <button
              type="button"
              class="btn-copy-snippet"
              @click="copyValue('snippet', connectionSnippet)"
            >
              <i class="fas" :class="copiedKey === 'snippet' ? 'fa-check' : 'fa-copy'" />
              {{ copiedKey === 'snippet' ? 'Copied Code' : 'Copy Snippet' }}
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="dbInfo === 'Loading…'" class="empty-note mt">
        <i class="fas fa-spinner fa-spin" /> Loading database configuration…
      </div>
      <div v-else-if="dbCreds?.empty || (!dbCreds && dbInfo)" class="empty-note mt">
        <i class="fas fa-database" />
        {{ dbInfo || 'No database on this site yet. Create one above or install WordPress/Laravel from Stack.' }}
      </div>
      <div v-else-if="dbCreds?.error" class="empty-note mt err">
        <i class="fas fa-triangle-exclamation" /> {{ dbCreds.error }}
      </div>

      <!-- Import .SQL File Modal -->
      <div v-if="showImportModal" class="db-import-modal-backdrop" @click.self="closeImportModal">
        <div class="db-import-modal">
          <div class="modal-top">
            <div class="modal-title-wrap">
              <i class="fas fa-file-import modal-ico" />
              <div>
                <h3>Import SQL Database Dump</h3>
                <p class="muted tiny">Upload your <code>.sql</code> backup or export file from your computer.</p>
              </div>
            </div>
            <button type="button" class="btn-close-modal" @click="closeImportModal">
              <i class="fas fa-xmark" />
            </button>
          </div>

          <div class="modal-body mt">
            <label class="field">
              <span class="field-label-wrap">
                <strong>Target Database</strong>
              </span>
              <select v-model="targetImportDbId" class="modal-select">
                <option value="">{{ dbCreds?.name ? `Primary (${dbCreds.name})` : 'Default Database' }}</option>
                <option v-for="d in dbList" :key="d.id" :value="d.id">
                  {{ d.logical_name || d.name }} ({{ d.engine }} · {{ d.name }})
                </option>
              </select>
            </label>

            <div class="sql-dropzone mt">
              <input type="file" accept=".sql,.txt" class="dropzone-input" @change="onImportFileSelected" />
              <div class="dropzone-content">
                <i class="fas fa-cloud-arrow-up dropzone-ico" />
                <p v-if="!importFile"><strong>Choose a .sql file</strong> or drag and drop here</p>
                <p v-else class="file-picked-name">
                  <i class="fas fa-file-code" /> {{ importFile.name }}
                  <span class="tiny muted">({{ (importFile.size / 1024).toFixed(1) }} KB)</span>
                </p>
              </div>
            </div>

            <div class="sql-text-toggle-wrap mt">
              <label class="field">
                <span class="field-label-wrap">
                  <strong>Or Paste Raw SQL Statements</strong>
                </span>
                <textarea
                  v-model="importSqlText"
                  rows="6"
                  class="sql-import-textarea"
                  spellcheck="false"
                  placeholder="CREATE TABLE IF NOT EXISTS ..."
                />
              </label>
            </div>

            <div v-if="importSuccessMsg" class="import-alert success mt">
              <i class="fas fa-circle-check" /> {{ importSuccessMsg }}
            </div>
            <div v-if="importErrorMsg" class="import-alert error mt">
              <i class="fas fa-triangle-exclamation" /> {{ importErrorMsg }}
            </div>
          </div>

          <div class="modal-foot mt">
            <button type="button" class="btn-ghost" @click="closeImportModal">Cancel</button>
            <button
              type="button"
              class="btn-primary"
              :disabled="importBusy || !importSqlText.trim()"
              @click="runDirectSqlImport"
            >
              <i class="fas" :class="importBusy ? 'fa-spinner fa-spin' : 'fa-bolt'" />
              {{ importBusy ? 'Importing SQL File…' : 'Run Import' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="siteTab === 'ftp' && !canFtp" class="block">
      <p>{{ packLocked('SFTP / FTP') }}</p>
    </div>
    <div v-else-if="siteTab === 'ftp'" class="block">
      <h3>SFTP</h3>
      <p class="muted">
        Secure file transfer over SSH (port 22). Limited to this site’s files only — no interactive shell.
        Use FTP below if your app prefers port 21.
      </p>
      <p v-if="ftpCreds?.sftp_coming_note" class="empty-note mt">{{ ftpCreds.sftp_coming_note }}</p>
      <p v-if="sftpInfo === 'Loading…'" class="muted mt">Loading…</p>
      <p v-else-if="sftpCreds?.error" class="empty-note mt err">{{ sftpCreds.error }}</p>
      <div v-else-if="sftpCreds?.username" class="cred-list mt">
        <div class="cred-row">
          <div>
            <p class="cred-label">SFTP host</p>
            <p class="cred-value mono">{{ sftpCreds.host }}</p>
            <p class="hint">FileZilla → SFTP. Port {{ sftpCreds.port || 22 }}.</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('sftp-host', sftpCreds.host || '')">
            {{ copiedKey === 'sftp-host' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">Username</p>
            <p class="cred-value mono">{{ sftpCreds.username }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('sftp-user', sftpCreds.username || '')">
            {{ copiedKey === 'sftp-user' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div class="grow">
            <p class="cred-label">Password</p>
            <p class="cred-value mono">
              <template v-if="showSftpPassword && sftpCreds.password">{{ sftpCreds.password }}</template>
              <template v-else-if="sftpCreds.password_set || sftpCreds.password">••••••••••••</template>
              <template v-else>Not set</template>
            </p>
          </div>
          <div class="row-actions">
            <button type="button" class="btn-ghost" @click="toggleSftpPassword">
              {{ showSftpPassword ? 'Hide' : 'Show' }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!sftpCreds.password"
              @click="copyValue('sftp-pass', sftpCreds.password || '')"
            >
              {{ copiedKey === 'sftp-pass' ? 'Copied' : 'Copy' }}
            </button>
          </div>
        </div>
        <p v-if="sftpCreds.command" class="hint mt mono">{{ sftpCreds.command }}</p>
        <p class="hint mt">{{ sftpCreds.message || sftpCreds.hint }}</p>
      </div>
      <div v-else class="empty-note mt">Create your SFTP login to upload files securely.</div>
      <div class="toolbar mt">
        <button type="button" class="btn-primary" @click="emit('ensureSftp', false)">
          {{ sftpCreds?.username ? 'Refresh SFTP login' : 'Create SFTP login' }}
        </button>
        <button
          v-if="sftpCreds?.username"
          type="button"
          class="btn-ghost"
          @click="emit('ensureSftp', true)"
        >
          Reset SFTP password
        </button>
      </div>

      <h4 class="mt">SSH keys (optional)</h4>
      <p class="muted">Add a public key for passwordless SFTP. One OpenSSH line (ssh-ed25519 / ssh-rsa).</p>
      <ul v-if="sftpCreds?.keys?.length" class="job-list mt">
        <li v-for="k in sftpCreds.keys" :key="k.id">
          <span>{{ k.name || 'key' }} · {{ k.fingerprint }}</span>
          <button type="button" class="btn-ghost" @click="emit('removeSftpKey', k.id)">Remove</button>
        </li>
      </ul>
      <div class="toolbar mt" style="flex-wrap: wrap; gap: 0.5rem">
        <input
          :value="sftpKeyName"
          class="text-input"
          placeholder="Key name (optional)"
          @input="emit('update:sftpKeyName', ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="sftpKeyInput"
          class="text-input grow"
          placeholder="ssh-ed25519 AAAA… comment"
          @input="emit('update:sftpKeyInput', ($event.target as HTMLInputElement).value)"
        />
        <button type="button" class="btn-primary" @click="emit('addSftpKey')">Add key</button>
      </div>

      <h3 class="mt">Legacy FTP</h3>
      <p class="muted">
        Separate username and password from SSH/SFTP. Kept for WordPress “FTP credentials” prompts.
        Prefer SFTP above for normal uploads.
      </p>

      <p v-if="ftpInfo === 'Loading…'" class="muted mt">Loading…</p>
      <p v-else-if="ftpCreds?.error" class="empty-note mt err">{{ ftpCreds.error }}</p>

      <div v-else-if="ftpCreds?.username" class="cred-list mt">
        <div class="cred-row">
          <div>
            <p class="cred-label">FTP host</p>
            <p class="cred-value mono">{{ ftpCreds.host }}</p>
            <p class="hint">FileZilla → Host. Port {{ ftpCreds.port || 21 }}. Protocol FTP (not SFTP).</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('ftp-host', ftpCreds.host)">
            {{ copiedKey === 'ftp-host' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">WordPress hostname</p>
            <p class="cred-value mono">{{ ftpCreds.wordpress_host || 'localhost' }}</p>
            <p class="hint">If WordPress asks for an FTP hostname, enter this — not a server address.</p>
          </div>
          <button
            type="button"
            class="btn-ghost"
            @click="copyValue('ftp-wp', ftpCreds.wordpress_host || 'localhost')"
          >
            {{ copiedKey === 'ftp-wp' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">FTP username</p>
            <p class="cred-value">{{ ftpCreds.username }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('ftp-user', ftpCreds.username)">
            {{ copiedKey === 'ftp-user' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div class="grow">
            <p class="cred-label">FTP password</p>
            <p class="cred-value mono">
              <template v-if="showFtpPassword && ftpCreds.password">{{ ftpCreds.password }}</template>
              <template v-else-if="ftpCreds.password_set || ftpCreds.password">••••••••••••</template>
              <template v-else>Not ready yet</template>
            </p>
          </div>
          <div class="row-actions">
            <button type="button" class="btn-ghost" @click="toggleFtpPassword">
              {{ showFtpPassword ? 'Hide' : 'Show' }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!ftpCreds.password"
              @click="copyValue('ftp-pass', ftpCreds.password)"
            >
              {{ copiedKey === 'ftp-pass' ? 'Copied' : 'Copy password' }}
            </button>
          </div>
        </div>
        <p v-if="ftpCreds.message || ftpCreds.hint" class="hint mt">
          {{ ftpCreds.message || ftpCreds.hint }}
        </p>
      </div>

      <div v-else class="empty-note mt">
        Optional FTP account for WordPress prompts.
      </div>

      <div class="toolbar mt">
        <button type="button" class="btn-ghost" @click="emit('ensureFtp', false)">
          {{ ftpCreds?.username ? 'Refresh FTP login' : 'Create FTP account' }}
        </button>
        <button
          v-if="ftpCreds?.username"
          type="button"
          class="btn-ghost"
          @click="emit('ensureFtp', true)"
        >
          Reset password
        </button>
        <button
          v-if="isWordpressInstalled"
          type="button"
          class="btn-ghost"
          @click="emit('repairFs')"
        >
          Fix WordPress file access
        </button>
      </div>

      <h3 class="mt">SSH access</h3>
      <p class="muted">
        Every site gets the shared access host. SSH unlocks from ₵{{ sshCreds?.min_price_ghs || 300 }}/month on eligible packs.
        When enabled, SSH uses the same Unix login as SFTP — not the FTP password.
      </p>
      <p v-if="sshCreds?.error" class="empty-note mt err">{{ sshCreds.error }}</p>
      <div v-else class="cred-list mt">
        <div class="cred-row">
          <div>
            <p class="cred-label">Shared host</p>
            <p class="cred-value mono">{{ sshCreds?.host || 'ssh.ifnotus.space' }}</p>
            <p class="hint">Not the operator server address.</p>
          </div>
        </div>
        <div v-if="sshCreds?.shared_ip" class="cred-row">
          <div>
            <p class="cred-label">Shared IP</p>
            <p class="cred-value mono">{{ sshCreds.shared_ip }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('ssh-ip', sshCreds.shared_ip)">
            {{ copiedKey === 'ssh-ip' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">SSH</p>
            <p class="cred-value">{{ sshCreds?.ssh_allowed ? 'Enabled' : 'Not included on this pack' }}</p>
            <p class="hint">{{ sshCreds?.hint || sshCreds?.message }}</p>
          </div>
        </div>
        <div v-if="sshCreds?.command" class="cred-row">
          <div>
            <p class="cred-label">Connect</p>
            <p class="cred-value mono">{{ sshCreds.command }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('ssh-cmd', sshCreds.command)">
            {{ copiedKey === 'ssh-cmd' ? 'Copied' : 'Copy' }}
          </button>
        </div>
      </div>
      <div class="toolbar mt">
        <button type="button" class="btn-ghost" @click="emit('ensureSsh')">Enable SSH for this pack</button>
      </div>
    </div>

    <div v-else-if="siteTab === 'mail' && !canMail" class="block">
      <p>{{ packLocked('Email') }}</p>
    </div>
    <div v-else-if="siteTab === 'mail'" class="block">
      <PortalMailPanel
        :environment-id="activeEnv.id"
        :domain="activeEnv.domain"
        :mailbox-limit="activeEnv.capabilities?.mail?.mailboxes ?? activeEnv.capabilities?.mailboxes ?? null"
        :storage-limit-mb="activeEnv.capabilities?.mail?.storage_mb ?? null"
      />
    </div>

    <div v-else class="protect-pane">
      <PortalDomainTools
        :environment-id="activeEnv.id"
        :can-redirects="envCan(activeEnv, 'redirects')"
        :can-git="envCan(activeEnv, 'git')"
        :repos-limit="Number(activeEnv.capabilities?.repos ?? 1)"
        :mailboxes-limit="activeEnv.capabilities?.mailboxes == null ? null : Number(activeEnv.capabilities.mailboxes)"
      />
    </div>
  </section>
</template>

<style scoped>
.site-panel { display: flex; flex-direction: column; gap: 1rem; }
.site-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.1rem 1.2rem;
  border-radius: 1rem;
  background: var(--if-surface);
  border: 1px solid var(--if-border);
  box-shadow: var(--shadow-card);
}
.eyebrow {
  margin: 0 0 0.25rem;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent, var(--if-plan));
}
.site-head h2 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.25rem;
  letter-spacing: -0.03em;
}
.head-actions { display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center; }
.p-banner, .iso-banner {
  padding: 0.85rem 1rem;
  border-radius: 0.85rem;
  background: color-mix(in srgb, var(--if-plan) 10%, var(--if-surface));
  border: 1px solid color-mix(in srgb, var(--if-plan) 25%, var(--if-border));
  color: var(--if-ink);
  font-size: 0.84rem;
  line-height: 1.45;
}
.p-banner strong, .iso-banner strong { color: var(--p-accent, var(--if-plan)); }
.subtabs {
  display: flex;
  gap: 0.3rem;
  padding: 0.28rem;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  border-radius: 999px;
  background: color-mix(in srgb, var(--if-border) 50%, var(--if-surface));
}
.subtabs button {
  border: none;
  background: transparent;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 650;
  color: var(--if-muted);
  cursor: pointer;
  white-space: nowrap;
}
.subtabs button.on {
  background: var(--if-surface);
  color: var(--if-ink);
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.06);
}
.subtabs button.off {
  opacity: 0.45;
}
.grid-2 { display: grid; gap: 1rem; }
@media (min-width: 900px) { .grid-2 { grid-template-columns: 1fr 1fr; } }
.protect-grid { display: grid; gap: 1rem; }
@media (min-width: 800px) {
  .protect-grid { grid-template-columns: 1fr 1fr; }
  .protect-grid .wide { grid-column: 1 / -1; }
}
.block {
  background: var(--if-surface);
  border: 1px solid var(--if-border);
  border-radius: 1rem;
  padding: 1.05rem 1.1rem;
  box-shadow: var(--shadow-card);
}
.block h3 { margin: 0 0 0.35rem; font-size: 0.95rem; font-weight: 650; }
.toolbar { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.path-chip {
  font-size: 0.75rem;
  color: var(--if-muted);
  font-family: ui-monospace, monospace;
  padding: 0.25rem 0.5rem;
  border-radius: 0.4rem;
  background: color-mix(in srgb, var(--if-border) 40%, white);
}
.file-list {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0;
  max-height: 18rem;
  overflow: auto;
  border: 1px solid var(--if-border);
  border-radius: 0.7rem;
}
.file-list li {
  display: flex;
  gap: 0.55rem;
  align-items: center;
  padding: 0.55rem 0.75rem;
  cursor: pointer;
  font-size: 0.85rem;
  border-bottom: 1px solid color-mix(in srgb, var(--if-border) 65%, white);
}
.file-list li.on {
  background: color-mix(in srgb, var(--if-plan) 12%, var(--if-surface));
}
.studio-split {
  display: grid;
  gap: 0.85rem;
}
@media (min-width: 800px) {
  .studio-split { grid-template-columns: 12rem 1fr; }
}
.db-scroll {
  overflow: auto;
  max-height: 18rem;
  border: 1px solid var(--if-border);
  border-radius: 0.7rem;
}
.db-grid {
  border-collapse: collapse;
  font-size: 0.75rem;
  width: max-content;
  min-width: 100%;
}
.db-grid th, .db-grid td {
  padding: 0.35rem 0.55rem;
  border-bottom: 1px solid var(--if-border);
  text-align: left;
  white-space: nowrap;
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.db-grid th { color: var(--if-muted); font-weight: 650; }
.db-sql {
  width: 100%;
  box-sizing: border-box;
  border-radius: 0.7rem;
  border: 1px solid var(--if-border);
  padding: 0.55rem 0.7rem;
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  background: var(--if-surface);
  color: var(--if-ink);
}
.file-list li:hover { background: color-mix(in srgb, var(--if-plan) 7%, white); }
.file-list .empty { cursor: default; color: var(--if-muted); }
.ftype {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--p-accent, var(--if-plan));
  min-width: 2.4rem;
}
.editor-head { display: flex; justify-content: space-between; gap: 0.75rem; align-items: center; margin-bottom: 0.55rem; }
.editor {
  width: 100%;
  border: 1px solid var(--if-border);
  border-radius: 0.65rem;
  padding: 0.7rem;
  font-family: ui-monospace, monospace;
  font-size: 0.78rem;
  min-height: 16rem;
  background: #fff;
  color: var(--if-ink);
}
.empty-box {
  border: 1px dashed var(--if-border);
  border-radius: 0.75rem;
  padding: 2rem 1rem;
  text-align: center;
}
.empty-box p { margin: 0; }
.empty-box .muted { margin-top: 0.35rem; }
.form-row { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.form-row .grow { flex: 1 1 12rem; }
.job-list { list-style: none; margin: 0; padding: 0; }
.job-list li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-top: 1px solid var(--if-border);
}
.row-actions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.info-line {
  margin: 0;
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
  background: color-mix(in srgb, var(--if-border) 35%, white);
  font-size: 0.85rem;
  word-break: break-word;
}
.env-name { margin: 0; font-weight: 650; font-size: 0.92rem; }
.muted { color: var(--if-muted); font-size: 0.84rem; margin: 0; }
.mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.mt { margin-top: 0.75rem; }
.block.mt, .select.block { display: block; width: 100%; }
.select, .input {
  border: 1px solid var(--if-border);
  border-radius: 0.5rem;
  padding: 0.45rem 0.6rem;
  font-size: 0.85rem;
  background: #fff;
  color: var(--if-ink);
}
.input { min-width: 8rem; }
.btn-primary {
  border: none;
  border-radius: 0.55rem;
  background: var(--p-accent, var(--if-primary));
  color: #fff;
  font-weight: 650;
  font-size: 0.84rem;
  padding: 0.5rem 0.9rem;
  cursor: pointer;
}
.btn-primary:hover { filter: brightness(0.92); }
.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  filter: none;
}
.tiny { font-size: 0.78rem; margin: 0.15rem 0 0.35rem; }
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
.install-panel {
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.85rem;
  padding: 0.95rem 1rem;
  background: color-mix(in srgb, var(--p-accent, var(--if-plan)) 6%, white);
}
.install-panel.success {
  background: #f0faf4;
  border-color: #b7e4c7;
}
.install-panel.error {
  background: #fff5f5;
  border-color: #f0c2c2;
}
.install-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.9rem;
  color: var(--p-ink, var(--if-ink));
}
.install-head .pct {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  color: var(--p-accent, var(--if-plan));
  font-size: 0.8rem;
}
.install-panel .meter {
  margin-top: 0.65rem;
  height: 0.4rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--p-border, var(--if-border)) 70%, white);
  overflow: hidden;
}
.install-panel .meter i {
  display: block;
  height: 100%;
  background: var(--p-accent, var(--if-plan));
  border-radius: inherit;
  transition: width 0.35s ease;
}
.install-label {
  margin: 0.65rem 0 0;
  font-size: 0.84rem;
  line-height: 1.45;
  color: var(--p-muted, var(--if-muted));
}
.install-panel.error .install-label {
  color: #9b1c1c;
  font-weight: 550;
}
.install-panel.success .install-label {
  color: #0f7a45;
  font-weight: 550;
}
.step-list {
  list-style: none;
  margin: 0.85rem 0 0;
  padding: 0;
  display: grid;
  gap: 0.4rem;
}
.step-list li {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  font-size: 0.8rem;
  color: var(--p-muted, var(--if-muted));
}
.step-list li .dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  background: var(--p-border, var(--if-border));
  flex-shrink: 0;
}
.step-list li.done { color: var(--p-ink, var(--if-ink)); }
.step-list li.done .dot { background: #0f7a45; }
.step-list li.active {
  color: var(--p-accent, var(--if-plan));
  font-weight: 650;
}
.step-list li.active .dot {
  background: var(--p-accent, var(--if-plan));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--p-accent, var(--if-plan)) 22%, transparent);
}
.step-list li.failed { color: #9b1c1c; font-weight: 650; }
.step-list li.failed .dot { background: #b42318; }
.install-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.9rem;
}
.files-launch h3 {
  margin: 0;
  font-size: 1.05rem;
}
.files-launch > .muted {
  margin-top: 0.4rem;
  max-width: 36rem;
}
.err-hint {
  margin: 0.7rem 0 0;
  font-size: 0.78rem;
  color: #7f1d1d;
  line-height: 1.4;
}
.badge-ok {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #0f7a45;
  background: #e7f8ee;
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
}
.support-hint {
  margin: 0.9rem 0 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--p-muted, var(--if-muted));
}
.support-hint.err { color: #7f1d1d; }
.linkish {
  border: none;
  background: none;
  padding: 0;
  color: var(--p-accent, var(--if-plan));
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.reinstall {
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.85rem;
  padding: 0.75rem 1rem;
  background: var(--p-surface, var(--if-surface));
}
.reinstall summary {
  cursor: pointer;
  font-size: 0.84rem;
  font-weight: 650;
  color: var(--p-ink, var(--if-ink));
}
.cred-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.cred-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  padding: 0.85rem 0.95rem;
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.85rem;
  background: color-mix(in srgb, var(--p-paper, var(--if-paper)) 55%, white);
}
.cred-label {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--p-muted, var(--if-muted));
}
.cred-value {
  margin: 0.2rem 0 0;
  font-size: 0.95rem;
  font-weight: 650;
  color: var(--p-ink, var(--if-ink));
  word-break: break-all;
}
.cred-value.mono { font-family: ui-monospace, monospace; font-size: 0.86rem; }
.hint {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  color: var(--p-muted, var(--if-muted));
  line-height: 1.4;
}
.empty-note {
  margin: 0;
  padding: 0.9rem 1rem;
  border-radius: 0.75rem;
  background: color-mix(in srgb, var(--p-border, var(--if-border)) 40%, white);
  font-size: 0.86rem;
  color: var(--p-ink, var(--if-ink));
  line-height: 1.45;
}
.empty-note.err { background: #fff5f5; color: #9b1c1c; }
.ok-note {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 650;
  color: #0f7a45;
}
.stack-telemetry-card {
  border: 1px solid rgba(14, 165, 233, 0.25);
  background: linear-gradient(135deg, rgba(240, 249, 255, 0.95), rgba(224, 242, 254, 0.65));
  border-radius: 0.85rem;
  padding: 1.15rem;
  margin-bottom: 1.25rem;
}
.dark .stack-telemetry-card {
  border-color: rgba(56, 189, 248, 0.2);
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(12, 74, 110, 0.25));
}
.stk-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid rgba(14, 165, 233, 0.2);
}
.stk-id-block {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}
.stk-pill {
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  background: #0284c7;
  color: #fff;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
}
.stk-token-wrap {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
}
.stk-token-label {
  color: #64748b;
  font-weight: 500;
}
.dark .stk-token-label { color: #94a3b8; }
.stk-token-val {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 700;
  font-size: 0.82rem;
  color: #0369a1;
  background: rgba(255, 255, 255, 0.8);
  padding: 0.2rem 0.45rem;
  border-radius: 0.35rem;
  border: 1px solid rgba(14, 165, 233, 0.3);
}
.dark .stk-token-val {
  background: rgba(15, 23, 42, 0.8);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.3);
}
.stk-copy-btn {
  background: transparent;
  border: 1px solid rgba(14, 165, 233, 0.4);
  color: #0284c7;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.18rem 0.45rem;
  border-radius: 0.35rem;
  cursor: pointer;
  transition: all 0.15s;
}
.stk-copy-btn:hover {
  background: #0284c7;
  color: #fff;
}
.dark .stk-copy-btn { color: #38bdf8; border-color: rgba(56, 189, 248, 0.4); }
.dark .stk-copy-btn:hover { background: #38bdf8; color: #0f172a; }
.stk-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #047857;
  background: #d1fae5;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  border: 1px solid #a7f3d0;
}
.dark .stk-status-badge {
  background: rgba(6, 78, 59, 0.4);
  color: #34d399;
  border-color: rgba(52, 211, 153, 0.3);
}
.stk-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}
.stk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.75rem;
  margin-top: 0.9rem;
}
.stk-metric {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  background: rgba(255, 255, 255, 0.65);
  padding: 0.6rem 0.75rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(14, 165, 233, 0.15);
}
.dark .stk-metric {
  background: rgba(15, 23, 42, 0.55);
  border-color: rgba(56, 189, 248, 0.15);
}
.stk-lbl {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
  color: #64748b;
}
.dark .stk-lbl { color: #94a3b8; }
.stk-num {
  font-size: 0.88rem;
  font-weight: 700;
  color: #0f172a;
}
.dark .stk-num { color: #f1f5f9; }
.stk-sub {
  font-size: 0.68rem;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.dark .stk-sub { color: #94a3b8; }

.grow { flex: 1; min-width: 0; }
.stack-pick {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: 0.55rem;
}
.stack-opt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 0.75rem 0.4rem;
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.8rem;
  background: #fff;
  cursor: pointer;
  font: inherit;
}
.stack-opt strong { font-size: 0.72rem; }
.stack-opt em { font-style: normal; font-size: 0.62rem; color: var(--p-muted, var(--if-muted)); }
.stack-opt.on { border-color: var(--p-accent, var(--if-primary)); background: var(--p-accent-soft, #ecfdf5); }
.stack-opt.is-matrix:not(.on) { opacity: 0.92; border-style: dashed; }
.stack-opt.faded,
.stack-opt:disabled {
  opacity: 0.42;
  filter: grayscale(0.4);
  cursor: not-allowed;
}
.stack-pick.pack {
  list-style: none;
  margin: 0.65rem 0 0;
  padding: 0;
}
.stack-pick.pack li {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 0.75rem 0.4rem;
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.8rem;
  background: #fff;
  text-align: center;
}
.stack-pick.pack strong { font-size: 0.72rem; }
.stack-pick.pack em { font-style: normal; font-size: 0.62rem; color: var(--p-muted, var(--if-muted)); }
.stack-pick.pack li.faded { opacity: 0.42; filter: grayscale(0.35); }
.pack-soft h3 { margin: 0; font-size: 0.92rem; }
.log-view {
  margin: 0.75rem 0 0;
  max-height: 28rem;
  overflow: auto;
  padding: 0.85rem 1rem;
  border-radius: 0.75rem;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 0.75rem;
  line-height: 1.45;
  white-space: pre-wrap;
}
.steps-ns {
  margin: 0.7rem 0 0;
  padding-left: 1.15rem;
  color: #5c6670;
  font-size: 0.86rem;
  line-height: 1.5;
}
.dns-mode-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.dns-mode-tab {
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  font-size: 0.78rem;
  color: #334155;
  cursor: pointer;
}
.dns-mode-tab.active {
  background: #0f172a;
  border-color: #0f172a;
  color: #fff;
}
.db-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
}
.db-head .btn-primary {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.studio-tabs {
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
  margin-bottom: 0.55rem;
}
.studio-tabs .on {
  font-weight: 700;
  color: #1e3a5f;
  font-size: 0.9rem;
}
.studio-tabs .muted-tab {
  font-size: 0.8rem;
  color: #5c6670;
}
.dns-check {
  border: 1px solid var(--if-border, #d7dee8);
  border-radius: 0.85rem;
  padding: 0.85rem 1rem;
  background: color-mix(in srgb, var(--if-surface, #fff) 92%, #eef2f6);
}
.status-summary {
  margin: 0 0 0.65rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--if-ink, #0f172a);
  line-height: 1.4;
}
.status-summary.ok { color: #1e3a5f; }
.status-summary.wait { color: #5b6b7c; }
.check-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.check-list li {
  display: flex;
  gap: 0.55rem;
  align-items: flex-start;
}
.check-list .mark {
  width: 1.1rem;
  flex-shrink: 0;
  font-weight: 700;
  color: #94a3b8;
  line-height: 1.35;
}
.check-list li.done .mark { color: #1e3a5f; }
.check-label {
  margin: 0;
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--if-ink, #0f172a);
}
.panel-a { color: #1e3a5f; font-weight: 600; }

/* Applications UI styling */
.apps-head-box {
  margin-bottom: 1.25rem;
}
.apps-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 100%;
}
.app-family-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.app-family-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
  text-align: left;
  padding: 1.25rem 1.15rem;
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1rem;
  background: #fff;
  cursor: pointer;
}
.app-family-card i {
  font-size: 1.6rem;
  color: #2563eb;
}
.app-family-card strong {
  font-size: 1.05rem;
}
.app-family-card span,
.app-family-card em {
  font-size: 0.85rem;
  color: #64748b;
}
.apps-help-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 52rem;
}
.apps-help-hero h3,
.apps-help-page h3 {
  margin: 0.25rem 0 0.5rem;
}
.apps-help-kicker {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #2563eb;
}
.apps-help-steps {
  margin: 0;
  padding-left: 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  line-height: 1.45;
}
.apps-help-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
}
.app-family-card em {
  font-size: 0.82rem;
  color: #64748b;
  font-style: normal;
}
.dark .app-family-card {
  background: #111827;
  border-color: #1e293b;
}
.apps-list-card,
.app-create-card {
  background: var(--p-surface, #fff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.85rem;
  padding: 1.25rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.dark .apps-list-card,
.dark .app-create-card {
  background: #111827;
  border-color: #1e293b;
}
.apps-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--p-border, #f1f5f9);
}
.apps-card-header h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: var(--p-ink, #0f172a);
}
.app-create-header {
  align-items: flex-start;
  gap: 0.8rem;
}
.app-create-subtitle {
  margin: 0.3rem 0 0;
  font-size: 0.82rem;
  color: #64748b;
}
.apps-count-badge {
  font-size: 0.72rem;
  font-weight: 600;
  background: #f1f5f9;
  color: #475569;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
}
.dark .apps-count-badge {
  background: #1e293b;
  color: #94a3b8;
}
.framework-badge {
  white-space: nowrap;
}
.app-items-grid {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.app-card-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
}
.dark .app-card-item {
  background: #1e293b;
  border-color: #334155;
}
.app-card-main {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.app-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.app-icon-tag {
  color: #0284c7;
  font-size: 0.95rem;
}
.app-title {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
}
.dark .app-title {
  color: #f8fafc;
}
.app-meta-row {
  display: flex;
  gap: 0.85rem;
  font-size: 0.78rem;
  color: #64748b;
}
.app-card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}
.app-act {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  background: #f8fafc;
  color: #334155;
}
.app-act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.app-act i {
  font-size: 0.72rem;
}
.app-act-edit {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
}
.app-act-edit i { color: #2563eb; }
.app-act-refresh {
  color: #0f766e;
  background: #f0fdfa;
  border-color: #99f6e4;
}
.app-act-refresh i { color: #0d9488; }
.app-act-restart {
  color: #b45309;
  background: #fffbeb;
  border-color: #fcd34d;
}
.app-act-restart i { color: #d97706; }
.app-act-stop {
  color: #9a3412;
  background: #fff7ed;
  border-color: #fdba74;
}
.app-act-stop i { color: #ea580c; }
.app-act-start,
.app-act-deploy,
.app-act-save {
  color: #166534;
  background: #f0fdf4;
  border-color: #86efac;
}
.app-act-start i,
.app-act-deploy i,
.app-act-save i { color: #16a34a; }
.app-act-delete {
  color: #b91c1c;
  background: #fef2f2;
  border-color: #fecaca;
}
.app-act-delete i { color: #dc2626; }
.app-act-cancel {
  color: #475569;
  background: #f8fafc;
  border-color: #e2e8f0;
}
.app-edit-panel {
  width: 100%;
  flex-basis: 100%;
  margin-top: 0.35rem;
  padding: 0.85rem 0.95rem;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  background: #fff;
}
.app-edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.65rem;
}
.app-edit-grid .field span {
  display: block;
  font-size: 0.72rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 0.25rem;
}
.app-edit-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.app-env-block {
  margin-top: 0.85rem;
  padding-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
}
.app-env-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.55rem;
}
.app-env-help {
  margin: 0.2rem 0 0;
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.35;
}
.app-env-empty {
  font-size: 0.78rem;
  color: #94a3b8;
  margin-bottom: 0.35rem;
}
.app-env-row {
  display: grid;
  grid-template-columns: minmax(7rem, 0.9fr) minmax(8rem, 1.2fr) auto;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}
.app-env-row input {
  width: 100%;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.45rem 0.55rem;
  font-size: 0.8rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.app-act-add,
.app-act-remove {
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 0.5rem;
  padding: 0.4rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}
.app-act-remove {
  padding: 0.4rem 0.55rem;
  color: #b91c1c;
}
.app-path-row {
  margin-top: 0.25rem;
  font-size: 0.78rem;
  opacity: 0.88;
}
.app-error-msg {
  margin: 0.55rem 0 0;
  padding: 0.55rem 0.65rem;
  font-size: 0.72rem;
  line-height: 1.4;
  border-radius: 0.5rem;
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 10rem;
  overflow: auto;
}
.app-serve-link {
  color: var(--if-plan, #0b5fff);
  text-decoration: underline;
}
.app-root-tree {
  margin: 0.5rem 0 0;
  padding: 0.55rem 0.7rem;
  font-size: 0.72rem;
  line-height: 1.45;
  border-radius: 0.55rem;
  background: #f3f4f6;
  color: #334155;
  white-space: pre;
  overflow-x: auto;
}
.app-root-fields {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: min(100%, 15rem);
}
.app-serve-check {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.78rem;
  color: #475569;
}
.btn-sm {
  padding: 0.35rem 0.75rem !important;
  font-size: 0.78rem !important;
}
.apps-empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 1rem;
  text-align: center;
  color: #64748b;
}
.empty-icon {
  font-size: 2rem;
  color: #94a3b8;
  margin-bottom: 0.65rem;
}
.app-create-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.app-form-section {
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.85rem;
  background: #f8fafc;
  padding: 1rem 1.05rem;
}
.dark .app-form-section {
  background: #0f172a;
  border-color: #334155;
}
.app-control-list {
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}
.app-control-row {
  display: grid;
  grid-template-columns: minmax(180px, 220px) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}
.app-control-meta {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding-top: 0.2rem;
}
.app-control-title {
  font-size: 0.84rem;
  font-weight: 700;
  color: var(--p-ink, #0f172a);
}
.dark .app-control-title {
  color: #f8fafc;
}
.app-control-help {
  margin: 0;
  font-size: 0.76rem;
  line-height: 1.45;
  color: #64748b;
}
.app-control-input {
  margin: 0;
}
.app-readonly-pill {
  min-height: 2.65rem;
  display: inline-flex;
  align-items: center;
  padding: 0.68rem 0.85rem;
  border-radius: 0.7rem;
  border: 1px solid var(--p-border, #d7dee8);
  background: #fff;
  color: var(--p-ink, #0f172a);
  font-size: 0.9rem;
  font-weight: 600;
}
.dark .app-readonly-pill {
  background: #111827;
  border-color: #334155;
  color: #f8fafc;
}
.app-form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.85rem;
}
.app-form-grid.compact {
  gap: 0.75rem;
}
.field-span-full {
  grid-column: 1 / -1;
}
.app-section-label {
  margin-bottom: 0.75rem;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #475569;
}
.app-help-note {
  margin: 0.75rem 0 0;
}
@media (min-width: 720px) {
  .app-form-grid {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 820px) {
  .app-control-row {
    grid-template-columns: 1fr;
    gap: 0.55rem;
  }
}
.btn-create-app {
  width: 100%;
  margin-top: 0.5rem;
  justify-content: center;
}

/* ─────────────────────────────────────────────────────────────
   DATABASE MANAGEMENT & STEP 2 WORKFLOW STYLING
   ───────────────────────────────────────────────────────────── */
.db-management-section {
  display: flex;
  flex-direction: column;
}
.db-title-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.25rem;
}
.db-title-row h3 {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.db-badge-mysql {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
}
.dark .db-badge-mysql {
  background: rgba(22, 101, 52, 0.2);
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.3);
}

.db-head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.pma-btn {
  background: #0284c7 !important;
  border-color: #0284c7 !important;
  color: #fff !important;
  font-weight: 650 !important;
}
.pma-btn:hover {
  background: #0369a1 !important;
}
.btn-import-sql {
  color: #0f766e !important;
  border-color: #99f6e4 !important;
  background: #f0fdfa !important;
}
.dark .btn-import-sql {
  background: rgba(15, 118, 110, 0.2) !important;
  border-color: rgba(45, 212, 191, 0.3) !important;
  color: #5eead4 !important;
}

/* Compact Database Header & Toolbar */
.db-head-compact {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--p-border, #e2e8f0);
}
.dark .db-head-compact {
  border-bottom-color: #334155;
}

/* Compact Creation Card */
.db-create-compact {
  background: var(--p-surface, #f8fafc);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.75rem;
  padding: 0.85rem 1rem;
}
.dark .db-create-compact {
  background: #0f172a;
  border-color: #1e293b;
}
.db-compact-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.db-compact-title {
  font-size: 0.82rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--p-ink, #0f172a);
}
.db-compact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.65rem;
}
.field-compact {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.label-tiny {
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--p-muted, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.input-compact {
  width: 100%;
  padding: 0.4rem 0.6rem;
  border-radius: 0.5rem;
  border: 1px solid var(--p-border, #cbd5e1);
  background: var(--p-card-bg, #ffffff);
  color: var(--p-ink, #0f172a);
  font-size: 0.82rem;
  outline: none;
}
.dark .input-compact {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.input-compact:focus {
  border-color: #0284c7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}
.input-with-mini-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
.btn-mini-ico {
  background: var(--p-card-bg, #ffffff);
  border: 1px solid var(--p-border, #cbd5e1);
  border-radius: 0.5rem;
  padding: 0.4rem 0.55rem;
  font-size: 0.75rem;
  color: #64748b;
  cursor: pointer;
}
.dark .btn-mini-ico {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}
.btn-mini-ico:hover {
  color: #0284c7;
  border-color: #0284c7;
}
.db-compact-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.btn-sm {
  padding: 0.4rem 0.85rem !important;
  font-size: 0.8rem !important;
}

/* Compact Table Section */
.db-table-section {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.75rem;
  overflow: hidden;
}
.dark .db-table-section {
  background: #111827;
  border-color: #1e293b;
}
.table-responsive {
  width: 100%;
  overflow-x: auto;
}
.db-compact-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.82rem;
}
.db-compact-table th {
  background: var(--p-table-head, #f8fafc);
  color: var(--p-muted, #64748b);
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--p-border, #e2e8f0);
  white-space: nowrap;
}
.dark .db-compact-table th {
  background: #0f172a;
  border-color: #1e293b;
  color: #94a3b8;
}
.db-compact-table td {
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--p-border, #f1f5f9);
  vertical-align: middle;
  color: var(--p-ink, #0f172a);
}
.dark .db-compact-table td {
  border-color: #1e293b;
  color: #f1f5f9;
}
.db-compact-table tr:last-child td {
  border-bottom: none;
}
.db-compact-table tr {
  cursor: pointer;
  transition: background 0.15s ease;
}
.db-compact-table tr:hover {
  background: #f8fafc;
}
.dark .db-compact-table tr:hover {
  background: rgba(30, 41, 59, 0.5);
}
.db-compact-table tr.row-active {
  background: #f0f9ff;
}
.dark .db-compact-table tr.row-active {
  background: rgba(2, 132, 199, 0.15);
}

.db-name-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 650;
}
.db-row-ico {
  color: #0284c7;
  font-size: 0.85rem;
}
.db-sub-name {
  font-size: 0.72rem;
  color: #64748b;
  font-weight: normal;
}
.db-engine-chip {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.03em;
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}
.db-engine-chip.postgresql {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}
.dark .db-engine-chip {
  background: rgba(22, 101, 52, 0.25);
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.3);
}
.dark .db-engine-chip.postgresql {
  background: rgba(29, 78, 216, 0.25);
  color: #60a5fa;
  border-color: rgba(59, 130, 246, 0.3);
}
.mono-text {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  color: #334155;
}
.dark .mono-text {
  color: #cbd5e1;
}
.size-text {
  font-size: 0.76rem;
  color: #64748b;
}

.th-actions {
  text-align: right;
}
.td-actions {
  text-align: right;
}
.action-btn-group {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  justify-content: flex-end;
}
.btn-tbl-action {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 600;
  border-radius: 0.45rem;
  border: 1px solid var(--p-border, #cbd5e1);
  background: var(--p-card-bg, #ffffff);
  color: var(--p-ink, #334155);
  cursor: pointer;
  transition: all 0.15s ease;
}
.dark .btn-tbl-action {
  background: #1e293b;
  border-color: #334155;
  color: #e2e8f0;
}
.btn-tbl-action:hover:not(:disabled) {
  border-color: #0284c7;
  color: #0284c7;
}
.btn-tbl-action.pma {
  background: #0284c7;
  border-color: #0284c7;
  color: #ffffff !important;
}
.btn-tbl-action.pma:hover {
  background: #0369a1;
}
.btn-tbl-action.import {
  background: #f0fdfa;
  border-color: #99f6e4;
  color: #0f766e;
}
.dark .btn-tbl-action.import {
  background: rgba(15, 118, 110, 0.2);
  border-color: rgba(45, 212, 191, 0.3);
  color: #5eead4;
}
.btn-tbl-action.active-cred-btn {
  border-color: #0284c7;
  background: #e0f2fe;
  color: #0369a1;
}
.dark .btn-tbl-action.active-cred-btn {
  background: rgba(2, 132, 199, 0.25);
  color: #38bdf8;
}
.btn-tbl-action.danger:hover:not(:disabled) {
  border-color: #ef4444;
  color: #ef4444;
}

/* Alert Bar */
.db-alert-bar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.6rem 0.85rem;
  border-radius: 0.55rem;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  font-size: 0.8rem;
  font-weight: 600;
}
.db-alert-bar.is-err {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}
.dark .db-alert-bar {
  background: rgba(6, 95, 70, 0.25);
  border-color: rgba(52, 211, 153, 0.3);
  color: #6ee7b7;
}
.dark .db-alert-bar.is-err {
  background: rgba(153, 27, 27, 0.25);
  border-color: rgba(248, 113, 113, 0.3);
  color: #fca5a5;
}

/* Create Database Card */
.db-create-card {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.85rem;
  padding: 1.25rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.dark .db-create-card {
  background: #111827;
  border-color: #1e293b;
}
.card-head-simple {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid var(--p-border, #f1f5f9);
  margin-bottom: 1rem;
}
.card-icon-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.card-icon-title h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.card-badge-muted {
  font-size: 0.72rem;
  font-weight: 600;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #64748b;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
}
.dark .card-badge-muted {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

.db-form-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}
@media (min-width: 640px) {
  .db-form-row {
    grid-template-columns: 1fr 1fr;
  }
}
.mt-sm {
  margin-top: 0.85rem;
}
.field-label-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  margin-bottom: 0.35rem;
}
.field-label-wrap strong {
  font-size: 0.82rem;
  color: var(--p-ink, #0f172a);
}
.sub-hint {
  font-size: 0.72rem;
  color: var(--p-muted, #64748b);
}
.input-with-icon {
  position: relative;
  display: flex;
  align-items: center;
}
.input-with-icon.full-w {
  flex: 1 1 auto;
}
.field-ico {
  position: absolute;
  left: 0.75rem;
  color: #94a3b8;
  font-size: 0.85rem;
  pointer-events: none;
}
.input-with-icon input,
.input-with-icon select {
  width: 100%;
  padding: 0.55rem 0.75rem 0.55rem 2.2rem;
  border: 1px solid var(--p-border, #cbd5e1);
  border-radius: 0.55rem;
  font-size: 0.85rem;
  background: #ffffff;
  color: var(--p-ink, #0f172a);
  transition: border-color 0.15s;
}
.dark .input-with-icon input,
.dark .input-with-icon select {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.input-with-icon input:focus,
.input-with-icon select:focus {
  outline: none;
  border-color: #0284c7;
}

.input-with-addon {
  display: flex;
  align-items: stretch;
  gap: 0.35rem;
}
.btn-addon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 0.45rem 0.65rem;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}
.dark .btn-addon {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.btn-addon:hover {
  background: #e2e8f0;
}
.dark .btn-addon:hover {
  background: #334155;
}
.btn-generate {
  color: #0284c7;
}
.dark .btn-generate {
  color: #38bdf8;
}

.db-create-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  padding-top: 1rem;
  border-top: 1px solid var(--p-border, #f1f5f9);
}
.db-privilege-note {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  color: #059669;
}
.dark .db-privilege-note {
  color: #34d399;
}
.btn-submit-db {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.6rem 1.25rem !important;
  font-size: 0.88rem !important;
  font-weight: 700 !important;
}

/* Databases List Cards Grid */
.db-list-section {
  display: flex;
  flex-direction: column;
}
.section-title-bar {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  margin-bottom: 0.5rem;
}
.section-title-bar h4 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.db-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.75rem;
}
.db-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.75rem;
  padding: 0.85rem 1rem;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
}
.dark .db-card {
  background: #111827;
  border-color: #1e293b;
}
.db-card:hover {
  border-color: #93c5fd;
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.db-card.on {
  border-color: #0284c7;
  background: #f0f9ff;
}
.dark .db-card.on {
  border-color: #0284c7;
  background: rgba(2, 132, 199, 0.15);
}
.db-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}
.db-name-group {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.db-card-engine-tag {
  font-size: 0.65rem;
  font-weight: 800;
  padding: 0.15rem 0.45rem;
  border-radius: 0.35rem;
  background: #fef3c7;
  color: #92400e;
}
.db-card-engine-tag.postgresql {
  background: #e0f2fe;
  color: #0369a1;
}
.dark .db-card-engine-tag {
  background: #78350f;
  color: #fef3c7;
}
.db-card-title {
  font-size: 0.92rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.badge-primary-site {
  font-size: 0.65rem;
  font-weight: 700;
  background: #e0e7ff;
  color: #3730a3;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
}
.dark .badge-primary-site {
  background: #312e81;
  color: #c7d2fe;
}
.db-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  font-size: 0.75rem;
  color: var(--p-muted, #64748b);
  margin-bottom: 0.75rem;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.db-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding-top: 0.65rem;
  border-top: 1px solid var(--p-border, #f1f5f9);
}
.btn-card-action {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.28rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 650;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  border-radius: 0.45rem;
  cursor: pointer;
  transition: all 0.12s;
}
.dark .btn-card-action {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.btn-card-action:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}
.dark .btn-card-action:hover {
  background: #334155;
}
.btn-card-action.pma {
  color: #0284c7;
  border-color: #bae6fd;
}
.btn-card-action.import {
  color: #0f766e;
  border-color: #99f6e4;
}
.btn-card-action.danger {
  color: #dc2626;
}
.btn-card-action.danger:hover {
  background: #fef2f2;
  border-color: #fca5a5;
}

/* Active Database Credentials Box */
.db-creds-box {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.85rem;
  padding: 1.25rem;
}
.dark .db-creds-box {
  background: #111827;
  border-color: #1e293b;
}
.creds-box-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid var(--p-border, #f1f5f9);
}
.creds-box-head h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.badge-privilege {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
}
.dark .badge-privilege {
  background: rgba(5, 150, 105, 0.2);
  color: #34d399;
  border-color: rgba(52, 211, 153, 0.3);
}
.creds-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}
.cred-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 0.75rem 0.85rem;
}
.dark .cred-item {
  background: #1e293b;
  border-color: #334155;
}
.cred-data {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.cred-key {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}
.cred-val {
  font-size: 0.92rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
  word-break: break-all;
}
.cred-sub {
  font-size: 0.7rem;
  color: #94a3b8;
}
.btn-copy-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.6rem;
  font-size: 0.72rem;
  font-weight: 650;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  border-radius: 0.45rem;
  cursor: pointer;
  flex-shrink: 0;
}
.dark .btn-copy-chip {
  background: #0f172a;
  border-color: #334155;
  color: #cbd5e1;
}
.btn-copy-chip.primary {
  background: #0284c7;
  border-color: #0284c7;
  color: #ffffff;
}
.btn-copy-chip.ghost {
  background: transparent;
  border-color: transparent;
}
.cred-btn-group {
  display: flex;
  gap: 0.25rem;
  align-items: center;
}
.text-green {
  color: #16a34a !important;
}

/* Code Snippet Generator */
.snippet-helper-box {
  background: #0f172a;
  border-radius: 0.75rem;
  padding: 0.85rem 1rem;
  color: #e2e8f0;
}
.snippet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}
.snippet-title {
  font-size: 0.78rem;
  font-weight: 750;
  color: #38bdf8;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.snippet-tabs {
  display: flex;
  gap: 0.3rem;
  background: #1e293b;
  padding: 0.2rem;
  border-radius: 0.5rem;
}
.snippet-tab {
  background: transparent;
  border: none;
  color: #94a3b8;
  padding: 0.25rem 0.55rem;
  border-radius: 0.35rem;
  font-size: 0.72rem;
  font-weight: 650;
  cursor: pointer;
}
.snippet-tab.active {
  background: #0284c7;
  color: #ffffff;
}
.snippet-code-wrap {
  position: relative;
}
.snippet-code {
  margin: 0;
  padding: 0.75rem 0.85rem;
  background: #020617;
  border: 1px solid #1e293b;
  border-radius: 0.5rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  color: #f8fafc;
  line-height: 1.45;
  overflow-x: auto;
}
.btn-copy-snippet {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.65rem;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.35rem;
  color: #ffffff;
  font-size: 0.72rem;
  font-weight: 650;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.btn-copy-snippet:hover {
  background: rgba(255, 255, 255, 0.22);
}

/* SQL Import Modal */
.db-import-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 1rem;
}
.db-import-modal {
  width: 100%;
  max-width: 580px;
  background: #ffffff;
  border-radius: 0.85rem;
  padding: 1.5rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
}
.dark .db-import-modal {
  background: #0f172a;
  border: 1px solid #334155;
}
.modal-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.modal-title-wrap {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.modal-ico {
  font-size: 1.4rem;
  color: #0284c7;
}
.modal-top h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.btn-close-modal {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  color: #94a3b8;
  cursor: pointer;
}
.modal-select {
  width: 100%;
  padding: 0.55rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  font-size: 0.85rem;
  background: #ffffff;
  color: #0f172a;
}
.dark .modal-select {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.sql-dropzone {
  position: relative;
  border: 2px dashed #cbd5e1;
  border-radius: 0.75rem;
  padding: 1.5rem 1rem;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.15s;
}
.dark .sql-dropzone {
  background: #1e293b;
  border-color: #334155;
}
.sql-dropzone:hover {
  border-color: #0284c7;
  background: #f0f9ff;
}
.dropzone-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}
.dropzone-ico {
  font-size: 2rem;
  color: #0284c7;
  margin-bottom: 0.45rem;
}
.file-picked-name {
  font-weight: 700;
  color: #0f172a;
}
.dark .file-picked-name {
  color: #f8fafc;
}
.sql-import-textarea {
  width: 100%;
  padding: 0.65rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  background: #f8fafc;
  color: #0f172a;
}
.dark .sql-import-textarea {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.import-alert {
  padding: 0.65rem 0.85rem;
  border-radius: 0.55rem;
  font-size: 0.82rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.import-alert.success {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}
.import-alert.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.65rem;
}

/* Stack & Hosting Architecture Guide Modal */
.stack-guide-modal-card {
  width: 100%;
  max-width: 840px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  overflow: hidden;
}
.dark .stack-guide-modal-card {
  background: #0f172a;
  border-color: #1e293b;
}
.modal-ico-wrap.info-ico {
  background: #e0f2fe;
  color: #0284c7;
}
.dark .modal-ico-wrap.info-ico {
  background: rgba(2, 132, 199, 0.2);
  color: #38bdf8;
}
.guide-tabs-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.75rem 0 0.5rem;
  border-bottom: 1px solid var(--p-border, #e2e8f0);
}
.dark .guide-tabs-nav {
  border-color: #1e293b;
}
.guide-nav-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.85rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.15s ease;
}
.guide-nav-tab:hover {
  background: #f1f5f9;
  color: #0f172a;
}
.dark .guide-nav-tab:hover {
  background: #1e293b;
  color: #f8fafc;
}
.guide-nav-tab.active {
  background: #0284c7;
  color: #ffffff;
  border-color: #0284c7;
}
.guide-nav-tab.active i {
  color: #ffffff !important;
}
.guide-modal-content {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 1rem 0;
  max-height: calc(85vh - 180px);
}
.guide-panel-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.guide-intro-banner {
  padding: 0.85rem 1.1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
}
.dark .guide-intro-banner {
  background: #1e293b;
  border-color: #334155;
}
.intro-badge {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 750;
  text-transform: uppercase;
  color: #ff6c2c;
  letter-spacing: 0.05em;
  margin-bottom: 0.25rem;
}
.guide-intro-banner h3 {
  margin: 0 0 0.25rem;
  font-size: 1.1rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.guide-intro-banner p {
  margin: 0;
  font-size: 0.84rem;
  color: #64748b;
  line-height: 1.45;
}
.guide-steps-list {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.guide-step-item {
  display: flex;
  gap: 0.85rem;
  padding: 0.85rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: var(--p-surface, #ffffff);
}
.dark .guide-step-item {
  background: #111827;
  border-color: #1e293b;
}
.step-badge {
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #0284c7;
  background: #e0f2fe;
  padding: 0.2rem 0.55rem;
  border-radius: 0.4rem;
  height: fit-content;
  white-space: nowrap;
}
.dark .step-badge {
  background: rgba(2, 132, 199, 0.25);
  color: #38bdf8;
}
.step-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.step-body strong {
  font-size: 0.92rem;
  color: var(--p-ink, #0f172a);
}
.step-body p {
  margin: 0;
  font-size: 0.83rem;
  color: #64748b;
  line-height: 1.5;
}
.guide-code-box {
  margin-top: 0.45rem;
  background: #0f172a;
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  overflow-x: auto;
}
.guide-code-box pre {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  color: #e2e8f0;
  line-height: 1.5;
}

/* Guide trigger buttons */
.btn-guide-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 650;
  color: #ff6c2c;
}
.guide-info-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #0284c7;
  background: #e0f2fe;
  border: 1px solid #bae6fd;
  border-radius: 1rem;
  padding: 0.2rem 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.guide-info-pill:hover {
  background: #0284c7;
  color: #ffffff;
}
.snippet-tab.guide-btn {
  background: #fff7ed;
  color: #ea580c;
  border-color: #ffedd5;
  font-weight: 700;
}
.snippet-tab.guide-btn:hover {
  background: #ea580c;
  color: #ffffff;
}
.stk-actions-top {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.stk-guide-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 0.5rem;
  padding: 0.25rem 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.stk-guide-btn:hover {
  background: #38bdf8;
  color: #0f172a;
}

/* Git Panel Styles */
.git-panel-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.git-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1rem;
}
.git-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}
.git-badge {
  font-size: 0.7rem;
  font-weight: 750;
  text-transform: uppercase;
  color: #ea580c;
  background: #fff7ed;
  border: 1px solid #ffedd5;
  padding: 0.15rem 0.5rem;
  border-radius: 0.4rem;
}
.dark .git-badge {
  background: rgba(234, 88, 12, 0.2);
  border-color: rgba(234, 88, 12, 0.35);
  color: #fb923c;
}
.git-head-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.git-alert-bar {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.75rem 1rem;
  border-radius: 0.65rem;
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
  font-size: 0.85rem;
  font-weight: 600;
}
.git-alert-bar.is-err {
  background: #fef2f2;
  color: #991b1b;
  border-color: #fecaca;
}
.git-status-card,
.git-clone-card {
  background: var(--p-surface, #ffffff);
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.85rem;
  padding: 1.25rem;
  box-shadow: 0 2px 8px -2px rgba(0, 0, 0, 0.04);
}
.dark .git-status-card,
.dark .git-clone-card {
  background: #111827;
  border-color: #1e293b;
}
.git-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #f1f5f9;
}
.dark .git-card-top {
  border-color: #1e293b;
}
.git-repo-ident {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.git-main-ico {
  font-size: 1.6rem;
  color: #ea580c;
}
.git-repo-ident h4 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.git-remote-url {
  margin: 0.15rem 0 0;
  font-size: 0.8rem;
  color: #64748b;
}
.git-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.74rem;
  font-weight: 700;
  padding: 0.25rem 0.65rem;
  border-radius: 1rem;
}
.git-badge-pill.clean {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}
.git-badge-pill.clean .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}
.git-badge-pill.dirty {
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
}
.git-badge-pill.dirty .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f97316;
}
.git-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.85rem;
  margin-top: 1rem;
}
.git-meta-box {
  padding: 0.75rem 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.dark .git-meta-box {
  background: #1e293b;
  border-color: #334155;
}
.git-meta-box .lbl {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #64748b;
}
.git-meta-box .val {
  font-size: 0.95rem;
  font-weight: 750;
  color: var(--p-ink, #0f172a);
}
.val-copy-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.btn-copy-mini {
  font-size: 0.72rem;
  padding: 0.15rem 0.45rem;
  border-radius: 0.35rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
}
.dark .btn-copy-mini {
  background: #334155;
  border-color: #475569;
  color: #f8fafc;
}
.val-sub {
  font-size: 0.78rem;
  color: #64748b;
  word-break: break-all;
}
.git-deploy-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
}
.btn-pull {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-weight: 700;
}
.git-form-grid {
  display: grid;
  grid-template-columns: 1fr minmax(130px, 180px);
  gap: 0.85rem;
}
@media (max-width: 640px) {
  .git-form-grid {
    grid-template-columns: 1fr;
  }
}
.git-clone-btn-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
}

.git-vc-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}
.git-crumbs {
  font-size: 0.85rem;
  color: #64748b;
}
.git-create-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 1.25rem;
  align-items: start;
}
.git-related {
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.5rem;
  padding: 0.85rem 1rem;
  background: #f8fafc;
}
.git-related h5 {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
}
.git-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 650;
}
.git-create-form {
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
  margin-top: 0.75rem;
}
.git-create-form .field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
}
.git-create-form .field > span {
  font-size: 0.8rem;
  font-weight: 700;
  color: #334155;
}
.git-create-form .field .hint {
  margin: 0;
  font-size: 0.74rem;
  line-height: 1.35;
  color: #64748b;
}
.git-create-form .field input,
.git-list-toolbar input[type='search'] {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.55rem 0.75rem;
  font-size: 0.88rem;
  color: #0f172a;
  background: #fff;
  outline: none;
}
.git-create-form .field input:focus,
.git-list-toolbar input[type='search']:focus {
  border-color: var(--hp-accent, #2b4c7e);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--hp-accent, #2b4c7e) 18%, transparent);
}
.git-create-form .field input:disabled {
  opacity: 0.65;
  background: #f8fafc;
}
.git-create-card {
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.75rem;
  padding: 1rem 1.1rem 1.15rem;
  background: #fff;
}
.git-create-card h4 {
  margin: 0 0 0.65rem;
  font-size: 1rem;
}
.git-create-actions,
.git-list-toolbar,
.git-row,
.git-detail-actions,
.git-clone-url {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
}
.git-list-toolbar {
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.git-row {
  border: 1px solid var(--p-border, #e2e8f0);
  border-radius: 0.65rem;
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  align-items: flex-start;
}
.git-row-main {
  flex: 1;
  text-align: left;
  background: none;
  border: 0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.git-row-main code,
.git-row-detail code {
  font-size: 0.8rem;
  word-break: break-all;
}
.git-row-detail {
  width: 100%;
  border-top: 1px solid var(--p-border, #e2e8f0);
  padding-top: 0.75rem;
}
.git-row-detail dl {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 0.35rem 0.75rem;
}
.git-row-detail dt {
  color: #64748b;
  font-size: 0.8rem;
}
.git-clone-url input {
  flex: 1;
  min-width: 12rem;
}
.git-history-list {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.git-empty {
  padding: 1.25rem;
  color: #64748b;
  border: 1px dashed var(--p-border, #cbd5e1);
  border-radius: 0.65rem;
}
.git-another {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
@media (max-width: 800px) {
  .git-create-layout {
    grid-template-columns: 1fr;
  }
  .git-row-detail dl {
    grid-template-columns: 1fr;
  }
}
</style>
