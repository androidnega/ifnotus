import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'theme'

function resolveDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true
  if (mode === 'light') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function applyTheme(isDark: boolean) {
  document.documentElement.classList.toggle('dark', isDark)
  document.documentElement.style.colorScheme = isDark ? 'dark' : 'light'
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
