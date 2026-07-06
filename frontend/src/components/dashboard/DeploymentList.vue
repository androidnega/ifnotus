<script setup lang="ts">
import type { DeploymentItem } from '@/types/dashboard'
import Badge from '@/components/ui/Badge.vue'
import { IconDeploy } from '@/components/icons'

defineProps<{
  deployments: DeploymentItem[]
  loading?: boolean
}>()

function statusVariant(status: DeploymentItem['status']) {
  const map = {
    success: 'success',
    failed: 'danger',
    in_progress: 'info',
    pending: 'neutral',
  } as const
  return map[status]
}

function formatTime(ts: string) {
  return new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <p v-if="!deployments.length && !loading" class="text-sm text-surface-muted">
    No deployment records found in registered applications.
  </p>
  <ul v-else class="space-y-2" role="list" aria-label="Recent deployments">
    <li
      v-for="dep in deployments"
      :key="dep.id"
      class="flex items-center gap-3 rounded-lg border border-surface-border px-3 py-2.5 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
    >
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600 dark:text-brand-400">
        <IconDeploy :size="16" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium text-slate-900 dark:text-white">{{ dep.application }}</p>
        <p class="text-xs text-surface-muted">
          {{ dep.version }} → {{ dep.environment }} · {{ dep.triggeredBy }}
        </p>
      </div>
      <div class="shrink-0 text-right">
        <Badge :variant="statusVariant(dep.status)" size="sm">{{ dep.status.replace('_', ' ') }}</Badge>
        <p class="mt-1 text-[10px] text-surface-muted">{{ formatTime(dep.timestamp) }}</p>
      </div>
    </li>
  </ul>
</template>
