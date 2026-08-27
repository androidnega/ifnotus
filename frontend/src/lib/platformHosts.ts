/** Platform hostname helpers for staff cpanel host vs customer portal. */

export const STAFF_PANEL_HOST = 'cpanel.ifnotus.space'
export const STAFF_PANEL_ORIGIN = `https://${STAFF_PANEL_HOST}`

export function hostnameNow(): string {
  if (typeof window === 'undefined') return ''
  return (window.location.hostname || '').toLowerCase()
}

export function isStaffPanelHost(host = hostnameNow()): boolean {
  return host === STAFF_PANEL_HOST
}

/** @deprecated Tenant panels use /cpanel on the site — not cpanel.<domain>. */
export function isCustomerCpanelHost(host = hostnameNow()): boolean {
  return host.startsWith('cpanel.') && host !== STAFF_PANEL_HOST
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

/** Tenant panel entry — always path-based /cpanel on the site hostname. */
export function tenantCpanelUrl(domain: string, tab?: string | null): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (host === 'ifnotus.space' || host === STAFF_PANEL_HOST || host === 'mail.ifnotus.space') {
    return null
  }
  if (host.startsWith('cpanel.') && host !== STAFF_PANEL_HOST) {
    host = host.slice('cpanel.'.length)
  }
  const base = `https://${host}/cpanel`
  const t = (tab || '').trim()
  return t ? `${base}?tab=${encodeURIComponent(t)}` : base
}

/** Tenant webmail entry — /mail on the site (IFNOTUS uses mail.ifnotus.space). */
export function tenantMailUrl(domain: string): string | null {
  let host = normalizedApex(domain)
  if (!host) return null
  if (host === 'ifnotus.space' || host === STAFF_PANEL_HOST) {
    return 'https://mail.ifnotus.space/'
  }
  if (host.startsWith('cpanel.') && host !== STAFF_PANEL_HOST) {
    host = host.slice('cpanel.'.length)
  }
  return `https://${host}/mail`
}

/** @deprecated Use tenantCpanelUrl — panels are domain.tld/cpanel, not cpanel.domain. */
export function customPanelHostname(domain: string): string | null {
  const url = tenantCpanelUrl(domain)
  if (!url) return null
  try {
    const u = new URL(url)
    return `${u.host}/cpanel`
  } catch {
    return null
  }
}

/** @deprecated Use tenantMailUrl — mail is domain.tld/mail except mail.ifnotus.space. */
export function customMailHostname(domain: string): string | null {
  const url = tenantMailUrl(domain)
  if (!url) return null
  try {
    const u = new URL(url)
    return u.pathname === '/' || u.pathname === '' ? u.host : `${u.host}${u.pathname.replace(/\/$/, '')}`
  } catch {
    return null
  }
}

export function openTenantCpanel(domain: string, tab?: string | null): void {
  const url = tenantCpanelUrl(domain, tab)
  if (!url || typeof window === 'undefined') return
  window.open(url, '_blank', 'noopener,noreferrer')
}
