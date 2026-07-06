export type AppReconciliationState =
  | 'registered'
  | 'discovered_unregistered'
  | 'registry_missing_root'
  | 'registry_invalid_binding'
  | 'registry_invalid_config'
  | 'orphaned_runtime'
  | 'orphaned_nginx_site'

export type DomainReconciliationState =
  | 'managed'
  | 'discovered'
  | 'drifted'
  | 'disabled_in_nginx'
  | 'proxy_target_detected'
  | 'missing_document_root'

export type SslReconciliationState =
  | 'managed'
  | 'discovered'
  | 'expiring'
  | 'expired'
  | 'missing'
  | 'mismatch'
  | 'unbound'

export interface DiscoveredApplication {
  id: string
  name: string
  probable_type: string
  root_path: string
  git_path?: string | null
  environment?: string | null
  server_names: string[]
  nginx_site_path?: string | null
  systemd_unit?: string | null
  process_match?: string | null
  signals: string[]
  registered: boolean
  registered_id?: string | null
  reconciliation_state: AppReconciliationState
  runtime_status?: string | null
  registry_errors?: string[]
}

export interface NginxDiscoveredDomain {
  server_name: string
  site_path: string
  enabled: boolean
  ssl_enabled: boolean
  document_root?: string | null
  proxy_pass?: string | null
  certificate_path?: string | null
  in_database: boolean
  database_id?: string | null
  linked_app_id?: string | null
  reconciliation_state: DomainReconciliationState
}

export interface VpsInventorySummary {
  timestamp: string
  registered_apps: number
  discovered_apps: number
  unregistered_discovered_apps: number
  managed_domains: number
  discovered_domains: number
  domains_with_drift: number
  certificates_healthy: number
  certificates_expiring: number
  certificates_missing: number
  runtime_issues: number
}

export interface VpsInventoryResponse {
  summary: VpsInventorySummary
  applications: {
    registered_total: number
    discovered_total: number
    unregistered_discovered: number
    issues_count: number
    registered: DiscoveredApplication[]
    discovered: DiscoveredApplication[]
  }
  domains: {
    managed_total: number
    discovered_total: number
    drift_count: number
    managed: NginxDiscoveredDomain[]
    discovered: NginxDiscoveredDomain[]
  }
  ssl: {
    managed_total: number
    discovered_total: number
    expiring_count: number
    expired_count: number
    missing_count: number
    certificates: Array<{
      domain: string
      reconciliation_state: SslReconciliationState
      in_database: boolean
      nginx_bound: boolean
      days_remaining?: number | null
    }>
  }
}

export type TerminalScope = 'ops' | 'hosting' | 'app'
