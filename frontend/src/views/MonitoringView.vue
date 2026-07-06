<script setup lang="ts">
import { computed, onMounted } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import Badge from '@/components/ui/Badge.vue'
import StatCard from '@/components/dashboard/StatCard.vue'
import ResourceChart from '@/components/dashboard/ResourceChart.vue'
import ServiceStatusCard from '@/components/dashboard/ServiceStatusCard.vue'
import AlertList from '@/components/dashboard/AlertList.vue'
import { healthApi, monitoringApi, serverApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { usePolling } from '@/composables/usePolling'
import type {
  DashboardApiResponse,
  IntegrationsResponse,
  ReadinessResponse,
  ServiceItem,
  ServiceStatus,
  SystemMetrics,
} from '@/types/dashboard'
import { IconServer } from '@/components/icons'

const { data: dashboard, error: dashboardError, loading, refreshing, refresh: refreshDashboard } =
  usePolling<DashboardApiResponse>(
    async () => (await monitoringApi.dashboard()).data,
    REALTIME_POLL_MS,
  )

const { data: metrics, refresh: refreshMetrics } = usePolling<SystemMetrics>(
  async () => (await monitoringApi.metrics()).data,
  REALTIME_POLL_MS,
)

const { data: integrations, error: integrationsError, refresh: refreshIntegrations } =
  usePolling<IntegrationsResponse>(
    async () => (await monitoringApi.integrations()).data,
    REALTIME_POLL_MS,
  )

const { data: readiness, refresh: refreshReadiness } = usePolling<ReadinessResponse>(
  async () => (await healthApi.readiness()).data,
  REALTIME_POLL_MS,
)

const { data: health, refresh: refreshHealth } = usePolling(
  async () => (await healthApi.liveness()).data,
  REALTIME_POLL_MS,
)

const { data: services, refresh: refreshServices } = usePolling(
  async () => (await serverApi.services({ mode: 'relevant' })).data,
  REALTIME_POLL_MS,
)

function mapServiceStatus(status: string): ServiceStatus {
  const map: Record<string, ServiceStatus> = {
    running: 'running',
    stopped: 'stopped',
    degraded: 'degraded',
    unknown: 'unknown',
    failed: 'stopped',
  }
  return map[status] ?? 'unknown'
}

const serviceItems = computed<ServiceItem[]>(() =>
  (services.value?.services ?? []).map((svc) => ({
    id: svc.id,
    name: svc.display_name || svc.name,
    status: mapServiceStatus(String(svc.status)),
    description: svc.description ?? `${svc.category ?? svc.source} service`,
    uptime: svc.uptime_seconds
      ? `${Math.floor(svc.uptime_seconds / 3600)}h uptime`
      : undefined,
  })),
)

const servicesSubtitle = computed(() => {
  const shown = serviceItems.value.length
  const total = services.value?.total_relevant ?? shown
  return `${shown} shown · ${total} operational`
})

const integrationEntries = computed(() => {
  if (!integrations.value) return []
  return Object.entries(integrations.value).map(([name, info]) => ({
    name,
    configured: info.configured,
    status: String(info.status ?? 'unknown'),
  }))
})

const metricStats = computed(() => {
  if (!metrics.value) return []
  return [
    {
      id: 'cpu-live',
      label: 'CPU',
      value: metrics.value.cpu_percent?.toFixed(1) ?? '—',
      unit: '%',
    },
    {
      id: 'mem-live',
      label: 'Memory',
      value: metrics.value.memory_percent?.toFixed(1) ?? '—',
      unit: '%',
    },
    {
      id: 'disk-live',
      label: 'Disk',
      value: metrics.value.disk_percent?.toFixed(1) ?? '—',
      unit: '%',
    },
    {
      id: 'uptime-live',
      label: 'Uptime',
      value: metrics.value.uptime_seconds
        ? `${Math.floor(metrics.value.uptime_seconds / 3600)}h`
        : '—',
      unit: '',
    },
  ]
})

function refreshAll() {
  refreshDashboard()
  refreshMetrics()
  refreshIntegrations()
  refreshReadiness()
  refreshHealth()
  refreshServices()
}

onMounted(refreshAll)
</script>

<template>
  <DashboardLayout :refreshing="refreshing" @refresh="refreshAll">
    <ErrorState
      v-if="dashboardError && !dashboard"
      :message="dashboardError.message"
      @retry="refreshAll"
    />

    <div v-else class="animate-fade-in space-y-5">
      <Card title="Platform Status" subtitle="Live · updates every 5s">
        <div class="flex flex-wrap gap-4 text-sm">
          <div>
            <p class="text-surface-muted">Liveness</p>
            <Badge :variant="health?.status === 'healthy' ? 'success' : 'warning'" dot>
              {{ health?.status ?? '—' }}
            </Badge>
          </div>
          <div>
            <p class="text-surface-muted">Readiness</p>
            <Badge :variant="readiness?.status === 'healthy' ? 'success' : 'warning'" dot>
              {{ readiness?.status ?? '—' }}
            </Badge>
          </div>
          <div>
            <p class="text-surface-muted">Environment</p>
            <p class="font-medium">{{ health?.environment ?? '—' }}</p>
          </div>
          <div>
            <p class="text-surface-muted">Version</p>
            <p class="font-medium">{{ health?.version ?? '—' }}</p>
          </div>
        </div>
      </Card>

      <section class="dashboard-grid grid-cols-2 md:grid-cols-4">
        <StatCard v-for="stat in metricStats" :key="stat.id" :stat="stat" :loading="loading" />
      </section>

      <section class="dashboard-grid lg:grid-cols-3">
        <Card title="CPU" subtitle="Live history">
          <ResourceChart
            title="CPU"
            :chart="dashboard?.charts.cpu ?? { categories: [], series: [] }"
            :loading="loading"
            unit="%"
          />
        </Card>
        <Card title="Memory" subtitle="Live history">
          <ResourceChart
            title="Memory"
            :chart="dashboard?.charts.memory ?? { categories: [], series: [] }"
            :loading="loading"
            unit="%"
          />
        </Card>
        <Card title="Network" subtitle="Live history">
          <ResourceChart
            title="Network"
            :chart="dashboard?.charts.network ?? { categories: [], series: [] }"
            :loading="loading"
          />
        </Card>
      </section>

      <div class="dashboard-grid items-start lg:grid-cols-2">
        <Card title="Integrations" subtitle="Collector status" class="min-w-0">
          <ErrorState
            v-if="integrationsError"
            message="Unable to load integration status."
            @retry="refreshIntegrations"
          />
          <div v-else class="space-y-2">
            <div
              v-for="item in integrationEntries"
              :key="item.name"
              class="flex items-center justify-between rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-900"
            >
              <span class="font-medium capitalize">{{ item.name }}</span>
              <div class="flex items-center gap-2">
                <span class="text-xs text-surface-muted">
                  {{ item.configured ? 'configured' : 'not configured' }}
                </span>
                <Badge
                  :variant="
                    item.status === 'healthy'
                      ? 'success'
                      : item.status === 'degraded'
                        ? 'warning'
                        : 'neutral'
                  "
                  dot
                  size="sm"
                >
                  {{ item.status }}
                </Badge>
              </div>
            </div>
          </div>
        </Card>

        <Card title="Services" :subtitle="servicesSubtitle" class="flex min-h-0 min-w-0 flex-col">
          <div class="relative min-h-0">
            <div
              class="services-scroll max-h-72 space-y-2 overflow-y-auto overscroll-y-contain pr-1"
              role="list"
              aria-label="Operational services"
            >
              <ServiceStatusCard
                v-for="service in serviceItems"
                :key="service.id"
                :service="service"
              >
                <template #icon>
                  <IconServer :size="16" class="text-brand-500" />
                </template>
              </ServiceStatusCard>
            </div>
            <div
              v-if="serviceItems.length > 4"
              class="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-surface-raised to-transparent"
              aria-hidden="true"
            />
          </div>
          <p v-if="!serviceItems.length && !loading" class="text-sm text-surface-muted">
            No services detected on this host.
          </p>
        </Card>
      </div>

      <Card title="Active Alerts">
        <AlertList :alerts="dashboard?.alerts ?? []" :loading="loading" />
      </Card>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.services-scroll {
  scrollbar-width: thin;
  scrollbar-color: rgb(148 163 184 / 0.5) transparent;
}

.services-scroll::-webkit-scrollbar {
  width: 6px;
}

.services-scroll::-webkit-scrollbar-thumb {
  border-radius: 9999px;
  background-color: rgb(148 163 184 / 0.45);
}
</style>
