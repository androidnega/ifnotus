<script setup lang="ts">
import { computed } from 'vue'
import Badge from '@/components/ui/Badge.vue'
import { useFileTransferStore, type TransferItem } from '@/stores/fileTransfers'

const store = useFileTransferStore()

const visibleItems = computed(() => store.items.filter((i) => i.status !== 'cancelled'))

function statusVariant(item: TransferItem) {
  if (item.status === 'done') return 'success' as const
  if (item.status === 'error') return 'danger' as const
  if (item.status === 'active') return 'info' as const
  return 'neutral' as const
}

function formatBytes(n: number) {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}
</script>

<template>
  <div v-if="visibleItems.length" class="overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
    <div class="flex items-center justify-between border-b border-surface-border px-4 py-3">
      <div>
        <h2 class="text-sm font-semibold text-slate-900 dark:text-white">Transfer queue</h2>
        <p class="text-xs text-surface-muted">One file at a time to avoid timeouts</p>
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
            <p class="text-xs text-surface-muted">{{ formatBytes(item.sizeBytes) }} · {{ item.message }}</p>
          </div>
          <div class="flex items-center gap-2">
            <Badge :variant="statusVariant(item)" size="sm">{{ item.status }}</Badge>
            <button
              v-if="item.status === 'queued'"
              type="button"
              class="text-xs text-red-600"
              @click="store.removeItem(item.id)"
            >
              Cancel
            </button>
          </div>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
          <div
            class="h-full rounded-full bg-brand-600 transition-all duration-300"
            :class="item.status === 'error' ? 'bg-red-500' : ''"
            :style="{ width: `${item.progress}%` }"
          />
        </div>
      </li>
    </ul>
  </div>
</template>
