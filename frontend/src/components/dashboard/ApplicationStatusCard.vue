<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { ApplicationItem } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'

const props = defineProps<{
  application: ApplicationItem
}>()

const variant = computed(() => {
  switch (props.application.status) {
    case 'running':
      return 'success'
    case 'degraded':
      return 'warning'
    case 'failed':
    case 'stopped':
      return 'danger'
    default:
      return 'neutral'
  }
})
</script>

<template>
  <RouterLink
    :to="{ name: 'application-detail', params: { id: application.id } }"
    class="block rounded-lg border border-surface-border p-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-500/40 hover:shadow-card"
    :aria-label="`${application.name} ${application.status}`"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <p class="truncate text-sm font-semibold text-slate-900 dark:text-white">
          {{ application.name }}
        </p>
        <p class="mt-0.5 text-xs text-surface-muted">
          <span v-if="application.version">v{{ application.version }}</span>
          <span v-if="application.environment"> · {{ application.environment }}</span>
        </p>
      </div>
      <Badge :variant="variant" dot size="sm">{{ application.status }}</Badge>
    </div>
    <span
      v-if="application.url"
      class="mt-2 inline-block truncate text-xs text-brand-600 dark:text-brand-400"
    >
      {{ application.url }}
    </span>
  </RouterLink>
</template>
