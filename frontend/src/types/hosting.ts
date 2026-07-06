export interface Domain {
  id: string
  name: string
  domain_type: 'primary' | 'subdomain' | 'addon'
  parent_domain_id?: string | null
  application_id?: string | null
  document_root?: string | null
  enabled: boolean
  dns_points_here?: boolean | null
  nginx_enabled?: boolean | null
  ssl_certificate_path?: string | null
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface DomainListResponse {
  timestamp: string
  total: number
  domains: Domain[]
}

export interface DnsCheckResponse {
  domain: string
  resolves: boolean
  addresses: string[]
  points_to_server: boolean | null
  server_ip: string | null
  message?: string | null
}

export interface SslCertificate {
  domain_id?: string | null
  domain: string
  configured: boolean
  certificate_path?: string | null
  private_key_path?: string | null
  chain_path?: string | null
  subject?: string | null
  issuer?: string | null
  valid_from?: string | null
  valid_until?: string | null
  days_remaining?: number | null
  status?: string | null
  sans: string[]
  fingerprint_sha256?: string | null
  document_root?: string | null
  domain_enabled?: boolean | null
  nginx_ssl_enabled?: boolean | null
  message?: string | null
}

export interface SslSummary {
  total: number
  configured: number
  healthy: number
  expiring_soon: number
  expired: number
  missing: number
}

export interface SslListResponse {
  timestamp: string
  summary: SslSummary
  certificates: SslCertificate[]
}

export interface SslReadinessResponse {
  domain: string
  ready: boolean
  checks: Record<string, boolean>
  messages: string[]
  document_root?: string | null
  certificate_path?: string | null
}

export interface Mailbox {
  id: string
  domain_id: string
  email: string
  local_part: string
  quota_mb?: number | null
  suspended: boolean
  display_name?: string | null
  created_at: string
}

export interface MailAlias {
  id: string
  domain_id: string
  source_local: string
  source_email: string
  destination: string
  enabled: boolean
  created_at: string
}

export interface MailDomainResponse {
  timestamp: string
  domain: Domain
  mailboxes: Mailbox[]
  aliases: MailAlias[]
  webmail_url?: string | null
  mail_config_path?: string | null
}

export interface FileRoot {
  id: string
  label: string
  path: string
}

export interface FileRootsResponse {
  timestamp: string
  roots: FileRoot[]
}

export interface FileUploadInitResponse {
  upload_id: string
  chunk_size: number
  total_chunks: number
}

export interface FileDetail {
  name: string
  path: string
  is_dir: boolean
  size_bytes?: number | null
  mode?: string | null
  owner?: string | null
  group?: string | null
  modified?: string | null
  content?: string | null
}

export interface TerminalExecuteResponse {
  exit_code: number
  stdout: string
  stderr: string
  success: boolean
  audit_id: string
}

export interface TerminalAuditEntry {
  id: string
  username: string
  command: string
  exit_code: number | null
  success: boolean
  output_preview: string | null
  executed_at: string
}
