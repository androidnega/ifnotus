/** Account → Hosting Panel deeplinks (Phase H). Opens tenant /cpanel in a new tab. */

import { openTenantCpanel, tenantCpanelUrl } from '@/lib/platformHosts'

export type HostingPanelTab =
  | 'overview'
  | 'files'
  | 'databases'
  | 'domains'
  | 'email'
  | 'transfer'
  | 'stack'
  | 'apps'
  | 'cron'
  | 'backups'
  | 'logs'

/** Map legacy Account site-workspace tabs to Hosting Panel tabs. */
export function siteTabToHostingTab(tab?: string | null): HostingPanelTab {
  const t = String(tab || '').toLowerCase().trim()
  if (t === 'files') return 'files'
  if (t === 'database' || t === 'databases') return 'databases'
  if (t === 'protect' || t === 'domains' || t === 'domain') return 'domains'
  if (t === 'mail' || t === 'email') return 'email'
  if (t === 'ftp' || t === 'transfer' || t === 'sftp' || t === 'ssh') return 'transfer'
  if (t === 'logs' || t === 'log') return 'logs'
  if (t === 'backups' || t === 'backup') return 'backups'
  if (t === 'cron' || t === 'crons' || t === 'scheduler') return 'cron'
  if (t === 'stack' || t === 'stacks' || t === 'install' || t === 'wordpress') return 'stack'
  if (t === 'applications' || t === 'apps' || t === 'ai') return 'apps'
  if (t === 'overview' || t === 'home' || !t) return 'overview'
  return 'overview'
}

export function hostingLocation(
  environmentId: string,
  tab?: string | null,
): { name: string; params: { environmentId: string }; query?: Record<string, string> } {
  const mapped = siteTabToHostingTab(tab)
  if (mapped === 'files') {
    return { name: 'hosting-files', params: { environmentId } }
  }
  if (mapped === 'overview') {
    return { name: 'hosting-panel', params: { environmentId } }
  }
  return {
    name: 'hosting-panel',
    params: { environmentId },
    query: { tab: mapped },
  }
}

/** Open the tenant hosting panel from the account (via single-use SSO handoff to cpanel.<domain>). */
export function openHostingFromAccount(
  domain: string | null | undefined,
  tab?: string | null,
  environmentId?: string | null,
): boolean {
  if (!domain && !environmentId) return false
  void openTenantCpanel(
    domain || '',
    tab && tab !== 'overview' ? siteTabToHostingTab(tab) : null,
    environmentId,
  )
  return true
}

export function accountHostingHref(domain: string | null | undefined, tab?: string | null): string | null {
  if (!domain) return null
  return tenantCpanelUrl(domain, tab && tab !== 'overview' ? siteTabToHostingTab(tab) : null)
}
