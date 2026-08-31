/** Platform hostname helpers for staff fpanel host vs customer portal. */

import { customersApi } from '@/api'

export const STAFF_PANEL_HOST = 'fpanel.ifnotus.space'
export const STAFF_PANEL_ORIGIN = `https://${STAFF_PANEL_HOST}`

export function hostnameNow(): string {
  if (typeof window === 'undefined') return ''
  return (window.location.hostname || '').toLowerCase()
}

export function isStaffPanelHost(host = hostnameNow()): boolean {
  return host === STAFF_PANEL_HOST
}

/** Customer fPanel host: fpanel.<domain> (e.g. fpanel.yalleydadzie.online). */
export function isCustomerFpanelHost(host = hostnameNow()): boolean {
  if (isStaffPanelHost(host)) return false
  return host.startsWith('fpanel.')
}

export const isCustomerCpanelHost = isCustomerFpanelHost

export function staffPanelHref(path = '/'): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return `${STAFF_PANEL_ORIGIN}${p}`
}

function normalizedApex(host: string): string {
  return (host || '').toLowerCase().replace(/\.$/, '').replace(/^www\./, '')
}

export function isPlatformOrStudentHost(host: string): boolean {
  const h = normalizedApex(host)
  if (h.endsWith('.customers.ifnotus.space')) return false
  return (
    h === 'ifnotus.space' ||
    h.endsWith('.ifnotus.space') ||
    h === 'serverlabsttu.space' ||
    h.endsWith('.serverlabsttu.space')
  )
}

export function customApex(host: string): string | null {
  const h = normalizedApex(host)
  if (!h || isPlatformOrStudentHost(h)) return null
  return h
}

export function primaryApexDomain(host: string): string {
  let h = normalizedApex(host)
  if (h.startsWith('fpanel.')) h = h.slice('fpanel.'.length)
  if (h.startsWith('webmail.')) h = h.slice('webmail.'.length)
  if (h.startsWith('mail.')) h = h.slice('mail.'.length)
  if (h.startsWith('www.')) h = h.slice(4)
  if (h.endsWith('.customers.ifnotus.space')) return h
  if (isPlatformOrStudentHost(h)) return h

  const parts = h.split('.')
  if (parts.length > 2) {
    const twoLevelTlds = new Set(['co.uk', 'org.uk', 'me.uk', 'com.gh', 'org.gh', 'edu.gh', 'gov.gh', 'net.gh', 'com.ng', 'co.za'])
    const suffix2 = parts.slice(-2).join('.')
    if (twoLevelTlds.has(suffix2) && parts.length > 3) {
      return parts.slice(-3).join('.')
    } else if (!twoLevelTlds.has(suffix2)) {
      return parts.slice(-2).join('.')
    }
  }
  return h
}

/** Tenant panel canonical entry — https://fpanel.<domain>/{tab}. */
export function tenantFpanelUrl(domain: string, tab?: string | null): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (host === 'ifnotus.space' || host === STAFF_PANEL_HOST || host === 'mail.ifnotus.space') {
    return null
  }
  const primary = primaryApexDomain(host)
  const fpanelHost = isPlatformOrStudentHost(primary) ? primary : `fpanel.${primary}`
  const base = `https://${fpanelHost}`
  const t = (tab || '').trim().replace(/^\//, '')
  return t && t !== 'overview' ? `${base}/${encodeURIComponent(t)}` : `${base}/`
}

export const tenantCpanelUrl = tenantFpanelUrl

/** Tenant webmail canonical entry — https://webmail.<domain>. */
export function tenantMailUrl(domain: string): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (host === 'ifnotus.space' || host === STAFF_PANEL_HOST) {
    return 'https://mail.ifnotus.space/'
  }
  const primary = primaryApexDomain(host)
  const wmHost = isPlatformOrStudentHost(primary) ? 'mail.ifnotus.space' : `webmail.${primary}`
  return `https://${wmHost}`
}

export function customPanelHostname(domain: string): string | null {
  const url = tenantFpanelUrl(domain)
  if (!url) return null
  try {
    const u = new URL(url)
    return u.host
  } catch {
    return null
  }
}

export function customMailHostname(domain: string): string | null {
  const url = tenantMailUrl(domain)
  if (!url) return null
  try {
    const u = new URL(url)
    return u.host
  } catch {
    return null
  }
}

/** Open tenant fPanel via secure single-use SSO handoff token (opens in a new tab). */
export async function openTenantFpanel(
  domain: string,
  tab?: string | null,
  environmentId?: string | null,
  newTab = true,
): Promise<void> {
  if (typeof window === 'undefined') return

  try {
    const { data } = await customersApi.createSsoHandoff({
      domain: domain || undefined,
      environment_id: environmentId || undefined,
      tab: tab || undefined,
    })
    if (data.handoff_url) {
      if (newTab) {
        const opened = window.open(data.handoff_url, '_blank')
        if (opened) return
      }
      window.location.href = data.handoff_url
      return
    }
  } catch {
    // Fallback if SSO handoff creation fails
  }

  const fallback = tenantFpanelUrl(domain, tab)
  if (fallback) {
    if (newTab) {
      const opened = window.open(fallback, '_blank')
      if (opened) return
    }
    window.location.href = fallback
  }
}

export const openTenantCpanel = openTenantFpanel
