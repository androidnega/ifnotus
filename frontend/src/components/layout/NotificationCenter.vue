<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useNotificationStore } from '@/stores/notifications'
import Badge from '@/components/ui/Badge.vue'
import { IconClose } from '@/components/icons'

const notifications = useNotificationStore()

function formatTime(ts: string) {
  return new Date(ts).toLocaleString([], { hour: '2-digit', minute: '2-digit' })
}

function typeVariant(type: string) {
  if (type === 'error') return 'danger'
  if (type === 'warning') return 'warning'
  if (type === 'success') return 'success'
  return 'info'
}

function handleClickOutside(event: MouseEvent) {
  if (!notifications.panelOpen) return
  const target = event.target as HTMLElement
  if (!target.closest('[data-notification-center]')) {
    notifications.closePanel()
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>

<template>
  <Transition
    enter-active-class="transition duration-200 ease-out"
    enter-from-class="opacity-0 translate-y-1 scale-95"
    enter-to-class="opacity-100 translate-y-0 scale-100"
    leave-active-class="transition duration-150 ease-in"
    leave-from-class="opacity-100 translate-y-0 scale-100"
    leave-to-class="opacity-0 translate-y-1 scale-95"
  >
    <div
      v-if="notifications.panelOpen"
      data-notification-center
      class="absolute right-0 top-full z-50 mt-2 w-[min(100vw-2rem,24rem)] overflow-hidden rounded-xl border border-surface-border bg-surface-overlay shadow-elevated"
      role="dialog"
      aria-label="Notifications"
    >
      <div class="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <h2 class="text-sm font-semibold text-slate-900 dark:text-white">Notifications</h2>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs text-brand-600 hover:underline dark:text-brand-400"
            @click="notifications.markAllRead()"
          >
            Mark all read
          </button>
          <button
            type="button"
            class="inline-flex h-7 w-7 items-center justify-center rounded-md text-surface-muted hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="Close notifications"
            @click="notifications.closePanel()"
          >
            <IconClose :size="16" />
          </button>
        </div>
      </div>

      <ul v-if="notifications.items.length" class="max-h-80 overflow-y-auto">
        <li
          v-for="item in notifications.items"
          :key="item.id"
          class="border-b border-surface-border px-4 py-3 transition hover:bg-slate-50 dark:hover:bg-slate-800/50"
          :class="!item.read ? 'bg-brand-500/5' : ''"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <p class="text-sm font-medium text-slate-900 dark:text-white">{{ item.title }}</p>
                <Badge :variant="typeVariant(item.type)" size="sm">{{ item.type }}</Badge>
              </div>
              <p class="mt-0.5 text-xs text-surface-muted">{{ item.message }}</p>
              <p class="mt-1 text-[10px] text-surface-muted">{{ formatTime(item.timestamp) }}</p>
            </div>
            <button
              v-if="!item.read"
              type="button"
              class="shrink-0 text-[10px] text-brand-600 hover:underline dark:text-brand-400"
              @click="notifications.markRead(item.id)"
            >
              Read
            </button>
          </div>
        </li>
      </ul>
      <p v-else class="px-4 py-6 text-center text-sm text-surface-muted">
        No active alerts — all systems normal.
      </p>
    </div>
  </Transition>
</template>
