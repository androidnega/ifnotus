<script setup lang="ts">
import { computed } from 'vue'
import type { HealthStatus } from '@/types/dashboard'
import ProgressRing from '@/components/ui/ProgressRing.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'

const props = defineProps<{
  score: number
  status: HealthStatus
  environment?: string
  version?: string
  loading?: boolean
}>()

const statusVariant = computed(() => {
  switch (props.status) {
    case 'healthy':
      return 'success'
    case 'degraded':
      return 'warning'
    default:
      return 'danger'
  }
})

const ringColor = computed(() => {
  if (props.score >= 85) return '#10b981'
  if (props.score >= 65) return '#f59e0b'
  return '#ef4444'
})
</script>

<template>
  <section
    class="flex flex-col items-center justify-center rounded-xl border border-surface-border bg-surface-raised p-5 shadow-card md:p-6"
    aria-labelledby="health-score-title"
  >
    <template v-if="loading">
      <Skeleton :width="'120px'" :height="'120px'" :rounded="true" />
      <Skeleton class="mt-4" width="60%" height="0.875rem" />
    </template>

    <template v-else>
      <ProgressRing :value="score" label="Score" :color="ringColor" :size="132" />
      <h2 id="health-score-title" class="mt-4 text-sm font-semibold text-slate-900 dark:text-white">
        Platform Health
      </h2>
      <Badge class="mt-2" :variant="statusVariant" dot>{{ status }}</Badge>
      <p v-if="environment || version" class="mt-3 text-center text-xs text-surface-muted">
        <span v-if="environment">{{ environment }}</span>
        <span v-if="environment && version"> · </span>
        <span v-if="version">v{{ version }}</span>
      </p>
    </template>
  </section>
</template>
