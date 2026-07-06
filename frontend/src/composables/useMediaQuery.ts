import { onMounted, onUnmounted, ref } from 'vue'

export function useMediaQuery(query: string) {
  const matches = ref(false)

  let media: MediaQueryList | null = null

  function update() {
    if (media) matches.value = media.matches
  }

  onMounted(() => {
    media = window.matchMedia(query)
    update()
    media.addEventListener('change', update)
  })

  onUnmounted(() => {
    media?.removeEventListener('change', update)
  })

  return matches
}

export function useBreakpoint() {
  const isMobile = useMediaQuery('(max-width: 767px)')
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1023px)')
  const isDesktop = useMediaQuery('(min-width: 1024px)')

  return { isMobile, isTablet, isDesktop }
}
