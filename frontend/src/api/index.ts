import apiClient, { transferClient } from './client'
import type { LoginRequest, User } from '@/types/auth'
import type {
  AccessAttemptEntry,
  BlockedActionEntry,
  FirewallRuleEntry,
  IpBlacklistEntry,
  SystemActionLogEntry,
} from '@/types/security'
import type {
  AlertsResponse,
  ApplicationDeploymentsResponse,
  ApplicationListResponse,
  DashboardApiResponse,
  HealthResponse,
  IntegrationsResponse,
  PortsResponse,
  ReadinessResponse,
  ServerOverview,
  ServicesResponse,
  SystemMetrics,
} from '@/types/dashboard'
import type {
  DnsCheckResponse,
  Domain,
  DomainListResponse,
  FileDetail,
  FileRootsResponse,
  FileUploadInitResponse,
  MailAlias,
  MailDomainResponse,
  Mailbox,
  SslCertificate,
  SslListResponse,
  SslReadinessResponse,
  TerminalAuditEntry,
  TerminalExecuteResponse,
} from '@/types/hosting'
import type {
  ApplicationDetail,
  ApplicationLogsResponse,
  BackupEntry,
  CronJob,
  DatabaseStatus,
  EnvironmentResponse,
  FileListResponse,
  OperationResult,
  OperationsOverview,
  SslAppStatus,
  StorageVolume,
} from '@/types/operations'

export const authApi = {
  login: (credentials: LoginRequest) =>
    apiClient.post<import('@/types/auth').LoginResponse>('/auth/login', credentials),

  verifyDevice: (body: import('@/types/auth').VerifyDeviceRequest) =>
    apiClient.post<import('@/types/auth').LoginResponse>('/auth/verify-device', body),

  probe: (body: { device_fingerprint?: string }) =>
    apiClient.post<{ message: string }>('/auth/probe', body),

  me: () => apiClient.get<User>('/auth/me'),

  logout: () => apiClient.post('/auth/logout'),

  switchPrivilege: (role: string) =>
    apiClient.post<import('@/types/auth').TokenResponse>('/auth/privilege-switch', { role }),

  restorePrivilege: () =>
    apiClient.post<import('@/types/auth').TokenResponse>('/auth/privilege-restore'),

  confirmPassword: (password: string) =>
    apiClient.post<{ message: string }>('/auth/confirm-password', { password }),

  requestPasswordReset: (email: string) =>
    apiClient.post<{ message: string }>('/auth/password-reset/request', { email }),

  confirmPasswordReset: (token: string, new_password: string) =>
    apiClient.post<{ message: string }>('/auth/password-reset/confirm', { token, new_password }),
}

export const securityApi = {
  blacklist: (activeOnly = true) =>
    apiClient.get<{ total: number; entries: IpBlacklistEntry[] }>('/security/blacklist', {
      params: { active_only: activeOnly },
    }),

  blockIp: (body: { ip_address: string; reason?: string; hours?: number | null }) =>
    apiClient.post<IpBlacklistEntry>('/security/blacklist', body),

  unlock: (id: string, note?: string) =>
    apiClient.post<{ message: string }>(`/security/blacklist/${id}/unlock`, { note }),

  attempts: (limit = 100) =>
    apiClient.get<{ total: number; attempts: AccessAttemptEntry[] }>('/security/attempts', {
      params: { limit },
    }),

  firewall: () =>
    apiClient.get<{ total: number; rules: FirewallRuleEntry[] }>('/security/firewall'),

  createFirewallRule: (body: { cidr: string; action: 'allow' | 'deny'; note?: string }) =>
    apiClient.post<FirewallRuleEntry>('/security/firewall', body),

  deleteFirewallRule: (id: string) =>
    apiClient.delete<{ message: string }>(`/security/firewall/${id}`),

  blockedActions: () =>
    apiClient.get<{
      total: number
      entries: BlockedActionEntry[]
      available: Array<{ key: string; label: string }>
    }>('/security/blocked-actions'),

  setBlockedAction: (body: {
    action_key: string
    enabled?: boolean
    reason?: string
    label?: string
  }) => apiClient.post<BlockedActionEntry>('/security/blocked-actions', body),

  unblockAction: (actionKey: string) =>
    apiClient.delete<{ message: string }>(`/security/blocked-actions/${encodeURIComponent(actionKey)}`),

  actionLogs: (limit = 200) =>
    apiClient.get<{ total: number; logs: SystemActionLogEntry[] }>('/security/actions', {
      params: { limit },
    }),

  clearLogs: (body: {
    confirm_password: string
    acknowledge_downloaded: boolean
    clear_attempts?: boolean
    clear_actions?: boolean
    clear_terminal?: boolean
  }) =>
    apiClient.post<{ message: string; cleared: Record<string, number> }>(
      '/security/logs/clear',
      body,
    ),
}

export const healthApi = {
  liveness: () => apiClient.get<HealthResponse>('/health'),

  readiness: () => apiClient.get<ReadinessResponse>('/health/ready'),
}

export const monitoringApi = {
  overview: () => apiClient.get<Record<string, unknown>>('/monitoring'),

  metrics: () => apiClient.get<SystemMetrics>('/monitoring/metrics'),

  integrations: () => apiClient.get<IntegrationsResponse>('/monitoring/integrations'),

  dashboard: () => apiClient.get<DashboardApiResponse>('/dashboard'),
}

export const serverApi = {
  overview: () => apiClient.get<ServerOverview>('/server/overview'),

  ports: () => apiClient.get<PortsResponse>('/server/ports'),

  services: (params?: { mode?: 'relevant' | 'all'; category?: string }) =>
    apiClient.get<ServicesResponse>('/services', { params }),

  clearCache: (reloadNginx = false) =>
    apiClient.post<OperationResult>('/server/cache/clear', null, {
      params: { reload_nginx: reloadNginx },
    }),

  refresh: (reloadNginx = true) =>
    apiClient.post<OperationResult>('/server/refresh', null, {
      params: { reload_nginx: reloadNginx },
    }),
}

export const alertsApi = {
  list: () => apiClient.get<AlertsResponse>('/alerts'),
}

export const applicationsApi = {
  list: () => apiClient.get<ApplicationListResponse>('/applications'),

  get: (appId: string) => apiClient.get<ApplicationDetail>(`/applications/${appId}`),

  logs: (appId: string, lines = 100) =>
    apiClient.get<ApplicationLogsResponse>(`/applications/${appId}/logs`, { params: { lines } }),

  clearLogs: (appId: string, confirmPassword: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/logs/clear`, {
      confirm_password: confirmPassword,
    }),

  environment: (appId: string) =>
    apiClient.get<{ timestamp: string; application_id: string; variables: Record<string, string> }>(
      `/applications/${appId}/environment`,
    ),

  revealEnvironment: (appId: string) =>
    apiClient.get<Record<string, string>>(`/applications/${appId}/environment/reveal`),

  deployments: (appId: string) =>
    apiClient.get<ApplicationDeploymentsResponse>(`/applications/${appId}/deployments`),

  gitPull: (appId: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/git/pull`),

  deploy: (
    appId: string,
    body: { version?: string; message?: string; pull?: boolean; restart?: boolean } = {},
  ) => apiClient.post<OperationResult>(`/applications/${appId}/deploy`, body),

  redeploy: (appId: string, deploymentId: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/deployments/${deploymentId}/redeploy`),

  restart: (appId: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/restart`),

  serviceAction: (appId: string, action: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/services/action`, { action }),

  setEnabled: (appId: string, enabled: boolean) =>
    apiClient.patch<OperationResult>(`/applications/${appId}`, { enabled }),

  refresh: (appId: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/refresh`),

  clearCache: (appId: string) =>
    apiClient.post<OperationResult>(`/applications/${appId}/cache/clear`),

  clearAllCaches: () =>
    apiClient.post<OperationResult>('/applications/cache/clear-all'),
}

export const operationsApi = {
  overview: () => apiClient.get<OperationsOverview>('/operations/overview'),

  environment: (reveal = false) =>
    apiClient.get<EnvironmentResponse>('/operations/environment', { params: { reveal } }),

  smtpTest: (toEmail: string) =>
    apiClient.post<OperationResult>('/operations/smtp/test', {
      to_email: toEmail,
      subject: 'IFNOTUS SMTP Test',
      body: 'Test message from IFNOTUS operations panel.',
    }),

  restartNginx: () => apiClient.post<OperationResult>('/operations/nginx/restart'),

  restartWorker: () => apiClient.post<OperationResult>('/operations/worker/restart'),

  refreshServer: () => apiClient.post<OperationResult>('/operations/server/refresh'),

  clearCentralCache: (reloadNginx = false) =>
    apiClient.post<OperationResult>('/operations/cache/clear', null, {
      params: { reload_nginx: reloadNginx },
    }),

  clearAllAppCaches: () => apiClient.post<OperationResult>('/operations/cache/clear-apps'),

  queueStatus: () =>
    apiClient.get<Array<{ queue: string; depth: number }>>('/operations/queue'),

  backups: () => apiClient.get<{ timestamp: string; backups: BackupEntry[] }>('/operations/backups'),

  createBackup: () => apiClient.post<OperationResult>('/operations/backups'),

  cron: () => apiClient.get<{ timestamp: string; jobs: CronJob[] }>('/operations/cron'),

  files: (path = '.', appId?: string) =>
    apiClient.get<FileListResponse>('/operations/files', { params: { path, app_id: appId } }),

  storage: () => apiClient.get<{ timestamp: string; volumes: StorageVolume[] }>('/operations/storage'),

  ssl: () => apiClient.get<SslAppStatus[]>('/operations/ssl'),

  database: () =>
    apiClient.get<{ timestamp: string; databases: DatabaseStatus[] }>('/operations/database'),

  databaseAction: (action: string) =>
    apiClient.post<OperationResult>(`/operations/database/${action}`),

  hostLogs: (lines = 100) =>
    apiClient.get<{ entries: Array<{ message: string; level?: string; source?: string }> }>(
      '/operations/logs/host',
      { params: { lines } },
    ),
}

export const domainsApi = {
  list: () => apiClient.get<DomainListResponse>('/domains'),

  get: (id: string) => apiClient.get<Domain>(`/domains/${id}`),

  create: (body: {
    name?: string
    subdomain_label?: string
    domain_type?: string
    parent_domain_id?: string
    application_id?: string
    document_root?: string
    proxy_port?: number
    enabled?: boolean
    force_https?: boolean
    redirect_url?: string
    provision?: boolean
    create_docroot?: boolean
    notes?: string
  }) => apiClient.post<Domain>('/domains', body),

  update: (
    id: string,
    body: Partial<{
      application_id: string | null
      document_root: string | null
      proxy_port: number | null
      enabled: boolean
      force_https: boolean
      redirect_url: string | null
      notes: string | null
      reprovision: boolean
    }>,
  ) => apiClient.patch<Domain>(`/domains/${id}`, body),

  delete: (id: string) => apiClient.delete<OperationResult>(`/domains/${id}`),

  dnsCheck: (id: string) => apiClient.post<DnsCheckResponse>(`/domains/${id}/dns-check`),

  provision: (id: string) => apiClient.post<OperationResult>(`/domains/${id}/provision`),

  importDiscovered: (body: { server_name: string; domain_type?: string; parent_domain_id?: string }) =>
    apiClient.post<Domain>('/domains/import', body),

  listRedirects: (id: string) =>
    apiClient.get<import('@/types/hosting').DomainRedirect[]>(`/domains/${id}/redirects`),

  createRedirect: (
    id: string,
    body: { source_path: string; target_url: string; status_code?: number; enabled?: boolean },
  ) => apiClient.post<import('@/types/hosting').DomainRedirect>(`/domains/${id}/redirects`, body),

  deleteRedirect: (id: string, redirectId: string) =>
    apiClient.delete<OperationResult>(`/domains/${id}/redirects/${redirectId}`),

  listDnsRecords: (id: string) =>
    apiClient.get<import('@/types/hosting').DomainDnsRecord[]>(`/domains/${id}/dns-records`),

  createDnsRecord: (
    id: string,
    body: { record_type: string; host?: string; value: string; ttl?: number; priority?: number },
  ) => apiClient.post<import('@/types/hosting').DomainDnsRecord>(`/domains/${id}/dns-records`, body),

  deleteDnsRecord: (id: string, recordId: string) =>
    apiClient.delete<OperationResult>(`/domains/${id}/dns-records/${recordId}`),
}

export const databasesApi = {
  list: () => apiClient.get<import('@/types/databases').DatabaseOverview>('/databases'),
  engines: () => apiClient.get<import('@/types/databases').EngineStatus[]>('/databases/engines'),
  create: (body: import('@/types/databases').DatabaseCreateBody) =>
    apiClient.post<import('@/types/databases').DatabaseCreated>('/databases', body),
  drop: (id: string, opts?: { confirmPassword: string; dropUser?: boolean; removeFiles?: boolean }) =>
    apiClient.post<OperationResult>(`/databases/${id}/drop`, {
      confirm_password: opts?.confirmPassword || '',
      drop_user: opts?.dropUser ?? true,
      remove_files: opts?.removeFiles ?? true,
    }),
  dropLive: (body: import('@/types/databases').DatabaseLiveDropBody) =>
    apiClient.post<OperationResult>('/databases/live/drop', body),
  adopt: (body: import('@/types/databases').DatabaseAdoptBody) =>
    apiClient.post<import('@/types/databases').DatabaseCreated>('/databases/adopt', body),
  backupManaged: (id: string) =>
    apiClient.post<import('@/types/databases').DatabaseBackup>(`/databases/${id}/backup`),
  backupLive: (body: { engine: string; name: string; path?: string }) =>
    apiClient.post<import('@/types/databases').DatabaseBackup>('/databases/live/backup', body),
  listBackups: () =>
    apiClient.get<{ backups: import('@/types/databases').DatabaseBackup[] }>('/databases/backups'),
  downloadBackupUrl: (id: string) => `/api/v1/databases/backups/${id}/download`,
  restore: (form: FormData) =>
    apiClient.post<OperationResult>('/databases/restore', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  revealPassword: (id: string) =>
    apiClient.post<{ id: string; password: string; connection_uri?: string | null }>(
      `/databases/${id}/password`,
    ),
  ensure: (engine: import('@/types/databases').DatabaseEngine) =>
    apiClient.post<OperationResult>(`/databases/engines/${engine}/ensure`),

  schema: (id: string) =>
    apiClient.get<import('@/types/databases').DbSchema>(`/databases/${id}/schema`),
  rows: (
    id: string,
    params: { table?: string; collection?: string; schema_name?: string; limit?: number; offset?: number },
  ) => apiClient.get<import('@/types/databases').DbQueryResult>(`/databases/${id}/rows`, { params }),
  query: (id: string, body: { sql?: string; script?: string; limit?: number }) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(`/databases/${id}/query`, body),
  updateRow: (
    id: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      primary_key?: Record<string, unknown>
      filter?: Record<string, unknown>
      values: Record<string, unknown>
    },
  ) => apiClient.patch<import('@/types/databases').DbQueryResult>(`/databases/${id}/rows`, body),
  insertRow: (
    id: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      values: Record<string, unknown>
    },
  ) => apiClient.post<import('@/types/databases').DbQueryResult>(`/databases/${id}/rows/insert`, body),
  deleteRow: (
    id: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      primary_key?: Record<string, unknown>
      filter?: Record<string, unknown>
    },
  ) => apiClient.post<import('@/types/databases').DbQueryResult>(`/databases/${id}/rows/delete`, body),

  liveSchema: (engine: string, name: string, path?: string) =>
    apiClient.get<import('@/types/databases').DbSchema>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/schema`,
      { params: path ? { path } : undefined },
    ),
  liveRows: (
    engine: string,
    name: string,
    params: {
      table?: string
      collection?: string
      schema_name?: string
      path?: string
      limit?: number
      offset?: number
    },
  ) =>
    apiClient.get<import('@/types/databases').DbQueryResult>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/rows`,
      { params },
    ),
  liveQuery: (
    engine: string,
    name: string,
    body: { sql?: string; script?: string; limit?: number },
    path?: string,
  ) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/query`,
      body,
      { params: path ? { path } : undefined },
    ),
  liveUpdateRow: (
    engine: string,
    name: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      primary_key?: Record<string, unknown>
      filter?: Record<string, unknown>
      values: Record<string, unknown>
    },
    path?: string,
  ) =>
    apiClient.patch<import('@/types/databases').DbQueryResult>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/rows`,
      body,
      { params: path ? { path } : undefined },
    ),
  liveInsertRow: (
    engine: string,
    name: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      values: Record<string, unknown>
    },
    path?: string,
  ) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/rows/insert`,
      body,
      { params: path ? { path } : undefined },
    ),
  liveDeleteRow: (
    engine: string,
    name: string,
    body: {
      table?: string
      collection?: string
      schema_name?: string
      primary_key?: Record<string, unknown>
      filter?: Record<string, unknown>
    },
    path?: string,
  ) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/databases/live/${engine}/${encodeURIComponent(name)}/rows/delete`,
      body,
      { params: path ? { path } : undefined },
    ),
}

export const sslApi = {
  list: () => apiClient.get<SslListResponse>('/ssl'),

  get: (domain: string) => apiClient.get<SslCertificate>(`/ssl/${encodeURIComponent(domain)}`),

  readiness: (domain: string) => apiClient.get<SslReadinessResponse>(`/ssl/readiness/${encodeURIComponent(domain)}`),

  issue: (body: { domain: string; email?: string; webroot?: string; dry_run?: boolean }) =>
    apiClient.post<OperationResult>('/ssl/issue', body),

  renew: (body: { domain: string; email?: string; webroot?: string; dry_run?: boolean }) =>
    apiClient.post<OperationResult>('/ssl/renew', body),

  reissue: (body: { domain: string; email?: string; webroot?: string; dry_run?: boolean }) =>
    apiClient.post<OperationResult>('/ssl/reissue', body),

  renewAll: (dryRun = false, email?: string) =>
    apiClient.post<OperationResult>('/ssl/renew-all', null, { params: { dry_run: dryRun, email } }),
}

export const mailApi = {
  getDomain: (domainId: string) => apiClient.get<MailDomainResponse>(`/mail/domains/${domainId}`),

  getSettings: () =>
    apiClient.get<{
      support_whatsapp: string
      support_url: string
      product_name: string
      auto_detect_domains: boolean
      updated_at?: string | null
    }>('/mail/settings'),

  updateSettings: (body: {
    support_whatsapp?: string
    product_name?: string
    auto_detect_domains?: boolean
  }) =>
    apiClient.put<{
      support_whatsapp: string
      support_url: string
      product_name: string
      auto_detect_domains: boolean
      updated_at?: string | null
    }>('/mail/settings', body),

  syncDomains: () => apiClient.post<OperationResult>('/mail/sync-domains'),

  ensureAuth: (domainId: string) =>
    apiClient.post<OperationResult>(`/mail/domains/${domainId}/auth`),

  syncAuth: () => apiClient.post<OperationResult>('/mail/auth/sync'),

  createMailbox: (domainId: string, body: { local_part: string; password: string; quota_mb?: number; display_name?: string }) =>
    apiClient.post<Mailbox>(`/mail/domains/${domainId}/mailboxes`, body),

  updateMailbox: (
    domainId: string,
    mailboxId: string,
    body: {
      password?: string
      quota_mb?: number
      suspended?: boolean
      display_name?: string | null
    },
  ) => apiClient.patch<Mailbox>(`/mail/domains/${domainId}/mailboxes/${mailboxId}`, body),

  deleteMailbox: (domainId: string, mailboxId: string) =>
    apiClient.delete<OperationResult>(`/mail/domains/${domainId}/mailboxes/${mailboxId}`),

  createAlias: (domainId: string, body: { source_local: string; destination: string }) =>
    apiClient.post<MailAlias>(`/mail/domains/${domainId}/aliases`, body),

  updateAlias: (
    domainId: string,
    aliasId: string,
    body: { destination?: string; enabled?: boolean },
  ) => apiClient.patch<MailAlias>(`/mail/domains/${domainId}/aliases/${aliasId}`, body),

  deleteAlias: (domainId: string, aliasId: string) =>
    apiClient.delete<OperationResult>(`/mail/domains/${domainId}/aliases/${aliasId}`),

  probe: (domainId: string, body?: { to?: string }) =>
    apiClient.post<OperationResult>(`/mail/domains/${domainId}/probe`, body ?? {}),
}

export const filesApi = {
  roots: () => apiClient.get<FileRootsResponse>('/files/roots'),

  list: (path = '.', scope?: { appId?: string; rootId?: string }) =>
    apiClient.get<FileListResponse>('/files', {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
    }),

  read: (path: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.get<FileDetail>('/files/content', {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
    }),

  write: (path: string, content: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.put<OperationResult>('/files/content', { path, content }, {
      params: { app_id: scope?.appId, root_id: scope?.rootId },
    }),

  mkdir: (path: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.post<OperationResult>('/files/mkdir', { path }, {
      params: { app_id: scope?.appId, root_id: scope?.rootId },
    }),

  move: (source: string, destination: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.post<OperationResult>('/files/move', { source, destination }, {
      params: { app_id: scope?.appId, root_id: scope?.rootId },
    }),

  delete: (path: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.delete<OperationResult>('/files', {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
    }),

  chmod: (path: string, mode: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.post<OperationResult>('/files/chmod', { path, mode }, {
      params: { app_id: scope?.appId, root_id: scope?.rootId },
    }),

  upload: (path: string, file: File, scope?: { appId?: string; rootId?: string }) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<OperationResult>('/files/upload', form, {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  unzip: (path: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.post<OperationResult>('/files/unzip', null, {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
    }),

  stat: (path: string, scope?: { appId?: string; rootId?: string }) =>
    apiClient.get<FileDetail>('/files/stat', {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
    }),

  uploadChunked: async (
    file: File,
    targetPath: string,
    scope?: { appId?: string; rootId?: string },
    onProgress?: (percent: number) => void,
  ) => {
    const { data: init } = await transferClient.post<FileUploadInitResponse>(
      '/files/upload/init',
      {
        filename: file.name,
        path: targetPath,
        size_bytes: file.size,
      },
      { params: { app_id: scope?.appId, root_id: scope?.rootId } },
    )
    const chunkSize = init.chunk_size
    const totalChunks = init.total_chunks
    let uploaded = 0

    for (let index = 0; index < totalChunks; index += 1) {
      const start = index * chunkSize
      const end = Math.min(start + chunkSize, file.size)
      const chunk = file.slice(start, end)
      const form = new FormData()
      form.append('file', chunk, file.name)
      await transferClient.post('/files/upload/chunk', form, {
        params: { upload_id: init.upload_id, chunk_index: index },
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      uploaded = end
      onProgress?.(Math.round((uploaded / file.size) * 100))
    }

    return transferClient.post<OperationResult>('/files/upload/complete', {
      upload_id: init.upload_id,
    })
  },

  downloadQueued: async (
    path: string,
    filename: string,
    scope?: { appId?: string; rootId?: string },
    onProgress?: (percent: number) => void,
  ) => {
    const response = await transferClient.get<Blob>('/files/download', {
      params: { path, app_id: scope?.appId, root_id: scope?.rootId },
      responseType: 'blob',
      onDownloadProgress: (ev) => {
        if (ev.total) onProgress?.(Math.round((ev.loaded / ev.total) * 100))
      },
    })
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
  },
}

export const inventoryApi = {
  get: () => apiClient.get<import('@/types/inventory').VpsInventoryResponse>('/inventory'),
}

export const terminalApi = {
  execute: (
    command: string,
    cwd?: string,
    options?: { scope?: import('@/types/inventory').TerminalScope; appId?: string; rootId?: string },
  ) =>
    apiClient.post<TerminalExecuteResponse>('/terminal/execute', {
      command,
      cwd,
      scope: options?.scope ?? 'ops',
      app_id: options?.appId,
      root_id: options?.rootId,
    }),

  audit: (limit = 50) => apiClient.get<TerminalAuditEntry[]>('/terminal/audit', { params: { limit } }),

  clearAudit: () => apiClient.delete<OperationResult>('/terminal/audit'),
}

export const aiApi = {
  status: () => apiClient.get<import('@/types/ai').AiSettings>('/ai/status'),
  getSettings: () => apiClient.get<import('@/types/ai').AiSettings>('/ai/settings'),
  updateSettings: (body: { api_key?: string | null; model?: string | null; clear?: boolean }) =>
    apiClient.put<import('@/types/ai').AiSettings>('/ai/settings', body),
  chat: (body: {
    message: string
    history?: import('@/types/ai').AiChatMessage[]
    surface: 'files' | 'terminal' | 'editor' | 'dashboard' | 'studio'
    path?: string
    appId?: string
    rootId?: string
    cwd?: string
    fileContent?: string
    originalContent?: string
  }) =>
    apiClient.post<import('@/types/ai').AiChatResponse>('/ai/chat', {
      message: body.message,
      history: body.history ?? [],
      surface: body.surface,
      path: body.path,
      app_id: body.appId,
      root_id: body.rootId,
      cwd: body.cwd,
      file_content: body.fileContent,
      original_content: body.originalContent,
    }),
  applyAction: (token: string) =>
    apiClient.post<OperationResult>('/ai/actions/apply', { token }),
  undoAction: () => apiClient.post<OperationResult>('/ai/actions/undo'),
  listSessions: (surface?: string, path?: string) =>
    apiClient.get<{ sessions: import('@/types/ai').AiSessionSummary[] }>('/ai/sessions', {
      params: {
        ...(surface ? { surface } : {}),
        ...(path != null ? { path } : {}),
      },
    }),
  createSession: (body: {
    surface: string
    title?: string
    path?: string
    appId?: string
    rootId?: string
  }) =>
    apiClient.post<import('@/types/ai').AiSessionDetail>('/ai/sessions', {
      surface: body.surface,
      title: body.title,
      path: body.path,
      app_id: body.appId,
      root_id: body.rootId,
    }),
  getSession: (id: string) =>
    apiClient.get<import('@/types/ai').AiSessionDetail>(`/ai/sessions/${id}`),
  deleteSession: (id: string) => apiClient.delete<OperationResult>(`/ai/sessions/${id}`),
  clearSessions: (surface?: string) =>
    apiClient.delete<OperationResult>('/ai/sessions', {
      params: surface ? { surface } : undefined,
    }),
}

export const catalogApi = {
  plans: () =>
    apiClient.get<{ items: import('@/types/platform').HostingPlan[]; brand: string; currency: string }>(
      '/catalog/plans',
    ),
  meta: () =>
    apiClient.get<{
      brand: string
      panel_name: string
      currency: string
      domain_prices: Array<{ extension: string; price_yearly: number; currency: string }>
      theme?: string
      themes?: Array<{
        id: string
        name: string
        description: string
        home_scroll?: boolean
        colors?: Record<string, string>
      }>
      colors?: Record<string, string>
      plan_colors?: Array<{ id: string; label: string; max_price: string | number; accent: string }>
      registrar_enabled?: boolean
      nameservers?: string[]
      student_zone?: string
      legacy_student_zone?: string
      support_hours?: string
      support_whatsapp?: string
      support_email?: string
    }>('/catalog/meta'),
  status: () =>
    apiClient.get<{
      ok: boolean
      message: string
      nameservers: string[]
      support_hours: string
    }>('/catalog/status'),
}

export type StackInstallProgress = {
  status: string
  stack?: string
  step?: string
  label?: string
  percent?: number
  message?: string | null
  error?: string | null
  job_id?: string | null
  updated_at?: string
  steps?: Array<{ id: string; label: string; state: 'pending' | 'active' | 'done' | 'failed' | string }>
}

export const customersApi = {
  register: (body: {
    email: string
    password: string
    full_name: string
    phone?: string
    company?: string
  }) =>
    apiClient.post<{
      customer: import('@/types/platform').CustomerProfile
      verification_token: string
      message: string
    }>('/customers/register', body),

  verifyEmail: (body: { token: string; code: string }) =>
    apiClient.post<import('@/types/platform').CustomerProfile>('/customers/verify-email', body),

  requestPhoneOtp: (body: { phone: string }) =>
    apiClient.post<{
      challenge_id: string
      phone: string
      message: string
      sms_sent: boolean
      debug_code?: string | null
    }>('/customers/phone/request-otp', body),

  verifyPhoneOtp: (body: { phone: string; challenge_id: string; code: string }) =>
    apiClient.post<import('@/types/auth').LoginResponse>('/customers/phone/verify-otp', body),

  completeProfile: (body: {
    full_name: string
    email: string
    company?: string | null
    password?: string
  }) =>
    apiClient.post<import('@/types/platform').CustomerProfile>('/customers/me/complete-profile', body),

  login: (credentials: LoginRequest) =>
    apiClient.post<import('@/types/auth').LoginResponse>('/customers/login', credentials),

  me: () => apiClient.get<import('@/types/platform').CustomerProfile>('/customers/me'),

  updateMe: (body: { full_name?: string; phone?: string; company?: string | null }) =>
    apiClient.patch<import('@/types/platform').CustomerProfile>('/customers/me', body),

  changePassword: (body: { current_password: string; new_password: string }) =>
    apiClient.post('/customers/me/password', body),

  totpSetup: () =>
    apiClient.post<{ secret: string; otpauth_url: string; enabled: boolean }>('/customers/me/totp/setup'),

  totpConfirm: (code: string) => apiClient.post('/customers/me/totp/confirm', { code }),

  totpDisable: (code: string) => apiClient.post('/customers/me/totp/disable', { code }),

  dashboard: () =>
    apiClient.get<import('@/types/platform').CustomerDashboard>('/customers/dashboard'),

  createOrder: (body: {
    plan_id: string
    domain_name?: string
    domain_extension?: string
    include_domain?: boolean
    domain_kind?: 'register' | 'own' | 'student'
    student_surname?: string
  }) =>
    apiClient.post<{
      order: {
        id: string
        total_price: number
        currency: string
        paystack_reference?: string
        invoice_number?: string
        payment_status?: string
        payment_method?: string
      }
      authorization_url?: string
      reference: string
      demo: boolean
      payment_method?: string
      invoice_number?: string
      momo?: { network: string; number: string; account_name: string }
    }>('/customers/orders', body),

  getInvoice: (orderId: string) =>
    apiClient.get<{
      order: import('@/types/platform').CustomerOrder
      plan_name?: string | null
      momo: { network: string; number: string; account_name: string; merchant?: boolean }
      payment_methods: { id: string; title: string; description?: string }[]
      support_hours?: string | null
      support_whatsapp?: string | null
      support_email?: string | null
    }>('/customers/orders/' + orderId),

  submitMomo: (orderId: string, transactionId: string) =>
    apiClient.post('/customers/orders/' + orderId + '/momo', { transaction_id: transactionId }),

  verifyPayment: (reference: string) =>
    apiClient.post('/customers/orders/verify-payment', { reference }),

  checkDomain: (name: string, extension: string) =>
    apiClient.post<{
      domain: string
      available: boolean
      price_yearly: number
      message: string
      provider?: string
    }>('/customers/domains/check', { name, extension }),

  previewStudentHostname: (surname: string) =>
    apiClient.post<{
      surname: string
      hostname: string
      available: boolean
      message: string
    }>('/customers/domains/student-preview', { surname }),

  renewSubscription: (subscriptionId: string) =>
    apiClient.post<{
      reference: string
      authorization_url?: string
      demo: boolean
      amount: number
      applied?: boolean
      invoice_number?: string
      order_id?: string
      message?: string
      subscription?: import('@/types/platform').CustomerSubscription
    }>(`/customers/subscriptions/${subscriptionId}/renew`),

  changePlan: (subscriptionId: string, planId: string) =>
    apiClient.post<{
      reference: string
      authorization_url?: string
      demo: boolean
      amount: number
      applied?: boolean
      invoice_number?: string
      order_id?: string
      message?: string
      subscription?: import('@/types/platform').CustomerSubscription
    }>(`/customers/subscriptions/${subscriptionId}/change-plan`, { plan_id: planId }),

  setAutoRenew: (subscriptionId: string, enabled: boolean) =>
    apiClient.post<import('@/types/platform').CustomerSubscription>(
      `/customers/subscriptions/${subscriptionId}/auto-renew`,
      { enabled },
    ),

  topUpCredits: (credits: number) =>
    apiClient.post<{
      reference: string
      authorization_url?: string
      demo: boolean
      credits: number
      amount: number
      invoice_number?: string
      order_id?: string
    }>('/customers/credits/topup', { credits }),

  environments: () =>
    apiClient.get<import('@/types/platform').CustomerEnvironment[]>('/customers/environments'),

  listEnvFiles: (environmentId: string, path = '.') =>
    apiClient.get<{ path: string; parent: string | null; entries: Array<{
      name: string
      path: string
      is_dir: boolean
      size_bytes?: number | null
    }> }>(`/customers/environments/${environmentId}/files`, { params: { path } }),

  readEnvFile: (environmentId: string, path: string) =>
    apiClient.get<{ name: string; path: string; content?: string | null }>(
      `/customers/environments/${environmentId}/files/content`,
      { params: { path } },
    ),

  writeEnvFile: (environmentId: string, path: string, content: string) =>
    apiClient.put(`/customers/environments/${environmentId}/files/content`, { path, content }),

  mkdirEnv: (environmentId: string, path: string) =>
    apiClient.post(`/customers/environments/${environmentId}/files/mkdir`, { path }),

  deleteEnvFile: (environmentId: string, path: string) =>
    apiClient.delete(`/customers/environments/${environmentId}/files`, { params: { path } }),

  uploadEnvFile: (environmentId: string, path: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ success: boolean; message: string }>(
      `/customers/environments/${environmentId}/files/upload`,
      form,
      {
        params: { path },
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 300_000,
      },
    )
  },

  uploadEnvChunked: async (
    environmentId: string,
    file: File,
    targetPath: string,
    onProgress?: (percent: number) => void,
  ) => {
    const { data: init } = await transferClient.post<FileUploadInitResponse>(
      `/customers/environments/${environmentId}/files/upload/init`,
      {
        filename: file.name,
        path: targetPath,
        size_bytes: file.size,
      },
    )
    const chunkSize = init.chunk_size
    const totalChunks = init.total_chunks
    let uploaded = 0
    for (let index = 0; index < totalChunks; index += 1) {
      const start = index * chunkSize
      const end = Math.min(start + chunkSize, file.size)
      const chunk = file.slice(start, end)
      const form = new FormData()
      form.append('file', chunk, file.name)
      await transferClient.post(`/customers/environments/${environmentId}/files/upload/chunk`, form, {
        params: { upload_id: init.upload_id, chunk_index: index },
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      uploaded = end
      onProgress?.(Math.round((uploaded / Math.max(file.size, 1)) * 100))
    }
    return transferClient.post<{ success: boolean; message: string }>(
      `/customers/environments/${environmentId}/files/upload/complete`,
      { upload_id: init.upload_id },
    )
  },

  getEnvDatabase: (environmentId: string, reveal = false) =>
    apiClient.get<{
      environment_id: string
      engine?: string | null
      name?: string | null
      username?: string | null
      host?: string | null
      port?: number | null
      password_set: boolean
      password?: string | null
      connection_uri?: string | null
    }>(`/customers/environments/${environmentId}/database`, { params: { reveal } }),

  getEnvDatabaseSchema: (environmentId: string) =>
    apiClient.get<import('@/types/databases').DbSchema>(
      `/customers/environments/${environmentId}/database/schema`,
    ),

  getEnvDatabaseRows: (
    environmentId: string,
    params: { table?: string; limit?: number; offset?: number; schema_name?: string },
  ) =>
    apiClient.get<import('@/types/databases').DbQueryResult>(
      `/customers/environments/${environmentId}/database/rows`,
      { params },
    ),

  queryEnvDatabase: (environmentId: string, sql: string, limit = 100) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/customers/environments/${environmentId}/database/query`,
      { sql, limit },
    ),

  listEnvAiSessions: (environmentId: string, surface = 'portal', path?: string | null) =>
    apiClient.get<{ sessions: import('@/types/ai').AiSessionSummary[] }>(
      `/customers/environments/${environmentId}/ai/sessions`,
      { params: { surface, ...(path != null ? { path } : {}) } },
    ),

  createEnvAiSession: (
    environmentId: string,
    body: { surface?: string; title?: string; path?: string | null },
  ) =>
    apiClient.post<import('@/types/ai').AiSessionDetail>(
      `/customers/environments/${environmentId}/ai/sessions`,
      {
        surface: body.surface || 'portal',
        title: body.title,
        path: body.path,
      },
    ),

  getEnvAiSession: (environmentId: string, sessionId: string) =>
    apiClient.get<import('@/types/ai').AiSessionDetail>(
      `/customers/environments/${environmentId}/ai/sessions/${sessionId}`,
    ),

  deleteEnvAiSession: (environmentId: string, sessionId: string) =>
    apiClient.delete<OperationResult>(
      `/customers/environments/${environmentId}/ai/sessions/${sessionId}`,
    ),

  clearEnvAiSessions: (environmentId: string, surface = 'portal') =>
    apiClient.delete<OperationResult>(`/customers/environments/${environmentId}/ai/sessions`, {
      params: { surface },
    }),

  insertEnvDatabaseRow: (
    environmentId: string,
    body: {
      table: string
      schema_name?: string
      values: Record<string, unknown>
    },
  ) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/customers/environments/${environmentId}/database/rows/insert`,
      body,
    ),

  updateEnvDatabaseRow: (
    environmentId: string,
    body: {
      table: string
      schema_name?: string
      primary_key: Record<string, unknown>
      values: Record<string, unknown>
    },
  ) =>
    apiClient.patch<import('@/types/databases').DbQueryResult>(
      `/customers/environments/${environmentId}/database/rows`,
      body,
    ),

  deleteEnvDatabaseRow: (
    environmentId: string,
    body: {
      table: string
      schema_name?: string
      primary_key: Record<string, unknown>
    },
  ) =>
    apiClient.post<import('@/types/databases').DbQueryResult>(
      `/customers/environments/${environmentId}/database/rows/delete`,
      body,
    ),

  getEnvFtp: (environmentId: string, reveal = false) =>
    apiClient.get<{
      environment_id: string
      enabled: boolean
      username?: string | null
      host: string
      wordpress_host?: string
      port: number
      home?: string | null
      password_set: boolean
      password?: string | null
      connection_type?: string
      hint?: string
      message?: string | null
    }>(`/customers/environments/${environmentId}/ftp`, { params: { reveal } }),

  ensureEnvFtp: (environmentId: string, resetPassword = false) =>
    apiClient.post<{
      environment_id: string
      enabled: boolean
      username?: string | null
      host: string
      wordpress_host?: string
      port: number
      home?: string | null
      password_set: boolean
      password?: string | null
      connection_type?: string
      hint?: string
      message?: string | null
    }>(`/customers/environments/${environmentId}/ftp/ensure`, {}, {
      params: { reset_password: resetPassword },
    }),

  getEnvMail: (environmentId: string) =>
    apiClient.get<{
      domain: { id: string; name: string }
      mailboxes: Array<{ id: string; email: string; local_part: string }>
      webmail_url?: string
      clients?: {
        imap_host?: string
        imap_port?: number
        imap_security?: string
        smtp_host?: string
        smtp_port?: number
        smtp_security?: string
        pop_host?: string
        pop_port?: number
        webmail_url?: string
        username_hint?: string
      }
    }>(`/customers/environments/${environmentId}/mail`),

  createEnvMailbox: (environmentId: string, body: { local_part: string; password: string }) =>
    apiClient.post(`/customers/environments/${environmentId}/mail/mailboxes`, body),

  listEnvRedirects: (environmentId: string) =>
    apiClient.get<
      Array<{ id: string; source_path: string; target_url: string; status_code: number; enabled: boolean }>
    >(`/customers/environments/${environmentId}/redirects`),

  createEnvRedirect: (
    environmentId: string,
    body: { source_path: string; target_url: string; status_code?: number },
  ) => apiClient.post(`/customers/environments/${environmentId}/redirects`, body),

  deleteEnvRedirect: (environmentId: string, redirectId: string) =>
    apiClient.delete(`/customers/environments/${environmentId}/redirects/${redirectId}`),

  getEnvZone: (environmentId: string) =>
    apiClient.get<{
      domain?: string | null
      included_hostname: boolean
      editable: boolean
      nameservers: string[]
      records: Array<{
        id: string
        record_type: string
        host: string
        value: string
        ttl: number
        priority?: number | null
      }>
      message: string
    }>(`/customers/environments/${environmentId}/zone`),

  createEnvZoneRecord: (
    environmentId: string,
    body: { record_type: string; host: string; value: string; ttl?: number; priority?: number | null },
  ) => apiClient.post(`/customers/environments/${environmentId}/zone`, body),

  getEnvGit: (environmentId: string) =>
    apiClient.get<{
      configured: boolean
      path?: string
      branch?: string | null
      commit?: string | null
      remote?: string | null
      dirty?: boolean
      message?: string
    }>(`/customers/environments/${environmentId}/git`),

  cloneEnvGit: (environmentId: string, body: { repo_url: string; branch?: string }) =>
    apiClient.post(`/customers/environments/${environmentId}/git/clone`, body),

  pullEnvGit: (environmentId: string) =>
    apiClient.post(`/customers/environments/${environmentId}/git/pull`, {}),

  getEnvSsh: (environmentId: string, reveal = false) =>
    apiClient.get<{
      environment_id: string
      ssh_allowed: boolean
      enabled: boolean
      username?: string | null
      host: string
      shared_ip?: string | null
      port: number
      password_set: boolean
      password?: string | null
      command?: string | null
      min_price_ghs: number
      hint?: string
      message?: string | null
    }>(`/customers/environments/${environmentId}/ssh`, { params: { reveal } }),

  ensureEnvSsh: (environmentId: string) =>
    apiClient.post<{
      environment_id: string
      ssh_allowed: boolean
      enabled: boolean
      username?: string | null
      host: string
      shared_ip?: string | null
      port: number
      password_set: boolean
      password?: string | null
      command?: string | null
      min_price_ghs: number
      hint?: string
      message?: string | null
    }>(`/customers/environments/${environmentId}/ssh/ensure`),

  repairEnvFilesystem: (environmentId: string) =>
    apiClient.post<{ message: string }>(`/customers/environments/${environmentId}/filesystem/repair`),

  getEnvUsage: (environmentId: string) =>
    apiClient.get<{
      environment_id: string
      domain?: string | null
      cpu_limit: number
      ram_limit_gb: number
      storage_limit_gb: number
      storage_used_bytes: number
      storage_used_gb: number
      storage_pct: number
      file_count: number
      soft_warning?: boolean
      hard_exceeded?: boolean
      storage_status?: string
      message?: string | null
      note: string
    }>(`/customers/environments/${environmentId}/usage`),

  checkEnvHealth: (environmentId: string) =>
    apiClient.post<{
      environment_id: string
      domain?: string | null
      status: string
      health_status: string
      summary: string
      checks: Record<string, unknown>
      checked_at?: string | null
      message?: string | null
    }>(`/customers/environments/${environmentId}/health/check`),

  listEnvStacks: (environmentId: string) =>
    apiClient.get<{
      environment_id: string
      stacks: Array<{ id: string; name: string; description: string }>
      current?: Record<string, unknown> | null
      progress?: StackInstallProgress | null
      active_job_id?: string | null
    }>(`/customers/environments/${environmentId}/stacks`),

  installEnvStack: (environmentId: string, body: { stack: string; replace?: boolean }) =>
    apiClient.post<{
      environment_id: string
      stack: string
      queued: boolean
      job_id?: string | null
      message: string
      result?: Record<string, unknown>
      current?: Record<string, unknown> | null
      progress?: StackInstallProgress | null
    }>(`/customers/environments/${environmentId}/stacks/install`, body),

  clearEnvStack: (environmentId: string, body?: { drop_database?: boolean }) =>
    apiClient.post<{
      environment_id: string
      message: string
      result?: Record<string, unknown>
      current?: Record<string, unknown> | null
    }>(`/customers/environments/${environmentId}/stacks/clear`, body || {}),

  getEnvStackJob: (environmentId: string, jobId: string) =>
    apiClient.get<{
      environment_id: string
      job_id: string
      status: string
      stack?: string | null
      message?: string | null
      error?: string | null
      progress?: StackInstallProgress | null
      current?: Record<string, unknown> | null
      result?: Record<string, unknown> | null
    }>(`/customers/environments/${environmentId}/stacks/jobs/${jobId}`),

  listEnvCron: (environmentId: string) =>
    apiClient.get<{
      environment_id: string
      jobs: Array<{
        id: string
        schedule: string
        command: string
        enabled: boolean
        created_at?: string | null
        last_run_at?: string | null
        last_status?: string | null
        last_exit_code?: number | null
        last_output?: string | null
      }>
      note?: string
    }>(`/customers/environments/${environmentId}/cron`),

  createEnvCron: (
    environmentId: string,
    body: { schedule: string; command: string; enabled?: boolean },
  ) =>
    apiClient.post<{
      id: string
      schedule: string
      command: string
      enabled: boolean
      last_run_at?: string | null
      last_status?: string | null
      last_output?: string | null
    }>(`/customers/environments/${environmentId}/cron`, body),

  updateEnvCron: (
    environmentId: string,
    jobId: string,
    body: { schedule?: string; command?: string; enabled?: boolean },
  ) =>
    apiClient.patch<{
      id: string
      schedule: string
      command: string
      enabled: boolean
      last_status?: string | null
    }>(`/customers/environments/${environmentId}/cron/${jobId}`, body),

  deleteEnvCron: (environmentId: string, jobId: string) =>
    apiClient.delete<{ message: string }>(`/customers/environments/${environmentId}/cron/${jobId}`),

  runEnvCron: (environmentId: string, jobId: string) =>
    apiClient.post<{
      id: string
      schedule: string
      command: string
      enabled: boolean
      last_run_at?: string | null
      last_status?: string | null
      last_exit_code?: number | null
      last_output?: string | null
    }>(`/customers/environments/${environmentId}/cron/${jobId}/run`),

  getEnvDns: (environmentId: string) =>
    apiClient.get<{
      environment_id: string
      domain?: string | null
      addon_domain?: string | null
      custom_domain?: string | null
      nameservers?: string[]
      custom_domains?: string[]
      available_domains?: string[]
      custom_domains_used?: number
      custom_domains_limit?: number
      can_assign?: boolean
      recommended_ip: string
      records?: Array<{ record_type: string; host: string; value: string; ttl: number }>
      namecheap_pushed?: boolean
      message: string
    }>(`/customers/environments/${environmentId}/dns`),

  ensureEnvDnsA: (environmentId: string) =>
    apiClient.post<{
      environment_id: string
      domain?: string | null
      addon_domain?: string | null
      custom_domain?: string | null
      nameservers?: string[]
      custom_domains?: string[]
      available_domains?: string[]
      custom_domains_used?: number
      custom_domains_limit?: number
      can_assign?: boolean
      recommended_ip: string
      namecheap_pushed?: boolean
      message: string
    }>(`/customers/environments/${environmentId}/dns/ensure-a`),

  attachEnvCustomDomain: (environmentId: string, domainName: string) =>
    apiClient.post<{
      environment_id: string
      domain?: string | null
      addon_domain?: string | null
      custom_domain?: string | null
      nameservers?: string[]
      custom_domains?: string[]
      available_domains?: string[]
      custom_domains_used?: number
      custom_domains_limit?: number
      can_assign?: boolean
      recommended_ip: string
      namecheap_pushed?: boolean
      message: string
    }>(`/customers/environments/${environmentId}/domains/custom`, { domain_name: domainName }),

  unassignEnvCustomDomain: (environmentId: string, domainName: string) =>
    apiClient.post<{
      environment_id: string
      domain?: string | null
      addon_domain?: string | null
      custom_domain?: string | null
      nameservers?: string[]
      custom_domains?: string[]
      available_domains?: string[]
      custom_domains_used?: number
      custom_domains_limit?: number
      can_assign?: boolean
      recommended_ip: string
      namecheap_pushed?: boolean
      message: string
    }>(`/customers/environments/${environmentId}/domains/unassign`, { domain_name: domainName }),

  issueEnvSsl: (environmentId: string) =>
    apiClient.post<{
      success: boolean
      queued?: boolean
      job_id?: string | null
      message: string
      domain?: string | null
      ssl_expiry?: string | null
    }>(`/customers/environments/${environmentId}/ssl/issue`),

  envAiStatus: (environmentId: string) =>
    apiClient.get<{
      configured: boolean
      model: string
      base_url: string
      api_key_masked?: string | null
      credits_remaining: number
      tokens_remaining?: number
      tokens_per_credit?: number
      total_allocated?: number
      lifetime_used?: number
      environment_id: string
      scope: string
    }>(`/customers/environments/${environmentId}/ai/status`),

  listEnvBackups: (environmentId: string) =>
    apiClient.get<
      Array<{
        id: string
        environment_id: string
        filename: string
        file_size?: number | null
        checksum?: string | null
        backup_type: string
        status: string
        verified_at?: string | null
        created_at?: string | null
      }>
    >(`/customers/environments/${environmentId}/backups`),

  createEnvBackup: (environmentId: string) =>
    apiClient.post<{
      id: string
      environment_id: string
      filename: string
      status: string
      backup_type: string
      file_size?: number | null
      created_at?: string | null
    }>(`/customers/environments/${environmentId}/backups`),

  restoreEnvBackup: (environmentId: string, backupId: string) =>
    apiClient.post<{
      job_id: string
      backup_id: string
      environment_id: string
      status: string
      message: string
    }>(`/customers/environments/${environmentId}/backups/${backupId}/restore`),

  listEnvLogs: (environmentId: string, lines = 200) =>
    apiClient.get<{
      environment_id: string
      sources: string[]
      entries: Array<{ source: string; message: string }>
      message?: string | null
    }>(`/customers/environments/${environmentId}/logs`, { params: { lines } }),

  listTickets: () => apiClient.get<import('@/types/support').SupportTicket[]>('/customers/tickets'),

  createTicket: (body: {
    subject: string
    body: string
    priority?: string
    environment_id?: string
  }) => apiClient.post<import('@/types/support').SupportTicket>('/customers/tickets', body),

  getTicket: (ticketId: string) =>
    apiClient.get<import('@/types/support').SupportTicket>(`/customers/tickets/${ticketId}`),

  replyTicket: (ticketId: string, body: string) =>
    apiClient.post<import('@/types/support').SupportTicketMessage>(
      `/customers/tickets/${ticketId}/messages`,
      { body },
    ),

  notifications: () => apiClient.get('/customers/notifications'),
}

export const supportApi = {
  listTickets: (params?: { status?: string; priority?: string }) =>
    apiClient.get<import('@/types/support').SupportTicket[]>('/support/tickets', { params }),

  getTicket: (ticketId: string) =>
    apiClient.get<import('@/types/support').SupportTicket>(`/support/tickets/${ticketId}`),

  replyTicket: (ticketId: string, body: string) =>
    apiClient.post<import('@/types/support').SupportTicketMessage>(
      `/support/tickets/${ticketId}/messages`,
      { body },
    ),

  closeTicket: (ticketId: string) =>
    apiClient.post<import('@/types/support').SupportTicket>(`/support/tickets/${ticketId}/close`),

  reopenTicket: (ticketId: string) =>
    apiClient.post<import('@/types/support').SupportTicket>(`/support/tickets/${ticketId}/reopen`),

  setTicketPriority: (ticketId: string, priority: string) =>
    apiClient.patch<import('@/types/support').SupportTicket>(
      `/support/tickets/${ticketId}/priority`,
      null,
      { params: { priority } },
    ),
}

export const platformAdminApi = {
  listCustomers: (params?: { q?: string; limit?: number }) =>
    apiClient.get<import('@/types/staffPlatform').StaffCustomerListItem[]>('/platform/customers', {
      params,
    }),

  getCustomer: (customerId: string) =>
    apiClient.get<import('@/types/staffPlatform').StaffCustomerDetail>(
      `/platform/customers/${customerId}`,
    ),

  grantCustomerCredits: (customerId: string, body: { credits: number; note?: string }) =>
    apiClient.post<{
      customer_id: string
      credits_granted: number
      credits_remaining: number
      total_allocated: number
      tokens_remaining: number
      message: string
    }>(`/platform/customers/${customerId}/credits/grant`, body),

  listOrders: (params?: { payment_status?: string; limit?: number }) =>
    apiClient.get<import('@/types/staffPlatform').StaffOrderItem[]>('/platform/orders', { params }),

  confirmOrderPayment: (orderId: string, body?: { amount_received?: number; notes?: string }) =>
    apiClient.post(`/platform/orders/${orderId}/confirm-payment`, body || {}),

  retryOrderProvision: (orderId: string) =>
    apiClient.post(`/platform/orders/${orderId}/retry-provision`, {}),

  rejectOrderPayment: (orderId: string, body?: { notes?: string }) =>
    apiClient.post(`/platform/orders/${orderId}/reject-payment`, body || {}),

  provisionCustomerHosting: (
    customerId: string,
    body: { plan_id: string; domain_name?: string; domain_extension?: string },
  ) => apiClient.post(`/platform/customers/${customerId}/provision`, body),

  createStaffUser: (body: { email: string; password: string; full_name: string; role: string }) =>
    apiClient.post('/platform/staff-users', body),

  listStaffUsers: () =>
    apiClient.get<
      Array<{
        id: string
        email: string
        username: string
        full_name?: string | null
        roles: string[]
        is_active: boolean
        is_superuser: boolean
        created_at?: string | null
        last_login_at?: string | null
        last_login_ip?: string | null
      }>
    >('/platform/staff-users'),

  updateStaffUser: (
    userId: string,
    body: { is_active?: boolean; role?: string; full_name?: string; password?: string },
  ) => apiClient.patch(`/platform/staff-users/${userId}`, body),

  listPlans: (includeInactive = true) =>
    apiClient.get<import('@/types/platform').HostingPlan[]>('/platform/plans', {
      params: { include_inactive: includeInactive },
    }),

  createPlan: (body: import('@/types/staffPlatform').StaffPlanInput) =>
    apiClient.post<import('@/types/platform').HostingPlan>('/platform/plans', body),

  updatePlan: (planId: string, body: Partial<import('@/types/staffPlatform').StaffPlanInput>) =>
    apiClient.patch<import('@/types/platform').HostingPlan>(`/platform/plans/${planId}`, body),

  rebalancePlansFromPrice: () =>
    apiClient.post<import('@/types/platform').HostingPlan[]>('/platform/plans/rebalance-from-price'),

  suspendEnvironment: (environmentId: string) =>
    apiClient.post<import('@/types/staffPlatform').StaffEnvironmentItem>(
      `/platform/environments/${environmentId}/suspend`,
    ),

  restoreEnvironment: (environmentId: string) =>
    apiClient.post<import('@/types/staffPlatform').StaffEnvironmentItem>(
      `/platform/environments/${environmentId}/restore`,
    ),

  terminateEnvironment: (environmentId: string) =>
    apiClient.post<import('@/types/staffPlatform').StaffEnvironmentItem>(
      `/platform/environments/${environmentId}/terminate`,
    ),

  clearEnvironmentStack: (environmentId: string, dropDatabase = false) =>
    apiClient.post<{ message: string }>(
      `/platform/environments/${environmentId}/stacks/clear`,
      null,
      { params: { drop_database: dropDatabase } },
    ),

  checkEnvironmentHealth: (environmentId: string) =>
    apiClient.post<import('@/types/staffPlatform').StaffEnvHealth>(
      `/platform/environments/${environmentId}/health/check`,
    ),

  getEnvironmentUsage: (environmentId: string) =>
    apiClient.get<import('@/types/staffPlatform').StaffEnvUsage>(
      `/platform/environments/${environmentId}/usage`,
    ),

  getEnvironmentStacks: (environmentId: string) =>
    apiClient.get<import('@/types/staffPlatform').StaffEnvStacks>(
      `/platform/environments/${environmentId}/stacks`,
    ),

  getEnvironmentLogs: (environmentId: string, lines = 200) =>
    apiClient.get<import('@/types/staffPlatform').StaffEnvLogs>(
      `/platform/environments/${environmentId}/logs`,
      { params: { lines } },
    ),

  repairEnvironmentFilesystem: (environmentId: string) =>
    apiClient.post<{ message: string }>(
      `/platform/environments/${environmentId}/filesystem/repair`,
    ),

  installEnvironmentStack: (environmentId: string, stack: string, replace = false) =>
    apiClient.post(`/platform/environments/${environmentId}/stacks/install`, null, {
      params: { stack, replace },
    }),

  getCustomerAudit: (customerId: string, limit = 50) =>
    apiClient.get<import('@/types/staffPlatform').StaffAuditItem[]>(
      `/platform/customers/${customerId}/audit`,
      { params: { limit } },
    ),

  getIntegrations: () =>
    apiClient.get<import('@/types/integrations').IntegrationsStatus>('/platform/integrations'),

  updateIntegrations: (body: import('@/types/integrations').IntegrationsUpdatePayload) =>
    apiClient.put<import('@/types/integrations').IntegrationsStatus>('/platform/integrations', body),

  importIntegrationsFromEnv: () =>
    apiClient.post<import('@/types/integrations').IntegrationsStatus>(
      '/platform/integrations/import-env',
    ),

  getSiteTheme: () =>
    apiClient.get<{
      theme: string
      themes: Array<{
        id: string
        name: string
        description: string
        home_scroll?: boolean
        colors?: Record<string, string>
      }>
      colors?: Record<string, string>
      plan_colors?: Array<{ id: string; label: string; max_price: string | number; accent: string }>
      updated_at?: string | null
    }>('/platform/site-theme'),

  updateSiteTheme: (body: {
    theme: string
    colors?: Record<string, string>
    plan_colors?: Record<string, string>
  }) =>
    apiClient.put<{
      theme: string
      themes: Array<{
        id: string
        name: string
        description: string
        home_scroll?: boolean
        colors?: Record<string, string>
      }>
      colors?: Record<string, string>
      plan_colors?: Array<{ id: string; label: string; max_price: string | number; accent: string }>
      updated_at?: string | null
    }>('/platform/site-theme', body),
}
