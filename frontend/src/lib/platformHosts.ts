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

export function isTenantSubdomainHost(host = hostnameNow()): boolean {
  const h = normalizedApex(host)
  if (!h || h === PLATFORM_APEX) return false
  // Staff WHM + mail/api/www are platform service hosts — never tenant sites.
  if (PLATFORM_SERVICE_HOSTS.has(h) || isStaffPanelHost(h)) return false
  if (h.endsWith('.customers.ifnotus.space')) return true
  if (h.endsWith('.ifnotus.space') && h !== PLATFORM_APEX) return true
  if (h.endsWith('.serverlabsttu.space') && h !== 'serverlabsttu.space') return true
  return false
}

/** Custom fpanel host or tenant subdomain — same panel tool paths (/files, /databases, …). */
export function isTenantPanelHost(host = hostnameNow()): boolean {
  return isCustomerCpanelHost(host) || isTenantSubdomainHost(host)
}

export const PLATFORM_APEX = 'ifnotus.space'
export const PLATFORM_ORIGIN = `https://${PLATFORM_APEX}`

export const PLATFORM_SERVICE_HOSTS = new Set([
  STAFF_PANEL_HOST,
  'cpanel.ifnotus.space',
  'mail.ifnotus.space',
  'webmail.ifnotus.space',
  'api.ifnotus.space',
  'www.ifnotus.space',
])

/** Strip fpanel./cpanel. prefix for panel-alias / go/hosting lookups. */
export function normalizeGoHostingHost(raw: string): string {
  let host = normalizedApex(raw)
  if (host.startsWith('fpanel.')) host = host.slice('fpanel.'.length)
  if (host.startsWith('cpanel.')) host = host.slice('cpanel.'.length)
  return host
}

/** Hostnames that must never be resolved via /go/hosting (platform + staff fpanel). */
export function isReservedPanelHost(raw: string): boolean {
  const host = normalizedApex(raw)
  if (!host) return true
  if (host === PLATFORM_APEX || host === STAFF_PANEL_HOST) return true
  if (PLATFORM_SERVICE_HOSTS.has(host)) return true
  return normalizeGoHostingHost(host) === PLATFORM_APEX
}

export function portalAccountUrl(path = '/account'): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return `${PLATFORM_ORIGIN}${p}`
}

export function redirectToStaffPanel(path = '/panel'): void {
  if (typeof window === 'undefined') return
  window.location.replace(staffPanelHref(path))
}

export function redirectToPortalAccount(path = '/account'): void {
  if (typeof window === 'undefined') return
  window.location.replace(portalAccountUrl(path))
}

/** Where logout should land on the current host. */
export function logoutLandingUrl(): string {
  if (isStaffPanelHost()) return staffPanelHref('/login')
  if (isTenantSubdomainHost()) return portalLoginRedirectForTenantHost()
  return `${PLATFORM_ORIGIN}/login`
}

/** Canonical customer account login — always on ifnotus.space, never tenant subdomains. */
export function portalLoginUrl(redirectPath?: string | null): string {
  const base = `${PLATFORM_ORIGIN}/login`
  const r = (redirectPath || '').trim()
  if (!r || r === '/login' || r.startsWith('//')) return base
  if (r.startsWith('/')) {
    return `${base}?redirect=${encodeURIComponent(r)}`
  }
  return `${base}?redirect=${encodeURIComponent(r)}`
}

/** Login URL that returns the user to tenant hosting via /go/hosting SSO after sign-in. */
export function portalLoginRedirectForTenantHost(
  host = hostnameNow(),
  returnPath?: string,
): string {
  const h = normalizedApex(host)
  if (!isTenantSubdomainHost(h)) {
    const path = returnPath || '/account'
    return portalLoginUrl(path.startsWith('/') ? path : `/${path}`)
  }
  const path =
    returnPath ||
    (typeof window !== 'undefined' ? `${window.location.pathname}${window.location.search}` : '/hosting/')
  let tab: string | null = null
  if (path.includes('/files')) tab = 'files'
  const goPath = `/go/hosting?host=${encodeURIComponent(h)}${tab ? `&tab=${encodeURIComponent(tab)}` : ''}`
  // Hosting entry must use panel username/password login (hosting_name), not account email.
  const base = `${PLATFORM_ORIGIN}/login`
  return `${base}?mode=panel&host=${encodeURIComponent(h)}&redirect=${encodeURIComponent(goPath)}`
}

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
    h === PLATFORM_APEX ||
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

/** Tenant panel entry URL — subdomains: same-host /hosting/; custom apex: fpanel.<domain>. */
export function tenantFpanelUrl(domain: string, tab?: string | null): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (host === PLATFORM_APEX || host === STAFF_PANEL_HOST || host === 'mail.ifnotus.space') {
    return null
  }
  const t = (tab || '').trim().replace(/^\//, '')
  if (isTenantSubdomainHost(host)) {
    const base = `https://${host}/hosting/`
    return t && t !== 'overview' ? `${base}?tab=${encodeURIComponent(t)}` : base
  }
  const primary = primaryApexDomain(host)
  const fpanelHost = `fpanel.${primary}`
  const base = `https://${fpanelHost}`
  return t && t !== 'overview' ? `${base}/${encodeURIComponent(t)}` : `${base}/`
}

export const tenantCpanelUrl = tenantFpanelUrl

/** Tenant webmail entry — same-host /mail (never bounce tenants to mail.ifnotus.space). */
export function tenantMailUrl(domain: string): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (
    host === PLATFORM_APEX ||
    host === STAFF_PANEL_HOST ||
    host === 'mail.ifnotus.space' ||
    host === 'webmail.ifnotus.space' ||
    PLATFORM_SERVICE_HOSTS.has(host)
  ) {
    return 'https://mail.ifnotus.space/'
  }
  if (host.startsWith('webmail.')) {
    return `https://${host}/`
  }
  if (host.startsWith('fpanel.')) host = host.slice('fpanel.'.length)
  if (host.startsWith('cpanel.')) host = host.slice('cpanel.'.length)
  if (host.startsWith('mail.') && host !== 'mail.ifnotus.space') {
    host = host.slice('mail.'.length)
  }
  // Tenant subdomain or custom apex: webmail stays on that site at /mail.
  return `https://${host}/mail`
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

/** Open tenant hosting panel via SSO handoff (new tab). */
export async function openTenantFpanel(
  domain: string,
  tab?: string | null,
  environmentId?: string | null,
  newTab = true,
): Promise<boolean> {
  if (typeof window === 'undefined') return false

  try {
    const { data } = await customersApi.createSsoHandoff({
      domain: domain || undefined,
      environment_id: environmentId || undefined,
      tab: tab || undefined,
    })
    const handoffUrl = correctTenantHandoffUrl(
      data.handoff_url,
      data.token,
      data.domain || domain,
      tab,
    )
    if (handoffUrl) {
      if (newTab) {
        // Modern browsers return null for window.open(..., 'noopener') even when the
        // tab opens — never fall back to navigating the account tab.
        window.open(handoffUrl, '_blank', 'noopener,noreferrer')
        return true
      }
      window.location.assign(handoffUrl)
      return true
    }
  } catch {
    /* fallback below */
  }

  const fallback = tenantFpanelUrl(domain, tab)
  if (fallback) {
    if (newTab) {
      window.open(fallback, '_blank', 'noopener,noreferrer')
      return true
    }
    window.location.assign(fallback)
    return true
  }
  return false
}

export const openTenantCpanel = openTenantFpanel

/** Rewrite legacy staff-panel SSO URLs for platform tenant subdomains. */
export function correctTenantHandoffUrl(
  handoffUrl: string,
  token: string,
  domain: string | null | undefined,
  tab?: string | null,
): string {
  let host = normalizedApex(domain || '')
  if (!host || !isTenantSubdomainHost(host)) return handoffUrl
  try {
    const parsed = new URL(handoffUrl)
    if (parsed.hostname === host && parsed.pathname.startsWith('/hosting/')) {
      return handoffUrl
    }
  } catch {
    /* rebuild below */
  }
  const q = new URLSearchParams({ token })
  const t = (tab || '').trim().replace(/^\//, '')
  if (t && t !== 'overview') q.set('tab', t)
  return `https://${host}/hosting/sso?${q.toString()}`
}
