<script setup lang="ts">
import { computed } from 'vue'
import Badge from '@/components/ui/Badge.vue'
import { useFileTransferStore, type TransferItem } from '@/stores/fileTransfers'

const store = useFileTransferStore()

const visibleItems = computed(() => store.items.filter((i) => i.status !== 'cancelled'))

function statusVariant(item: TransferItem) {
  if (item.status === 'complete' || item.status === 'done') return 'success' as const
  if (item.status === 'failed' || item.status === 'error') return 'danger' as const
  if (item.status === 'uploading' || item.status === 'processing' || item.status === 'active') {
    return 'info' as const
  }
  return 'neutral' as const
}

function statusLabel(item: TransferItem) {
  if (item.status === 'done') return 'complete'
  if (item.status === 'error') return 'failed'
  if (item.status === 'active') return 'uploading'
  return item.status
}

function formatBytes(n: number) {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${Math.max(0, Math.round(n))} B`
}

function formatSpeed(bps: number) {
  if (!bps || bps < 1) return ''
  if (bps >= 1_048_576) return `${(bps / 1_048_576).toFixed(1)} MB/s`
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`
  return `${Math.round(bps)} B/s`
}

function canCancel(item: TransferItem) {
  return (
    item.status === 'queued' ||
    item.status === 'uploading' ||
    item.status === 'active' ||
    item.status === 'processing'
  )
}

function canRetry(item: TransferItem) {
  return item.status === 'failed' || item.status === 'error' || item.status === 'cancelled'
}
</script>

<template>
  <div v-if="visibleItems.length" class="overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
    <div class="flex items-center justify-between border-b border-surface-border px-4 py-3">
      <div>
        <h2 class="text-sm font-semibold text-slate-900 dark:text-white">Transfer queue</h2>
        <p class="text-xs text-surface-muted">
          {{ store.queuedCount ? `${store.queuedCount} waiting · ` : '' }}uploads run one at a time
        </p>
      </div>
      <button
        type="button"
        class="text-xs text-surface-muted underline hover:text-slate-700 dark:hover:text-slate-200"
        @click="store.clearCompleted()"
      >
        Clear completed
      </button>
    </div>

    <ul class="divide-y divide-surface-border">
      <li v-for="item in visibleItems" :key="item.id" class="px-4 py-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-900 dark:text-white">
              {{ item.kind === 'upload' ? '↑' : '↓' }} {{ item.name }}
            </p>
            <p class="text-xs text-surface-muted">
              {{ formatBytes(item.bytesUploaded || 0) }} / {{ formatBytes(item.sizeBytes) }}
              <span v-if="formatSpeed(item.speedBps)"> · {{ formatSpeed(item.speedBps) }}</span>
              · {{ item.message }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <Badge :variant="statusVariant(item)" size="sm">{{ statusLabel(item) }}</Badge>
            <button
              v-if="canCancel(item)"
              type="button"
              class="text-xs text-red-600"
              @click="store.cancelItem(item.id)"
            >
              Cancel
            </button>
            <button
              v-if="canRetry(item)"
              type="button"
              class="text-xs text-brand-700 dark:text-brand-300"
              @click="store.retryItem(item.id)"
            >
              Retry
            </button>
          </div>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="
              item.status === 'failed' || item.status === 'error'
                ? 'bg-red-500'
                : item.status === 'complete' || item.status === 'done'
                  ? 'bg-emerald-500'
                  : 'bg-sky-500'
            "
            :style="{ width: `${item.progress}%` }"
          />
        </div>
        <p class="mt-1 text-right text-[11px] tabular-nums text-surface-muted">{{ item.progress }}%</p>
      </li>
    </ul>
  </div>
</template>
