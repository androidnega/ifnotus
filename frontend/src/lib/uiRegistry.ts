/**
 * Master UI map — every route, shell, tabs, and permission gate.
 * Used by redesign work and QA walkthroughs.
 */

export type UiShell = 'public' | 'portal' | 'staff' | 'auth' | 'standalone'

export type UiRouteEntry = {
  path: string
  name: string
  shell: UiShell
  view: string
  permission?: string
  panel?: 'public' | 'portal' | 'staff'
  tabs?: string[]
  notes?: string
}

/** Customer account primary tabs (/account) */
export const PORTAL_ACCOUNT_TABS = [
  { id: 'home', label: 'Overview' },
  { id: 'hosting', label: 'Hosting' },
  { id: 'billing', label: 'Billing' },
  { id: 'support', label: 'Support' },
  { id: 'settings', label: 'Settings' },
] as const

/** Site workspace subtabs (PortalSitePanel / hosting embed) */
export const SITE_WORKSPACE_TABS = [
  { id: 'stack', label: 'Stack' },
  { id: 'applications', label: 'Applications' },
  { id: 'files', label: 'Files', planGate: 'file_manager' },
  { id: 'git', label: 'Git', planGate: 'git' },
  { id: 'logs', label: 'Logs' },
  { id: 'cron', label: 'Cron', planGate: 'cron' },
  { id: 'database', label: 'Database', planGate: 'db_manage' },
  { id: 'ftp', label: 'Transfer', planGate: 'sftp' },
  { id: 'mail', label: 'Email', planGate: 'mail' },
  { id: 'protect', label: 'Domain' },
] as const

/** Hosting panel top tabs (/hosting/:id) */
export const HOSTING_PANEL_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'files', label: 'Files' },
  { id: 'databases', label: 'Databases' },
  { id: 'domains', label: 'Domains' },
  { id: 'email', label: 'Email' },
  { id: 'transfer', label: 'Transfer' },
  { id: 'terminal', label: 'Terminal' },
  { id: 'stack', label: 'Stack' },
  { id: 'apps', label: 'Apps' },
  { id: 'ai', label: 'AI Engineer' },
  { id: 'git', label: 'Git' },
  { id: 'cron', label: 'Cron' },
  { id: 'backups', label: 'Backups' },
  { id: 'logs', label: 'Logs' },
] as const

/** Staff sidebar groups (AppSidebar) */
export const STAFF_NAV = {
  host: [
    { to: '/panel', name: 'dashboard', label: 'Dashboard' },
    { to: '/applications', name: 'applications', label: 'Apps', permission: 'apps:read' },
    { to: '/domains', name: 'domains', label: 'DNS', permission: 'domains:read' },
    { to: '/files', name: 'files', label: 'File Manager', permission: 'files:read' },
    { to: '/databases', name: 'databases', label: 'Databases', permission: 'databases:read' },
    { to: '/admin/mail', name: 'mail-admin', label: 'Email', permission: 'mail:read' },
    { to: '/ssl', name: 'ssl', label: 'SSL', permission: 'ssl:read' },
    { to: '/operations', name: 'operations', label: 'Operations', permission: 'system:read' },
    { to: '/security', name: 'security', label: 'Security', permission: 'system:admin' },
    { to: '/terminal', name: 'terminal', label: 'Terminal', permission: 'terminal:execute' },
    { to: '/servers', name: 'servers', label: 'Host', permission: 'servers:read' },
  ],
  customers: [
    { to: '/platform/customers', name: 'platform-customers', label: 'Customers', permission: 'platform:read' },
  ],
  money: [
    { to: '/platform/orders', name: 'platform-orders', label: 'Orders', permission: 'billing:view' },
    { to: '/platform/accounting', name: 'platform-accounting', label: 'Accounting', permission: 'billing:view' },
    { to: '/platform/plans', name: 'platform-plans', label: 'Plans', permission: 'platform:write' },
  ],
  support: [{ to: '/support', name: 'support', label: 'Tickets', permission: 'support:read' }],
  system: [{ to: '/settings', name: 'settings', label: 'Settings', permission: 'system:read' }],
} as const

export const UI_ROUTES: UiRouteEntry[] = [
  { path: '/', name: 'home', shell: 'public', view: 'HomeView.vue', panel: 'public' },
  { path: '/plans', name: 'plans', shell: 'public', view: 'PlansView.vue', panel: 'public' },
  { path: '/plans/:slug', name: 'plan-detail', shell: 'public', view: 'PlanDetailView.vue', panel: 'public' },
  { path: '/contact', name: 'contact', shell: 'public', view: 'ContactView.vue', panel: 'public' },
  { path: '/status', name: 'status', shell: 'public', view: 'PublicStatusView.vue', panel: 'public' },
  { path: '/legal/:slug', name: 'legal', shell: 'public', view: 'LegalView.vue', panel: 'public' },
  { path: '/login', name: 'login', shell: 'public', view: 'portal/PortalSignupView.vue (or LoginView on fpanel.ifnotus.space)', panel: 'public' },
  { path: '/signup', name: 'portal-signup', shell: 'public', view: 'portal/PortalSignupView.vue', panel: 'public' },
  { path: '/admin_1', name: 'admin-1-legacy', shell: 'auth', view: 'redirect→/login', panel: 'public' },
  { path: '/staff-login', name: 'staff-login-legacy', shell: 'auth', view: 'redirect→/login', panel: 'public' },
  { path: '/staff/login', name: 'staff-login-nested', shell: 'auth', view: 'redirect→/login', panel: 'public' },
  { path: '/forgot-password', name: 'forgot-password', shell: 'auth', view: 'ForgotPasswordView.vue', panel: 'public' },
  { path: '/reset-password', name: 'reset-password', shell: 'auth', view: 'ResetPasswordView.vue', panel: 'public' },
  {
    path: '/account',
    name: 'portal-dashboard',
    shell: 'portal',
    view: 'portal/PortalDashboardView.vue',
    panel: 'portal',
    tabs: PORTAL_ACCOUNT_TABS.map((t) => t.label),
  },
  { path: '/account/plans', name: 'portal-account-plans', shell: 'portal', view: 'portal/PortalAccountPlansView.vue', panel: 'portal' },
  { path: '/account/settings', name: 'portal-account-settings', shell: 'portal', view: 'portal/PortalAccountSettingsView.vue', panel: 'portal' },
  { path: '/account/support', name: 'portal-support', shell: 'portal', view: 'portal/PortalSupportView.vue', panel: 'portal' },
  { path: '/account/invoice/:id', name: 'portal-invoice', shell: 'portal', view: 'portal/PortalInvoiceView.vue', panel: 'portal' },
  { path: '/account/files', name: 'portal-files', shell: 'portal', view: 'redirect→hosting-files', panel: 'portal', notes: 'Legacy; redirects to /hosting/:id/files' },
  { path: '/account/files/upload', name: 'portal-file-upload', shell: 'portal', view: 'portal/PortalFileUploadView.vue', panel: 'portal' },
  { path: '/account/files/edit', name: 'portal-file-editor', shell: 'portal', view: 'portal/PortalFileEditorView.vue', panel: 'portal' },
  { path: '/account/database/studio', name: 'portal-database-studio', shell: 'portal', view: 'portal/PortalDatabaseStudioView.vue', panel: 'portal' },
  {
    path: '/hosting/:environmentId',
    name: 'hosting-panel',
    shell: 'portal',
    view: 'hosting/HostingPanelView.vue',
    panel: 'portal',
    tabs: HOSTING_PANEL_TABS.map((t) => t.label),
  },
  {
    path: '/hosting/:environmentId/files',
    name: 'hosting-files',
    shell: 'portal',
    view: 'hosting/HostingPanelView.vue',
    panel: 'portal',
    notes: 'hostingTab=files',
  },
  { path: '/panel', name: 'dashboard', shell: 'staff', view: 'DashboardView.vue', panel: 'staff' },
  { path: '/applications', name: 'applications', shell: 'staff', view: 'ApplicationsView.vue', panel: 'staff', permission: 'apps:read' },
  { path: '/applications/:id', name: 'application-detail', shell: 'staff', view: 'ApplicationDetailView.vue', panel: 'staff', permission: 'apps:read' },
  { path: '/domains', name: 'domains', shell: 'staff', view: 'DomainsView.vue', panel: 'staff', permission: 'domains:read' },
  { path: '/files', name: 'files', shell: 'staff', view: 'FilesView.vue', panel: 'staff', permission: 'files:read' },
  { path: '/files/upload', name: 'files-upload', shell: 'staff', view: 'FileUploadView.vue', panel: 'staff', permission: 'files:write' },
  { path: '/files/edit', name: 'file-editor', shell: 'staff', view: 'FileEditorView.vue', panel: 'staff', permission: 'files:read' },
  { path: '/databases', name: 'databases', shell: 'staff', view: 'DatabasesView.vue', panel: 'staff', permission: 'databases:read' },
  { path: '/admin/mail', name: 'mail-admin', shell: 'staff', view: 'MailView.vue', panel: 'staff', permission: 'mail:read' },
  { path: '/ssl', name: 'ssl', shell: 'staff', view: 'SslView.vue', panel: 'staff', permission: 'ssl:read' },
  { path: '/operations', name: 'operations', shell: 'staff', view: 'OperationsView.vue', panel: 'staff', permission: 'system:read' },
  { path: '/terminal', name: 'terminal', shell: 'staff', view: 'TerminalView.vue', panel: 'staff', permission: 'terminal:execute' },
  { path: '/servers', name: 'servers', shell: 'staff', view: 'ServersView.vue', panel: 'staff', permission: 'servers:read' },
  { path: '/platform/customers', name: 'platform-customers', shell: 'staff', view: 'PlatformCustomersView.vue', panel: 'staff', permission: 'platform:read' },
  { path: '/platform/plans', name: 'platform-plans', shell: 'staff', view: 'PlatformPlansView.vue', panel: 'staff', permission: 'platform:write' },
    { path: '/platform/orders', name: 'platform-orders', shell: 'staff', view: 'PlatformOrdersView.vue', panel: 'staff', permission: 'platform:read' },
  {
    path: '/platform/orders/:id/receipt',
    name: 'platform-order-receipt',
    shell: 'staff',
    view: 'PlatformOrderReceiptView.vue',
    panel: 'staff',
    permission: 'customers:manage',
  },
  { path: '/platform/accounting', name: 'platform-accounting', shell: 'staff', view: 'PlatformAccountingView.vue', panel: 'staff', permission: 'customers:manage' },
  { path: '/support', name: 'support', shell: 'staff', view: 'SupportTicketsView.vue', panel: 'staff', permission: 'support:read' },
  { path: '/settings', name: 'settings', shell: 'staff', view: 'SettingsView.vue', panel: 'staff', permission: 'system:read' },
  { path: '/security', name: 'security', shell: 'staff', view: 'SecurityView.vue', panel: 'staff', permission: 'system:admin' },
  { path: '/databases/studio', name: 'database-studio', shell: 'standalone', view: 'DatabaseStudioView.vue', panel: 'staff', permission: 'databases:read' },
  { path: '/terminal/full', name: 'terminal-full', shell: 'standalone', view: 'TerminalFullscreenView.vue', panel: 'staff', permission: 'terminal:execute' },
]

export function routesForShell(shell: UiShell): UiRouteEntry[] {
  return UI_ROUTES.filter((r) => r.shell === shell)
}
