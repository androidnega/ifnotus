<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CustomerEnvironment, HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import ServiceBrandMark from '@/components/dashboard/ServiceBrandMark.vue'
import PortalMailPanel from '@/components/portal/PortalMailPanel.vue'
import PortalDomainTools from '@/components/portal/PortalDomainTools.vue'
import { envCan, visibleStacks } from '@/lib/planMatrix'

const props = defineProps<{
  environments: CustomerEnvironment[]
  activeEnv: CustomerEnvironment
  activePlan?: HostingPlan | null
  initialTab?: 'files' | 'stack' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail' | ''
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
  dbInfo: string
  dbCreds?: {
    engine?: string | null
    name?: string | null
    username?: string | null
    host?: string | null
    port?: number | null
    password_set?: boolean
    password?: string | null
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
  loadDbSchema: []
  loadDbRows: [string, number?]
  runDbQuery: []
  updateDbSql: [string]
  loadFtp: [boolean?]
  ensureFtp: [boolean?]
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
}>()

const siteTab = ref<'files' | 'stack' | 'cron' | 'database' | 'protect' | 'ftp' | 'logs' | 'mail'>('stack')
const copiedKey = ref('')
const customDomainInput = ref('')
const assignPick = ref('')

function confirmClear(dropDatabase = false) {
  const msg = dropDatabase
    ? 'Clear this site’s installation and drop its database? This only affects this environment.'
    : 'Clear this site’s installation files? You can install a fresh stack afterward. This only affects this environment.'
  if (!confirm(msg)) return
  emit('clearStack', dropDatabase)
}

function openFileManager(path = '.') {
  const id = props.activeEnv?.id
  if (!id) return
  const q = new URLSearchParams({ env: id })
  if (path && path !== '.') q.set('path', path)
  window.open(`/account/files?${q.toString()}`, `ifnotus-files-${id}`)
}
const showPassword = ref(false)
const showFtpPassword = ref(false)

watch(
  () => [props.activeEnv.id, props.initialTab] as const,
  ([, tab]) => {
    if (
      tab === 'files' ||
      tab === 'stack' ||
      tab === 'cron' ||
      tab === 'database' ||
      tab === 'protect' ||
      tab === 'ftp' ||
      tab === 'logs' ||
      tab === 'mail'
    ) {
      siteTab.value = tab
    } else {
      siteTab.value = 'stack'
    }
  },
  { immediate: true },
)

watch(siteTab, (tab) => {
  if (tab === 'database') {
    showPassword.value = false
    emit('loadDb', true)
  }
  if (tab === 'ftp') {
    showFtpPassword.value = false
    emit('loadFtp', true)
    emit('loadSsh')
  }
  if (tab === 'protect') emit('loadDns')
  if (tab === 'logs') emit('loadLogs')
})

const packStacks = computed(() => visibleStacks(props.activePlan))
const canFiles = computed(() => envCan(props.activeEnv, 'file_manager'))
const canCron = computed(() => envCan(props.activeEnv, 'cron'))
const canDb = computed(() => envCan(props.activeEnv, 'db_manage'))
const canFtp = computed(() => envCan(props.activeEnv, 'sftp'))

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

function openSqlStudio() {
  const id = props.activeEnv?.id
  if (!id) return
  const href = `/account/database/studio?env=${encodeURIComponent(id)}`
  window.open(href, `ifnotus-sql-${id}`)
}

function packLocked(label: string) {
  return `${label} is not on ${props.activePlan?.name || 'this package'}. Open Billing to upgrade.`
}
const currentStackIcon = computed(() => {
  const id = String(props.currentStack?.stack || '')
  const hit = props.stacks.find((s) => s.id === id)
  return hit?.icon || id || 'php'
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
        <h2>{{ activeEnv.domain || 'Your site' }}</h2>
        <p class="muted">
          {{ formatCpu(activeEnv.cpu_limit) }} vCPU · {{ formatRamGb(activeEnv.ram_limit_gb) }} ·
          {{ activeEnv.storage_limit_gb }} GB · {{ activePlan?.name || 'Plan' }}
        </p>
      </div>
      <div class="head-actions">
        <select
          class="select"
          :value="activeEnv.id"
          @change="emit('selectEnv', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="env in environments" :key="env.id" :value="env.id">
            {{ env.domain || env.id }}
          </option>
        </select>
        <a
          v-if="activeEnv.domain"
          class="btn-ghost"
          :href="publicSiteUrl(activeEnv.domain)"
          target="_blank"
          rel="noopener"
        >Open site</a>
      </div>
    </header>

    <nav v-if="!hideSubnav" class="subtabs" aria-label="Site sections">
      <button type="button" :class="{ on: siteTab === 'stack' }" @click="siteTab = 'stack'">Stack</button>
      <button type="button" :class="{ on: siteTab === 'files', off: !canFiles }" @click="siteTab = 'files'">Files</button>
      <button type="button" :class="{ on: siteTab === 'logs' }" @click="siteTab = 'logs'">Logs</button>
      <button type="button" :class="{ on: siteTab === 'cron', off: !canCron }" @click="siteTab = 'cron'">Cron</button>
      <button type="button" :class="{ on: siteTab === 'database', off: !canDb }" @click="siteTab = 'database'">Database</button>
      <button type="button" :class="{ on: siteTab === 'ftp', off: !canFtp }" @click="siteTab = 'ftp'">FTP</button>
      <button type="button" :class="{ on: siteTab === 'mail' }" @click="siteTab = 'mail'">Email</button>
      <button type="button" :class="{ on: siteTab === 'protect' }" @click="siteTab = 'protect'">Domain</button>
    </nav>

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

    <div v-else-if="siteTab === 'stack'" class="block">
      <div class="pack-soft">
        <h3>On {{ activePlan?.name || 'this package' }}</h3>
        <p class="muted">Runtimes included with this package.</p>
        <ul class="stack-pick pack">
          <li v-for="s in packStacks" :key="s.id" :class="{ faded: s.level === 'limited' }">
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
              v-if="activeEnv.domain"
              class="btn-primary"
              :href="publicSiteUrl(activeEnv.domain)"
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
            Everything listed here is included with your plan.
            One-click installers: Static/PHP, WordPress, Laravel, and Node.js.
            Other runtimes (Python, Django, Flask, and more) deploy via Files or Git.
          </p>
          <div class="stack-pick mt">
            <button
              v-for="s in stacks"
              :key="s.id"
              type="button"
              class="stack-opt"
              :class="{ on: selectedStack === s.id, 'is-matrix': s.one_click === false }"
              :disabled="stackBusy"
              @click="stackModel = s.id"
            >
              <ServiceBrandMark :name="s.icon || s.id" :size="36" />
              <strong>{{ s.name }}</strong>
              <em v-if="s.one_click === false">Files / Git</em>
              <em v-else-if="s.level === 'limited'">Limited</em>
              <em v-else>One-click</em>
            </button>
          </div>
          <p class="muted mt">{{ stacks.find((s) => s.id === selectedStack)?.description }}</p>
          <button
            type="button"
            class="btn-primary mt"
            :disabled="stackBusy || stacks.find((s) => s.id === selectedStack)?.one_click === false"
            @click="emit('installStack')"
          >
            {{
              stacks.find((s) => s.id === selectedStack)?.one_click === false
                ? 'Use Files or Git'
                : 'Replace stack'
            }}
          </button>
        </details>
      </template>

      <!-- Fresh install / in-progress / failed -->
      <template v-else>
        <h3>{{ stackOutcome === 'running' ? 'Installing stack' : 'Install stack' }}</h3>
        <p class="muted">
          Your pack includes the stacks below.
          One-click: Static/PHP, WordPress, Laravel, Node.js.
          Others are supported — deploy with Files or Git.
        </p>
        <div class="stack-pick mt">
          <button
            v-for="s in stacks"
            :key="s.id"
            type="button"
            class="stack-opt"
            :class="{ on: selectedStack === s.id, 'is-matrix': s.one_click === false }"
            :disabled="stackBusy"
            @click="stackModel = s.id"
          >
            <ServiceBrandMark :name="s.icon || s.id" :size="36" />
            <strong>{{ s.name }}</strong>
            <em v-if="s.one_click === false">Files / Git</em>
            <em v-else-if="s.level === 'limited'">Limited</em>
            <em v-else>One-click</em>
          </button>
        </div>
        <p class="muted mt">{{ stacks.find((s) => s.id === selectedStack)?.description }}</p>
        <button
          type="button"
          class="btn-primary mt"
          :disabled="stackBusy || stacks.find((s) => s.id === selectedStack)?.one_click === false"
          @click="emit('installStack')"
        >
          {{
            stackBusy
              ? 'Installing…'
              : stacks.find((s) => s.id === selectedStack)?.one_click === false
                ? 'Use Files or Git'
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
      <p class="muted">Commands run with your site folder as the working directory — not the host.</p>
      <div class="form-row mt">
        <input v-model="cronScheduleModel" class="input" placeholder="*/15 * * * *" />
        <input v-model="cronCommandModel" class="input grow" placeholder="php artisan schedule:run" />
        <button type="button" class="btn-primary" :disabled="cronBusy" @click="emit('addCron')">
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
    <div v-else-if="siteTab === 'database'" class="block">
      <div class="db-head">
        <div>
          <h3>MySQL / Database</h3>
          <p class="muted">
            Connection details for your site database, plus a full SQL studio (structure, browse, edit, run queries) —
            the same jobs phpMyAdmin covers on classic cPanel.
          </p>
        </div>
        <button
          v-if="dbCreds && !dbCreds.empty && !dbCreds.error"
          type="button"
          class="btn-primary"
          @click="openSqlStudio"
        >
          Open SQL studio
        </button>
      </div>
      <p v-if="dbCreds && !dbCreds.empty && !dbCreds.error" class="hint mt">
        SQL studio opens in a new page — browse tables, edit rows, and run SQL without leaving your account.
      </p>
      <p v-if="dbEngineLabel === 'PostgreSQL'" class="muted mt">
        This login is PostgreSQL. WordPress and Laravel on this pack use MySQL — install that stack when you need MySQL for those apps.
      </p>

      <p v-if="dbInfo === 'Loading…'" class="muted mt">Loading…</p>
      <p v-else-if="dbCreds?.empty || (!dbCreds && dbInfo)" class="empty-note mt">
        {{ dbInfo || 'No database on this site yet. Install WordPress or Laravel from Stack when you need one.' }}
      </p>
      <p v-else-if="dbCreds?.error" class="empty-note mt err">{{ dbCreds.error }}</p>

      <div v-else-if="dbCreds" class="cred-list mt">
        <div v-if="dbEngineLabel" class="cred-row">
          <div>
            <p class="cred-label">Engine</p>
            <p class="cred-value">{{ dbEngineLabel }}</p>
          </div>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">Database name</p>
            <p class="cred-value">{{ dbCreds.name || '—' }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('name', dbCreds.name)">
            {{ copiedKey === 'name' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">Username</p>
            <p class="cred-value">{{ dbCreds.username || '—' }}</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('user', dbCreds.username)">
            {{ copiedKey === 'user' ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <div class="cred-row">
          <div class="grow">
            <p class="cred-label">Password</p>
            <p class="cred-value mono">
              <template v-if="showPassword && dbCreds.password">{{ dbCreds.password }}</template>
              <template v-else-if="dbCreds.password_set || dbCreds.password">••••••••••••</template>
              <template v-else>Not set yet</template>
            </p>
          </div>
          <div class="row-actions">
            <button
              type="button"
              class="btn-ghost"
              :disabled="!dbCreds.password && !dbCreds.password_set"
              @click="togglePassword"
            >
              {{ showPassword ? 'Hide' : 'Show' }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!dbCreds.password"
              @click="copyValue('pass', dbCreds.password)"
            >
              {{ copiedKey === 'pass' ? 'Copied' : 'Copy password' }}
            </button>
          </div>
        </div>
        <div class="cred-row">
          <div>
            <p class="cred-label">Server</p>
            <p class="cred-value">{{ dbCreds.host || 'localhost' }}</p>
            <p class="hint">Usually leave this as localhost. Port {{ dbCreds.port || 3306 }}.</p>
          </div>
          <button type="button" class="btn-ghost" @click="copyValue('host', dbCreds.host || 'localhost')">
            {{ copiedKey === 'host' ? 'Copied' : 'Copy' }}
          </button>
        </div>
      </div>

      <button type="button" class="btn-ghost mt" @click="emit('loadDb', true)">Refresh</button>
      <button
        v-if="isWordpressInstalled"
        type="button"
        class="btn-ghost mt"
        style="margin-left: 0.4rem"
        @click="emit('repairFs')"
      >
        Fix WordPress file access
      </button>
    </div>

    <div v-else-if="siteTab === 'ftp' && !canFtp" class="block">
      <p>{{ packLocked('FTP') }}</p>
    </div>
    <div v-else-if="siteTab === 'ftp'" class="block">
      <h3>Your FTP login</h3>
      <p class="muted">
        One account for this site. Use it in FileZilla, or enter localhost if WordPress asks for FTP.
      </p>

      <p v-if="ftpInfo === 'Loading…'" class="muted mt">Loading…</p>
      <p v-else-if="ftpCreds?.error" class="empty-note mt err">{{ ftpCreds.error }}</p>

      <div v-else-if="ftpCreds?.username" class="cred-list mt">
        <div class="cred-row">
          <div>
            <p class="cred-label">FTP host</p>
            <p class="cred-value mono">{{ ftpCreds.host }}</p>
            <p class="hint">FileZilla → Host. Port {{ ftpCreds.port || 21 }}.</p>
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
        <div class="cred-row">
          <div>
            <p class="cred-label">Connection type</p>
            <p class="cred-value">{{ ftpCreds.connection_type || 'FTP' }}</p>
            <p class="hint">Port {{ ftpCreds.port || 21 }}. Choose FTP (not FTPS) unless we enable SSL later.</p>
            <p
              v-if="(ftpCreds.connection_type || 'FTP').toUpperCase() === 'FTP'"
              class="hint"
            >
              {{ ftpCreds.sftp_coming_note || 'SFTP coming for entitled plans' }}
            </p>
          </div>
        </div>
        <p v-if="ftpCreds.message || ftpCreds.hint" class="hint mt">
          {{ ftpCreds.message || ftpCreds.hint }}
        </p>
      </div>

      <div v-else class="empty-note mt">
        Your plan includes one FTP account for this site. Create it to upload files or finish WordPress prompts.
      </div>

      <div class="toolbar mt">
        <button type="button" class="btn-primary" @click="emit('ensureFtp', false)">
          {{ ftpCreds?.username ? 'Refresh login' : 'Create my FTP account' }}
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
        Every site gets the shared access host. Jailed SSH (not root) unlocks from ₵{{ sshCreds?.min_price_ghs || 300 }}/month.
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

    <div v-else-if="siteTab === 'mail'" class="block">
      <PortalMailPanel
        :environment-id="activeEnv.id"
        :domain="activeEnv.domain"
        :mailbox-limit="activeEnv.capabilities?.mailboxes == null ? null : Number(activeEnv.capabilities.mailboxes)"
      />
    </div>

    <div v-else class="protect-grid">
      <div class="block">
        <h3>Connect your domain</h3>
        <p class="muted">
          Point nameservers to IFNOTUS. Do not use an IP address — that keeps our server address private
          and makes email, www, and HTTPS work the same for every site.
        </p>
        <ol class="steps-ns">
          <li>Copy both nameservers below.</li>
          <li>At your registrar, replace the current nameservers with these two. Do not add an A record to an IP.</li>
          <li>Wait until DNS updates (often 15 minutes to a few hours).</li>
          <li>Click Test again, then turn on HTTPS.</li>
        </ol>

        <div v-if="dnsData?.checklist?.length" class="dns-check mt">
          <p class="status-summary" :class="{ ok: dnsData.nsLive && dnsData.resolves, wait: !dnsData.nsLive }">
            {{ dnsData.statusSummary || dnsData.message }}
          </p>
          <ul class="check-list">
            <li v-for="step in dnsData.checklist" :key="step.id" :class="{ done: step.done }">
              <span class="mark">{{ step.done ? '✓' : '○' }}</span>
              <div>
                <p class="check-label">{{ step.label }}</p>
                <p v-if="step.detail" class="hint">{{ step.detail }}</p>
              </div>
            </li>
          </ul>
        </div>

        <p v-if="dnsData?.panelUrl" class="hint mt">
          Control panel:
          <a class="panel-a" :href="dnsData.panelUrl" target="_blank" rel="noopener">{{ dnsData.panelHostname || dnsData.panelUrl }}</a>
          (opens your IFNOTUS account)
        </p>

        <p v-if="dnsData?.addon" class="hint mt">
          Included hostname: <strong>{{ dnsData.addon }}</strong>
          <span v-if="dnsData.custom"> · Professional name: <strong>{{ dnsData.custom }}</strong></span>
        </p>
        <p v-else-if="dnsData?.custom || dnsData?.domain" class="hint mt">
          Site name: <strong>{{ dnsData.custom || dnsData.domain }}</strong>
        </p>

        <p v-if="dnsInfo === 'Loading…' || dnsInfo === 'Updating…' || dnsInfo === 'Adding…' || dnsInfo === 'Unassigning…' || dnsInfo === 'Connecting…'" class="muted mt">{{ dnsInfo }}</p>
        <p v-else-if="dnsData?.error || (!dnsData && dnsInfo)" class="empty-note mt err">
          {{ dnsData?.error || dnsInfo }}
        </p>

        <div v-if="dnsData && !dnsData.error" class="cred-list mt">
          <div v-for="(ns, i) in nameservers" :key="ns" class="cred-row">
            <div>
              <p class="cred-label">Nameserver {{ i + 1 }}</p>
              <p class="cred-value mono">{{ ns }}</p>
              <p class="hint">Paste both nameservers at the registrar. Host / name is not needed.</p>
            </div>
            <button type="button" class="btn-ghost" @click="copyValue(`dns-ns-${i}`, ns)">
              {{ copiedKey === `dns-ns-${i}` ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <p v-if="dnsData.namecheap" class="ok-note mt">
            This domain is already on IFNOTUS nameservers (registered with us).
          </p>
        </div>

        <div class="toolbar mt">
          <button type="button" class="btn-ghost" @click="emit('loadDns')">Test again</button>
          <button type="button" class="btn-primary" @click="emit('ensureDns')">Apply nameservers</button>
        </div>
      </div>

      <div class="block">
        <h3>Professional domains</h3>
        <p class="muted">
          Paid packages can add a real domain the same way as an addon domain: it uses this site’s
          files. You can assign a name you already bought here, or add one from another registrar.
        </p>
        <p class="hint mt">
          {{ customUsed }} / {{ customLimit }} professional domain{{ customLimit === 1 ? '' : 's' }} on this plan.
        </p>

        <ul v-if="assignedDomains.length" class="job-list mt">
          <li v-for="name in assignedDomains" :key="name">
            <span>{{ name }}</span>
            <button type="button" class="btn-ghost" @click="emit('unassignCustom', name)">Unassign</button>
          </li>
        </ul>
        <p v-else class="hint mt">No professional domain assigned. The included hostname still works.</p>

        <form v-if="canAttachCustom && availableDomains.length" class="form-row mt" @submit.prevent="submitAssign">
          <select v-model="assignPick" class="input grow">
            <option value="">Assign a domain you already own…</option>
            <option v-for="name in availableDomains" :key="name" :value="name">{{ name }}</option>
          </select>
          <button type="submit" class="btn-primary" :disabled="!assignPick">Assign</button>
        </form>

        <form v-if="canAttachCustom" class="form-row mt" @submit.prevent="submitCustomDomain">
          <input
            v-model="customDomainInput"
            class="input grow"
            placeholder="Add domain (studio.online)"
            autocomplete="off"
            spellcheck="false"
          />
          <button type="submit" class="btn-primary">Add domain</button>
        </form>
        <p v-else-if="customLimit <= 0" class="hint mt">
          This package does not include a professional domain. Upgrade to add or assign one.
        </p>
        <p v-else class="hint mt">
          This plan’s professional domain slot is in use. Unassign one to add another, or upgrade.
        </p>
      </div>

      <div class="block">
        <h3>Secure site (HTTPS)</h3>
        <p class="muted">
          Hostnames under serverlabsttu.space (and legacy student hosts on ifnotus.space) get a
          certificate as soon as the site is created. For a professional domain, wait until
          nameservers update, then turn on the padlock.
        </p>
        <p v-if="dnsData?.sslReady" class="ok-note mt">HTTPS is on for this site.</p>
        <p v-else-if="dnsData && dnsData.nsLive === false" class="hint mt">
          HTTPS will wait until nameservers are live. Use Test again above.
        </p>
        <p v-if="sslMsg" class="hint mt">{{ sslMsg }}</p>
        <button type="button" class="btn-primary mt" @click="emit('issueSsl')">Turn on HTTPS</button>
      </div>

      <div class="block wide">
        <h3>Backups</h3>
        <p class="muted">{{ backupMsg || 'Save a restore point of your site files.' }}</p>
        <div class="toolbar mt">
          <button type="button" class="btn-ghost" @click="emit('loadBackups')">Show backups</button>
          <button type="button" class="btn-primary" @click="emit('createBackup')">Back up now</button>
        </div>
        <ul v-if="backups.length" class="job-list mt">
          <li v-for="b in backups" :key="b.id">
            <span>{{ b.status }} · {{ formatBytes(b.file_size) }} · {{ b.filename }}</span>
            <button
              v-if="b.status === 'success'"
              type="button"
              class="btn-ghost"
              @click="emit('restoreBackup', b.id)"
            >Restore</button>
          </li>
        </ul>
      </div>

      <PortalDomainTools
        class="wide"
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
</style>
