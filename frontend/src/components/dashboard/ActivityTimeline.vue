<script setup lang="ts">
import type { ActivityItem } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { IconActivity } from '@/components/icons'

defineProps<{
  items: ActivityItem[]
  loading?: boolean
}>()

function formatTime(ts: string) {
  const d = new Date(ts)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3600_000)}h ago`
  return d.toLocaleDateString()
}

function typeVariant(type: ActivityItem['type']) {
  const map = {
    deployment: 'info',
    alert: 'warning',
    service: 'success',
    system: 'neutral',
    user: 'default',
  } as const
  return map[type]
}
</script>

<template>
  <div role="feed" aria-label="Activity timeline">
    <template v-if="loading">
      <div v-for="i in 4" :key="i" class="flex gap-3 py-3">
        <Skeleton width="2rem" height="2rem" :rounded="true" />
        <div class="flex-1">
          <Skeleton width="50%" height="0.75rem" />
          <Skeleton class="mt-2" width="80%" height="0.625rem" />
        </div>
      </div>
    </template>

    <EmptyState v-else-if="!items.length" title="No recent activity" />

    <ol v-else class="relative space-y-0">
      <li
        v-for="(item, index) in items"
        :key="item.id"
        class="relative flex gap-3 pb-5 last:pb-0"
      >
        <div
          v-if="index < items.length - 1"
          class="absolute left-4 top-8 h-[calc(100%-1rem)] w-px bg-surface-border"
          aria-hidden="true"
        />
        <div
          class="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-surface-border bg-surface-raised"
        >
          <IconActivity :size="14" class="text-brand-500" />
        </div>
        <div class="min-w-0 flex-1 pt-0.5">
          <div class="flex flex-wrap items-center gap-2">
            <p class="text-sm font-medium text-slate-900 dark:text-white">{{ item.title }}</p>
            <Badge :variant="typeVariant(item.type)" size="sm">{{ item.type }}</Badge>
          </div>
          <p v-if="item.description" class="mt-0.5 text-xs text-surface-muted">
            {{ item.description }}
          </p>
          <time class="mt-1 block text-[11px] text-surface-muted" :datetime="item.timestamp">
            {{ formatTime(item.timestamp) }}
          </time>
        </div>
      </li>
    </ol>
  </div>
</template>
