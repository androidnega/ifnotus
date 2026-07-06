<script setup lang="ts">
import { computed } from 'vue'
import type { StatCardData } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'

const props = defineProps<{
  stat: StatCardData
  loading?: boolean
}>()

const statusVariant = computed(() => {
  switch (props.stat.status) {
    case 'healthy':
      return 'success'
    case 'degraded':
      return 'warning'
    case 'unhealthy':
      return 'danger'
    default:
      return 'neutral'
  }
})

const trendIcon = computed(() => {
  if (props.stat.trend === 'up') return '↑'
  if (props.stat.trend === 'down') return '↓'
  return '→'
})
</script>

<template>
  <article
    class="group relative overflow-hidden rounded-xl border border-surface-border bg-surface-raised p-4 shadow-card transition-all duration-300 hover:-translate-y-0.5 hover:shadow-elevated md:p-5"
    :aria-label="`${stat.label}: ${stat.value}${stat.unit || ''}`"
  >
    <div
      class="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full bg-brand-500/5 transition-transform duration-500 group-hover:scale-110"
    />

    <template v-if="loading">
      <Skeleton height="0.75rem" width="40%" />
      <Skeleton class="mt-3" height="1.75rem" width="55%" />
    </template>

    <template v-else>
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs font-medium uppercase tracking-wide text-surface-muted">{{ stat.label }}</p>
        <Badge v-if="stat.status" :variant="statusVariant" dot size="sm">
          {{ stat.status }}
        </Badge>
      </div>

      <div class="mt-2 flex items-end gap-1.5">
        <p class="text-2xl font-bold tabular-nums tracking-tight text-slate-900 dark:text-white">
          {{ stat.value }}
        </p>
        <span v-if="stat.unit" class="mb-1 text-sm text-surface-muted">{{ stat.unit }}</span>
      </div>

      <p
        v-if="stat.trend"
        class="mt-2 text-xs text-surface-muted"
        :class="{
          'text-amber-600 dark:text-amber-400': stat.trend === 'up',
          'text-emerald-600 dark:text-emerald-400': stat.trend === 'down',
        }"
      >
        <span aria-hidden="true">{{ trendIcon }}</span>
        <span class="sr-only">Trend {{ stat.trend }}</span>
        {{ stat.trendValue || stat.trend }}
      </p>
    </template>
  </article>
</template>
