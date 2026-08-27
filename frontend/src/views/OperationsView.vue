<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { operationsApi } from '@/api'
import type { BackupEntry, CronJob, OperationsOverview, StorageVolume } from '@/types/operations'

const loading = ref(true)
const loadError = ref<string | null>(null)
const actionLoading = ref<string | null>(null)
const actionMessage = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const overview = ref<OperationsOverview | null>(null)
const backups = ref<BackupEntry[]>([])
const cronJobs = ref<CronJob[]>([])
const storage = ref<StorageVolume[]>([])
const hostLogs = ref<Array<{ message: string; level?: string; source?: string }>>([])
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

async function refreshAll() {
  loading.value = true
  loadError.value = null
  try {
    const results = await Promise.allSettled([
      operationsApi.overview(),
      operationsApi.backups(),
      operationsApi.cron(),
      operationsApi.storage(),
      operationsApi.hostLogs(80),
      operationsApi.queueStatus(),
    ])

    const fulfilled = <T>(i: number): T | null => {
      const result = results[i]
      if (result.status !== 'fulfilled') return null
      return result.value.data as T
    }

    const ov = fulfilled<OperationsOverview>(0)
    const bk = fulfilled<{ backups: BackupEntry[] }>(1)
    const cr = fulfilled<{ jobs: CronJob[] }>(2)
    const st = fulfilled<{ volumes: StorageVolume[] }>(3)
    const logs = fulfilled<{ entries: Array<{ message: string; level?: string; source?: string }> }>(4)
    const queue = fulfilled<Array<{ queue: string; depth: number }>>(5)

    if (ov) overview.value = ov
    if (bk) backups.value = bk.backups
    if (cr) cronJobs.value = cr.jobs
    if (st) storage.value = st.volumes
    if (logs) hostLogs.value = logs.entries ?? []
    queueDepth.value = ov?.worker_queue_depth ?? queue?.[0]?.depth ?? 0

    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed && !ov) loadError.value = 'Failed to load operations data.'
    else if (failed) loadError.value = `${failed} operations section(s) failed to load.`
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load operations.'
  } finally {
    loading.value = false
  }
}

function formatBytes(n?: number) {
  if (n == null) return '—'
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

const enabledApps = computed(() => overview.value?.applications_enabled ?? 0)

onMounted(refreshAll)
</script>

<template>
  <DashboardLayout @refresh="refreshAll">
    <div class="animate-fade-in space-y-5">
      <UiAlert v-if="loadError" tone="warn">{{ loadError }}</UiAlert>
      <UiPageHeader
        title="Operations"
        lede="Host backups, scheduled jobs, cache/nginx controls, and syslog — use Files, SSL, and Databases for those tools."
      >
        <template #actions>
          <button type="button" class="ds-btn-ghost text-sm" :disabled="loading" @click="refreshAll">
            Refresh
          </button>
        </template>
      </UiPageHeader>

      <UiAlert v-if="actionMessage" :tone="actionMessage.type === 'ok' ? 'ok' : 'err'">
        {{ actionMessage.text }}
      </UiAlert>

      <section v-if="overview" class="dashboard-grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5">
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Enabled apps</p>
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

      <Card title="Host controls" subtitle="Refresh inventory, clear caches, restart core services">
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="action-btn-primary"
            :disabled="!!actionLoading"
            @click="runAction('refresh-server', () => operationsApi.refreshServer())"
          >
            {{ actionLoading === 'refresh-server' ? '…' : 'Refresh server' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('cache-central', () => operationsApi.clearCentralCache(false))"
          >
            {{ actionLoading === 'cache-central' ? '…' : 'Clear central cache' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('cache-apps', () => operationsApi.clearAllAppCaches())"
          >
            {{ actionLoading === 'cache-apps' ? '…' : 'Clear all app caches' }}
          </button>
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
            {{ actionLoading === 'worker' ? '…' : 'Restart queue worker' }}
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="runAction('backup', () => operationsApi.createBackup())"
          >
            {{ actionLoading === 'backup' ? '…' : 'Create backup' }}
          </button>
        </div>
        <p class="mt-3 text-xs text-surface-muted">
          Files → <RouterLink class="text-brand-600 underline" to="/files">File Manager</RouterLink>
          · SSL → <RouterLink class="text-brand-600 underline" to="/ssl">SSL</RouterLink>
          · Databases → <RouterLink class="text-brand-600 underline" to="/databases">Databases</RouterLink>
          · Sites → <RouterLink class="text-brand-600 underline" to="/applications">Apps</RouterLink>
        </p>
      </Card>

      <div class="dashboard-grid lg:grid-cols-2">
        <Card title="Backups">
          <div v-if="!backups.length" class="text-sm text-surface-muted">No backups found yet.</div>
          <ul v-else class="max-h-48 space-y-1 overflow-y-auto text-xs">
            <li v-for="b in backups.slice(0, 20)" :key="b.id" class="truncate font-mono">
              {{ b.name }} · {{ formatBytes(b.size_bytes) }}
            </li>
          </ul>
        </Card>

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
        <Card title="Storage">
          <div v-if="!storage.length" class="text-sm text-surface-muted">No volumes reported.</div>
          <div v-else class="space-y-2">
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

        <Card title="Host logs" subtitle="Syslog tail">
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
.action-btn-primary {
  @apply rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50;
}
</style>
