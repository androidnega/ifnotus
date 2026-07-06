import type { DiscoveredApplication, VpsInventorySummary } from '@/types/inventory'

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy'
export type ServiceStatus = 'running' | 'stopped' | 'degraded' | 'unknown'
export type AlertSeverity = 'critical' | 'warning' | 'info'
export type TrendDirection = 'up' | 'down' | 'neutral'

export interface HealthResponse {
  status: HealthStatus
  version: string
  environment: string
  timestamp: string
}

export interface ComponentHealth {
  name: string
  status: HealthStatus
  latency_ms?: number | null
  message?: string | null
}

export interface ReadinessResponse {
  status: HealthStatus
  version: string
  environment: string
  timestamp: string
  components: ComponentHealth[]
}

export interface SystemMetrics {
  timestamp: string
  uptime_seconds?: number | null
  cpu_percent?: number | null
  memory_percent?: number | null
  disk_percent?: number | null
}

export interface IntegrationStatus {
  configured: boolean
  [key: string]: unknown
}

export interface IntegrationsResponse {
  netdata: IntegrationStatus
  nginx: IntegrationStatus
  github: IntegrationStatus
  supervisor: IntegrationStatus
  systemd: IntegrationStatus
  postgresql?: IntegrationStatus
  redis?: IntegrationStatus
  mysql?: IntegrationStatus
}

export interface StatCardData {
  id: string
  label: string
  value: string | number
  unit?: string
  trend?: TrendDirection
  trend_value?: string
  trendValue?: string
  status?: HealthStatus
}

export interface ServerHealth {
  id: string
  name: string
  status: HealthStatus
  score: number
  cpu: number
  memory: number
  disk: number
}

export interface ServiceItem {
  id: string
  name: string
  status: ServiceStatus
  description?: string
  uptime?: string
}

export interface ApplicationItem {
  id: string
  name: string
  status: ServiceStatus
  version?: string
  environment?: string
  url?: string
}

export interface AlertItem {
  id: string
  title: string
  message: string
  severity: AlertSeverity
  timestamp: string
  source: string
  acknowledged?: boolean
}

export interface ActivityItem {
  id: string
  title: string
  description?: string
  timestamp: string
  type: 'deployment' | 'alert' | 'service' | 'system' | 'user'
  status?: HealthStatus | ServiceStatus
}

export interface DeploymentItem {
  id: string
  application: string
  environment: string
  version: string
  status: 'success' | 'failed' | 'in_progress' | 'pending'
  timestamp: string
  triggeredBy: string
}

export interface ResourceSeries {
  name: string
  data: number[]
  color: string
}

export interface ChartData {
  categories: string[]
  series: ResourceSeries[]
}

export interface DashboardApiResponse {
  timestamp: string
  health_score: number
  status: HealthStatus
  hostname: string
  environment: string
  version: string
  stats: StatCardData[]
  servers: ServerHealth[]
  services: ApiManagedService[]
  applications: ApplicationItem[]
  alerts: AlertItem[]
  activities: ActivityItem[]
  charts: {
    cpu: ChartData
    memory: ChartData
    network: ChartData
  }
  load_average: number[]
  network_throughput: { in: string; out: string }
  collectors: ApiCollectorHealth[]
  inventory?: import('@/types/inventory').VpsInventorySummary | null
}

export interface ApiCollectorHealth {
  name: string
  status: string
  latency_ms: number
  message?: string | null
  available: boolean
}

export interface ApiManagedService {
  id: string
  name: string
  status: ServiceStatus | string
  description?: string | null
  source: string
  pid?: number | null
  uptime_seconds?: number | null
  memory_bytes?: number | null
}

export interface ListeningPort {
  port: number
  address: string
  family: string
  protocol: string
  pid?: number | null
  process_name?: string | null
  status: string
}

export interface ServerOverview {
  timestamp: string
  hostname: string
  status: HealthStatus
  health_score: number
  uptime_seconds: number
  cpu_percent: number
  memory_percent: number
  disk_percent: number
  load_average: number[]
  network_bytes_recv_per_sec: number
  network_bytes_sent_per_sec: number
  process_count: number
  listening_ports: number
  missing_expected_ports: number[]
}

export interface PortsResponse {
  timestamp: string
  ports: ListeningPort[]
  total: number
  expected_ports: number[]
  missing_ports: number[]
  collectors: ApiCollectorHealth[]
}

export interface ServicesResponse {
  timestamp: string
  services: ApiManagedService[]
  collectors: ApiCollectorHealth[]
}

export interface AlertsResponse {
  timestamp: string
  alerts: AlertItem[]
  total: number
}

export interface ApplicationSummary {
  id: string
  name: string
  type?: string
  environment: string
  enabled: boolean
  status: string
  health: HealthStatus
  health_score: number
  domain?: string | null
  root_path?: string | null
  version?: string | null
}

export interface ApplicationListResponse {
  timestamp: string
  total: number
  applications: ApplicationSummary[]
  discovered?: DiscoveredApplication[]
  discovered_total?: number
  unregistered_discovered?: number
  issues_count?: number
}

export interface DeploymentRecord {
  id: string
  version: string
  status: string
  environment: string
  timestamp: string
  triggered_by?: string | null
  message?: string | null
}

export interface ApplicationDeploymentsResponse {
  timestamp: string
  application_id: string
  deployments: DeploymentRecord[]
  module_enabled?: boolean
}

export interface DashboardData {
  health: HealthResponse | null
  readiness: ReadinessResponse | null
  metrics: SystemMetrics | null
  integrations: IntegrationsResponse | null
  healthScore: number
  stats: StatCardData[]
  servers: ServerHealth[]
  services: ServiceItem[]
  applications: ApplicationItem[]
  alerts: AlertItem[]
  deployments: DeploymentItem[]
  activities: ActivityItem[]
  charts: {
    cpu: ChartData
    memory: ChartData
    network: ChartData
  }
  loadAverage: number[]
  networkThroughput: { in: string; out: string }
  collectors: ApiCollectorHealth[]
  inventory: VpsInventorySummary | null
}
