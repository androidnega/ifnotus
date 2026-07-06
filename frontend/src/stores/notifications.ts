import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { alertsApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import type { AlertItem } from '@/types/dashboard'

export type NotificationType = 'info' | 'success' | 'warning' | 'error'

export interface Notification {
  id: string
  title: string
  message: string
  type: NotificationType
  timestamp: string
  read: boolean
}

const READ_KEY = 'ifnotus_read_notifications'

function loadReadIds(): Set<string> {
  try {
    const raw = localStorage.getItem(READ_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function saveReadIds(ids: Set<string>) {
  localStorage.setItem(READ_KEY, JSON.stringify([...ids]))
}

function alertToType(severity: AlertItem['severity']): NotificationType {
  if (severity === 'critical') return 'error'
  if (severity === 'warning') return 'warning'
  return 'info'
}

function mapAlert(alert: AlertItem, readIds: Set<string>): Notification {
  return {
    id: alert.id,
    title: alert.title,
    message: alert.message,
    type: alertToType(alert.severity),
    timestamp: alert.timestamp,
    read: alert.acknowledged || readIds.has(alert.id),
  }
}

export const useNotificationStore = defineStore('notifications', () => {
  const items = ref<Notification[]>([])
  const panelOpen = ref(false)
  const loading = ref(false)
  const readIds = ref<Set<string>>(loadReadIds())
  let timer: ReturnType<typeof setInterval> | null = null

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)

  async function syncFromApi() {
    if (!localStorage.getItem('access_token')) return
    loading.value = true
    try {
      const { data } = await alertsApi.list()
      items.value = data.alerts.map((alert) => mapAlert(alert, readIds.value))
    } catch {
      /* keep last known notifications on transient errors */
    } finally {
      loading.value = false
    }
  }

  function startPolling() {
    stopPolling()
    syncFromApi()
    timer = setInterval(syncFromApi, REALTIME_POLL_MS)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function togglePanel() {
    panelOpen.value = !panelOpen.value
  }

  function closePanel() {
    panelOpen.value = false
  }

  function markRead(id: string) {
    readIds.value.add(id)
    saveReadIds(readIds.value)
    const item = items.value.find((n) => n.id === id)
    if (item) item.read = true
  }

  function markAllRead() {
    items.value.forEach((n) => readIds.value.add(n.id))
    saveReadIds(readIds.value)
    items.value.forEach((n) => {
      n.read = true
    })
  }

  function dismiss(id: string) {
    markRead(id)
    items.value = items.value.filter((n) => n.id !== id)
  }

  return {
    items,
    panelOpen,
    loading,
    unreadCount,
    syncFromApi,
    startPolling,
    stopPolling,
    togglePanel,
    closePanel,
    markRead,
    markAllRead,
    dismiss,
  }
})
