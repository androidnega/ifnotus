import { ref, onMounted, onUnmounted } from 'vue'

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5_000,
) {
  const data = ref<T | null>(null)
  const error = ref<Error | null>(null)
  const loading = ref(true)
  const refreshing = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh(isBackground = false) {
    if (isBackground) refreshing.value = true
    else loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e))
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  onMounted(() => {
    refresh(false)
    timer = setInterval(() => refresh(true), intervalMs)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { data, error, loading, refreshing, refresh: () => refresh(true) }
}
