<script setup lang="ts">
import { computed } from 'vue'
import type { ServiceItem } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'

const props = defineProps<{
  service: ServiceItem
}>()

const variant = computed(() => {
  switch (props.service.status) {
    case 'running':
      return 'success'
    case 'degraded':
      return 'warning'
    case 'stopped':
      return 'danger'
    default:
      return 'neutral'
  }
})
</script>

<template>
  <article
    class="flex items-start gap-3 rounded-lg border border-surface-border p-3 transition-all duration-200 hover:border-brand-500/30 hover:bg-brand-500/5"
    :aria-label="`${service.name} status ${service.status}`"
  >
    <div
      class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800"
    >
      <slot name="icon" />
    </div>
    <div class="min-w-0 flex-1">
      <div class="flex items-center justify-between gap-2">
        <p class="truncate text-sm font-medium text-slate-900 dark:text-white">{{ service.name }}</p>
        <Badge :variant="variant" dot size="sm">{{ service.status }}</Badge>
      </div>
      <p v-if="service.description" class="mt-0.5 text-xs text-surface-muted">
        {{ service.description }}
      </p>
      <p v-if="service.uptime" class="mt-1 text-[11px] text-surface-muted">
        Uptime {{ service.uptime }}
      </p>
    </div>
  </article>
</template>
