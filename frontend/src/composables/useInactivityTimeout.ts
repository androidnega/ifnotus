import { onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const INACTIVITY_LIMIT_MS = 20 * 60 * 1000 // 20 minutes
const CHECK_INTERVAL_MS = 15 * 1000 // Check every 15 seconds
const ACTIVITY_STORAGE_KEY = 'ifnotus_last_active'

export function useInactivityTimeout() {
  const auth = useAuthStore()
  const router = useRouter()

  let lastLocalRecord = Date.now()
  let timer: ReturnType<typeof setInterval> | null = null

  function recordActivity() {
    const now = Date.now()
    // Throttle local updates to once every 2 seconds
    if (now - lastLocalRecord > 2000) {
      lastLocalRecord = now
      try {
        localStorage.setItem(ACTIVITY_STORAGE_KEY, String(now))
      } catch {
        // ignore storage errors
      }
    }
  }

  function getLastActivity(): number {
    try {
      const stored = localStorage.getItem(ACTIVITY_STORAGE_KEY)
      if (stored) {
        const val = Number(stored)
        if (!isNaN(val) && val > 0) return val
      }
    } catch {
      // ignore
    }
    return lastLocalRecord
  }

  function checkInactivity() {
    // Only check if user is currently logged in
    const token = localStorage.getItem('access_token')
    if (!token) return

    const now = Date.now()
    const lastActive = getLastActivity()
    if (now - lastActive >= INACTIVITY_LIMIT_MS) {
      // Inactive for 20+ minutes — log user out
      auth.clearSession()
      try {
        localStorage.removeItem(ACTIVITY_STORAGE_KEY)
      } catch {
        // ignore
      }
      const host = (window.location.hostname || '').toLowerCase()
      if (host.startsWith('fpanel.') || host.startsWith('cpanel.')) {
        window.location.href = `/login?inactivity=1`
      } else {
        void router.replace({ path: '/login', query: { inactivity: '1' } })
      }
    }
  }

  onMounted(() => {
    if (typeof window === 'undefined') return

    // Record initial activity
    recordActivity()

    const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart']
    for (const ev of events) {
      window.addEventListener(ev, recordActivity, { passive: true })
    }

    timer = setInterval(checkInactivity, CHECK_INTERVAL_MS)
  })

  onUnmounted(() => {
    if (typeof window === 'undefined') return

    const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart']
    for (const ev of events) {
      window.removeEventListener(ev, recordActivity)
    }

    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })
}
