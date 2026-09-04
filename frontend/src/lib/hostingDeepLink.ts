/** Account → Hosting Panel deeplinks. */

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
  | 'ai'
  | 'git'
  | 'cron'
  | 'backups'
  | 'logs'
  | 'terminal'

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
  if (t === 'ai' || t === 'ai-engineer' || t === 'companion') return 'ai'
  if (t === 'git' || t === 'deploy') return 'git'
  if (t === 'applications' || t === 'apps') return 'apps'
  if (t === 'terminal' || t === 'ssh-terminal') return 'terminal'
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

/** Open the tenant hosting panel from the account (via single-use SSO handoff). */
export async function openHostingFromAccount(
  domain: string | null | undefined,
  tab?: string | null,
  environmentId?: string | null,
): Promise<boolean> {
  if (!domain && !environmentId) return false
  return openTenantCpanel(
    domain || '',
    tab && tab !== 'overview' ? siteTabToHostingTab(tab) : null,
    environmentId,
    true,
  )
}

export function accountHostingHref(domain: string | null | undefined, tab?: string | null): string | null {
  if (!domain) return null
  return tenantCpanelUrl(domain, tab && tab !== 'overview' ? siteTabToHostingTab(tab) : null)
}
