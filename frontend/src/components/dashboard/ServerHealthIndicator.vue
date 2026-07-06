<script setup lang="ts">
import { computed } from 'vue'
import type { ServerHealth } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'

const props = defineProps<{
  server: ServerHealth
}>()

const statusVariant = computed(() => {
  switch (props.server.status) {
    case 'healthy':
      return 'success'
    case 'degraded':
      return 'warning'
    default:
      return 'danger'
  }
})

function barColor(value: number) {
  if (value >= 85) return 'bg-red-500'
  if (value >= 70) return 'bg-amber-500'
  return 'bg-emerald-500'
}
</script>

<template>
  <article
    class="rounded-lg border border-surface-border bg-surface/50 p-3 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
    :aria-label="`${server.name} health score ${server.score}`"
  >
    <div class="flex items-center justify-between gap-2">
      <div class="min-w-0">
        <p class="truncate text-sm font-medium text-slate-900 dark:text-white">{{ server.name }}</p>
        <p class="text-xs text-surface-muted">Score {{ server.score }}/100</p>
      </div>
      <Badge :variant="statusVariant" dot size="sm">{{ server.status }}</Badge>
    </div>

    <div class="mt-3 space-y-2">
      <div v-for="metric in ['cpu', 'memory', 'disk'] as const" :key="metric">
        <div class="mb-1 flex justify-between text-[10px] uppercase tracking-wide text-surface-muted">
          <span>{{ metric }}</span>
          <span class="tabular-nums">{{ server[metric] }}%</span>
        </div>
        <div class="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="barColor(server[metric])"
            :style="{ width: `${server[metric]}%` }"
            role="progressbar"
            :aria-valuenow="server[metric]"
            aria-valuemin="0"
            aria-valuemax="100"
          />
        </div>
      </div>
    </div>
  </article>
</template>
