<script setup lang="ts">
import { IconRefresh } from '@/components/icons'

defineProps<{
  title?: string
  message: string
}>()

defineEmits<{ retry: [] }>()
</script>

<template>
  <div
    class="flex flex-col items-center justify-center rounded-xl border border-dashed border-red-300 bg-red-50 px-6 py-10 text-center dark:border-red-900/50 dark:bg-red-950/20"
    role="alert"
  >
    <p class="text-sm font-semibold text-red-700 dark:text-red-300">
      {{ title || 'Something went wrong' }}
    </p>
    <p class="mt-2 max-w-md text-sm text-red-600/80 dark:text-red-300/80">{{ message }}</p>
    <button
      type="button"
      class="mt-4 inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-500"
      @click="$emit('retry')"
    >
      <IconRefresh :size="16" />
      Try again
    </button>
  </div>
</template>
