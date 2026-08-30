import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { DEFAULT_COLORS } from '@/lib/theme'
import { syncSiteDocumentTone } from '@/composables/useSiteTheme'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'theme'

function resolveDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true
  if (mode === 'light') return false
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(isDark: boolean) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', isDark)
  root.style.colorScheme = isDark ? 'dark' : 'light'

  if (isDark) {
    root.style.setProperty('--color-surface', '#0b1120')
    root.style.setProperty('--color-surface-raised', '#111827')
    root.style.setProperty('--color-surface-overlay', '#1e293b')
    root.style.setProperty('--color-border', '#1e293b')
    root.style.setProperty('--color-text-muted', '#94a3b8')
    root.style.setProperty('--if-paper', '#0b1120')
    root.style.setProperty('--if-surface', '#111827')
    root.style.setProperty('--if-ink', '#f8fafc')
    root.style.setProperty('--if-muted', '#94a3b8')
    root.style.setProperty('--if-border', '#1e293b')
  } else {
    try {
      const cached = JSON.parse(localStorage.getItem('ifnotus_theme_colors') || 'null')
      const merged = { ...DEFAULT_COLORS, ...(cached || {}) }
      root.style.setProperty('--if-ink', merged.ink)
      root.style.setProperty('--if-paper', merged.paper)
      root.style.setProperty('--if-surface', merged.surface)
      root.style.setProperty('--if-muted', merged.muted)
      root.style.setProperty('--if-border', merged.border)
      root.style.setProperty('--color-surface', merged.paper)
      root.style.setProperty('--color-surface-raised', merged.surface)
      root.style.setProperty('--color-surface-overlay', merged.surface)
      root.style.setProperty('--color-border', merged.border)
      root.style.setProperty('--color-text-muted', merged.muted)
    } catch {
      /* ignore */
    }
  }

  if (!root.classList.contains('control-ui')) {
    syncSiteDocumentTone()
  }
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>((localStorage.getItem(STORAGE_KEY) as ThemeMode) || 'system')
  const isDark = ref(resolveDark(mode.value))

  const resolvedTheme = computed(() => (isDark.value ? 'dark' : 'light'))

  function setMode(next: ThemeMode) {
    mode.value = next
    localStorage.setItem(STORAGE_KEY, next)
    isDark.value = resolveDark(next)
    applyTheme(isDark.value)
  }

  function toggle() {
    setMode(isDark.value ? 'light' : 'dark')
  }

  watch(
    mode,
    (value) => {
      isDark.value = resolveDark(value)
      applyTheme(isDark.value)
    },
    { immediate: true },
  )

  if (typeof window !== 'undefined') {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (mode.value === 'system') {
        isDark.value = resolveDark('system')
        applyTheme(isDark.value)
      }
    })
  }

  return { mode, isDark, resolvedTheme, setMode, toggle }
})
