<script setup lang="ts">
import { computed, onMounted } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import ServiceStatusCard from '@/components/dashboard/ServiceStatusCard.vue'
import { serverApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { usePolling } from '@/composables/usePolling'
import type { PortsResponse, ServerOverview, ServicesResponse } from '@/types/dashboard'

const { data: overview, error: overviewError, loading, refresh: refreshOverview } =
  usePolling<ServerOverview>(async () => (await serverApi.overview()).data, REALTIME_POLL_MS)

const { data: ports, error: portsError, refresh: refreshPorts } = usePolling<PortsResponse>(
  async () => (await serverApi.ports()).data,
  REALTIME_POLL_MS,
)

const { data: services, error: servicesError, refresh: refreshServices } =
  usePolling<ServicesResponse>(async () => (await serverApi.services()).data, REALTIME_POLL_MS)

const errorMessage = computed(() => {
  const err = overviewError.value || portsError.value || servicesError.value
  return err instanceof Error ? err.message : err ? String(err) : null
})

const serviceCards = computed(() =>
  (services.value?.services ?? []).map((svc) => ({
    id: svc.id,
    name: svc.name,
    status: svc.status as 'running' | 'stopped' | 'degraded' | 'unknown',
    description: svc.description ?? svc.source,
    uptime: svc.uptime_seconds
      ? `${Math.floor(svc.uptime_seconds / 3600)}h uptime`
      : undefined,
  })),
)

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

onMounted(refreshAll)
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

      <section>
        <h2 class="mb-3 text-sm font-semibold text-surface-muted">Managed Services</h2>
        <div class="dashboard-grid md:grid-cols-2 xl:grid-cols-3">
          <ServiceStatusCard v-for="svc in serviceCards" :key="svc.id" :service="svc" />
        </div>
        <p v-if="!serviceCards.length" class="text-sm text-surface-muted">No services detected.</p>
      </section>
    </div>
  </DashboardLayout>
</template>
