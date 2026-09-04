import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { alertsApi, platformAdminApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { isSoundMuted, setSoundMuted, playOrderBell } from '@/lib/sound'
import type { AlertItem } from '@/types/dashboard'

export type NotificationType = 'info' | 'success' | 'warning' | 'error'

export interface Notification {
  id: string
  title: string
  message: string
  type: NotificationType
  timestamp: string
  read: boolean
  href?: string
  kind?: string
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

function alertToType(severity: AlertItem['severity'] | string): NotificationType {
  if (severity === 'critical') return 'error'
  if (severity === 'warning') return 'warning'
  if (severity === 'success') return 'success'
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
    kind: 'system',
  }
}

export const useNotificationStore = defineStore('notifications', () => {
  const items = ref<Notification[]>([])
  const panelOpen = ref(false)
  const loading = ref(false)
  const awaitingPaymentConfirm = ref(0)
  const readyForActivation = ref(0)
  const recentlyPaid = ref(0)
  const openSupportTickets = ref(0)
  const readIds = ref<Set<string>>(loadReadIds())
  const soundMuted = ref(isSoundMuted())
  const initialSyncComplete = ref(false)
  const lastAwaitingCount = ref(0)
  const lastActivationCount = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)
  const ordersBadge = computed(() => awaitingPaymentConfirm.value)
  const activationQueueBadge = computed(() => readyForActivation.value)
  const supportBadge = computed(() => openSupportTickets.value)

  function toggleSound() {
    soundMuted.value = !soundMuted.value
    setSoundMuted(soundMuted.value)
    if (!soundMuted.value) {
      playOrderBell()
    }
  }

  function testSound() {
    playOrderBell()
  }

  async function syncFromApi() {
    if (!localStorage.getItem('access_token')) return
    loading.value = true
    try {
      const [alertsRes, inboxRes] = await Promise.allSettled([
        alertsApi.list(),
        platformAdminApi.opsInbox(),
      ])

      const next: Notification[] = []
      if (alertsRes.status === 'fulfilled') {
        next.push(
          ...alertsRes.value.data.alerts.map((alert) => mapAlert(alert, readIds.value)),
        )
      }

      if (inboxRes.status === 'fulfilled') {
        const inbox = inboxRes.value.data
        const newAwaitingCount = inbox.awaiting_payment_confirm || 0
        const newActivationCount = inbox.ready_for_activation || 0
        
        // Bell chime: trigger sound when a new order needing confirmation arrives
        if (initialSyncComplete.value && newAwaitingCount > lastAwaitingCount.value) {
          playOrderBell()
        }
        if (initialSyncComplete.value && newActivationCount > lastActivationCount.value) {
          playOrderBell()
        }

        awaitingPaymentConfirm.value = newAwaitingCount
        lastAwaitingCount.value = newAwaitingCount
        readyForActivation.value = newActivationCount
        lastActivationCount.value = newActivationCount
        recentlyPaid.value = inbox.recently_paid || 0
        openSupportTickets.value = inbox.open_support_tickets || 0

        for (const item of inbox.items || []) {
          next.push({
            id: item.id,
            title: item.title,
            message: item.message,
            type: alertToType(item.severity),
            timestamp:
              typeof item.timestamp === 'string'
                ? item.timestamp
                : new Date(item.timestamp).toISOString(),
            read: readIds.value.has(item.id),
            href: item.href || '/platform/orders',
            kind: item.kind,
          })
        }
      } else {
        awaitingPaymentConfirm.value = 0
        readyForActivation.value = 0
        recentlyPaid.value = 0
        openSupportTickets.value = 0
      }

      next.sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      )
      items.value = next
      initialSyncComplete.value = true
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
    ordersBadge,
    activationQueueBadge,
    supportBadge,
    awaitingPaymentConfirm,
    readyForActivation,
    recentlyPaid,
    openSupportTickets,
    soundMuted,
    toggleSound,
    testSound,
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
