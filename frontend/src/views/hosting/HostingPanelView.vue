<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalShell from '@/components/portal/PortalShell.vue'
import PortalSitePanel from '@/components/portal/PortalSitePanel.vue'
import { usePortalSiteTools, type PortalSiteTab } from '@/composables/usePortalSiteTools'
import { getApiErrorMessage } from '@/lib/apiError'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'

type HostingTab =
  | 'overview'
  | 'files'
  | 'databases'
  | 'domains'
  | 'email'
  | 'transfer'
  | 'apps'
  | 'backups'
  | 'logs'

const TABS: Array<{ id: HostingTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'files', label: 'Files' },
  { id: 'databases', label: 'Databases' },
  { id: 'domains', label: 'Domains' },
  { id: 'email', label: 'Email' },
  { id: 'transfer', label: 'Transfer' },
  { id: 'apps', label: 'Apps' },
  { id: 'backups', label: 'Backups' },
  { id: 'logs', label: 'Logs' },
]

const HOSTING_TO_SITE: Record<Exclude<HostingTab, 'overview' | 'backups'>, PortalSiteTab> = {
  files: 'files',
  databases: 'database',
  domains: 'protect',
  email: 'mail',
  transfer: 'ftp',
  apps: 'applications',
  logs: 'logs',
}

const route = useRoute()
const router = useRouter()

const dash = ref<CustomerDashboard | null>(null)
const plans = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')
const tab = ref<HostingTab>('overview')

const environmentId = computed(() => String(route.params.environmentId || ''))

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
  loadDbSchema,
  loadDbRows,
  runDbQuery,
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
  loadLogs,
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

const siteInitialTab = computed<PortalSiteTab>(() => {
  if (tab.value === 'overview' || tab.value === 'backups') return ''
  return HOSTING_TO_SITE[tab.value] || 'stack'
})

const showSitePanel = computed(() => tab.value !== 'overview' && tab.value !== 'backups')

function resolveTabFromRoute(): HostingTab {
  if (route.name === 'hosting-files' || route.meta.hostingTab === 'files') return 'files'
  const raw = typeof route.query.tab === 'string' ? route.query.tab : ''
  if (TABS.some((t) => t.id === raw)) return raw as HostingTab
  return 'overview'
}

function goTab(next: HostingTab) {
  tab.value = next
  if (next === 'files') {
    void router.push({ name: 'hosting-files', params: { environmentId: environmentId.value } })
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
    const owned = data.environments.some((e) => e.id === environmentId.value)
    if (!owned) {
      error.value = 'This hosting service is not on your account.'
      return
    }
    setActiveEnvId(environmentId.value)
    await hydrateActiveEnv()
  } catch (e: unknown) {
    error.value = getApiErrorMessage(e, 'Could not load hosting panel.')
  } finally {
    loading.value = false
  }
}

watch(
  () => [route.name, route.query.tab, route.meta.hostingTab] as const,
  () => {
    tab.value = resolveTabFromRoute()
  },
  { immediate: true },
)

watch(environmentId, () => {
  void load()
})

watch(tab, (next) => {
  if (next === 'backups' && env.value) void loadBackups()
  if (next === 'apps' && env.value) {
    void loadAppCatalog()
    void loadApplications()
  }
})

onMounted(() => {
  void load()
})
</script>

<template>
  <PortalShell mode="app" :email="dash?.customer.email" :display-name="dash?.customer.full_name" profile-menu>
    <div class="hosting">
      <header class="top">
        <div>
          <RouterLink class="back" :to="{ name: 'portal-dashboard' }">← Back to account</RouterLink>
          <h1>{{ env?.domain || 'Hosting' }}</h1>
          <p class="lede">Technical tools for this site — separate from billing and account settings.</p>
        </div>
        <p v-if="plan" class="plan-chip">{{ plan.name }}</p>
      </header>

      <nav class="tabs" aria-label="Hosting tools">
        <button
          v-for="item in TABS"
          :key="item.id"
          type="button"
          :class="{ on: tab === item.id }"
          @click="goTab(item.id)"
        >
          {{ item.label }}
        </button>
      </nav>

      <p v-if="loading" class="muted">Loading hosting…</p>
      <div v-else-if="error" class="p-card">
        <h2>Unavailable</h2>
        <p class="muted">{{ error }}</p>
        <RouterLink class="btn-primary" :to="{ name: 'portal-dashboard' }">Back to account</RouterLink>
      </div>

      <template v-else-if="env">
        <section v-if="tab === 'overview'" class="panel">
          <article class="p-card">
            <p class="kicker">Overview</p>
            <h2>{{ env.domain || 'Your site' }}</h2>
            <p class="muted">
              {{ spec.cpu }} vCPU · {{ spec.ram }} · {{ spec.disk }} GB disk · Status {{ env.status || '—' }}
            </p>
            <p v-if="usageInfo || healthInfo" class="muted status-line">
              {{ usageInfo || healthInfo }}
              <span v-if="usagePct" class="disk-pct"> · Disk {{ Math.min(100, Math.round(usagePct)) }}%</span>
            </p>
            <div class="actions">
              <button type="button" class="btn-primary" @click="goTab('files')">Open files</button>
              <a
                v-if="env.domain"
                class="btn-ghost"
                :href="`https://${env.domain}`"
                target="_blank"
                rel="noopener"
              >Open site</a>
              <button type="button" class="btn-ghost" @click="goTab('transfer')">FTP login</button>
            </div>
          </article>

          <div class="quick">
            <button
              v-for="item in TABS.filter((t) => t.id !== 'overview')"
              :key="item.id"
              type="button"
              @click="goTab(item.id)"
            >
              {{ item.label }}
            </button>
          </div>
        </section>

        <section v-else-if="tab === 'backups'" class="panel p-card">
          <p class="kicker">Backups</p>
          <h2>Restore points</h2>
          <p class="muted">{{ backupMsg || 'Save a restore point of your site files.' }}</p>
          <div class="actions">
            <button type="button" class="btn-ghost" @click="loadBackups">Refresh</button>
            <button type="button" class="btn-primary" @click="createBackup">Back up now</button>
          </div>
          <ul v-if="backups.length" class="backup-list">
            <li v-for="b in backups" :key="b.id">
              <span>{{ b.status }} · {{ formatBytes(b.file_size) }} · {{ b.filename }}</span>
              <button
                v-if="b.status === 'success'"
                type="button"
                class="btn-ghost"
                @click="restoreBackup(b.id)"
              >
                Restore
              </button>
            </li>
          </ul>
        </section>

        <PortalSitePanel
          v-else-if="showSitePanel"
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
      </template>
    </div>
  </PortalShell>
</template>

<style scoped>
.hosting {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  min-width: 0;
}
.top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
}
.back {
  display: inline-block;
  margin-bottom: 0.35rem;
  color: var(--p-accent);
  font-size: 0.84rem;
  font-weight: 700;
  text-decoration: none;
}
h1 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: clamp(1.35rem, 2.2vw, 1.75rem);
  letter-spacing: -0.03em;
  color: var(--p-ink);
}
.lede,
.muted {
  margin: 0.35rem 0 0;
  color: var(--p-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}
.status-line {
  margin-top: 0.55rem;
}
.disk-pct {
  white-space: nowrap;
}
.plan-chip {
  margin: 0;
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  border: 1px solid var(--p-border);
  background: var(--p-surface);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--p-ink);
}
.tabs {
  display: flex;
  gap: 0.25rem;
  overflow-x: auto;
  padding: 0.28rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--p-border) 55%, var(--p-surface));
  width: fit-content;
  max-width: 100%;
}
.tabs button {
  border: none;
  background: transparent;
  color: var(--p-muted);
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.45rem 0.9rem;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}
.tabs button.on {
  background: var(--p-surface);
  color: var(--p-ink);
  box-shadow: 0 1px 2px rgb(22 26 29 / 0.08);
}
.panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.kicker {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent);
}
h2 {
  margin: 0.3rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.15rem;
  color: var(--p-ink);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
}
.btn-primary,
.btn-ghost {
  border-radius: 0.6rem;
  font-size: 0.86rem;
  font-weight: 650;
  padding: 0.55rem 1rem;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.btn-primary {
  border: none;
  background: var(--p-accent);
  color: #fff;
}
.btn-ghost {
  border: 1px solid var(--p-border);
  background: transparent;
  color: var(--p-ink);
}
.quick {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
}
@media (min-width: 720px) {
  .quick {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.quick button {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.85rem 0.6rem;
  border: 1px solid var(--p-border);
  border-radius: 0.95rem;
  background: var(--p-surface);
  color: var(--p-ink);
  font-size: 0.84rem;
  font-weight: 650;
  cursor: pointer;
}
.backup-list {
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.backup-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--p-border);
  border-radius: 0.85rem;
  background: var(--p-surface);
  font-size: 0.86rem;
  color: var(--p-ink);
}
</style>
