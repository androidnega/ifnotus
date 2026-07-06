<script setup lang="ts">
import type { AlertItem } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { IconAlert } from '@/components/icons'

defineProps<{
  alerts: AlertItem[]
  loading?: boolean
  maxItems?: number
}>()

function formatTime(ts: string) {
  return new Date(ts).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function severityVariant(severity: AlertItem['severity']) {
  if (severity === 'critical') return 'danger'
  if (severity === 'warning') return 'warning'
  return 'info'
}
</script>

<template>
  <div role="feed" aria-label="Recent alerts">
    <template v-if="loading">
      <div v-for="i in 3" :key="i" class="border-b border-surface-border py-3 last:border-0">
        <Skeleton width="30%" height="0.75rem" />
        <Skeleton class="mt-2" width="80%" height="0.625rem" />
      </div>
    </template>

    <EmptyState
      v-else-if="!alerts.length"
      title="No active alerts"
      message="Your infrastructure is running smoothly."
    >
      <template #icon>
        <IconAlert :size="20" class="text-emerald-500" />
      </template>
    </EmptyState>

    <ul v-else class="divide-y divide-surface-border">
      <li
        v-for="alert in alerts.slice(0, maxItems || 5)"
        :key="alert.id"
        class="flex gap-3 py-3 transition-colors first:pt-0 last:pb-0 hover:bg-slate-50/50 dark:hover:bg-slate-800/30"
      >
        <div
          class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          :class="{
            'bg-red-100 text-red-600 dark:bg-red-950/40 dark:text-red-400': alert.severity === 'critical',
            'bg-amber-100 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400':
              alert.severity === 'warning',
            'bg-sky-100 text-sky-600 dark:bg-sky-950/40 dark:text-sky-400': alert.severity === 'info',
          }"
        >
          <IconAlert :size="16" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="text-sm font-medium text-slate-900 dark:text-white">{{ alert.title }}</p>
            <Badge :variant="severityVariant(alert.severity)" size="sm">{{ alert.severity }}</Badge>
          </div>
          <p class="mt-0.5 line-clamp-2 text-xs text-surface-muted">{{ alert.message }}</p>
          <p class="mt-1 text-[11px] text-surface-muted">
            {{ alert.source }} · {{ formatTime(alert.timestamp) }}
          </p>
        </div>
      </li>
    </ul>
  </div>
</template>
