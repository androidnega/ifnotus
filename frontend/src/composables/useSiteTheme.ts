import { computed, ref } from 'vue'
import { catalogApi } from '@/api'
import {
  applyThemeColors,
  DEFAULT_COLORS,
  DEFAULT_PLAN_TIERS,
  type PlanColorTier,
  type ThemeColors,
} from '@/lib/theme'

export type SiteThemeId = 'server-dark' | 'studio-light' | 'ocean-clean' | 'graphite' | string

export interface SiteThemeOption {
  id: string
  name: string
  description: string
  home_scroll?: boolean
  colors?: ThemeColors
}

const theme = ref<SiteThemeId>('studio-light')
const themes = ref<SiteThemeOption[]>([])
const colors = ref<ThemeColors>({ ...DEFAULT_COLORS })
const planColors = ref<PlanColorTier[]>([...DEFAULT_PLAN_TIERS])
const loaded = ref(false)
let loadInflight: Promise<void> | null = null

export function syncSiteDocumentTone() {
  if (document.documentElement.classList.contains('control-ui')) return
  const dark = theme.value === 'server-dark'
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export function useSiteTheme() {
  const isDark = computed(() => theme.value === 'server-dark')
  const isLight = computed(() => !isDark.value)
  const tone = computed<'light' | 'dark'>(() => (isDark.value ? 'dark' : 'light'))

  async function load(force = false) {
    if (loaded.value && !force) {
      syncSiteDocumentTone()
      return
    }
    if (loadInflight && !force) return loadInflight
    loadInflight = (async () => {
    try {
      const { data } = await catalogApi.meta()
      const id = (data.theme || 'studio-light') as SiteThemeId
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
      applyThemeColors(colors.value)
      syncSiteDocumentTone()
    } catch {
      theme.value = 'studio-light'
      colors.value = { ...DEFAULT_COLORS }
      applyThemeColors(colors.value)
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
    applyThemeColors(colors.value)
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
