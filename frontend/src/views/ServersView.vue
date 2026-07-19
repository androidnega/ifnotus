<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import { serverApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { usePolling } from '@/composables/usePolling'
import type {
  PortsResponse,
  ServerOverview,
  ServiceCategory,
  ServicesResponse,
} from '@/types/dashboard'

const viewMode = ref<'relevant' | 'all'>('relevant')
const categoryFilter = ref<string>('all')

const categories: Array<{ id: string; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'application', label: 'Application' },
  { id: 'web', label: 'Web' },
  { id: 'database', label: 'Database' },
  { id: 'cache', label: 'Cache' },
  { id: 'queue', label: 'Queue' },
  { id: 'monitoring', label: 'Monitoring' },
  { id: 'security', label: 'Security' },
  { id: 'system', label: 'System' },
]

const { data: overview, error: overviewError, loading, refresh: refreshOverview } =
  usePolling<ServerOverview>(
    async () => (await serverApi.overview()).data,
    REALTIME_POLL_MS,
    { requiresAuth: true },
  )

const { data: ports, error: portsError, refresh: refreshPorts } = usePolling<PortsResponse>(
  async () => (await serverApi.ports()).data,
  REALTIME_POLL_MS,
  { requiresAuth: true },
)

const {
  data: services,
  error: servicesError,
  refresh: refreshServices,
} = usePolling<ServicesResponse>(
  async () =>
    (
      await serverApi.services({
        mode: viewMode.value,
        category: categoryFilter.value === 'all' ? undefined : categoryFilter.value,
      })
    ).data,
  REALTIME_POLL_MS,
  { requiresAuth: true },
)

watch([viewMode, categoryFilter], () => refreshServices())

const errorMessage = computed(() => {
  const err = overviewError.value || portsError.value || servicesError.value
  return err instanceof Error ? err.message : err ? String(err) : null
})

function statusVariant(status: string) {
  if (status === 'running') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'stopped' || status === 'failed') return 'danger'
  return 'neutral'
}

function categoryVariant(category?: ServiceCategory) {
  const map: Record<string, 'success' | 'info' | 'warning' | 'neutral'> = {
    application: 'success',
    web: 'info',
    database: 'info',
    cache: 'warning',
    queue: 'warning',
    monitoring: 'info',
    security: 'warning',
    system: 'neutral',
  }
  return map[category ?? 'system'] ?? 'neutral'
}

function refreshAll() {
  refreshOverview()
  refreshPorts()
  refreshServices()
}

function formatUptime(seconds: number) {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  if (days > 0) return `${days}d ${hours}h`
  return `${hours}h`
}
</script>

<template>
  <DashboardLayout :refreshing="loading" @refresh="refreshAll">
    <ErrorState v-if="errorMessage && !overview" :message="errorMessage" @retry="refreshAll" />

    <div v-else class="animate-fade-in space-y-5">
      <Card title="Host Overview" :subtitle="overview?.hostname">
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p class="text-xs text-surface-muted">Status</p>
            <Badge :variant="overview?.status === 'healthy' ? 'success' : 'warning'" dot class="mt-1">
              {{ overview?.status ?? '—' }}
            </Badge>
          </div>
          <div>
            <p class="text-xs text-surface-muted">Health score</p>
            <p class="text-lg font-semibold">{{ overview?.health_score ?? '—' }}%</p>
          </div>
          <div>
            <p class="text-xs text-surface-muted">Uptime</p>
            <p class="font-medium">
              {{ overview ? formatUptime(overview.uptime_seconds) : '—' }}
            </p>
          </div>
          <div>
            <p class="text-xs text-surface-muted">Processes</p>
            <p class="font-medium">{{ overview?.process_count ?? '—' }}</p>
          </div>
        </div>

        <div class="mt-4 grid gap-4 sm:grid-cols-3">
          <div class="rounded-lg bg-slate-100 p-3 dark:bg-slate-900">
            <p class="text-xs text-surface-muted">CPU</p>
            <p class="text-xl font-semibold">{{ overview?.cpu_percent?.toFixed(1) ?? '—' }}%</p>
          </div>
          <div class="rounded-lg bg-slate-100 p-3 dark:bg-slate-900">
            <p class="text-xs text-surface-muted">Memory</p>
            <p class="text-xl font-semibold">{{ overview?.memory_percent?.toFixed(1) ?? '—' }}%</p>
          </div>
          <div class="rounded-lg bg-slate-100 p-3 dark:bg-slate-900">
            <p class="text-xs text-surface-muted">Disk</p>
            <p class="text-xl font-semibold">{{ overview?.disk_percent?.toFixed(1) ?? '—' }}%</p>
          </div>
        </div>
      </Card>

      <Card
        title="Listening Ports"
        :subtitle="`${ports?.total ?? 0} open · ${ports?.expected_ports?.length ?? 0} monitored`"
      >
        <div
          v-if="ports?.missing_ports?.length"
          class="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300"
        >
          Missing expected ports:
          <span class="font-mono font-medium">{{ ports.missing_ports.join(', ') }}</span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead class="text-xs text-surface-muted">
              <tr>
                <th class="pb-2 pr-4">Port</th>
                <th class="pb-2 pr-4">Process</th>
                <th class="pb-2 pr-4">Address</th>
                <th class="pb-2">Protocol</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="port in ports?.ports ?? []"
                :key="`${port.port}-${port.address}-${port.protocol}`"
                class="border-t border-surface-border"
              >
                <td class="py-2 pr-4 font-mono">
                  {{ port.port }}
                  <Badge
                    v-if="ports?.expected_ports?.includes(port.port)"
                    variant="info"
                    class="ml-1 text-[10px]"
                  >
                    monitored
                  </Badge>
                </td>
                <td class="py-2 pr-4">{{ port.process_name ?? '—' }}</td>
                <td class="py-2 pr-4 font-mono text-xs">{{ port.address }}</td>
                <td class="py-2 uppercase">{{ port.protocol }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <section class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-white">Running Services</h2>
            <p class="text-xs text-surface-muted">
              Showing {{ services?.services.length ?? 0 }}
              <span v-if="viewMode === 'relevant'">relevant</span>
              <span v-else>total</span>
              services
              <span v-if="services?.total_relevant != null">
                · {{ services.total_relevant }} relevant of {{ services.total_all }} on host
              </span>
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg border px-3 py-1.5 text-xs"
              :class="
                viewMode === 'relevant'
                  ? 'border-brand-500 bg-brand-500/10 text-brand-700'
                  : 'border-surface-border text-surface-muted'
              "
              @click="viewMode = 'relevant'"
            >
              Relevant
            </button>
            <button
              type="button"
              class="rounded-lg border px-3 py-1.5 text-xs"
              :class="
                viewMode === 'all'
                  ? 'border-brand-500 bg-brand-500/10 text-brand-700'
                  : 'border-surface-border text-surface-muted'
              "
              @click="viewMode = 'all'"
            >
              All services
            </button>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            v-for="cat in categories"
            :key="cat.id"
            type="button"
            class="rounded-full border px-3 py-1 text-xs"
            :class="
              categoryFilter === cat.id
                ? 'border-brand-500 bg-brand-500/10 text-brand-700'
                : 'border-surface-border text-surface-muted'
            "
            @click="categoryFilter = cat.id"
          >
            {{ cat.label }}
          </button>
        </div>

        <div v-if="!services?.services.length" class="text-sm text-surface-muted">
          No services match the current filters.
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="svc in services.services"
            :key="svc.id"
            class="rounded-xl border border-surface-border bg-surface-raised px-4 py-3"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium text-slate-900 dark:text-white">
                    {{ svc.display_name || svc.name }}
                  </span>
                  <Badge :variant="statusVariant(String(svc.status))" size="sm" dot>
                    {{ svc.status }}
                  </Badge>
                  <Badge :variant="categoryVariant(svc.category)" size="sm">
                    {{ svc.category || 'system' }}
                  </Badge>
                  <Badge v-if="svc.managed_by_ifnotus" size="sm" variant="info">IFNOTUS</Badge>
                </div>
                <p class="mt-1 font-mono text-xs text-surface-muted">
                  {{ svc.unit_name || svc.name }}
                  <span v-if="svc.source"> · {{ svc.source }}</span>
                </p>
                <p v-if="svc.description" class="mt-1 text-xs text-surface-muted">{{ svc.description }}</p>
                <p v-if="svc.app_id" class="mt-1 text-xs">
                  Linked app:
                  <RouterLink :to="`/applications/${svc.app_id}`" class="text-brand-600 underline">
                    {{ svc.app_id }}
                  </RouterLink>
                </p>
                <p v-if="svc.ports?.length" class="mt-1 text-xs text-surface-muted">
                  Ports: {{ svc.ports.join(', ') }}
                </p>
              </div>
              <div class="text-right text-xs text-surface-muted">
                <p v-if="svc.pid">PID {{ svc.pid }}</p>
                <p v-if="svc.uptime_seconds">{{ formatUptime(svc.uptime_seconds) }} uptime</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </DashboardLayout>
</template>
