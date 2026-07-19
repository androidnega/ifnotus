import apiClient, { transferClient } from './client'
import type { LoginRequest, TokenResponse, User } from '@/types/auth'
import type {
  AccessAttemptEntry,
  IpBlacklistEntry,
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
    apiClient.post<TokenResponse>('/auth/login', credentials),

  probe: (body: { device_fingerprint?: string }) =>
    apiClient.post<{ message: string }>('/auth/probe', body),

  me: () => apiClient.get<User>('/auth/me'),

  logout: () => apiClient.post('/auth/logout'),
}

export const securityApi = {
  blacklist: (activeOnly = true) =>
    apiClient.get<{ total: number; entries: IpBlacklistEntry[] }>('/security/blacklist', {
      params: { active_only: activeOnly },
    }),

  unlock: (id: string, note?: string) =>
    apiClient.post<{ message: string }>(`/security/blacklist/${id}/unlock`, { note }),

  attempts: (limit = 100) =>
    apiClient.get<{ total: number; attempts: AccessAttemptEntry[] }>('/security/attempts', {
      params: { limit },
    }),
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
}

export const alertsApi = {
  list: () => apiClient.get<AlertsResponse>('/alerts'),
}

export const applicationsApi = {
  list: () => apiClient.get<ApplicationListResponse>('/applications'),

  get: (appId: string) => apiClient.get<ApplicationDetail>(`/applications/${appId}`),

  logs: (appId: string, lines = 100) =>
    apiClient.get<ApplicationLogsResponse>(`/applications/${appId}/logs`, { params: { lines } }),

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
    name: string
    domain_type?: string
    parent_domain_id?: string
    application_id?: string
    document_root?: string
    proxy_port?: number
    enabled?: boolean
    notes?: string
  }) => apiClient.post<Domain>('/domains', body),

  update: (
    id: string,
    body: Partial<{
      application_id: string | null
      document_root: string | null
      proxy_port: number | null
      enabled: boolean
      notes: string | null
    }>,
  ) => apiClient.patch<Domain>(`/domains/${id}`, body),

  delete: (id: string) => apiClient.delete<OperationResult>(`/domains/${id}`),

  dnsCheck: (id: string) => apiClient.post<DnsCheckResponse>(`/domains/${id}/dns-check`),
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

  createMailbox: (domainId: string, body: { local_part: string; password: string; quota_mb?: number; display_name?: string }) =>
    apiClient.post<Mailbox>(`/mail/domains/${domainId}/mailboxes`, body),

  updateMailbox: (
    domainId: string,
    mailboxId: string,
    body: { password?: string; quota_mb?: number; suspended?: boolean; display_name?: string },
  ) => apiClient.patch<Mailbox>(`/mail/domains/${domainId}/mailboxes/${mailboxId}`, body),

  deleteMailbox: (domainId: string, mailboxId: string) =>
    apiClient.delete<OperationResult>(`/mail/domains/${domainId}/mailboxes/${mailboxId}`),

  createAlias: (domainId: string, body: { source_local: string; destination: string }) =>
    apiClient.post<MailAlias>(`/mail/domains/${domainId}/aliases`, body),

  deleteAlias: (domainId: string, aliasId: string) =>
    apiClient.delete<OperationResult>(`/mail/domains/${domainId}/aliases/${aliasId}`),
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
