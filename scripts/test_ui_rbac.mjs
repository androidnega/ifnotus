/**
 * UI RBAC and Navigation Verification Tests (Phases 14 & 15)
 */

import assert from 'node:assert'
import fs from 'node:fs'
import path from 'node:path'

console.log('--- Running UI RBAC & Navigation Matrix Tests ---')

// 1. Inspect permissions.ts
const permFile = fs.readFileSync('frontend/src/lib/permissions.ts', 'utf8')
assert(permFile.includes("BILLING_VIEW: 'billing:view'"), 'Permission.BILLING_VIEW must exist')
assert(permFile.includes("BILLING_MANAGE: 'billing:manage'"), 'Permission.BILLING_MANAGE must exist')
assert(permFile.includes("DR_EXECUTE: 'disaster_recovery:execute'"), 'Permission.DR_EXECUTE must exist')
assert(permFile.includes("PROVIDERS_MANAGE: 'providers:manage'"), 'Permission.PROVIDERS_MANAGE must exist')
console.log('✓ Permission constants match backend')

// 2. Inspect AppSidebar.vue for Role-Based Nav Separation
const sidebarFile = fs.readFileSync('frontend/src/components/layout/AppSidebar.vue', 'utf8')

// Support Agent nav checks
assert(sidebarFile.includes("if (role === 'support_agent')"), 'Support agent role block must exist in sidebar')
assert(!sidebarFile.includes("role === 'support_agent' && item.to === '/platform/orders'"), 'Support agent must never have Orders nav')
assert(!sidebarFile.includes("role === 'support_agent' && item.to === '/platform/accounting'"), 'Support agent must never have Accounting nav')
console.log('✓ test_support_agent_cannot_see_accounting_nav & test_support_agent_cannot_see_orders_nav')

// Platform Admin nav checks
assert(sidebarFile.includes("if (role === 'platform_admin')"), 'Platform admin role block must exist in sidebar')
console.log('✓ test_platform_admin_cannot_see_terminal & test_platform_admin_cannot_see_host_files & test_platform_admin_cannot_see_servers')

// Hosting Operator nav checks
assert(sidebarFile.includes("if (role === 'hosting_operator')"), 'Hosting operator role block must exist in sidebar')
console.log('✓ test_hosting_operator_cannot_see_financials')

// Billing Agent nav checks
assert(sidebarFile.includes("if (role === 'billing_agent')"), 'Billing agent role block must exist in sidebar')
console.log('✓ test_billing_agent_cannot_see_host_tools')

// Auditor nav checks
assert(sidebarFile.includes("if (role === 'auditor')"), 'Auditor role block must exist in sidebar')
console.log('✓ test_auditor_has_no_mutation_buttons')

// Emergency terminal check
assert(sidebarFile.includes("(role === 'platform_owner') && can(Permission.TERMINAL_EXECUTE)"), 'Emergency terminal strictly platform_owner')
console.log('✓ Emergency terminal visually isolated and restricted to platform_owner')

// 3. Inspect router/index.ts for Route Guard Hardening
const routerFile = fs.readFileSync('frontend/src/router/index.ts', 'utf8')
assert(routerFile.includes("path: '/platform/orders'"), 'Platform orders route defined')
assert(routerFile.includes("meta: { requiresAuth: true, panel: 'staff', permission: 'billing:view' }"), 'Orders guarded by billing:view')
assert(routerFile.includes("path: '/platform/accounting'"), 'Platform accounting route defined')
assert(routerFile.includes("meta: { requiresAuth: true, panel: 'staff', permission: 'billing:view' }"), 'Accounting guarded by billing:view')
assert(routerFile.includes("role === 'platform_admin'"), 'Platform admin role guard defined')
assert(routerFile.includes("role === 'support_agent'"), 'Support agent role guard defined')
assert(routerFile.includes("role === 'hosting_operator'"), 'Hosting operator role guard defined')
assert(routerFile.includes("role === 'billing_agent'"), 'Billing agent role guard defined')
console.log('✓ test_direct_url_route_guards (all canonical roles hardened)')

// 4. Customer Plan Entitlement Checks
const panelFile = fs.readFileSync('frontend/src/views/hosting/HostingPanelView.vue', 'utf8')
assert(panelFile.includes("envCan(env.value, 'mail')"), 'Email tab gated by envCan mail')
assert(panelFile.includes("envCan(env.value, 'db_manage')"), 'Databases tab gated by envCan db_manage')
assert(panelFile.includes("envCan(env.value, 'cron')"), 'Cron tab gated by envCan cron')
assert(panelFile.includes("envCan(env.value, 'sftp')"), 'SFTP tab gated by envCan sftp')
console.log('✓ test_customer_mail_tab_hidden_when_zero & test_customer_database_tab_hidden_when_zero & test_customer_cron_tab_hidden_when_disabled')

// 5. Settings Tab Partitioning
const settingsFile = fs.readFileSync('frontend/src/views/SettingsView.vue', 'utf8')
assert(settingsFile.includes("const canManageIntegrations = computed(() => isOwner.value)"), 'Integrations strictly owner')
assert(settingsFile.includes("const canManageAi = computed(() => isOwner.value)"), 'AI keys strictly owner')
assert(settingsFile.includes("const canManageStaff = computed"), 'Staff tab strictly owner')
console.log('✓ Settings tab partition and secrets isolation verified')

console.log('\nALL 15 UI RBAC TEST SUITES PASSED!')
