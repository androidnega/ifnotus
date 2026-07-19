<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { applicationsApi, operationsApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { ApplicationSummary } from '@/types/dashboard'
import type {
  BackupEntry,
  CronJob,
  DatabaseStatus,
  EnvVariable,
  FileEntry,
  OperationsOverview,
  SslAppStatus,
  StorageVolume,
} from '@/types/operations'

const loading = ref(true)
const loadError = ref<string | null>(null)
const actionLoading = ref<string | null>(null)
const actionMessage = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const overview = ref<OperationsOverview | null>(null)
const apps = ref<ApplicationSummary[]>([])
const envVars = ref<EnvVariable[]>([])
const envRevealed = ref(false)
const backups = ref<BackupEntry[]>([])
const cronJobs = ref<CronJob[]>([])
const storage = ref<StorageVolume[]>([])
const sslApps = ref<SslAppStatus[]>([])
const databases = ref<DatabaseStatus[]>([])
const files = ref<FileEntry[]>([])
const filePath = ref('.')
const fileParent = ref<string | undefined>()
const hostLogs = ref<Array<{ message: string; level?: string; source?: string }>>([])
const smtpEmail = ref('')
const queueDepth = ref(0)

async function runAction(key: string, fn: () => Promise<{ data: { success: boolean; message: string } }>) {
  actionLoading.value = key
  actionMessage.value = null
  try {
    const { data } = await fn()
    actionMessage.value = { type: data.success ? 'ok' : 'err', text: data.message }
    await refreshAll()
  } catch (e) {
    actionMessage.value = {
      type: 'err',
      text: e instanceof Error ? e.message : 'Action failed',
    }
  } finally {
    actionLoading.value = null
  }
}

async function loadFiles(path = '.') {
  const { data } = await operationsApi.files(path)
  files.value = data.entries
  filePath.value = data.path
  fileParent.value = data.parent
}

async function refreshAll() {
  loading.value = true
  loadError.value = null
  try {
    const results = await Promise.allSettled([
      operationsApi.overview(),
      applicationsApi.list(),
      operationsApi.environment(envRevealed.value),
      operationsApi.backups(),
      operationsApi.cron(),
      operationsApi.storage(),
      operationsApi.ssl(),
      operationsApi.database(),
      operationsApi.hostLogs(80),
      operationsApi.queueStatus(),
    ])

    const fulfilled = <T>(i: number): T | null => {
      const result = results[i]
      if (result.status !== 'fulfilled') return null
      return result.value.data as T
    }

    const ov = fulfilled<OperationsOverview>(0)
    const appList = fulfilled<{ applications: ApplicationSummary[] }>(1)
    const env = fulfilled<{ variables: EnvVariable[] }>(2)
    const bk = fulfilled<{ backups: BackupEntry[] }>(3)
    const cr = fulfilled<{ jobs: CronJob[] }>(4)
    const st = fulfilled<{ volumes: StorageVolume[] }>(5)
    const ssl = fulfilled<SslAppStatus[]>(6)
    const db = fulfilled<{ databases: DatabaseStatus[] }>(7)
    const logs = fulfilled<{ entries: Array<{ message: string; level?: string; source?: string }> }>(8)
    const queue = fulfilled<Array<{ queue: string; depth: number }>>(9)

    if (ov) overview.value = ov
    if (appList) apps.value = appList.applications
    if (env) envVars.value = env.variables
    if (bk) backups.value = bk.backups
    if (cr) cronJobs.value = cr.jobs
    if (st) storage.value = st.volumes
    if (ssl) sslApps.value = ssl
    if (db) databases.value = db.databases
    if (logs) hostLogs.value = logs.entries ?? []
    queueDepth.value = ov?.worker_queue_depth ?? queue?.[0]?.depth ?? 0

    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed && !ov) {
      loadError.value = 'Failed to load operations data.'
    } else if (failed) {
      loadError.value = `${failed} operations section(s) failed to load.`
    }

    try {
      await loadFiles(filePath.value)
    } catch {
      /* file browser is optional on this page */
    }
  } catch (e) {
    loadError.value = getApiErrorMessage(e, 'Failed to load operations.')
  } finally {
    loading.value = false
  }
}

async function toggleRevealEnv() {
  envRevealed.value = !envRevealed.value
  const { data } = await operationsApi.environment(envRevealed.value)
  envVars.value = data.variables
}

function formatBytes(n?: number) {
  if (n == null) return '—'
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

const enabledApps = computed(
  () => overview.value?.applications_enabled ?? apps.value.filter((a) => a.enabled).length,
)

onMounted(refreshAll)
</script>

<template>
  <DashboardLayout @refresh="refreshAll">
    <div class="animate-fade-in space-y-5">
      <p
        v-if="loadError"
        class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200"
      >
        {{ loadError }}
      </p>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Operations</h1>
          <p class="text-sm text-surface-muted">Deploy, restart services, inspect platform state</p>
        </div>
        <button
          type="button"
          class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
          :disabled="loading"
          @click="refreshAll"
        >
          Refresh
        </button>
      </div>

      <p
        v-if="actionMessage"
        class="rounded-lg px-3 py-2 text-sm"
        :class="
          actionMessage.type === 'ok'
            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
            : 'bg-red-500/10 text-red-700 dark:text-red-300'
        "
      >
        {{ actionMessage.text }}
      </p>

      <section v-if="overview" class="dashboard-grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6">
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Apps</p>
          <p class="text-xl font-semibold">{{ enabledApps }}/{{ overview.applications_total }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Queue depth</p>
          <p class="text-xl font-semibold">{{ queueDepth }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Backups</p>
          <p class="text-xl font-semibold">{{ overview.backup_count }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Cron jobs</p>
          <p class="text-xl font-semibold">{{ overview.cron_job_count }}</p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Nginx</p>
          <Badge :variant="overview.nginx_available ? 'success' : 'neutral'" size="sm">
            {{ overview.nginx_available ? 'Available' : 'N/A' }}
          </Badge>
        </Card>
      </section>

      <!-- Quick actions row -->
      <Card title="Service controls" subtitle="Restart platform services">
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('nginx', () => operationsApi.restartNginx())"
          >
            {{ actionLoading === 'nginx' ? '…' : 'Restart Nginx' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('worker', () => operationsApi.restartWorker())"
          >
            {{ actionLoading === 'worker' ? '…' : 'Restart Queue / Worker' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('backup', () => operationsApi.createBackup())"
          >
            {{ actionLoading === 'backup' ? '…' : 'Create backup' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('db-ping', () => operationsApi.databaseAction('ping'))"
          >
            DB ping
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('migrate', () => operationsApi.databaseAction('migrate'))"
          >
            Run migrations
          </button>
        </div>
      </Card>

      <div class="dashboard-grid lg:grid-cols-2">
        <!-- Applications -->
        <Card title="Applications" subtitle="Git pull / deploy / restart">
          <div class="space-y-2">
            <RouterLink
              v-for="app in apps"
              :key="app.id"
              :to="`/applications/${app.id}`"
              class="flex items-center justify-between rounded-lg border border-surface-border px-3 py-2 text-sm transition hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <span class="font-medium">{{ app.name }}</span>
              <Badge :variant="app.enabled ? 'success' : 'neutral'" size="sm">
                {{ app.status }}
              </Badge>
            </RouterLink>
            <p v-if="!apps.length && !loading" class="text-sm text-surface-muted">No applications registered.</p>
          </div>
        </Card>

        <!-- SMTP -->
        <Card title="Email / SMTP test">
          <div class="flex flex-wrap gap-2">
            <input
              v-model="smtpEmail"
              type="email"
              placeholder="recipient@example.com"
              class="min-w-0 flex-1 rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
            />
            <button
              type="button"
              class="action-btn"
              :disabled="!!actionLoading || !smtpEmail"
              @click="runAction('smtp', () => operationsApi.smtpTest(smtpEmail))"
            >
              Send test
            </button>
          </div>
          <p class="mt-2 text-xs text-surface-muted">Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME in backend .env</p>
        </Card>
      </div>

      <div class="dashboard-grid lg:grid-cols-2">
        <!-- Environment -->
        <Card title="Environment variables" subtitle="Platform settings (secrets masked)">
          <div class="mb-3 flex justify-end">
            <button type="button" class="text-xs text-brand-600 hover:underline" @click="toggleRevealEnv">
              {{ envRevealed ? 'Hide secrets' : 'Reveal (admin)' }}
            </button>
          </div>
          <div class="max-h-64 overflow-y-auto">
            <dl class="space-y-1 text-xs">
              <div
                v-for="v in envVars.slice(0, 40)"
                :key="v.key"
                class="grid grid-cols-[9rem_1fr] gap-2 border-b border-surface-border/50 py-1"
              >
                <dt class="truncate font-mono text-surface-muted">{{ v.key }}</dt>
                <dd class="truncate font-mono">{{ v.value }}</dd>
              </div>
            </dl>
          </div>
        </Card>

        <!-- SSL -->
        <Card title="SSL / domain status">
          <div class="space-y-2 text-sm">
            <div
              v-for="item in sslApps"
              :key="item.application_id"
              class="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900"
            >
              <p class="font-medium">{{ item.application_name }}</p>
              <p class="text-xs text-surface-muted">{{ item.domain || '—' }}</p>
              <Badge
                v-if="item.ssl?.status"
                :variant="
                  item.ssl.status === 'healthy'
                    ? 'success'
                    : item.ssl.status === 'degraded'
                      ? 'warning'
                      : 'danger'
                "
                size="sm"
                class="mt-1"
              >
                {{ item.ssl.status }}
                <span v-if="item.ssl.days_remaining != null"> · {{ item.ssl.days_remaining }}d</span>
              </Badge>
            </div>
          </div>
        </Card>
      </div>

      <div class="dashboard-grid lg:grid-cols-2">
        <!-- Storage -->
        <Card title="Storage checks">
          <div class="space-y-2">
            <div v-for="vol in storage" :key="vol.mount" class="text-sm">
              <div class="flex justify-between">
                <span class="font-medium">{{ vol.mount }}</span>
                <span class="text-surface-muted">{{ vol.percent.toFixed(1) }}%</span>
              </div>
              <div class="mt-1 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div
                  class="h-full rounded-full bg-brand-500"
                  :style="{ width: `${Math.min(vol.percent, 100)}%` }"
                />
              </div>
              <p class="mt-0.5 text-xs text-surface-muted">
                {{ formatBytes(vol.used_bytes) }} / {{ formatBytes(vol.total_bytes) }}
              </p>
            </div>
          </div>
        </Card>

        <!-- Database -->
        <Card title="Database actions">
          <div class="space-y-2">
            <div
              v-for="db in databases"
              :key="db.engine"
              class="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-900"
            >
              <span class="font-medium capitalize">{{ db.engine }}</span>
              <div class="text-right text-xs">
                <Badge :variant="db.status === 'healthy' ? 'success' : 'danger'" size="sm">{{ db.status }}</Badge>
                <p v-if="db.connections != null" class="mt-0.5 text-surface-muted">{{ db.connections }} conn</p>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div class="dashboard-grid lg:grid-cols-2">
        <!-- Backups -->
        <Card title="Backups">
          <div v-if="!backups.length" class="text-sm text-surface-muted">No backups found yet.</div>
          <ul v-else class="max-h-48 space-y-1 overflow-y-auto text-xs">
            <li v-for="b in backups.slice(0, 20)" :key="b.id" class="truncate font-mono">
              {{ b.name }} · {{ formatBytes(b.size_bytes) }}
            </li>
          </ul>
        </Card>

        <!-- Cron -->
        <Card title="Cron / scheduled tasks">
          <div v-if="!cronJobs.length" class="text-sm text-surface-muted">No cron jobs detected.</div>
          <ul v-else class="max-h-48 space-y-2 overflow-y-auto text-xs">
            <li v-for="job in cronJobs.slice(0, 15)" :key="job.id" class="rounded bg-slate-50 p-2 dark:bg-slate-900">
              <p class="font-mono text-brand-600">{{ job.schedule }}</p>
              <p class="truncate text-surface-muted">{{ job.command }}</p>
            </li>
          </ul>
        </Card>
      </div>

      <div class="dashboard-grid lg:grid-cols-2">
        <!-- File manager -->
        <Card title="File manager" :subtitle="`Path: ${filePath}`">
          <div class="mb-2 flex gap-2">
            <button
              v-if="fileParent != null"
              type="button"
              class="text-xs text-brand-600 hover:underline"
              @click="loadFiles(fileParent || '.')"
            >
              ↑ Up
            </button>
          </div>
          <ul class="max-h-56 space-y-1 overflow-y-auto text-sm">
            <li v-for="entry in files" :key="entry.path">
              <button
                v-if="entry.is_dir"
                type="button"
                class="w-full truncate text-left hover:text-brand-600"
                @click="loadFiles(entry.path)"
              >
                📁 {{ entry.name }}
              </button>
              <span v-else class="block truncate text-surface-muted">📄 {{ entry.name }}</span>
            </li>
          </ul>
        </Card>

        <!-- Host logs -->
        <Card title="Logs viewer" subtitle="Host syslog tail">
          <pre class="max-h-56 overflow-y-auto text-xs leading-relaxed text-surface-muted">{{
            hostLogs.map((l) => l.message).join('\n') || 'No log entries.'
          }}</pre>
        </Card>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.action-btn {
  @apply rounded-lg border border-surface-border bg-slate-50 px-3 py-2 text-sm font-medium transition hover:border-brand-500/30 hover:bg-brand-500/5 disabled:opacity-50 dark:bg-slate-900;
}
</style>
