import { computed, ref } from 'vue'
import { catalogApi } from '@/api'
import {
  applyThemeColors,
  DEFAULT_COLORS,
  DEFAULT_PLAN_TIERS,
  type PlanColorTier,
  type ThemeColors,
} from '@/lib/theme'

export type SiteThemeId =
  | 'studio-light'
  | 'ocean-clean'
  | 'graphite'
  | 'palm-grove'
  | string

export interface SiteThemeOption {
  id: string
  name: string
  description: string
  home_scroll?: boolean
  colors?: ThemeColors
}

const THEME_ALIASES: Record<string, SiteThemeId> = {
  'server-dark': 'studio-light',
  'ember-studio': 'studio-light',
  'atlantic-mist': 'ocean-clean',
  'baobab-indigo': 'graphite',
  palm: 'palm-grove',
}

const theme = ref<SiteThemeId>('studio-light')
const themes = ref<SiteThemeOption[]>([])
const colors = ref<ThemeColors>({ ...DEFAULT_COLORS })
const planColors = ref<PlanColorTier[]>([...DEFAULT_PLAN_TIERS])
const loaded = ref(false)
let loadInflight: Promise<void> | null = null

function normalizeThemeId(id: string | null | undefined): SiteThemeId {
  const raw = String(id || 'studio-light').trim().toLowerCase()
  return THEME_ALIASES[raw] || raw
}

export function syncSiteDocumentTone() {
  // Brand themes are light-only. Staff control-ui may still toggle its own dark mode.
  if (document.documentElement.classList.contains('control-ui')) return
  document.documentElement.classList.remove('dark')
  document.documentElement.style.colorScheme = 'light'
}

export function hydrateThemeFromCache() {
  try {
    const cached = JSON.parse(localStorage.getItem('ifnotus_theme_colors') || 'null') as Partial<ThemeColors> | null
    const id = normalizeThemeId(localStorage.getItem('ifnotus_theme_id') || 'studio-light')
    theme.value = id
    if (cached?.primary) {
      colors.value = { ...DEFAULT_COLORS, ...cached }
      applyThemeColors(colors.value, document.documentElement, id)
      loaded.value = true
    } else {
      applyThemeColors(DEFAULT_COLORS, document.documentElement, id)
    }
    syncSiteDocumentTone()
  } catch {
    applyThemeColors(DEFAULT_COLORS, document.documentElement, 'studio-light')
    syncSiteDocumentTone()
  }
}

export function useSiteTheme() {
  const isDark = computed(() => false)
  const isLight = computed(() => true)
  const tone = computed<'light' | 'dark'>(() => 'light')

  async function load(force = false) {
    if (loaded.value && !force) {
      syncSiteDocumentTone()
      applyThemeColors(colors.value, document.documentElement, theme.value)
      return
    }
    if (loadInflight && !force) return loadInflight
    loadInflight = (async () => {
      try {
        const { data } = await catalogApi.meta()
        const id = normalizeThemeId(data.theme || 'studio-light')
        theme.value = id
        themes.value = (data.themes || []) as SiteThemeOption[]
        colors.value = { ...DEFAULT_COLORS, ...(data.colors || {}) }
        planColors.value = (data.plan_colors?.length ? data.plan_colors : DEFAULT_PLAN_TIERS).map(
          (t) => ({
            id: String(t.id),
            label: String(t.label || t.id),
            max_price: t.max_price,
            accent: String(t.accent),
          }),
        )
        applyThemeColors(colors.value, document.documentElement, id)
        syncSiteDocumentTone()
      } catch {
        theme.value = 'studio-light'
        colors.value = { ...DEFAULT_COLORS }
        applyThemeColors(colors.value, document.documentElement, 'studio-light')
        syncSiteDocumentTone()
      } finally {
        loaded.value = true
        loadInflight = null
      }
    })()
    return loadInflight
  }

  function applyLocal(next: Partial<ThemeColors>) {
    colors.value = { ...colors.value, ...next }
    applyThemeColors(colors.value, document.documentElement, theme.value)
  }

  return {
    theme,
    themes,
    colors,
    planColors,
    loaded,
    isDark,
    isLight,
    tone,
    load,
    applyLocal,
    syncDocument: syncSiteDocumentTone,
  }
}
