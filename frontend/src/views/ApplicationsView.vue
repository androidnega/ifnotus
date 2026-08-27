<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import UiTabBar from '@/components/ui/UiTabBar.vue'
import { applicationsApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { ApplicationSummary, ClearablePath } from '@/types/dashboard'
import type { DiscoveredApplication } from '@/types/inventory'

const apps = ref<ApplicationSummary[]>([])
const discovered = ref<DiscoveredApplication[]>([])
const issuesCount = ref(0)
const loading = ref(true)
const loadError = ref<string | null>(null)
const filter = ref<'all' | 'registered' | 'discovered' | 'issues'>('all')
const actionBusy = ref<string | null>(null)
const actionMessage = ref<{ ok: boolean; text: string } | null>(null)

const reconciliationVariant = (state: string) => {
  if (state === 'registered') return 'success'
  if (state === 'discovered_unregistered') return 'info'
  if (state === 'registry_invalid_config') return 'warning'
  return 'warning'
}

const registryIssueApps = computed(() => apps.value.filter((app) => app.registry_valid === false))

const filterTabs = computed(() => [
  { id: 'all', label: 'All' },
  { id: 'registered', label: 'Registered' },
  { id: 'discovered', label: 'Discovered' },
  { id: 'issues', label: `Issues (${issuesCount.value})` },
])

const filteredRegistered = computed(() => {
  if (filter.value === 'discovered') return []
  if (filter.value === 'issues') return registryIssueApps.value
  return apps.value
})

const filteredDiscovered = computed(() => {
  if (filter.value === 'registered') return []
  if (filter.value === 'issues') {
    return discovered.value.filter(
      (d) => d.reconciliation_state !== 'registered' && d.reconciliation_state !== 'discovered_unregistered',
    )
  }
  return discovered.value
})

const totalMemory = computed(() =>
  apps.value.reduce((sum, app) => sum + (app.memory_bytes ?? 0), 0),
)
const totalClearable = computed(() =>
  apps.value.reduce((sum, app) => sum + (app.clearable_bytes ?? 0), 0),
)

function formatBytes(bytes?: number | null): string {
  if (bytes == null || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

function topClearable(paths?: ClearablePath[], limit = 3): ClearablePath[] {
  return [...(paths ?? [])].sort((a, b) => b.bytes - a.bytes).slice(0, limit)
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const { data } = await applicationsApi.list()
    apps.value = data.applications
    discovered.value = data.discovered ?? []
    issuesCount.value = data.issues_count ?? 0
  } catch (e) {
    loadError.value = getApiErrorMessage(e, 'Failed to load applications.')
  } finally {
    loading.value = false
  }
}

async function clearAllCaches() {
  if (!confirm('Clear caches/temp for every enabled application on this server?')) return
  actionBusy.value = 'cache-all'
  actionMessage.value = null
  try {
    const { data } = await applicationsApi.clearAllCaches()
    actionMessage.value = { ok: data.success, text: data.message }
    await load()
  } catch (e) {
    actionMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to clear app caches') }
  } finally {
    actionBusy.value = null
  }
}

async function clearAppCache(appId: string, event: Event) {
  event.preventDefault()
  event.stopPropagation()
  if (!confirm(`Clear temporary/cache files for ${appId}?`)) return
  actionBusy.value = `cache-${appId}`
  actionMessage.value = null
  try {
    const { data } = await applicationsApi.clearCache(appId)
    actionMessage.value = { ok: data.success, text: data.message }
    await load()
  } catch (e) {
    actionMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to clear cache') }
  } finally {
    actionBusy.value = null
  }
}

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="animate-fade-in space-y-5">
      <UiPageHeader
        title="Apps"
        lede="Every hosted site and subdomain on this server — live RAM/CPU, plus clearable temp files"
      >
        <template #actions>
          <button
            type="button"
            class="ds-btn-ghost text-xs"
            :disabled="!!actionBusy"
            @click="clearAllCaches"
          >
            {{ actionBusy === 'cache-all' ? 'Clearing…' : 'Clear all temp/caches' }}
          </button>
        </template>
      </UiPageHeader>

      <UiTabBar
        :model-value="filter"
        :items="filterTabs"
        aria-label="Application filters"
        @update:model-value="(id) => (filter = id as typeof filter)"
      />

      <UiAlert v-if="actionMessage" :tone="actionMessage.ok ? 'ok' : 'err'">
        {{ actionMessage.text }}
      </UiAlert>

      <div
        v-if="!loading && apps.length"
        class="grid gap-3 sm:grid-cols-3"
      >
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Apps tracked</p>
          <p class="mt-1 text-xl font-semibold tabular-nums text-slate-900 dark:text-white">
            {{ apps.length }}
          </p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">App process RAM (sum)</p>
          <p class="mt-1 text-xl font-semibold tabular-nums text-slate-900 dark:text-white">
            {{ formatBytes(totalMemory) }}
          </p>
        </Card>
        <Card padding="sm">
          <p class="text-xs text-surface-muted">Clearable temp/cache</p>
          <p class="mt-1 text-xl font-semibold tabular-nums text-slate-900 dark:text-white">
            {{ formatBytes(totalClearable) }}
          </p>
        </Card>
      </div>

      <UiAlert v-if="loadError" tone="err">{{ loadError }}</UiAlert>

      <div v-if="loading" class="space-y-3">
        <Skeleton v-for="n in 4" :key="n" height="3.5rem" width="100%" />
      </div>

      <template v-else>
        <section v-if="filter === 'all' || filter === 'registered' || filter === 'issues'" class="space-y-3">
          <h2 class="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {{ filter === 'issues' ? 'Registered with registry issues' : 'Resource usage' }}
          </h2>

          <div class="overflow-x-auto rounded-xl border border-surface-border bg-surface-raised shadow-card">
            <table class="min-w-full text-left text-sm">
              <thead class="border-b border-surface-border bg-slate-50 text-xs uppercase tracking-wide text-surface-muted dark:bg-slate-900/40">
                <tr>
                  <th class="px-4 py-3 font-medium">Application</th>
                  <th class="px-4 py-3 font-medium">Status</th>
                  <th class="px-4 py-3 font-medium">Procs</th>
                  <th class="px-4 py-3 font-medium">CPU</th>
                  <th class="px-4 py-3 font-medium">RAM</th>
                  <th class="px-4 py-3 font-medium">Clearable temp</th>
                  <th class="px-4 py-3 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="app in filteredRegistered"
                  :key="app.id"
                  class="border-b border-surface-border/70 last:border-0"
                >
                  <td class="px-4 py-3">
                    <RouterLink
                      :to="`/applications/${app.id}`"
                      class="font-medium text-slate-900 hover:text-brand-600 dark:text-white"
                    >
                      {{ app.name }}
                    </RouterLink>
                    <p class="text-xs text-surface-muted">{{ app.type }} · {{ app.domain || app.root_path }}</p>
                  </td>
                  <td class="px-4 py-3">
                    <div class="flex flex-wrap gap-1">
                      <Badge :variant="app.health === 'healthy' ? 'success' : 'warning'" size="sm">
                        {{ app.status }}
                      </Badge>
                      <Badge v-if="!app.enabled" variant="neutral" size="sm">disabled</Badge>
                    </div>
                  </td>
                  <td class="px-4 py-3 tabular-nums text-surface-muted">{{ app.process_count ?? 0 }}</td>
                  <td class="px-4 py-3 tabular-nums text-surface-muted">
                    {{ app.cpu_percent != null ? `${app.cpu_percent.toFixed(1)}%` : '—' }}
                  </td>
                  <td class="px-4 py-3">
                    <p class="font-medium tabular-nums text-slate-900 dark:text-white">
                      {{ formatBytes(app.memory_bytes) }}
                    </p>
                    <p v-if="app.memory_percent" class="text-xs tabular-nums text-surface-muted">
                      {{ app.memory_percent.toFixed(1) }}% of host
                    </p>
                  </td>
                  <td class="px-4 py-3">
                    <p class="font-medium tabular-nums text-slate-900 dark:text-white">
                      {{ formatBytes(app.clearable_bytes) }}
                    </p>
                    <ul
                      v-if="topClearable(app.clearable_paths).length"
                      class="mt-1 space-y-0.5 text-[11px] text-surface-muted"
                    >
                      <li v-for="item in topClearable(app.clearable_paths)" :key="item.path">
                        {{ item.label }} · {{ formatBytes(item.bytes) }}
                      </li>
                    </ul>
                    <p v-else class="text-xs text-surface-muted">No temp cache found</p>
                  </td>
                  <td class="px-4 py-3">
                    <button
                      type="button"
                      class="rounded-lg border border-surface-border px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50 dark:hover:bg-slate-800"
                      :disabled="!!actionBusy || !(app.clearable_bytes && app.clearable_bytes > 0)"
                      @click="clearAppCache(app.id, $event)"
                    >
                      {{ actionBusy === `cache-${app.id}` ? 'Clearing…' : 'Clear temp' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="!filteredRegistered.length" class="px-4 py-6 text-sm text-surface-muted">
              No registered applications in this view.
            </p>
          </div>
        </section>

        <section v-if="filter !== 'registered'" class="space-y-3">
          <h2 class="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {{ filter === 'issues' ? 'Reconciliation issues' : 'Still discovering' }}
          </h2>
          <p v-if="filter !== 'issues'" class="text-xs text-surface-muted">
            Excluded platform paths stay here. Everything else is auto-registered as an active app.
          </p>
          <div class="dashboard-grid md:grid-cols-2 xl:grid-cols-3">
            <Card
              v-for="app in filteredDiscovered"
              :key="`${app.root_path}-${app.name}`"
              padding="md"
            >
              <div class="flex items-start justify-between gap-2">
                <div>
                  <h3 class="font-semibold text-slate-900 dark:text-white">{{ app.name }}</h3>
                  <p class="text-xs text-surface-muted">{{ app.probable_type }} · {{ app.root_path }}</p>
                </div>
                <Badge :variant="reconciliationVariant(app.reconciliation_state)" size="sm">
                  {{ app.reconciliation_state }}
                </Badge>
              </div>
            </Card>
          </div>
          <p v-if="!filteredDiscovered.length" class="text-sm text-surface-muted">
            Nothing pending in discovery.
          </p>
        </section>
      </template>
    </div>
  </DashboardLayout>
</template>
