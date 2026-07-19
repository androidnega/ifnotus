<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import { applicationsApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import type { ApplicationSummary } from '@/types/dashboard'
import type { DiscoveredApplication } from '@/types/inventory'

const apps = ref<ApplicationSummary[]>([])
const discovered = ref<DiscoveredApplication[]>([])
const issuesCount = ref(0)
const loading = ref(true)
const loadError = ref<string | null>(null)
const filter = ref<'all' | 'registered' | 'discovered' | 'issues'>('all')

const reconciliationVariant = (state: string) => {
  if (state === 'registered') return 'success'
  if (state === 'discovered_unregistered') return 'info'
  if (state === 'registry_invalid_config') return 'warning'
  return 'warning'
}

const registryIssueApps = computed(() => apps.value.filter((app) => app.registry_valid === false))

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

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Applications</h1>
          <p class="text-sm text-surface-muted">
            Registered YAML apps and VPS-discovered applications
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="tab in [
              { id: 'all', label: 'All' },
              { id: 'registered', label: 'Registered' },
              { id: 'discovered', label: 'Discovered' },
              { id: 'issues', label: `Issues (${issuesCount})` },
            ]"
            :key="tab.id"
            type="button"
            class="rounded-lg border px-3 py-1.5 text-xs"
            :class="
              filter === tab.id
                ? 'border-brand-500 bg-brand-500/10 text-brand-700'
                : 'border-surface-border text-surface-muted'
            "
            @click="filter = tab.id as typeof filter"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <p v-if="loadError" class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
        {{ loadError }}
      </p>

      <section v-if="filter === 'all' || filter === 'registered' || filter === 'issues'" class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {{ filter === 'issues' ? 'Registered with registry issues' : 'Registered' }}
        </h2>
        <div class="dashboard-grid md:grid-cols-2 xl:grid-cols-3">
          <RouterLink
            v-for="app in filteredRegistered"
            :key="app.id"
            :to="`/applications/${app.id}`"
            class="block rounded-xl border border-surface-border bg-surface-raised p-4 shadow-card transition hover:border-brand-500/30"
          >
            <div class="flex items-start justify-between gap-2">
              <div>
                <h2 class="font-semibold text-slate-900 dark:text-white">{{ app.name }}</h2>
                <p class="text-xs text-surface-muted">{{ app.type }} · {{ app.environment }}</p>
              </div>
              <Badge :variant="app.health === 'healthy' ? 'success' : 'warning'" size="sm">
                {{ app.health_score }}
              </Badge>
            </div>
            <p class="mt-2 text-sm text-surface-muted">{{ app.domain || app.root_path }}</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <Badge size="sm">{{ app.status }}</Badge>
              <Badge variant="success" size="sm">registered</Badge>
              <Badge :variant="app.enabled ? 'success' : 'neutral'" size="sm">
                {{ app.enabled ? 'Enabled' : 'Disabled' }}
              </Badge>
              <Badge v-if="app.registry_valid === false" variant="warning" size="sm">
                registry issue
              </Badge>
            </div>
            <ul
              v-if="app.registry_errors?.length"
              class="mt-2 list-inside list-disc text-xs text-amber-700 dark:text-amber-300"
            >
              <li v-for="(err, idx) in app.registry_errors.slice(0, 3)" :key="idx">{{ err }}</li>
            </ul>
          </RouterLink>
        </div>
        <p v-if="!filteredRegistered.length && !loading" class="text-sm text-surface-muted">
          No registered applications in this view.
        </p>
      </section>

      <section v-if="filter !== 'registered'" class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {{ filter === 'issues' ? 'Reconciliation issues' : 'Discovered on VPS' }}
        </h2>
        <div class="dashboard-grid md:grid-cols-2 xl:grid-cols-3">
          <Card
            v-for="app in filteredDiscovered"
            :key="app.id + app.root_path"
            padding="md"
            class="border-dashed"
          >
            <div class="flex items-start justify-between gap-2">
              <div>
                <h2 class="font-semibold text-slate-900 dark:text-white">{{ app.name }}</h2>
                <p class="text-xs text-surface-muted">{{ app.probable_type }}</p>
              </div>
              <Badge :variant="reconciliationVariant(app.reconciliation_state)" size="sm">
                {{ app.reconciliation_state.replace(/_/g, ' ') }}
              </Badge>
            </div>
            <p class="mt-2 truncate text-sm text-surface-muted" :title="app.root_path">{{ app.root_path }}</p>
            <p v-if="app.server_names.length" class="mt-1 text-xs text-surface-muted">
              {{ app.server_names.join(', ') }}
            </p>
            <div class="mt-3 flex flex-wrap gap-1">
              <Badge v-for="signal in app.signals.slice(0, 4)" :key="signal" size="sm">{{ signal }}</Badge>
            </div>
            <ul
              v-if="app.registry_errors?.length"
              class="mt-2 list-inside list-disc text-xs text-amber-700 dark:text-amber-300"
            >
              <li v-for="(err, idx) in app.registry_errors.slice(0, 3)" :key="idx">{{ err }}</li>
            </ul>
          </Card>
        </div>
        <p v-if="!filteredDiscovered.length && !loading" class="text-sm text-surface-muted">
          No discovered applications in this view.
        </p>
      </section>
    </div>
  </DashboardLayout>
</template>
