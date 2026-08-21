import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { applicationsApi, healthApi, monitoringApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import type {
  ActivityItem,
  ApiManagedService,
  ApplicationItem,
  DashboardApiResponse,
  DashboardData,
  DeploymentItem,
  HealthResponse,
  ReadinessResponse,
  ServiceItem,
  ServiceStatus,
  SystemMetrics,
} from '@/types/dashboard'

function mapServiceStatus(status: string): ServiceStatus {
  const map: Record<string, ServiceStatus> = {
    running: 'running',
    stopped: 'stopped',
    degraded: 'degraded',
    unknown: 'unknown',
    failed: 'failed',
  }
  return map[status] ?? 'unknown'
}

function mapDeploymentStatus(status: string): DeploymentItem['status'] {
  const map: Record<string, DeploymentItem['status']> = {
    success: 'success',
    failed: 'failed',
    in_progress: 'in_progress',
    pending: 'pending',
    running: 'in_progress',
  }
  return map[status] ?? 'pending'
}

function mapManagedService(svc: ApiManagedService): ServiceItem {
  return {
    id: svc.id,
    name: svc.name,
    status: mapServiceStatus(String(svc.status)),
    description: svc.description ?? `${svc.source} service`,
    uptime: svc.uptime_seconds
      ? `${Math.floor(svc.uptime_seconds / 3600)}h uptime`
      : undefined,
  }
}

function mapDashboardApplications(dashboard: DashboardApiResponse): ApplicationItem[] {
  return (dashboard.applications ?? []).map((app) => ({
    id: app.id,
    name: app.name,
    status: mapServiceStatus(String(app.status)),
    version: app.version ?? undefined,
    environment: app.environment ?? undefined,
  }))
}

async function fetchRecentDeployments(): Promise<DeploymentItem[] | null> {
  try {
    const { data: list } = await applicationsApi.list()
    const enabled = list.applications.filter((app) => app.enabled).slice(0, 6)
    const batches = await Promise.allSettled(
      enabled.map((app) => applicationsApi.deployments(app.id)),
    )

    const deployments: DeploymentItem[] = []
    batches.forEach((result, index) => {
      if (result.status !== 'fulfilled') return
      const app = enabled[index]
      for (const dep of result.value.data.deployments.slice(0, 3)) {
        deployments.push({
          id: dep.id,
          application: app.name,
          environment: dep.environment,
          version: dep.version,
          status: mapDeploymentStatus(dep.status),
          timestamp: dep.timestamp,
          triggeredBy: dep.triggered_by ?? 'system',
        })
      }
    })

    return deployments
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 8)
  } catch {
    return null
  }
}

const STAFF_CACHE_KEY = 'ifnotus.staff.dashboard'

function readStaffCache(): DashboardApiResponse | null {
  try {
    const raw = sessionStorage.getItem(STAFF_CACHE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as DashboardApiResponse
  } catch {
    return null
  }
}

function writeStaffCache(payload: DashboardApiResponse) {
  try {
    sessionStorage.setItem(STAFF_CACHE_KEY, JSON.stringify(payload))
  } catch {
    /* ignore quota */
  }
}

function mapDashboardResponse(
  dashboard: DashboardApiResponse,
  health: HealthResponse | null,
  readiness: ReadinessResponse | null,
  deployments: DeploymentItem[],
): DashboardData {
  const metrics: SystemMetrics = {
    timestamp: dashboard.timestamp,
    uptime_seconds: undefined,
    cpu_percent: dashboard.servers[0]?.cpu ?? null,
    memory_percent: dashboard.servers[0]?.memory ?? null,
    disk_percent: dashboard.servers[0]?.disk ?? null,
  }

  return {
    health,
    readiness,
    metrics,
    integrations: null,
    healthScore: dashboard.health_score,
    stats: (dashboard.stats || []).map((s) => ({
      ...s,
      trendValue: s.trend_value,
    })),
    servers: dashboard.servers || [],
    services: (dashboard.services || []).map(mapManagedService),
    applications: mapDashboardApplications(dashboard),
    alerts: (dashboard.alerts || []).map((a) => ({
      id: a.id,
      title: a.title,
      message: a.message,
      severity: a.severity,
      timestamp: a.timestamp,
      source: a.source,
      acknowledged: a.acknowledged,
    })),
    deployments,
    activities: dashboard.activities as ActivityItem[],
    charts: dashboard.charts,
    loadAverage: ((dashboard.load_average?.length ?? 0) >= 3
      ? dashboard.load_average.slice(0, 3)
      : [...(dashboard.load_average || []), 0, 0, 0].slice(0, 3)) as [number, number, number],
    networkThroughput: dashboard.network_throughput,
    collectors: dashboard.collectors,
    inventory: dashboard.inventory ?? null,
  }
}

export function useDashboard() {
  const data = shallowRef<DashboardData | null>(null)
  const loading = ref(true)
  const refreshing = ref(false)
  const error = ref<string | null>(null)
  const extrasError = ref<string | null>(null)
  let timer: ReturnType<typeof setInterval> | null = null
  let pollCount = 0

  const runningServices = computed(
    () => data.value?.services.filter((s) => s.status === 'running').length ?? 0,
  )

  const activeApplications = computed(
    () => data.value?.applications.filter((a) => a.status === 'running').length ?? 0,
  )

  async function loadExtras() {
    const deployments = await fetchRecentDeployments()
    if (!data.value) return
    if (deployments === null) {
      extrasError.value = 'Could not load recent deployments.'
      return
    }
    extrasError.value = null
    data.value = {
      ...data.value,
      deployments,
    }
  }

  async function fetchDashboard(isRefresh = false, { withExtras = true } = {}) {
    if (!localStorage.getItem('access_token')) {
      loading.value = false
      refreshing.value = false
      return
    }
    if (typeof document !== 'undefined' && document.hidden && isRefresh) {
      return
    }
    error.value = null

    if (!isRefresh && !data.value) {
      const cached = readStaffCache()
      if (cached?.servers) {
        data.value = mapDashboardResponse(cached, null, null, [])
        loading.value = false
      } else {
        loading.value = true
      }
    }

    try {
      const dashboardRes = await monitoringApi.dashboard()
      writeStaffCache(dashboardRes.data)
      data.value = mapDashboardResponse(
        dashboardRes.data,
        data.value?.health ?? null,
        data.value?.readiness ?? null,
        data.value?.deployments ?? [],
      )
      loading.value = false

      void Promise.all([healthApi.liveness().catch(() => null), healthApi.readiness().catch(() => null)]).then(
        ([healthRes, readinessRes]) => {
          if (!data.value) return
          data.value = {
            ...data.value,
            health: healthRes?.data ?? data.value.health,
            readiness: readinessRes?.data ?? data.value.readiness,
          }
        },
      )

      if (withExtras) {
        void loadExtras()
      }
    } catch (e) {
      if (!data.value) {
        error.value = e instanceof Error ? e.message : 'Failed to load dashboard data.'
      }
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  function onVisibility() {
    if (!document.hidden && localStorage.getItem('access_token')) {
      fetchDashboard(true, { withExtras: false })
    }
  }

  onMounted(() => {
    if (!localStorage.getItem('access_token')) {
      loading.value = false
      return
    }
    fetchDashboard(false, { withExtras: false })
    timer = setInterval(() => {
      pollCount += 1
      // Refresh extras every 6th poll (~30s) to keep the 5s loop light.
      fetchDashboard(true, { withExtras: pollCount % 6 === 0 })
    }, REALTIME_POLL_MS)
    document.addEventListener('visibilitychange', onVisibility)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return {
    data,
    loading,
    refreshing,
    error,
    extrasError,
    runningServices,
    activeApplications,
    refresh: () => fetchDashboard(true, { withExtras: true }),
  }
}
