<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import { applicationsApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { ApplicationDetail, DeploymentRecord } from '@/types/operations'

const route = useRoute()
const appId = computed(() => String(route.params.id))

const app = ref<ApplicationDetail | null>(null)
const deployments = ref<DeploymentRecord[]>([])
const logs = ref<Array<{ message?: string; level?: string }>>([])
const envVars = ref<Record<string, string>>({})
const loading = ref(true)
const error = ref<string | null>(null)
const actionLoading = ref<string | null>(null)
const message = ref<{ ok: boolean; text: string } | null>(null)
const activeTab = ref<'overview' | 'deployments' | 'logs' | 'environment' | 'services'>('overview')

async function load() {
  loading.value = true
  error.value = null
  try {
    const detail = await applicationsApi.get(appId.value)
    app.value = detail.data

    const [deps, logRes, env] = await Promise.allSettled([
      applicationsApi.deployments(appId.value),
      applicationsApi.logs(appId.value, 120),
      applicationsApi.environment(appId.value),
    ])
    deployments.value = deps.status === 'fulfilled' ? (deps.value.data.deployments as DeploymentRecord[]) : []
    logs.value = logRes.status === 'fulfilled' ? logRes.value.data.entries : []
    envVars.value = env.status === 'fulfilled' ? env.value.data.variables : {}
  } catch (e) {
    app.value = null
    error.value = getApiErrorMessage(e, 'Failed to load application.')
  } finally {
    loading.value = false
  }
}

async function run(key: string, fn: () => Promise<{ data: { success: boolean; message: string } }>) {
  actionLoading.value = key
  message.value = null
  try {
    const { data } = await fn()
    message.value = { ok: data.success, text: data.message }
    await load()
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Action failed') }
  } finally {
    actionLoading.value = null
  }
}

async function revealEnv() {
  try {
    const { data } = await applicationsApi.revealEnvironment(appId.value)
    envVars.value = data
  } catch (e) {
    message.value = { ok: false, text: getApiErrorMessage(e, 'Failed to reveal environment') }
  }
}

const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'deployments', label: 'Deployments' },
  { id: 'logs', label: 'Logs' },
  { id: 'environment', label: 'Environment' },
  { id: 'services', label: 'Services' },
] as const

const serviceActions = ['start', 'stop', 'restart', 'enable', 'disable'] as const

const serviceRunning = computed(() => {
  const status = String(app.value?.status ?? '').toLowerCase()
  if (status === 'running') return true
  if (status === 'stopped' || status === 'failed') return false
  const nginx = app.value?.nginx as { enabled?: boolean } | undefined
  if (nginx?.enabled === true) return true
  if (nginx?.enabled === false) return false
  return !!app.value?.enabled
})

const serviceEnabled = computed(() => {
  const nginx = app.value?.nginx as { enabled?: boolean } | undefined
  if (typeof nginx?.enabled === 'boolean') return nginx.enabled
  return !!app.value?.enabled
})

function isServiceActionActive(action: (typeof serviceActions)[number]) {
  if (actionLoading.value === action) return true
  if (action === 'start') return serviceRunning.value
  if (action === 'stop') return !serviceRunning.value
  if (action === 'enable') return serviceEnabled.value
  if (action === 'disable') return !serviceEnabled.value
  return false
}

function serviceActionLabel(action: (typeof serviceActions)[number]) {
  if (actionLoading.value === action) return `${action}…`
  return action
}

watch(appId, load, { immediate: true })
</script>

<template>
  <DashboardLayout @refresh="load">
    <ErrorState v-if="error && !app && !loading" :message="error" @retry="load" />

    <div v-else-if="app" class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <RouterLink to="/applications" class="text-xs text-brand-600 hover:underline">← Applications</RouterLink>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">{{ app.name }}</h1>
          <p class="text-sm text-surface-muted">{{ app.id }} · {{ app.root_path }}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="run('refresh', () => applicationsApi.refresh(appId))"
          >
            Refresh status
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="run('pull', () => applicationsApi.gitPull(appId))"
          >
            Git pull
          </button>
          <button
            type="button"
            class="action-btn-primary"
            :disabled="!!actionLoading"
            @click="run('deploy', () => applicationsApi.deploy(appId))"
          >
            Deploy
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="run('restart', () => applicationsApi.restart(appId))"
          >
            Restart app
          </button>
          <button
            type="button"
            class="action-btn"
            :disabled="!!actionLoading"
            @click="run('toggle', () => applicationsApi.setEnabled(appId, !app!.enabled))"
          >
            {{ app.enabled ? 'Disable' : 'Enable' }}
          </button>
        </div>
      </div>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.ok ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <div class="flex flex-wrap gap-1 border-b border-surface-border">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          class="px-3 py-2 text-sm transition"
          :class="
            activeTab === tab.id
              ? 'border-b-2 border-brand-500 font-medium text-brand-700 dark:text-brand-300'
              : 'text-surface-muted hover:text-slate-800'
          "
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>

      <div v-if="activeTab === 'overview'" class="dashboard-grid lg:grid-cols-2">
        <Card title="Health">
          <div class="flex flex-wrap gap-3 text-sm">
            <Badge :variant="app.health === 'healthy' ? 'success' : 'warning'">{{ app.health }}</Badge>
            <span>Score {{ app.health_score }}</span>
            <span>Runtime {{ app.status }}</span>
            <span v-if="app.version">v{{ app.version }}</span>
          </div>
        </Card>
        <Card v-if="app.git" title="Git">
          <dl class="space-y-1 text-sm">
            <div class="flex justify-between"><dt class="text-surface-muted">Branch</dt><dd>{{ app.git.branch || '—' }}</dd></div>
            <div class="flex justify-between"><dt class="text-surface-muted">Commit</dt><dd class="font-mono">{{ app.git.commit || '—' }}</dd></div>
            <div class="flex justify-between"><dt class="text-surface-muted">Dirty</dt><dd>{{ app.git.dirty ? 'Yes' : 'No' }}</dd></div>
          </dl>
          <p v-if="app.git.message" class="mt-2 text-xs text-amber-700 dark:text-amber-300">{{ app.git.message }}</p>
        </Card>
        <Card v-if="app.ssl" title="SSL">
          <p class="text-sm">{{ app.ssl.domain || '—' }}</p>
          <Badge v-if="app.ssl.status" class="mt-2" size="sm">{{ app.ssl.status }}</Badge>
          <p v-if="app.ssl.message" class="mt-2 text-xs text-surface-muted">{{ app.ssl.message }}</p>
        </Card>
        <Card v-if="app.nginx" title="Nginx">
          <p class="text-sm">{{ (app.nginx.server_names as string[])?.join(', ') || '—' }}</p>
          <div class="mt-2 flex flex-wrap gap-2">
            <Badge :variant="app.nginx.enabled ? 'success' : 'warning'" size="sm">
              site {{ app.nginx.enabled ? 'enabled' : 'disabled' }}
            </Badge>
            <Badge v-if="app.nginx.ssl_enabled" size="sm">ssl</Badge>
          </div>
          <p v-if="app.nginx.root" class="mt-2 truncate text-xs text-surface-muted" :title="String(app.nginx.root)">
            root {{ app.nginx.root }}
          </p>
          <p v-if="app.nginx.message" class="mt-2 text-xs text-surface-muted">{{ app.nginx.message }}</p>
        </Card>
      </div>

      <Card v-if="activeTab === 'deployments'" title="Deployment history">
        <div v-if="!deployments.length" class="text-sm text-surface-muted">No deployments recorded yet.</div>
        <div v-else class="space-y-2">
          <div
            v-for="dep in deployments"
            :key="dep.id"
            class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm"
          >
            <div>
              <p class="font-medium">{{ dep.version }} · {{ dep.status }}</p>
              <p class="text-xs text-surface-muted">
                {{ new Date(dep.timestamp).toLocaleString() }} · {{ dep.triggered_by || 'system' }}
              </p>
              <p v-if="dep.message" class="text-xs text-surface-muted">{{ dep.message }}</p>
            </div>
            <button
              type="button"
              class="action-btn text-xs"
              :disabled="!!actionLoading"
              @click="run(`redep-${dep.id}`, () => applicationsApi.redeploy(appId, dep.id))"
            >
              Redeploy
            </button>
          </div>
        </div>
      </Card>

      <Card v-if="activeTab === 'logs'" title="Application logs">
        <pre class="max-h-96 overflow-y-auto text-xs leading-relaxed text-surface-muted">{{
          logs.map((l) => l.message).join('\n') || 'No log lines.'
        }}</pre>
      </Card>

      <Card v-if="activeTab === 'environment'" title="Environment / secrets">
        <button type="button" class="mb-3 text-xs text-brand-600 hover:underline" @click="revealEnv">
          Reveal values (admin)
        </button>
        <dl class="max-h-96 space-y-1 overflow-y-auto text-xs">
          <div
            v-for="(val, key) in envVars"
            :key="key"
            class="grid grid-cols-[10rem_1fr] gap-2 border-b border-surface-border/40 py-1"
          >
            <dt class="truncate font-mono text-surface-muted">{{ key }}</dt>
            <dd class="truncate font-mono">{{ val }}</dd>
          </div>
        </dl>
      </Card>

      <div v-if="activeTab === 'services'" class="dashboard-grid lg:grid-cols-2">
        <Card title="Service control">
          <div class="mb-3 flex flex-wrap gap-2">
            <Badge :variant="serviceRunning ? 'success' : 'warning'" size="sm">
              {{ serviceRunning ? 'running' : 'stopped' }}
            </Badge>
            <Badge :variant="serviceEnabled ? 'success' : 'neutral'" size="sm">
              {{ serviceEnabled ? 'enabled' : 'disabled' }}
            </Badge>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="action in serviceActions"
              :key="action"
              type="button"
              class="action-btn capitalize"
              :class="{
                'action-btn-active': isServiceActionActive(action) && actionLoading !== action,
                'action-btn-busy': actionLoading === action,
              }"
              :disabled="!!actionLoading"
              :aria-pressed="isServiceActionActive(action)"
              @click="run(action, () => applicationsApi.serviceAction(appId, action))"
            >
              {{ serviceActionLabel(action) }}
            </button>
          </div>
          <p class="mt-3 text-xs text-surface-muted">
            Active controls reflect the current runtime and nginx/service state.
          </p>
        </Card>
        <Card title="Bindings">
          <dl class="space-y-2 text-sm">
            <div v-if="app.systemd?.name">
              <dt class="text-surface-muted">systemd</dt>
              <dd>{{ app.systemd.name }} · {{ app.systemd.status }}</dd>
            </div>
            <div v-if="app.supervisor?.name">
              <dt class="text-surface-muted">supervisor</dt>
              <dd>{{ app.supervisor.name }} · {{ app.supervisor.status }}</dd>
            </div>
            <div v-if="app.nginx?.configured">
              <dt class="text-surface-muted">nginx site</dt>
              <dd>{{ app.nginx.enabled ? 'enabled' : 'disabled' }} · {{ app.nginx.site_path || '—' }}</dd>
            </div>
            <p
              v-if="!app.systemd?.name && !app.supervisor?.name && !app.nginx?.configured"
              class="text-xs text-surface-muted"
            >
              No service bindings configured in YAML.
            </p>
          </dl>
        </Card>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.action-btn {
  @apply rounded-lg border border-surface-border px-3 py-2 text-sm transition hover:bg-slate-50 disabled:opacity-50 dark:hover:bg-slate-800;
}
.action-btn-primary {
  @apply rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-500 disabled:opacity-50;
}
.action-btn-active {
  @apply border-brand-500 bg-brand-500/15 font-medium text-brand-800 ring-1 ring-brand-500/30 dark:text-brand-200;
}
.action-btn-busy {
  @apply border-amber-500/50 bg-amber-500/15 font-medium text-amber-800 ring-1 ring-amber-500/30 dark:text-amber-200;
}
</style>
