/** Permission strings — mirror backend app.core.permissions.Permission */
export const Permission = {
  SYSTEM_READ: 'system:read',
  SYSTEM_ADMIN: 'system:admin',
  SERVERS_READ: 'servers:read',
  SERVERS_WRITE: 'servers:write',
  DEPLOYMENTS_READ: 'deployments:read',
  DEPLOYMENTS_WRITE: 'deployments:write',
  DEPLOYMENTS_EXECUTE: 'deployments:execute',
  APPS_READ: 'apps:read',
  APPS_WRITE: 'apps:write',
  DOMAINS_READ: 'domains:read',
  DOMAINS_WRITE: 'domains:write',
  SSL_READ: 'ssl:read',
  SSL_WRITE: 'ssl:write',
  FILES_READ: 'files:read',
  FILES_WRITE: 'files:write',
  MAIL_READ: 'mail:read',
  MAIL_WRITE: 'mail:write',
  TERMINAL_EXECUTE: 'terminal:execute',
  MONITORING_READ: 'monitoring:read',
} as const

export type PermissionKey = (typeof Permission)[keyof typeof Permission]
