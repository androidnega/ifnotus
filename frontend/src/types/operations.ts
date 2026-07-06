export interface OperationResult {
  success: boolean
  message: string
  task_id?: string
  details: Record<string, unknown>
}

export interface OperationsOverview {
  timestamp: string
  nginx_available: boolean
  worker_queue_depth: number
  backup_count: number
  cron_job_count: number
  applications_total: number
  applications_enabled: number
}

export interface EnvVariable {
  key: string
  value: string
  secret: boolean
  source?: string
}

export interface EnvironmentResponse {
  timestamp: string
  variables: EnvVariable[]
  revealed: boolean
}

export interface FileEntry {
  name: string
  path: string
  is_dir: boolean
  size_bytes?: number
  modified?: string
  mode?: string
  owner?: string
  group?: string
}

export interface FileListResponse {
  timestamp: string
  path: string
  entries: FileEntry[]
  parent?: string
}

export interface StorageVolume {
  mount: string
  total_bytes: number
  used_bytes: number
  free_bytes: number
  percent: number
}

export interface BackupEntry {
  id: string
  name: string
  path: string
  size_bytes?: number
  created?: string
  application_id?: string
}

export interface CronJob {
  id: string
  schedule: string
  command: string
  source: string
  user?: string
  enabled: boolean
}

export interface DatabaseStatus {
  engine: string
  status: string
  message?: string
  size_bytes?: number
  connections?: number
}

export interface SslAppStatus {
  application_id: string
  application_name: string
  domain?: string
  ssl: Record<string, unknown>
}

export interface ApplicationDetail {
  id: string
  name: string
  type: string
  environment: string
  enabled: boolean
  status: string
  health: string
  health_score: number
  domain?: string
  root_path?: string
  version?: string
  description?: string
  tags: string[]
  paths: Record<string, unknown>
  runtime: Record<string, unknown>
  git?: Record<string, unknown>
  ssl?: Record<string, unknown>
  nginx?: Record<string, unknown>
  supervisor?: Record<string, unknown>
  systemd?: Record<string, unknown>
  modules: Record<string, boolean>
}

export interface ApplicationLogsResponse {
  timestamp: string
  application_id: string
  sources: string[]
  entries: Array<{ message?: string; level?: string; source?: string; line_number?: number }>
}

export interface DeploymentRecord {
  id: string
  version: string
  status: string
  environment: string
  timestamp: string
  triggered_by?: string
  message?: string
}
