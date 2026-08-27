/** Brand + plan accent theme helpers. */

export type ThemeColors = {
  primary: string
  primary_hover: string
  ink: string
  paper: string
  surface: string
  muted: string
  border: string
}

export type PlanColorTier = {
  id: string
  label: string
  max_price: string | number
  accent: string
}

export const DEFAULT_COLORS: ThemeColors = {
  primary: '#ff6c2c',
  primary_hover: '#e85a1c',
  ink: '#161a1d',
  paper: '#f4f1ec',
  surface: '#ffffff',
  muted: '#6b7280',
  border: '#e7e2db',
}

export const DEFAULT_PLAN_TIERS: PlanColorTier[] = [
  { id: 'starter', label: 'Starter', max_price: 40, accent: '#0f766e' },
  { id: 'growth', label: 'Growth', max_price: 80, accent: '#0369a1' },
  { id: 'pro', label: 'Pro', max_price: 160, accent: '#c2410c' },
  { id: 'power', label: 'Power', max_price: 99999, accent: '#1e3a5f' },
]

export function applyThemeColors(
  colors: Partial<ThemeColors>,
  root: HTMLElement = document.documentElement,
  themeId?: string | null,
) {
  const merged = { ...DEFAULT_COLORS, ...colors }
  root.style.setProperty('--if-primary', merged.primary)
  root.style.setProperty('--if-primary-hover', merged.primary_hover)
  root.style.setProperty('--if-ink', merged.ink)
  root.style.setProperty('--if-paper', merged.paper)
  root.style.setProperty('--if-surface', merged.surface)
  root.style.setProperty('--if-muted', merged.muted)
  root.style.setProperty('--if-border', merged.border)
  root.style.setProperty('--if-primary-soft', softAccent(merged.primary, 0.14))
  root.style.setProperty('--if-primary-ring', softAccent(merged.primary, 0.22))
  root.style.setProperty('--if-glow', softAccent(merged.primary, 0.1))

  // Staff / Tailwind bridge
  root.style.setProperty('--color-brand-500', merged.primary)
  root.style.setProperty('--color-brand-600', merged.primary_hover)
  root.style.setProperty('--brand-rgb-500', hexToRgbChannels(merged.primary))
  root.style.setProperty('--brand-rgb-600', hexToRgbChannels(merged.primary_hover))
  root.style.setProperty('--color-surface', merged.paper)
  root.style.setProperty('--color-surface-raised', merged.surface)
  root.style.setProperty('--color-border', merged.border)
  root.style.setProperty('--color-text-muted', merged.muted)

  const known = ['studio-light', 'ocean-clean', 'graphite', 'palm-grove', 'server-dark']
  for (const id of known) {
    root.classList.remove(`theme-${id}`)
  }
  if (themeId) {
    const safe = String(themeId).replace(/[^a-z0-9-]/gi, '')
    root.dataset.siteTheme = safe
    root.classList.add(`theme-${safe}`)
  }

  try {
    localStorage.setItem('ifnotus_theme_colors', JSON.stringify(merged))
    if (themeId) localStorage.setItem('ifnotus_theme_id', String(themeId))
  } catch {
    /* ignore quota / private mode */
  }
}

function hexToRgbChannels(hex: string): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  if (Number.isNaN(n)) return '255 108 44'
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`
}

export function planAccentFromPrice(
  price: number,
  tiers: PlanColorTier[] = DEFAULT_PLAN_TIERS,
  features?: Record<string, unknown> | null,
): string {
  const custom = features?.accent
  if (typeof custom === 'string' && /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(custom)) {
    return custom
  }
  const sorted = [...tiers].sort((a, b) => Number(a.max_price) - Number(b.max_price))
  for (const tier of sorted) {
    if (price <= Number(tier.max_price)) return tier.accent
  }
  return sorted[sorted.length - 1]?.accent || DEFAULT_COLORS.primary
}

export function softAccent(hex: string, alpha = 0.12): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
